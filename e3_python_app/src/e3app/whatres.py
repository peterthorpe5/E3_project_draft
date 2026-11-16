"""Score exact full-atom structures with the optional local WhatRes release."""

from __future__ import annotations

import csv
import logging
import math
import os
import re
import signal
import subprocess
from contextlib import suppress
from dataclasses import asdict, dataclass
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Mapping

import pandas as pd
from Bio.PDB import MMCIFParser, PDBIO, PDBParser
from Bio.PDB.PDBExceptions import PDBConstructionException, PDBIOException

from e3app.alphafold_hog_bundle import AlphaFoldHogBundle
from e3app.errors import AppError
from e3app.external_actions import normalise_uniprot_accession
from e3app.external_hog import prepared_hog_model

LOGGER = logging.getLogger(__name__)
WHATRES_VERSION = "1.0.0"
WHATRES_PAPER = "https://doi.org/10.64898/2026.11.06.764824"
WHATRES_CITATION = (
    "van der Kant, R., Delgado Blanco, J., Serrano, L., Schymkowitz, J., & Rousseau, F. (2026). "
    "*Realism and resolution: How AI-predicted protein structures differ from experimental "
    f"structures.* bioRxiv preprint. [doi:10.64898/2026.11.06.764824]({WHATRES_PAPER})"
)
MAX_COORDINATE_BYTES = 20_000_000
SCORE_TIMEOUT_SECONDS = 120
MODEL_ID = "e3_model"
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}")
HOG_SCORE_COLUMNS = (
    "hog_id", "accession", "species", "retrieval_status", "scoring_status",
    "realism", "apparent_resolution", "note", "detail", "whatres_version",
    "model_url", "model_sha256", "scored_pdb_sha256", "structure_id", "input_format",
)


@dataclass(frozen=True, kw_only=True)
class WhatResTarget:
    """A model selection with coordinates, a review checksum or a public accession."""

    label: str
    content: bytes | None = None
    filename: str = ""
    model_sha256: str = ""
    alphafold_accession: str = ""
    group_id: str = ""
    species: str = ""
    from_alphafold_database: bool = False


@dataclass(frozen=True, kw_only=True)
class WhatResScore:
    """The published scores and the identity of the atoms supplied to the tool."""

    model_sha256: str
    scored_pdb_sha256: str
    input_format: str
    structure_id: str
    apparent_resolution: float
    realism: float
    note: str
    whatres_version: str = WHATRES_VERSION


def whatres_directory(*, environment: Mapping[str, str] | None = None) -> Path | None:
    """Locate the supported WhatRes checkout and its separate Python environment.

    Args:
        environment: App host environment, defaulting to the current process environment.

    Returns:
        Absolute checkout path, or None when the optional tool is disabled.

    Raises:
        AppError: If the configured checkout is incomplete or has an unsupported version.
    """
    values = os.environ if environment is None else environment
    configured = values.get("E3_WHATRES_DIR", "").strip()
    if not configured:
        return None
    try:
        root = Path(configured).expanduser().resolve()
        version = (root / "whatres/__init__.py").read_text(encoding="utf-8")
    except (OSError, UnicodeError, RuntimeError, ValueError) as exc:
        raise AppError(
            "E3_WHATRES_DIR must point to the WhatRes checkout on the app host."
        ) from exc
    required_version = re.escape(WHATRES_VERSION)
    declaration = rf'^__version__\s*=\s*["\']{required_version}["\']\s*$'
    if not re.search(declaration, version, flags=re.MULTILINE):
        raise AppError(f"Use the WhatRes v{WHATRES_VERSION} release with this E3 app.")
    executables = (".venv/bin/python", "whatres-features/whatres-features")
    data_files = (
        "whatres/cli.py",
        "data/Options_features.txt",
        "data/native49_structure_reference.bin",
        "models/apparent_resolution_model.joblib",
        "models/over_regularisation_model.joblib",
        "models/training_oof_apparent_resolution.tsv",
        "models/training_oof_realism.tsv",
    )
    missing = [name for name in data_files if not (root / name).is_file()]
    missing.extend(
        name for name in executables
        if not (root / name).is_file() or not os.access(root / name, os.X_OK)
    )
    if missing:
        LOGGER.warning("Incomplete WhatRes installation at %s: %s", root, ", ".join(missing))
        raise AppError(
            "Complete the WhatRes setup on the app host. Missing: " + ", ".join(missing)
        )
    return root


def whatres_structure_id(*, filename: str) -> str:
    """Keep a PDB ID filename for WhatRes's published out-of-fold handling.

    Args:
        filename: Original coordinate filename supplied with a full model.

    Returns:
        A safe lower-case PDB ID or a neutral identifier for predictions.
    """
    stem = Path(filename).stem.lower()
    if re.fullmatch(r"[1-9][a-z0-9]{3}", stem) and not stem.isdecimal():
        return stem
    return MODEL_ID


