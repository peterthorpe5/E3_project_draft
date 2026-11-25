"""Map native WhatRes residue diagnostics to checked coordinates and reviewed pockets."""

from __future__ import annotations

import csv
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory

import numpy as np
from Bio.PDB import PDBParser, is_aa
from Bio.PDB.MMCIF2Dict import MMCIF2Dict
from Bio.SeqUtils import seq1

from e3app.errors import AppError
from e3app.research.linked_features import MAX_LINKED_RESIDUES
from e3app.whatres import MODEL_ID, WHATRES_VERSION, _prepare_pdb, run_whatres_command

LOGGER = logging.getLogger(__name__)
QC_FIELDS = {"pdb", "chain", "aa", "resnum", "ref_count", "residue_score",
             "n_outliers", "worst_metric", "worst_score"}
MAX_REPORT_BYTES = 128 * 1024 * 1024
MEASURES = ("residue_score", "n_outliers", "worst_metric", "worst_score")
EMPTY_MEASURES = dict.fromkeys(MEASURES)


@dataclass(frozen=True, kw_only=True)
class ResidueReport:
    """Residue observations from the first model and the exact source identities."""

    model_sha256: str
    scored_pdb_sha256: str
    input_format: str
    rows: tuple[dict, ...]
    colour_limit: float
    whatres_version: str = WHATRES_VERSION


def _label_ids(*, cif: bytes) -> dict:
    """Index first-model mmCIF Cα author identifiers by their sequence-axis aliases.

    Args:
        cif: Original mmCIF bytes before conversion to the WhatRes PDB.

    Returns:
        Unique label chain/position pairs keyed by author chain, number and insertion.
    """
    atoms = MMCIF2Dict(StringIO(cif.decode("utf-8-sig")))
    names = atoms["_atom_site.label_atom_id"]
    models = atoms.get("_atom_site.pdbx_PDB_model_num", ["1"] * len(names))
    insertions = atoms.get("_atom_site.pdbx_PDB_ins_code", ["?"] * len(names))
    aliases = defaultdict(set)
    if "_atom_site.label_asym_id" not in atoms or "_atom_site.label_seq_id" not in atoms:
        return {}
    author_numbers = atoms.get("_atom_site.auth_seq_id", atoms["_atom_site.label_seq_id"])
    for atom, model, chain, number, insertion, label_chain, label_number in zip(
        names, models, atoms["_atom_site.auth_asym_id"], author_numbers,
        insertions, atoms["_atom_site.label_asym_id"], atoms["_atom_site.label_seq_id"],
        strict=True,
    ):
        if atom == "CA" and model == models[0] and label_number not in {"?", "."}:
            code = "" if insertion in {"?", "."} else insertion.strip()
            key = chain.strip(), int(number), code
            aliases[key].add((label_chain.strip(), int(label_number)))
    return {key: next(iter(values)) for key, values in aliases.items() if len(values) == 1}


def _native_rows(*, pdb: bytes, aliases: dict | None) -> list[dict]:
    """Catalogue observed amino acids and Cα positions in the submitted first model.

    Args:
        pdb: Validated PDB input to the feature program.
        aliases: mmCIF sequence labels, or None for a PDB.

    Returns:
        Native residues in coordinate order, including unscored and ambiguous sites.

    Raises:
        AppError: If the model has no bounded set of protein residues.
    """
    structure = PDBParser(QUIET=True).get_structure(MODEL_ID, StringIO(pdb.decode("utf-8")))
    rows = []
    for residue in next(structure.get_models()).get_residues():
        hetero, number, code = residue.id
        if hetero != " " and not is_aa(residue):
            continue
        chain = residue.parent.id.strip()
        code = code.strip()
        label = (chain, number) if aliases is None else aliases.get((chain, number, code))
        ca = residue["CA"] if "CA" in residue else None
        xyz = tuple(map(float, ca.coord)) if ca is not None else (None, None, None)
        rows.append({
            "chain": chain, "author_number": number, "insertion_code": code,
            "label_chain": label[0] if label else None, "label_number": label[1] if label else None,
            "residue": seq1(residue.resname, custom_map={"MSE": "M", "H1S": "H", "H2S": "H"}),
            "x": xyz[0], "y": xyz[1], "z": xyz[2],
            "status": "alternate_conformer" if residue.is_disordered() else "not_reported",
            "reference_count": None, **EMPTY_MEASURES,
        })
    if not 0 < len(rows) <= MAX_LINKED_RESIDUES:
        raise AppError(f"Local geometry supports 1–{MAX_LINKED_RESIDUES:,} model residues.")
    return rows


