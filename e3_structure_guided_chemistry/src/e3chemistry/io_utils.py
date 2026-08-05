"""Atomic TSV, Parquet, JSON and checksum helpers."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from e3chemistry.errors import DependencyError, InputValidationError


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: Any) -> str:
    """Serialise a scalar for a tab-separated output."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_tsv(
    *, path: Path, records: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]
) -> None:
    """Atomically write tab-separated records with a stable schema."""
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fieldnames),
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for record in records:
            writer.writerow({field: _text(record.get(field)) for field in fieldnames})
    temporary.replace(destination)


def read_tsv(path: Path) -> list[dict[str, str]]:
    """Read a non-empty tab-separated table into dictionaries."""
    source = path.expanduser().resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise InputValidationError(f"TSV input is missing or empty: {source}")
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames:
            raise InputValidationError(f"TSV input has no header: {source}")
        return [dict(row) for row in reader]


def _quote_literal(value: Path | str) -> str:
    """Return one single-quoted DuckDB string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read TSV or Parquet records through a bounded local interface."""
    source = path.expanduser().resolve()
    if source.suffix.lower() in {".tsv", ".txt"}:
        return read_tsv(source)
    if source.suffix.lower() != ".parquet":
        raise InputValidationError(f"Input must be TSV or Parquet: {source}")
    if not source.is_file() or source.stat().st_size == 0:
        raise InputValidationError(f"Parquet input is missing or empty: {source}")
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - exercised in dependency tests
        raise DependencyError("DuckDB is required to read Parquet inputs") from exc
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            f"SELECT * FROM read_parquet({_quote_literal(source)})"
        ).fetchall()
        fields = [str(item[0]) for item in connection.description]
    except duckdb.Error as exc:
        raise InputValidationError(f"Could not read Parquet input {source}: {exc}") from exc
    finally:
        connection.close()
    return [dict(zip(fields, row)) for row in rows]


def write_records(
    *,
    tsv_path: Path,
    parquet_path: Path,
    records: Sequence[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    """Write matching TSV and Parquet authorities atomically."""
    write_tsv(path=tsv_path, records=records, fieldnames=fieldnames)
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - exercised in dependency tests
        raise DependencyError("DuckDB is required to publish Parquet outputs") from exc
    destination = parquet_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.unlink(missing_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        if records:
            connection.execute(
                "COPY (SELECT * FROM read_csv_auto("
                f"{_quote_literal(tsv_path.resolve())}, delim='\\t', header=true, "
                "sample_size=-1, all_varchar=false)) TO "
                f"{_quote_literal(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        else:
            columns = ", ".join(
                '"' + field.replace('"', '""') + '" VARCHAR' for field in fieldnames
            )
            connection.execute(f"CREATE TABLE empty_output ({columns})")
            connection.execute(
                f"COPY empty_output TO {_quote_literal(temporary)} "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
    except duckdb.Error as exc:
        temporary.unlink(missing_ok=True)
        raise InputValidationError(
            f"Could not publish Parquet output {destination}: {exc}"
        ) from exc
    finally:
        connection.close()
    temporary.replace(destination)


def write_json(*, path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically write an indented JSON object."""
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def require_columns(
    *, records: Sequence[Mapping[str, Any]], required: Sequence[str], label: str
) -> None:
    """Require named columns even when a table contains no data rows."""
    if not records:
        raise InputValidationError(f"{label} contains no records")
    observed = set(records[0])
    missing = sorted(set(required).difference(observed))
    if missing:
        raise InputValidationError(
            f"{label} is missing required columns: {', '.join(missing)}"
        )