def recorded_whatres_targets(
    *, inventory: pd.DataFrame, review_rank: int, group_id: str,
    pair_members: Mapping[str, tuple[str, str]] | None = None,
) -> tuple[WhatResTarget, ...]:
    """Find eligible original or public coordinates for the selected group or pair.

    Args:
        inventory: Portable review model inventory, potentially from a legacy bundle.
        review_rank: Selected review rank within the bundle.
        group_id: Exact group identifier from the selected review index row.
        pair_members: Optional role, accession and species from the pair index.

    Returns:
        Models with an unambiguous source row and a checksum or public accession.
    """
    if inventory.empty:
        return ()
    selected = inventory.loc[
        inventory["review_rank"].eq(review_rank) & inventory["primary_group_id"].eq(group_id)
    ]
    checksums: dict[tuple[str, str], list[str]] = {}
    for row in selected.itertuples(index=False):
        member = (str(row.candidate_accession), str(row.species_column))
        checksums.setdefault(member, []).append(str(getattr(row, "model_sha256", "")).lower())
    choices = pair_members.items() if pair_members is not None else (
        ("", member) for member in checksums
    )
    targets = []
    for role, (accession, species) in choices:
        digests = checksums.get((accession, species), [])
        if len(digests) != 1:
            continue
        digest = digests[0] if SHA256_PATTERN.fullmatch(digests[0]) else ""
        public_accession = normalise_uniprot_accession(value=accession) or ""
        if digest or public_accession:
            prefix = f"{role.capitalize()} · " if role else ""
            targets.append(WhatResTarget(
                label=f"{prefix}{accession} · {species.replace('_', ' ')}",
                model_sha256=digest, alphafold_accession=public_accession,
                group_id=group_id, species=species,
            ))
    return tuple(targets)


def _prepare_pdb(*, content: bytes, filename: str) -> tuple[bytes, str]:
    """Read the first atomic model and convert representable mmCIF coordinates to PDB."""
    if not content or len(content) > MAX_COORDINATE_BYTES:
        raise AppError("Choose a non-empty coordinate file up to 20 MB.")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdb", ".cif", ".mmcif"}:
        raise AppError("WhatRes accepts a full-atom PDB or mmCIF coordinate file.")
    is_cif = suffix != ".pdb"
    try:
        parser = MMCIFParser(QUIET=True) if is_cif else PDBParser(QUIET=True, PERMISSIVE=False)
        structure = parser.get_structure("whatres", StringIO(content.decode("utf-8-sig")))
        model = next(structure.get_models())
        residues = [residue for residue in model.get_residues() if residue.id[0] == " "]
        backbone = {"N", "CA", "C", "O"}
        if not any(backbone.issubset(residue.child_dict) for residue in residues):
            raise AppError("WhatRes needs full atomic coordinates, including backbone atoms.")
        if any(residue.resname != "GLY" for residue in residues) and not any(
            "CB" in residue for residue in residues
        ):
            raise AppError("WhatRes needs side-chain atoms for models with non-glycine residues.")
        if not all(
            math.isfinite(value) and len(f"{value:.3f}") <= 8
            for atom in model.get_atoms() for value in atom.coord
        ):
            raise AppError("Model coordinates must be finite and fit the PDB coordinate format.")
        if not is_cif:
            return content.removeprefix(b"\xef\xbb\xbf"), "PDB"
        writer = PDBIO()
        writer.set_structure(model)
        output = StringIO()
        writer.save(output)
        return output.getvalue().encode("ascii"), "mmCIF"
    except (
        KeyError, IndexError, OSError, PDBConstructionException, PDBIOException, StopIteration,
        TypeError, ValueError,
    ) as exc:
        LOGGER.info("Could not read a WhatRes coordinate file: %s", exc)
        raise AppError(
            "Could not read the first model as a valid PDB or convertible mmCIF."
        ) from exc


def _read_whatres_row(*, path: Path, structure_id: str) -> dict[str, str]:
    """Read exactly one complete TSV row for the staged structure."""
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            row = next(reader, None)
            if (
                row is None or row.get("id") != structure_id or None in row
                or len(row) != len(reader.fieldnames)
                or None in row.values() or next(reader, None) is not None
            ):
                raise ValueError("Expected exactly one complete row for the submitted structure")
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        raise AppError(f"WhatRes returned an invalid {path.name} table.") from exc
    return row