def _read_diagnostics(*, path: Path, rows: list[dict], minimum_reference: int) -> None:
    """Join the upstream report without guessing identities lost in its integer residue IDs.

    Args:
        path: Per-residue quality report written in private scratch.
        rows: Native coordinate records to populate.
        minimum_reference: Minimum reference count from the options used for this run.

    Raises:
        AppError: If the output is missing, malformed, incomplete in shape or oversized.
    """
    by_key = defaultdict(list)
    try:
        if path.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError("Report exceeds size limit")
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            fields = reader.fieldnames or []
            if len(fields) != len(set(fields)) or not QC_FIELDS.issubset(fields):
                raise ValueError("Missing or duplicate report columns")
            for index, raw in enumerate(reader):
                if (index >= MAX_LINKED_RESIDUES or raw["pdb"] != MODEL_ID or None in raw
                        or None in raw.values()):
                    raise ValueError("Unexpected model, row length or residue count")
                ref, flags = int(raw["ref_count"]), int(raw["n_outliers"])
                score, worst = float(raw["residue_score"]), float(raw["worst_score"])
                if (min(ref, flags) < 0 or not all(math.isfinite(v) and v >= 0
                                                   for v in (score, worst))):
                    raise ValueError("Invalid geometry values")
                by_key[raw["chain"].strip(), int(raw["resnum"])].append({
                    "aa": raw["aa"], "reference_count": ref, "residue_score": score,
                    "n_outliers": flags, "worst_metric": raw["worst_metric"], "worst_score": worst,
                })
        if not by_key:
            raise ValueError("Empty residue report")
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        LOGGER.warning("Could not read WhatRes residue diagnostics: %s", exc)
        raise AppError("WhatRes returned an invalid or missing residue geometry report.") from exc

    counts = Counter((row["chain"], row["author_number"]) for row in rows)
    for row in rows:
        key = row["chain"], row["author_number"]
        matches = by_key.get(key, ())
        if counts[key] > 1 or len(matches) > 1:
            row["status"] = "ambiguous_number"
        elif row["status"] != "alternate_conformer" and matches:
            hit = matches[0]
            if hit["aa"] != row["residue"]:
                row["status"] = "residue_mismatch"
            else:
                row["reference_count"] = hit["reference_count"]
                if hit["reference_count"] < minimum_reference:
                    row["status"] = "insufficient_reference"
                else:
                    row.update({field: hit[field] for field in MEASURES}, status="assessed")


def score_residue_geometry(
    *, directory: Path, content: bytes, filename: str, expected_sha256: str = "",
) -> ResidueReport:
    """Run the published quality check on the full structure in its native environment.

    Args:
        directory: Validated local WhatRes v1.0.0 installation.
        content: Complete source model bytes.
        filename: Original PDB or mmCIF filename.
        expected_sha256: Source file identity for a recorded model, when known.

    Returns:
        Residue scores and their provenance, with explicit reasons for missing scores.

    Raises:
        AppError: If the model, local installation or upstream output is unusable.
    """
    digest = sha256(content).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise AppError("The supplied model SHA-256 differs from the original review model.")
    pdb, input_format = _prepare_pdb(content=content, filename=filename)
    try:
        rows = _native_rows(pdb=pdb, aliases=_label_ids(cif=content)
                            if input_format == "mmCIF" else None)
        with TemporaryDirectory(prefix="e3-whatres-residues-", dir="/tmp") as work:
            scratch = Path(work)
            (scratch / "model.list").write_text(str(scratch / f"{MODEL_ID}.pdb") + "\n")
            (scratch / f"{MODEL_ID}.pdb").write_bytes(pdb)
            reference = directory / "data/native49_structure_reference.bin"
            (scratch / "reference.bin").symlink_to(reference)
            options = (directory / "data/Options_features.txt").read_text(encoding="utf-8")
            options, references = re.subn(r"(?m)^<qc_reference_db>[^;\n]*;",
                                          "<qc_reference_db>reference.bin;", options)
            options, prefixes = re.subn(r"(?m)^<prefix>[^;\n]*;", "<prefix>local_;", options)
            minimum = re.findall(r"(?m)^<qc_min_ref_count>([1-9]\d*);", options)
            if references != 1 or prefixes != 1 or len(minimum) != 1:
                raise AppError("The installed WhatRes feature options could not be read.")
            (scratch / "Options.txt").write_text(options, encoding="utf-8")
            LOGGER.info("Starting WhatRes residue geometry for SHA-256 %s", digest)
            run_whatres_command(
                argv=[str(directory / "whatres-features/whatres-features"), "-do",
                      "pdb_quality_check", "-in", "model.list", "-opt", "Options.txt"],
                cwd=scratch, scratch=scratch,
            )
            _read_diagnostics(path=scratch / "local_quality_report.tsv", rows=rows,
                              minimum_reference=int(minimum[0]))
    except (OSError, KeyError, ValueError, UnicodeError) as exc:
        LOGGER.warning("Could not prepare or read local geometry for %s: %s", digest, exc)
        raise AppError("Could not prepare the residue map or WhatRes working files.") from exc
    scores = [row["residue_score"] for row in rows if row["status"] == "assessed"]
    return ResidueReport(
        model_sha256=digest, scored_pdb_sha256=sha256(pdb).hexdigest(), input_format=input_format,
        rows=tuple(rows), colour_limit=float(np.quantile(scores, .95)) if scores else 0.0,
    )


