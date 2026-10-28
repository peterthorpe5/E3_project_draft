"""Auditable structural superposition and pocket-position comparison."""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import gemmi
import numpy as np
from Bio.Align import PairwiseAligner
from scipy.spatial.distance import cdist

from .conservation import residue_evidence
from .core import (
    ComparisonSettings,
    WorkbenchError,
    digest_file,
    inside,
    load_project,
    utc_now,
    write_json,
)
from .database import save_project

LOGGER = logging.getLogger(__name__)


def sequence_pairs(*, reference: str, mobile: str) -> list[tuple[int, int]]:
    """Map zero-based residues using an explicit global affine-gap alignment.

    Args:
        reference: Reference amino acid sequence.
        mobile: Mobile amino acid sequence.

    Returns:
        Aligned non-gap residue index pairs.
    """
    if not reference or not mobile or max(len(reference), len(mobile)) > 20000:
        raise WorkbenchError(
            "Pairwise sequence alignment needs non-empty bounded sequences"
        )
    aligner = PairwiseAligner(
        mode="global",
        match_score=3,
        mismatch_score=-1,
        open_gap_score=-8,
        extend_gap_score=-0.5,
    )
    alignment = aligner.align(reference, mobile)[0]
    pairs = []
    for ref_block, mob_block in zip(*alignment.aligned):
        pairs.extend(zip(range(*ref_block), range(*mob_block)))
    return [(int(first), int(second)) for first, second in pairs]


