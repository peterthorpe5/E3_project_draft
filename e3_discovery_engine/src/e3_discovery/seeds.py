"""Known E3 seed-table normalisation and metadata preservation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from e3_discovery.constants import DEFAULT_SEED_COLUMN_CANDIDATES
from e3_discovery.exceptions import DataValidationError
from e3_discovery.io_utils import (
    atomic_binary_path,
    json_dumps_sorted,
    read_delimited,
    write_tsv,
)

LOGGER = logging.getLogger(__name__)


def normalise_seed_identifier(value: str) -> str:
    """Normalise a seed accession for comparison with sequence identifiers."""

    token = str(value or "").strip().split()[0] if str(value or "").strip() else ""
    if not token:
        return ""
    parts = token.split("|")
    if len(parts) >= 3 and parts[0] in {"sp", "tr"} and parts[1]:
        return parts[1]
    return token


def choose_seed_column(
    fieldnames: Sequence[str],
    requested: Optional[str] = None,
) -> str:
    """Choose the accession column explicitly or from recognised candidates."""

    available = list(fieldnames)
    if requested:
        if requested not in available:
            raise DataValidationError(
                f"Requested seed column '{requested}' was not found. "
                f"Available columns: {', '.join(available)}"
            )
        return requested
    for candidate in DEFAULT_SEED_COLUMN_CANDIDATES:
        if candidate in available:
            return candidate
    raise DataValidationError(
        "Could not identify an E3 seed accession column. Available columns: "
        + ", ".join(available)
    )


def seed_schema() -> pa.Schema:
    """Return the stable Arrow schema for normalised known-E3 seeds."""

    return pa.schema(
        [
            ("seed_id", pa.string()),
            ("source_value", pa.string()),
            ("source_column", pa.string()),
            ("source_row", pa.int64()),
            ("source_path", pa.string()),
            ("seed_metadata_json", pa.string()),
        ]
    )


def prepare_seed_table(
    input_path: Path,
    output_tsv: Path,
    output_parquet: Path,
    seed_column: Optional[str] = None,
) -> Dict[str, int]:
    """Normalise and deduplicate known E3 seeds while retaining source metadata."""

    LOGGER.info("Preparing known E3 seed table from %s", input_path)
    rows = read_delimited(input_path)
    if not rows:
        raise DataValidationError(f"E3 seed table contains no data rows: {input_path}")
    column = choose_seed_column(tuple(rows[0]), seed_column)

    unique: Dict[str, Mapping[str, object]] = {}
    blank_count = 0
    duplicate_count = 0
    for source_row, row in enumerate(rows, start=2):
        raw = str(row.get(column, "") or "").strip()
        seed_id = normalise_seed_identifier(raw)
        if not seed_id:
            blank_count += 1
            continue
        record = {
            "seed_id": seed_id,
            "source_value": raw,
            "source_column": column,
            "source_row": source_row,
            "source_path": str(Path(input_path).resolve()),
            "seed_metadata_json": json_dumps_sorted(dict(row)),
        }
        if seed_id in unique:
            duplicate_count += 1
            continue
        unique[seed_id] = record

    if not unique:
        raise DataValidationError("No valid E3 seed accessions were recovered")

    records = [unique[key] for key in sorted(unique)]
    write_tsv(records, output_tsv)
    with atomic_binary_path(output_parquet) as temporary:
        table = pa.Table.from_pylist(records, schema=seed_schema())
        pq.write_table(table, temporary, compression="zstd", use_dictionary=True)

    LOGGER.info(
        "Prepared %d unique E3 seeds (%d duplicate rows, %d blank rows)",
        len(records),
        duplicate_count,
        blank_count,
    )
    return {
        "input_rows": len(rows),
        "unique_seeds": len(records),
        "blank_rows": blank_count,
        "duplicate_rows": duplicate_count,
    }


def seed_ids(records: Iterable[Mapping[str, object]]) -> List[str]:
    """Extract non-empty seed IDs from record dictionaries."""

    return sorted(
        {
            str(record.get("seed_id", "")).strip()
            for record in records
            if str(record.get("seed_id", "")).strip()
        }
    )