def pocket_geometry(*, pockets: list[dict], model: list[dict]) -> list[dict]:
    """Summarise unique mapped residues, counting each overlapping pocket independently.

    Args:
        pockets: Verified memberships on the selected trace.
        model: Sequence-positioned points with matched local measurements.

    Returns:
        Pocket tracks with numerical summaries and the positions behind each statistic.
    """
    by_position = {row["position"]: row for row in model}
    result = []
    for pocket in pockets:
        positions = sorted(set(pocket["positions"]))
        assessed = [by_position[pos] for pos in positions
                    if by_position.get(pos, {}).get("residue_score") is not None]
        flagged = [row for row in assessed if row["n_outliers"] > 0]
        peak = max(assessed, key=lambda row: row["residue_score"], default=None)
        confidence = [by_position[pos]["plddt"] for pos in positions
                      if by_position.get(pos, {}).get("plddt") is not None]
        result.append({**pocket, "positions": positions, "geometry": {
            "plddt_residues": len(confidence), "median_plddt": median(confidence)
            if confidence else None,
            "mapped_residues": len(positions), "assessed_residues": len(assessed),
            "flagged_residues": len(flagged), "outlier_count": (
                sum(row["n_outliers"] for row in assessed) if assessed else None
            ),
            "flagged_percent_of_assessed": 100 * len(flagged) / len(assessed) if assessed else None,
            "median_residue_score": median(row["residue_score"] for row in assessed)
            if assessed else None,
            "peak_residue_score": peak["residue_score"] if peak else None,
            "peak_position": peak["position"] if peak else None,
            "flagged_positions": " ".join(str(row["position"]) for row in flagged),
        }})
    return result


def link_residue_geometry(*, evidence: dict, report: ResidueReport) -> dict:
    """Match an entire displayed trace on source hash, residue identities and Cα coordinates.

    Args:
        evidence: Selected native review or AlphaFold sequence, trace and pocket tracks.
        report: Full-model report with author and sequence identifiers.

    Returns:
        A copy of the trace and its pocket tracks with their geometry diagnostics.

    Raises:
        AppError: If the model differs or a unique trace mapping cannot be established.
    """
    if str(evidence.get("model_sha256", "")).lower() != report.model_sha256:
        raise AppError("The displayed trace and the assessed model have different checksums.")
    matches = []
    for chain_field, number_field in (("label_chain", "label_number"), ("chain", "author_number")):
        index = defaultdict(list)
        for offset, row in enumerate(report.rows):
            index[row[chain_field], row[number_field]].append(offset)
        offsets = []
        for point in evidence["model"]:
            number = point.get("coordinate_number", point["position"])
            candidates = index.get((point["chain"], number), ())
            if len(candidates) != 1:
                break
            row = report.rows[candidates[0]]
            if (point["residue"] != row["residue"] or row["x"] is None or
                any(not math.isclose(point[axis], row[axis], rel_tol=0, abs_tol=.0011)
                    for axis in ("x", "y", "z"))):
                break
            offsets.append(candidates[0])
        else:
            if offsets:
                matches.append(tuple(offsets))
    if len(set(matches)) != 1:
        raise AppError("The residue identifiers and Cα coordinates could not verify this trace.")
    model = [{**point, **{field: report.rows[offset][field] for field in (*MEASURES, "status")}}
             for point, offset in zip(evidence["model"], matches[0], strict=True)]
    return {**evidence, "model": model, "geometry_limit": report.colour_limit,
            "pockets": pocket_geometry(pockets=evidence.get("pockets", []), model=model)}


def native_geometry_view(*, report: ResidueReport, chain: str) -> dict:
    """Construct a chain view on an observed-residue axis with explicit author numbering.

    Args:
        report: Geometry calculated in the context of every chain in the complete model.
        chain: Exact author chain identifier, including the empty identifier if present.

    Returns:
        A sequence and Cα trace for the selected chain, with gaps and native identifiers.
    """
    rows = [row for row in report.rows if row["chain"] == chain]
    sequence = "".join(row["residue"] for row in rows)
    model, untraced = [], []
    previous = None
    for position, row in enumerate(rows, start=1):
        point = {**row, "position": position, "plddt": None,
                 "native_id": f"{chain or '(blank)'} {row['author_number']}{row['insertion_code']}"}
        if row["x"] is None:
            untraced.append(point)
            previous = None
            continue
        xyz = tuple(row[axis] for axis in ("x", "y", "z"))
        model.append({**point, "break_before": previous is None or math.dist(xyz, previous) > 5})
        previous = xyz
    return {"sequence": sequence, "features": [], "model": model, "pockets": [],
            "untraced_geometry": untraced,
            "coordinate_scope": f"Observed residues in chain {chain or '(blank)'}",
            "geometry_limit": report.colour_limit, "model_sha256": report.model_sha256}
