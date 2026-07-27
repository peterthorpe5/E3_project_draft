"""P2Rank prediction discovery and normalisation."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .fpocket import normalise_metric_name, parse_scalar


_DIGITS = re.compile(r"(\d+)")


def discover_prediction_files(root: Path) -> list[Path]:
    """Locate non-empty P2Rank prediction CSV files recursively.

    Args:
        root: Accession-specific tool-output root.

    Returns:
        Sorted prediction CSV paths.
    """

    directory = Path(root).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"P2Rank output directory does not exist: {directory}")
    matches = []
    for path in directory.rglob("*predictions.csv"):
        if path.is_file() and path.stat().st_size > 0:
            matches.append(path.resolve())
    return sorted(matches)


def infer_fpocket_pocket_number(record: dict[str, Any]) -> int | None:
    """Infer the original FPocket pocket number from a P2Rank row.

    Args:
        record: Normalised P2Rank prediction record.

    Returns:
        Original FPocket pocket number when recoverable.
    """

    for key in ("old_rank", "fpocket_rank", "pocket_number"):
        value = record.get(key)
        if value is None or value == "":
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue

    name = str(record.get("name", ""))
    name_match = _DIGITS.search(name)
    if name_match:
        return int(name_match.group(1))
    return None


def parse_prediction_csv(path: Path, accession: str) -> list[dict[str, Any]]:
    """Parse one P2Rank predictions CSV into a stable, auditable schema.

    Args:
        path: P2Rank predictions CSV.
        accession: Protein accession.

    Returns:
        Normalised prediction records.

    Raises:
        FileNotFoundError: If the file is absent.
        ValueError: If the file has no header or no prediction rows.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"P2Rank predictions file does not exist: {source}")

    records: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"P2Rank predictions CSV has no header: {source}")
        for row_number, row in enumerate(reader, start=2):
            original = {
                str(key).strip(): "" if value is None else str(value).strip()
                for key, value in row.items()
                if key is not None
            }
            normalised = {
                normalise_metric_name(key): parse_scalar(value)
                for key, value in original.items()
            }
            normalised.update(
                {
                    "accession": accession,
                    "p2rank_predictions_path": str(source),
                    "p2rank_source_row": row_number,
                    "p2rank_original_row_json": json.dumps(
                        original,
                        sort_keys=True,
                        ensure_ascii=False,
                    ),
                }
            )
            normalised["fpocket_pocket_number"] = infer_fpocket_pocket_number(
                normalised
            )
            records.append(normalised)

    if not records:
        raise ValueError(f"P2Rank predictions CSV has no data rows: {source}")
    return records


def parse_all_prediction_files(
    root: Path,
    accession: str,
) -> list[dict[str, Any]]:
    """Parse all discovered P2Rank prediction files below one output root.

    Args:
        root: Accession-specific P2Rank output root.
        accession: Protein accession.

    Returns:
        Combined prediction records.

    Raises:
        ValueError: If no prediction files are found.
    """

    files = discover_prediction_files(root)
    if not files:
        raise ValueError(f"No P2Rank predictions CSV found under {root}")
    records: list[dict[str, Any]] = []
    for path in files:
        records.extend(parse_prediction_csv(path, accession))
    return records