def _run_whatres(*, directory: Path, pdb_path: Path, scratch: Path) -> None:
    """Run the local release with isolated scratch and a bounded process lifetime."""
    argv = [
        str(directory / ".venv/bin/python"), "-E", "-s", "-m", "whatres.cli", "score",
        str(pdb_path), "--out", str(scratch / "scores.tsv"),
        "--features-out", str(scratch / "features.tsv"),
    ]
    environment = dict(os.environ, TMPDIR=str(scratch))
    environment["WHATRES_FEATURES"] = str(directory / "whatres-features/whatres-features")
    environment["WHATRES_MODELS_DIR"] = str(directory / "models")
    try:
        with (scratch / "whatres.log").open("w+b") as log:
            with subprocess.Popen(
                argv, cwd=directory, env=environment, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            ) as process:
                try:
                    status = process.wait(timeout=SCORE_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired as exc:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    LOGGER.warning("WhatRes timed out for %s", pdb_path.name)
                    raise AppError(f"WhatRes exceeded {SCORE_TIMEOUT_SECONDS} seconds.") from exc
            if status:
                log.seek(max(0, log.tell() - 4_096))
                LOGGER.warning("WhatRes exited with status %d: %s", status,
                               log.read().decode("utf-8", errors="replace").strip())
                raise AppError("WhatRes could not score this model. Check the app host log.")
    except OSError as exc:
        LOGGER.warning("Could not start WhatRes at %s: %s", directory, exc)
        raise AppError("Could not run WhatRes on the app host.") from exc


def score_whatres(
    *, directory: Path, content: bytes, filename: str, expected_sha256: str = "",
) -> WhatResScore:
    """Calculate both WhatRes scores for the selected full-atom model.

    Args:
        directory: Validated WhatRes checkout used by the app host.
        content: Original coordinate file bytes.
        filename: Original filename used for coordinate format and optional PDB ID.
        expected_sha256: Exact source checksum when scoring a recorded review model.

    Returns:
        Validated WhatRes metrics and coordinate provenance.

    Raises:
        AppError: If the model identity, coordinates, local execution or output is invalid.
    """
    model_sha256 = sha256(content).hexdigest()
    if expected_sha256 and model_sha256 != expected_sha256:
        raise AppError("The supplied model SHA-256 differs from the original review model.")
    pdb, input_format = _prepare_pdb(content=content, filename=filename)
    structure_id = whatres_structure_id(filename=filename)
    try:
        with TemporaryDirectory(prefix="e3-whatres-", dir="/tmp") as work:
            scratch = Path(work)
            pdb_path = scratch / f"{structure_id}.pdb"
            pdb_path.write_bytes(pdb)
            LOGGER.info("Starting WhatRes v%s for model SHA-256 %s", WHATRES_VERSION, model_sha256)
            _run_whatres(directory=directory, pdb_path=pdb_path, scratch=scratch)
            features = _read_whatres_row(path=scratch / "features.tsv", structure_id=structure_id)
            metrics = _read_whatres_row(path=scratch / "scores.tsv", structure_id=structure_id)
    except OSError as exc:
        LOGGER.warning("Could not write the WhatRes working files: %s", exc)
        raise AppError("Could not use the WhatRes temporary directory on the app host.") from exc
    try:
        if (
            int(features["qc_n_residues"]) < 1 or int(features["surf_n_chains"]) < 1
            or not any(column.startswith("dist_") and features[column] for column in features)
        ):
            raise ValueError("Incomplete coordinate features")
        resolution = float(metrics["apparent_resolution"])
        realism = float(metrics["realism"])
        note = metrics["note"]
        if not math.isfinite(resolution) or resolution <= 0 or not 0 <= realism <= 100:
            raise ValueError("WhatRes scores are outside their supported ranges")
    except (KeyError, ValueError) as exc:
        LOGGER.warning("Invalid WhatRes result for model %s: %s", model_sha256, exc)
        raise AppError(
            "WhatRes did not produce complete geometry features and valid scores."
        ) from exc
    LOGGER.info("WhatRes scored model %s: realism %.4f, apparent resolution %.4f Å",
                model_sha256, realism, resolution)
    return WhatResScore(
        model_sha256=model_sha256, scored_pdb_sha256=sha256(pdb).hexdigest(),
        input_format=input_format, structure_id=structure_id, apparent_resolution=resolution,
        realism=realism, note=note,
    )


def score_whatres_bundle(
    *, directory: Path, bundle: AlphaFoldHogBundle, hog_id: str,
    progress: Callable[..., None] | None = None,
) -> pd.DataFrame:
    """Score each included HOG model while retaining the retrieval audit for all requests.

    Args:
        directory: Validated WhatRes installation used by the app host.
        bundle: Prepared AlphaFold Database models and their per-accession manifest.
        hog_id: Identifier for the selected HOG.
        progress: Optional callback taking completed and total counts as keyword arguments.

    Returns:
        One row per requested accession, with blank metrics where scoring was unavailable.
    """
    rows = []
    for index, record in enumerate(bundle.records, start=1):
        row = {
            "hog_id": hog_id, "accession": record.accession, "species": record.species,
            "retrieval_status": record.status, "scoring_status": "not_attempted",
            "model_url": record.model_url, "model_sha256": record.model_sha256,
            "detail": record.detail,
        }
        if record.status == "included":
            try:
                content = prepared_hog_model(bundle=bundle, accession=record.accession)
                score = score_whatres(
                    directory=directory, content=content, filename="alphafold.cif",
                    expected_sha256=record.model_sha256,
                )
            except AppError as exc:
                LOGGER.warning("WhatRes failed for %s in %s: %s", record.accession, hog_id, exc)
                row.update(scoring_status="error", detail=str(exc))
            else:
                row.update(asdict(score), scoring_status="scored")
        rows.append(row)
        if progress is not None:
            progress(completed=index, total=bundle.requested_count)
    return pd.DataFrame(rows, columns=HOG_SCORE_COLUMNS)
