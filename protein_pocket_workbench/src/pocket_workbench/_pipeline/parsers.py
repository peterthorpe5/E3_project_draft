"""Strict fpocket/P2Rank parsing, local confidence and within-model overlap."""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path

from .io import write_tsv
from .models import Settings


def finite_number(*, value: str, field: str) -> float:
    """Parse one mandatory finite numeric result.

    Args:
        value: Tool output text.
        field: Name for errors.

    Returns:
        Finite float.

    Raises:
        ValueError: For missing, non-numeric or non-finite values.
    """
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite {field}: {value}")
    return result


def read_tool_table(*, path: Path) -> list[dict[str, str]]:
    """Read native P2Rank CSV or its normalised TSV with stripped headers.

    Args:
        path: Prediction or residue table.

    Returns:
        Raw string records; a header-only table is a valid empty prediction.
    """
    with path.open(mode="r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(
            f=handle, delimiter="\t" if path.suffix == ".tsv" else ","
        )
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(
            reader.fieldnames
        ):
            raise ValueError(f"Missing or duplicate table headers: {path}")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed tool table: {path}")
            rows.append({key.strip(): value.strip() for key, value in row.items()})
    return rows


def convert_native_tables(*, directory: Path) -> None:
    """Convert all native tool CSV files to TSV, leaving no CSV deliverables.

    Args:
        directory: One completed tool run's output folder.
    """
    # Snapshot the listing before creating/removing entries in the same folders.
    # Live directory iteration can skip files on some filesystem implementations.
    for path in sorted(directory.rglob("*.csv")):
        with path.open(mode="r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            values = list(reader)
        if not values:
            path.with_suffix(".tsv").write_text(data="", encoding="utf-8")
        else:
            with path.with_suffix(".tsv").open(
                mode="w", encoding="utf-8", newline=""
            ) as handle:
                csv.writer(handle, delimiter="\t").writerows(values)
        path.unlink()


def parse_fpocket(*, directory: Path, sample_id: str) -> list[dict]:
    """Read one fpocket output directory, including all numeric descriptors.

    Args:
        directory: Directory containing exactly one *_info.txt.
        sample_id: Model identifier.

    Returns:
        Pocket dictionaries with original descriptors and lining residue IDs.

    Raises:
        ValueError: For missing/duplicate pockets or malformed metric records.
    """
    files = list(directory.glob("*_info.txt"))
    if len(files) != 1:
        raise ValueError("Expected exactly one fpocket *_info.txt output")
    pockets = []
    current = None
    for line in files[0].read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\s*Pocket\s+(\d+)\s*:?\s*", line, flags=re.I)
        if match:
            current = {
                "sample_id": sample_id,
                "method": "fpocket",
                "pocket_id": int(match.group(1)),
                "metrics": {},
            }
            pockets.append(current)
        elif current is not None and ":" in line:
            name, value = line.split(":", maxsplit=1)
            key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            if key in current["metrics"]:
                raise ValueError(f"Duplicate fpocket metric: {key}")
            current["metrics"][key] = finite_number(value=value.strip(), field=key)
    identifiers = [pocket["pocket_id"] for pocket in pockets]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Duplicate fpocket pocket numbers")
    for pocket in pockets:
        metrics = pocket["metrics"]
        required = {"score", "druggability_score", "volume"}
        if not required <= metrics.keys():
            raise ValueError("fpocket is missing score, druggability_score or volume")
        if not 0 <= metrics["druggability_score"] <= 1 or metrics["volume"] < 0:
            raise ValueError("Invalid fpocket druggability or volume")
        pocket.update(
            {
                "rank": pocket["pocket_id"],
                "score": metrics["score"],
                "druggability_score": metrics["druggability_score"],
                "volume_a3": metrics["volume"],
                "probability": None,
                "fpocket_pocket_id": None,
                "residues": [],
                "centre_x": None,
                "centre_y": None,
                "centre_z": None,
            }
        )
        atom_path = directory / "pockets" / f"pocket{pocket['pocket_id']}_atm.pdb"
        if not atom_path.is_file():
            raise ValueError(f"Missing fpocket pocket atoms: {atom_path}")
        keys = set()
        for line in atom_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ATOM  "):
                if len(line) < 27 or line[26].strip():
                    raise ValueError("Unexpected fpocket residue numbering")
                keys.add(f"{line[21].strip()}_{int(line[22:26])}")
        pocket["residues"] = sorted(
            keys, key=lambda key: (key.split("_")[0], int(key.split("_")[1]))
        )
        if not keys:
            raise ValueError("fpocket pocket has no protein lining residues")
    return pockets


def parse_p2rank(
    *, path: Path, sample_id: str, method: str, valid_fpocket_ids: set[int]
) -> list[dict]:
    """Read predictions while separating rescored cavities from new predictions.

    Args:
        path: P2Rank predictions CSV or normalised TSV.
        sample_id: Model identifier.
        method: 'p2rank' or 'p2rank_rescore'.
        valid_fpocket_ids: Permitted original cavity IDs for rescoring.

    Returns:
        Normalised pocket records retaining original raw fields.
    """
    if method not in {"p2rank", "p2rank_rescore"}:
        raise ValueError(f"Unknown P2Rank method: {method}")
    rows = read_tool_table(path=path)
    # Validate empty prediction tables too; an arbitrary header is not success.
    with path.open(mode="r", encoding="utf-8-sig", newline="") as handle:
        header = next(
            csv.reader(handle, delimiter="\t" if path.suffix == ".tsv" else ",")
        )
    required = {"name", "rank", "score", "probability", "residue_ids"}
    if not required <= {value.strip() for value in header}:
        raise ValueError("P2Rank predictions are missing required columns")
    pockets = []
    seen = set()
    for row in rows:
        numeric_rank = finite_number(value=row["rank"], field="rank")
        if not numeric_rank.is_integer() or numeric_rank < 1 or numeric_rank in seen:
            raise ValueError("P2Rank pocket ranks must be unique positive integers")
        rank = int(numeric_rank)
        seen.add(rank)
        probability = finite_number(value=row["probability"], field="probability")
        if not 0 <= probability <= 1:
            raise ValueError("P2Rank probability lies outside [0, 1]")
        residues = row["residue_ids"].split()
        if not residues or any(
            not re.fullmatch(r"[A-Za-z0-9]_\d+", key) for key in residues
        ):
            raise ValueError("P2Rank pocket has missing or malformed residue_ids")
        original = None
        if method == "p2rank_rescore":
            # The P2Rank name preserves the original fpocket cavity ID. Never
            # join by the new rank: rescoring deliberately changes that rank.
            match = re.fullmatch(r"pocket\.?([0-9]+)", row["name"])
            if match is None:
                raise ValueError("Cannot recover original fpocket ID from P2Rank name")
            original = int(match.group(1))
            if original not in valid_fpocket_ids:
                raise ValueError("Rescored pocket refers to an unknown fpocket cavity")
        pocket = {
            "sample_id": sample_id,
            "method": method,
            "pocket_id": rank,
            "rank": rank,
            "score": finite_number(value=row["score"], field="score"),
            "probability": probability,
            "druggability_score": None,
            "volume_a3": None,
            "fpocket_pocket_id": original,
            "residues": sorted(
                set(residues),
                key=lambda key: (key.split("_")[0], int(key.split("_")[1])),
            ),
            "metrics": row,
        }
        for axis in "xyz":
            pocket[f"centre_{axis}"] = (
                finite_number(value=row[f"center_{axis}"], field=f"center_{axis}")
                if row.get(f"center_{axis}")
                else None
            )
        pockets.append(pocket)
    if method == "p2rank_rescore" and len(
        {p["fpocket_pocket_id"] for p in pockets}
    ) != len(pockets):
        raise ValueError("Duplicate original fpocket IDs in rescoring output")
    return pockets


def annotate_pockets(
    *, pockets: list[dict], residues: list[dict], settings: Settings
) -> tuple[list[dict], list[dict]]:
    """Attach local pLDDT using all predicted residues as the denominator.

    Args:
        pockets: Parsed pocket records.
        residues: Prepared-to-original residue map.
        settings: Explicit confidence thresholds.

    Returns:
        Pocket records and a normalised pocket-to-residue membership table.
    """
    lookup = {row["residue_key"]: row for row in residues}
    membership = []
    for pocket in pockets:
        keys = pocket["residues"]
        mapped = [lookup[key] for key in keys if key in lookup]
        confidences = [row["plddt"] for row in mapped if row["plddt"] is not None]
        fraction = (
            sum(value >= settings.high_confidence for value in confidences) / len(keys)
            if settings.confidence == "plddt" and keys
            else None
        )
        if len(mapped) != len(keys):
            confidence_status = "unmapped_residues"
        elif fraction is None:
            confidence_status = "not_assessed"
        elif fraction >= settings.pocket_fraction:
            confidence_status = "meets_local_confidence_rule"
        else:
            confidence_status = "low_local_confidence"
        pocket.update(
            {
                "residue_count": len(keys),
                "mapped_residue_count": len(mapped),
                "unmapped_residue_count": len(keys) - len(mapped),
                "mean_plddt": sum(confidences) / len(confidences)
                if confidences
                else None,
                "fraction_ge_threshold": fraction,
                "confidence_status": confidence_status,
                "residue_ids": ";".join(keys),
            }
        )
        for key in keys:
            row = lookup.get(key, {})
            membership.append(
                {
                    "sample_id": pocket["sample_id"],
                    "method": pocket["method"],
                    "pocket_id": pocket["pocket_id"],
                    "residue_key": key,
                    "mapped": key in lookup,
                    "plddt": row.get("plddt"),
                    "author_chain": row.get("author_chain"),
                    "author_residue_number": row.get("author_residue_number"),
                    "insertion_code": row.get("insertion_code"),
                    "fasta_position": row.get("fasta_position"),
                }
            )
    return pockets, membership


def match_pockets(*, pockets: list[dict], threshold: float) -> list[dict]:
    """Report all within-model fpocket/P2Rank residue overlaps above a threshold.

    Args:
        pockets: One model's pockets; rescoring is excluded from this comparison.
        threshold: Minimum Jaccard index.

    Returns:
        Many-to-many overlap records, never a claim of cross-species homology.
    """
    matches = []
    for first in (p for p in pockets if p["method"] == "fpocket"):
        for second in (p for p in pockets if p["method"] == "p2rank"):
            left, right = set(first["residues"]), set(second["residues"])
            shared = len(left & right)
            union = len(left | right)
            jaccard = shared / union if union else 0.0
            if jaccard >= threshold:
                matches.append(
                    {
                        "sample_id": first["sample_id"],
                        "fpocket_pocket_id": first["pocket_id"],
                        "p2rank_pocket_id": second["pocket_id"],
                        "shared_residue_count": shared,
                        "union_residue_count": union,
                        "jaccard": jaccard,
                    }
                )
    return sorted(matches, key=lambda row: (-row["jaccard"], row["fpocket_pocket_id"]))


def export_raw_pockets(*, path: Path, pockets: list[dict]) -> None:
    """Export the union of raw descriptor fields without discarding metrics.

    Args:
        path: TSV destination.
        pockets: Parsed pockets with original metric dictionaries.
    """
    fields = sorted({key for pocket in pockets for key in pocket["metrics"]})
    rows = [
        {"pocket_id": pocket["pocket_id"], **pocket["metrics"]} for pocket in pockets
    ]
    write_tsv(path=path, rows=rows, columns=["pocket_id", *fields])