def kabsch(
    *, reference: np.ndarray, mobile: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit a proper rigid rotation, explicitly excluding mirror reflection.

    Args:
        reference: N by 3 paired reference coordinates.
        mobile: N by 3 paired mobile coordinates.

    Returns:
        Rotation R, translation t and RMSD, with transformed = mobile @ R.T + t.
    """
    reference, mobile = (
        np.asarray(reference, dtype=float),
        np.asarray(mobile, dtype=float),
    )
    if (
        reference.shape != mobile.shape
        or reference.ndim != 2
        or reference.shape[1] != 3
        or len(reference) < 3
    ):
        raise WorkbenchError("A rigid fit needs at least three paired 3D coordinates")
    if not np.isfinite(reference).all() or not np.isfinite(mobile).all():
        raise WorkbenchError("Fit coordinates must be finite")
    ref_centre, mob_centre = reference.mean(axis=0), mobile.mean(axis=0)
    ref, mob = reference - ref_centre, mobile - mob_centre
    if min(np.linalg.matrix_rank(ref), np.linalg.matrix_rank(mob)) < 2:
        raise WorkbenchError("The selected fit atoms are collinear")
    left, _, right = np.linalg.svd(mob.T @ ref)
    correction = np.diag([1.0, 1.0, np.linalg.det(right.T @ left.T)])
    rotation = right.T @ correction @ left.T
    translation = ref_centre - mob_centre @ rotation.T
    rmsd = float(
        np.sqrt(
            np.mean(
                np.sum((mobile @ rotation.T + translation - reference) ** 2, axis=1)
            )
        )
    )
    return rotation, translation, rmsd


def pocket_geometry(
    *, reference: np.ndarray, mobile: np.ndarray, radius: float
) -> dict:
    """Measure E3-compatible lining-residue proximity after superposition.

    Args:
        reference: M by 3 pocket C-alpha coordinates.
        mobile: N by 3 already-transformed pocket C-alpha coordinates.
        radius: Positive residue-neighbour threshold in Angstroms.

    Returns:
        Centroid distance, directional fractions and mutual-nearest Dice fraction.
    """
    reference, mobile = np.asarray(reference, float), np.asarray(mobile, float)
    if (
        not np.isfinite(radius)
        or radius <= 0
        or len(reference) == 0
        or len(mobile) == 0
    ):
        raise WorkbenchError(
            "Pocket geometry needs non-empty pockets and a positive radius"
        )
    if (
        reference.ndim != 2
        or mobile.ndim != 2
        or reference.shape[1] != 3
        or mobile.shape[1] != 3
        or not np.isfinite(reference).all()
        or not np.isfinite(mobile).all()
    ):
        raise WorkbenchError("Pocket coordinates must be finite N by 3 arrays")
    distances = cdist(reference, mobile)
    ref_nearest, mob_nearest = distances.argmin(axis=1), distances.argmin(axis=0)
    mutual = sum(
        mob_nearest[j] == i and distances[i, j] <= radius
        for i, j in enumerate(ref_nearest)
    )
    ref_fraction = float(np.mean(distances.min(axis=1) <= radius))
    mob_fraction = float(np.mean(distances.min(axis=0) <= radius))
    return {
        "centroid_distance": float(
            np.linalg.norm(reference.mean(axis=0) - mobile.mean(axis=0))
        ),
        "reference_fraction": ref_fraction,
        "mobile_fraction": mob_fraction,
        "symmetric_overlap": (ref_fraction + mob_fraction) / 2,
        "mutual_match_fraction": float(2 * mutual / (len(reference) + len(mobile))),
        "mutual_pairs": [
            [int(i), int(j)]
            for i, j in enumerate(ref_nearest)
            if mob_nearest[j] == i and distances[i, j] <= radius
        ],
    }


def parse_usalign(*, text: str, matrix: str) -> dict:
    """Validate standard USalign scores and its mobile-to-reference transform.

    Args:
        text: Standard USalign full stdout.
        matrix: Contents of the -m rotation file.

    Returns:
        Parsed alignment statistics and rigid transform.
    """
    aligned = re.search(r"Aligned\s+length=\s*(\d+),\s*RMSD=\s*([\d.eE+-]+)", text)
    scores = [float(value) for value in re.findall(r"TM-score=\s*([\d.eE+-]+)", text)]
    rows = {}
    for line in matrix.splitlines():
        fields = line.split()
        if len(fields) == 5 and fields[0] in {"0", "1", "2"}:
            if int(fields[0]) in rows:
                raise WorkbenchError("Duplicate USalign matrix row")
            rows[int(fields[0])] = [float(value) for value in fields[1:]]
    if aligned is None or len(scores) < 2 or set(rows) != {0, 1, 2}:
        raise WorkbenchError(
            "USalign output lacks its scores, aligned length or transform"
        )
    rotation = np.asarray([rows[i][1:] for i in range(3)])
    translation = np.asarray([rows[i][0] for i in range(3)])
    rmsd = float(aligned.group(2))
    if (
        not all(np.isfinite(value) and 0 <= value <= 1 for value in scores[:2])
        or not np.isfinite(rmsd)
        or rmsd < 0
        or int(aligned.group(1)) < 3
        or not np.isfinite(translation).all()
        or not np.isfinite(rotation).all()
        or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3)
        or not np.isclose(np.linalg.det(rotation), 1, atol=1e-3)
    ):
        raise WorkbenchError("USalign returned invalid scores or a non-rigid transform")
    return {
        "rotation": rotation.tolist(),
        "translation": translation.tolist(),
        "rmsd": rmsd,
        "aligned_atoms": int(aligned.group(1)),
        "tm_mobile": scores[0],
        "tm_reference": scores[1],
        "tool_version": (
            re.search(r"(?:US-align|TM-align)\s*\(Version\s+([^)]+)", text).group(1)
            if re.search(r"(?:US-align|TM-align)\s*\(Version\s+([^)]+)", text)
            else "unreported; inspect retained stdout"
        ),
        "aligned_sequence_identity": (
            float(
                re.search(r"Seq_ID=n_identical/n_aligned=\s*([0-9.]+)", text).group(1)
            )
            if re.search(r"Seq_ID=n_identical/n_aligned=\s*([0-9.]+)", text)
            else None
        ),
    }


def write_ca_pdb(*, path: Path, rows: list[dict]) -> None:
    """Write a selected protein C-alpha trace for the external aligner.

    Args:
        path: Output PDB file.
        rows: Selected residue/coordinate records.
    """
    lines = []
    for index, row in enumerate(rows, start=1):
        x, y, z = row["xyz"]
        lines.append(
            f"ATOM  {index:5d}  CA  {row['residue_name']:>3s} A{index:4d}   "
            f" {x:8.3f}{y:8.3f}{z:8.3f}{1:6.2f}{(row.get('plddt') or 0):6.2f}         "
            "  C  "
        )
    path.write_text("\n".join(lines) + "\nTER\nEND\n", encoding="utf-8")


def transform_pdb(
    *, source: Path, output: Path, rotation: list, translation: list
) -> None:
    """Apply the fitted rigid transform to every atom of the mobile model.

    Args:
        source: Prepared all-atom PDB.
        output: Transformed all-atom PDB.
        rotation: Validated 3 by 3 rotation.
        translation: Three-dimensional translation.
    """
    model = gemmi.read_structure(str(source))
    matrix, vector = np.asarray(rotation), np.asarray(translation)
    for chain in model[0]:
        for residue in chain:
            for atom in residue:
                point = np.asarray(list(atom.pos)) @ matrix.T + vector
                atom.pos = gemmi.Position(*point)
    model.write_pdb(str(output))


def compare_pair(
    *,
    root: Path,
    data: dict,
    reference: str,
    mobile: str,
    settings: ComparisonSettings,
    usalign: str = "USalign",
    tmalign: str = "TMalign",
) -> dict:
    """Superpose one pair and compare independent ranked fpocket cavities.

    Args:
        root: Workbench resource directory.
        data: Current project data.
        reference: Reference model ID.
        mobile: Mobile model ID.
        settings: Explicit confidence, domain and matching choices.
        usalign: USalign executable path/name.
        tmalign: TMalign executable path/name.

    Returns:
        Complete result, including per-pocket matches and retained file paths.
    """
    models = {row["sample_id"]: row for row in data["models"]}
    if reference == mobile or reference not in models or mobile not in models:
        raise WorkbenchError("Select two different existing models")
    ref_model, mob_model = models[reference], models[mobile]
    if not ref_model.get("coordinates") or not mob_model.get("coordinates"):
        raise WorkbenchError("Upload model coordinates before running a 3D comparison")
    ref = json.loads(inside(root=root, relative=ref_model["coordinates"]).read_text())
    mob = json.loads(inside(root=root, relative=mob_model["coordinates"]).read_text())
    pairs = sequence_pairs(
        reference=ref_model["sequence"], mobile=mob_model["sequence"]
    )
    reference_domain = {
        i
        for i, row in enumerate(ref)
        if settings.start is None
        or settings.start
        <= (row.get("sequence_position") or row["model_position"])
        <= settings.end
    }
    domain_keys = {
        reference: {ref[i]["residue_key"] for i in reference_domain},
        mobile: (
            {row["residue_key"] for row in mob}
            if settings.start is None
            else {mob[j]["residue_key"] for i, j in pairs if i in reference_domain}
        ),
    }
    selected = []
    for i, j in pairs:
        ref_position = ref[i].get("sequence_position") or ref[i]["model_position"]
        if (
            settings.start is not None
            and not settings.start <= ref_position <= settings.end
        ):
            continue
        values = [ref[i].get("plddt"), mob[j].get("plddt")]
        if settings.min_plddt > 0 and any(
            value is None or value < settings.min_plddt for value in values
        ):
            continue
        selected.append((i, j))
    if len(selected) < settings.min_atoms and settings.fit_scope == "paired":
        raise WorkbenchError(
            f"Only {len(selected)} paired C-alpha residues pass the fit selection;"
            f" {settings.min_atoms} required. Review pLDDT/domain settings."
        )
    executable = shutil.which(tmalign if settings.engine == "tmalign" else usalign)
    engine = "usalign" if settings.engine == "auto" and executable else settings.engine
    if engine == "auto":
        engine = "sequence_kabsch"
    if engine in {"usalign", "tmalign"} and executable is None:
        raise WorkbenchError(
            f"{engine} is unavailable; install the pinned structural environment"
        )
    if engine == "sequence_kabsch" and settings.fit_scope != "paired":
        raise WorkbenchError("Global fits require an installed structural aligner")
    pocket_sets = {}
    for identifier in (reference, mobile):
        candidates = [
            row
            for row in data["pockets"]
            if row["sample_id"] == identifier and row["method"] == "fpocket"
        ]
        if settings.confident_only:
            candidates = [
                row
                for row in candidates
                if row.get("confidence_status") == "meets_local_confidence_rule"
            ]
        if settings.quality_screen_only:
            candidates = [
                row
                for row in candidates
                if row.get("quality_screen_pass") is True
                and (row.get("review_rank") or 10**9) <= settings.top_pockets
            ]
        if settings.start is not None:
            candidates = [
                row
                for row in candidates
                if set(row["residues"]) <= domain_keys[identifier]
            ]
        pocket_sets[identifier] = sorted(
            candidates,
            key=lambda row: (row.get("review_rank") or 10**9, int(row["pocket_id"])),
        )[: settings.top_pockets]
    identity = {
        "algorithm_version": "1.2",
        "input_scopes": [ref_model.get("input_scope"), mob_model.get("input_scope")],
        "reference": reference,
        "mobile": mobile,
        "settings": asdict(settings),
        "ref_sha": digest_file(
            path=inside(root=root, relative=ref_model["prepared_model"])
        ),
        "mob_sha": digest_file(
            path=inside(root=root, relative=mob_model["prepared_model"])
        ),
        "ref_coordinates_sha": digest_file(
            path=inside(root=root, relative=ref_model["coordinates"])
        ),
        "mob_coordinates_sha": digest_file(
            path=inside(root=root, relative=mob_model["coordinates"])
        ),
        "engine": engine,
        "executable": executable if engine in {"usalign", "tmalign"} else None,
        "executable_sha": (
            digest_file(path=Path(executable))
            if engine in {"usalign", "tmalign"}
            else None
        ),
        "pockets": pocket_sets,
    }
    identifier = (
        "cmp_"
        + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    )
    directory = root / "comparisons" / identifier
    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / "result.json"
    if result_path.is_file():
        cached = json.loads(result_path.read_text())
        if (
            cached.get("status") == "complete"
            and cached.get("source_identity") == identity
            and all(
                cached.get(key) and inside(root=root, relative=cached[key]).is_file()
                for key in ("mobile_aligned", "viewer_path")
            )
        ):
            LOGGER.info("Reusing completed comparison %s", identifier)
            return cached
    ref_rows, mob_rows = [ref[i] for i, _ in selected], [mob[j] for _, j in selected]
    if settings.fit_scope == "global":
        ref_rows, mob_rows = [
            [
                row
                for row in rows
                if row["residue_key"] in domain_keys[name]
                and (
                    settings.min_plddt == 0
                    or row.get("plddt") is not None
                    and row["plddt"] >= settings.min_plddt
                )
            ]
            for name, rows in [(reference, ref), (mobile, mob)]
        ]
        if min(len(ref_rows), len(mob_rows)) < settings.min_atoms:
            raise WorkbenchError("Too few residues in an independent fit selection")
    if engine in {"usalign", "tmalign"}:
        write_ca_pdb(path=directory / "reference_fit.pdb", rows=ref_rows)
        write_ca_pdb(path=directory / "mobile_fit.pdb", rows=mob_rows)
        command = [
            executable,
            "mobile_fit.pdb",
            "reference_fit.pdb",
            "-m",
            "matrix.txt",
        ]
        LOGGER.info("Running %s in %s", command, directory)
        write_json(
            path=directory / "command.json",
            value={
                "argv": command,
                "cwd": str(directory),
                "timeout": settings.timeout,
                "executable_sha256": identity["executable_sha"],
            },
        )
        try:
            completed = subprocess.run(
                command,
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=settings.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkbenchError(f"USalign could not complete: {error}") from error
        (directory / "stdout.log").write_text(completed.stdout)
        (directory / "stderr.log").write_text(completed.stderr)
        if completed.returncode != 0 or not (directory / "matrix.txt").is_file():
            raise WorkbenchError(
                "USalign failed; inspect its retained stdout/stderr logs"
            )
        fit = parse_usalign(
            text=completed.stdout, matrix=(directory / "matrix.txt").read_text()
        )
    else:
        rotation, translation, rmsd = kabsch(
            reference=np.asarray([row["xyz"] for row in ref_rows]),
            mobile=np.asarray([row["xyz"] for row in mob_rows]),
        )
        fit = {
            "rotation": rotation.tolist(),
            "translation": translation.tolist(),
            "rmsd": rmsd,
            "aligned_atoms": len(selected),
            "tm_mobile": None,
            "tm_reference": None,
        }
    fit.update(
        comparison_id=identifier,
        reference=reference,
        mobile=mobile,
        engine=engine,
        status="complete",
        created_utc=utc_now(),
        settings=asdict(settings),
        reference_coverage=fit["aligned_atoms"] / len(ref),
        mobile_coverage=fit["aligned_atoms"] / len(mob),
        fit_selection_count=len(selected),
        scope=(
            "domain"
            if settings.start
            else (
                (
                    "cleaned_region"
                    if all(
                        models[k].get("input_scope") == "cleaned_region"
                        for k in (reference, mobile)
                    )
                    else "full_model"
                )
                if settings.fit_scope == "global" and settings.min_plddt == 0
                else (
                    "independent_confidence_selection"
                    if settings.fit_scope == "global"
                    else "confidence_selected_sequence_correspondences"
                )
            )
        ),
        reference_fit_residues=len(ref_rows),
        mobile_fit_residues=len(mob_rows),
        source_identity=identity,
        pocket_matches=[],
        result_path=result_path.relative_to(root).as_posix(),
    )
    rotation, translation = np.asarray(fit["rotation"]), np.asarray(fit["translation"])
    ref_by_key = {row["residue_key"]: row for row in ref}
    mob_by_key = {row["residue_key"]: row for row in mob}
    correspondence = {mob[j]["residue_key"]: ref[i]["residue_key"] for i, j in pairs}
    for a, b in itertools.product(pocket_sets[reference], pocket_sets[mobile]):
        ref_keys, mob_keys = set(a["residues"]), set(b["residues"])
        mapped_ref, mapped_mob = (
            sorted(ref_keys & ref_by_key.keys()),
            sorted(mob_keys & mob_by_key.keys()),
        )
        if not mapped_ref or not mapped_mob:
            continue
        geometry = pocket_geometry(
            reference=np.asarray([ref_by_key[key]["xyz"] for key in mapped_ref]),
            mobile=np.asarray([mob_by_key[key]["xyz"] for key in mapped_mob])
            @ rotation.T
            + translation,
            radius=settings.radius,
        )
        intersection = len(ref_keys & {correspondence.get(key) for key in mob_keys})
        complete = len(mapped_ref) == len(ref_keys) and len(mapped_mob) == len(mob_keys)
        position = (
            complete
            and geometry["centroid_distance"] <= settings.max_centroid
            and geometry["symmetric_overlap"] >= settings.min_overlap
        )
        fold = (
            min(fit["tm_mobile"], fit["tm_reference"]) >= settings.min_tm
            if engine in {"usalign", "tmalign"}
            else None
        )
        fit["pocket_matches"].append(
            dict(
                geometry,
                **residue_evidence(
                    reference=[ref_by_key[key] for key in mapped_ref],
                    mobile=[mob_by_key[key] for key in mapped_mob],
                    mobile_xyz=np.asarray(
                        [mob_by_key[key]["xyz"] for key in mapped_mob]
                    )
                    @ rotation.T
                    + translation,
                    radius=settings.radius,
                ),
                reference_pocket=int(a["pocket_id"]),
                mobile_pocket=int(b["pocket_id"]),
                reference_rank=a.get("review_rank"),
                mobile_rank=b.get("review_rank"),
                reference_residues=mapped_ref,
                mobile_residues=mapped_mob,
                complete_mapping=complete,
                position_supported=position,
                fold_supported=fold,
                sequence_jaccard=intersection
                / (len(ref_keys) + len(mob_keys) - intersection),
                reference_confidence=a.get("confidence_status"),
                mobile_confidence=b.get("confidence_status"),
                reference_mapping_fraction=len(mapped_ref) / len(ref_keys),
                mobile_mapping_fraction=len(mapped_mob) / len(mob_keys),
            )
        )
    fit["pocket_matches"].sort(
        key=lambda row: (
            -row["symmetric_overlap"],
            row["centroid_distance"],
            row["reference_pocket"],
            row["mobile_pocket"],
        )
    )
    transform_pdb(
        source=inside(root=root, relative=mob_model["prepared_model"]),
        output=directory / "mobile_aligned.pdb",
        rotation=fit["rotation"],
        translation=fit["translation"],
    )
    fit["mobile_aligned"] = (
        (directory / "mobile_aligned.pdb").relative_to(root).as_posix()
    )
    from .viewers import model_viewer_records, structure_document

    viewer_path = directory / "viewer.html"
    viewer_path.write_text(
        structure_document(
            reference_pdb=inside(
                root=root, relative=ref_model["prepared_model"]
            ).read_text(),
            mobile_pdb=(directory / "mobile_aligned.pdb").read_text(),
            reference_label=reference,
            mobile_label=mobile,
            reference_metadata=model_viewer_records(
                root=root, model=ref_model, pockets=data["pockets"]
            ),
            mobile_metadata=model_viewer_records(
                root=root, model=mob_model, pockets=data["pockets"]
            ),
            match=fit["pocket_matches"][0] if fit["pocket_matches"] else None,
            summary=(
                f"{engine}; RMSD {fit['rmsd']:.3f} Å over {fit['aligned_atoms']} CA"
                " atoms. Pocket proximity compares lining CA coordinates."
            ),
        ),
        encoding="utf-8",
    )
    fit["viewer_path"] = viewer_path.relative_to(root).as_posix()
    write_json(path=result_path, value=fit)
    return fit


def compare_batch(
    *,
    root: Path,
    pairs: list[tuple[str, str]],
    settings: ComparisonSettings,
    usalign: str = "USalign",
    tmalign: str = "TMalign",
    workers: int = 1,
) -> list[dict]:
    """Run a bounded comparison batch while retaining individual failures.

    Args:
        root: Project directory.
        pairs: Ordered reference/mobile ID pairs.
        settings: Shared comparison choices.
        usalign: USalign executable.
        tmalign: TMalign executable.
        workers: Concurrent independent fits; one parent writes the database.

    Returns:
        Results in input order, including failed records with reasons.
    """
    if not pairs or len(pairs) > 2000 or len(set(pairs)) != len(pairs):
        raise WorkbenchError("Choose 1–2,000 unique structure pairs")
    if type(workers) is not int or not 1 <= workers <= 128:
        raise WorkbenchError("Choose 1–128 comparison workers")
    data = load_project(root=root)

    def run_pair(pair: tuple[str, str]) -> dict:
        """Compute one independent fit without updating shared database state."""
        reference, mobile = pair
        LOGGER.info("Comparing %s to %s", mobile, reference)
        try:
            result = compare_pair(
                root=root,
                data=data,
                reference=reference,
                mobile=mobile,
                settings=settings,
                usalign=usalign,
                tmalign=tmalign,
            )
        except (ValueError, OSError, RuntimeError) as error:
            LOGGER.exception("Comparison failed")
            identifier = (
                "failed_"
                + hashlib.sha256(
                    json.dumps([reference, mobile, asdict(settings)]).encode()
                ).hexdigest()[:20]
            )
            relative = f"comparisons/{identifier}/result.json"
            result = {
                "comparison_id": identifier,
                "reference": reference,
                "mobile": mobile,
                "engine": settings.engine,
                "status": "failed",
                "error": str(error),
                "settings": asdict(settings),
                "result_path": relative,
                "pocket_matches": [],
            }
            write_json(path=root / relative, value=result)
        return result

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(run_pair, pairs))

    def assessment_key(record: dict) -> tuple:
        """Identify one pair and fully defaulted analysis scope for replacement."""
        values = asdict(ComparisonSettings(**record.get("settings", {})))
        return record["reference"], record["mobile"], json.dumps(values, sort_keys=True)

    replaced = {assessment_key(result) for result in results}
    data["comparisons"] = [
        row
        for row in data["comparisons"]
        if assessment_key(
            json.loads(inside(root=root, relative=row["result_path"]).read_text())
        )
        not in replaced
    ]
    for index, result in enumerate(results, start=1):
        LOGGER.info(
            "Collected comparison %s/%s: %s", index, len(results), result["status"]
        )
        data["comparisons"] = [
            row
            for row in data["comparisons"]
            if row["comparison_id"] != result["comparison_id"]
        ]
        data["comparisons"].append(
            {
                key: result.get(key)
                for key in (
                    "comparison_id",
                    "reference",
                    "mobile",
                    "engine",
                    "status",
                    "error",
                    "result_path",
                    "rmsd",
                )
            }
        )
    save_project(root=root, data=data)
    return results
