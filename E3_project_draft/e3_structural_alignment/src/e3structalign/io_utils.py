"""Validated file, table, checksum and logging utilities."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from e3structalign.errors import InputValidationError, StructuralAlignmentError

LOGGER_NAME = "e3structalign"


def utc_now() -> str:
    """Return the current UTC timestamp in a stable ISO-8601 representation."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_input_file(path: Path, label: str) -> Path:
    """Return an existing, non-empty input file.

    Args:
        path: User-supplied input path.
        label: Human-readable input name for error messages.

    Returns:
        Absolute input path.

    Raises:
        InputValidationError: If the path is missing, not a file or empty.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise InputValidationError(f"{label} is missing or empty: {resolved}")
    return resolved


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of one file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write deterministic JSON through an atomic same-directory replacement."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial.{os.getpid()}")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(destination)


def quote_literal(value: Path | str) -> str:
    """Return one safely quoted DuckDB string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def quote_identifier(value: str) -> str:
    """Return one safely quoted DuckDB identifier."""
    return '"' + value.replace('"', '""') + '"'


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read one Parquet or tab-separated table into row dictionaries."""
    source = resolve_input_file(path, "table")
    connection = duckdb.connect(":memory:")
    try:
        if source.suffix.lower() == ".parquet":
            relation = f"read_parquet({quote_literal(source)})"
        elif source.suffix.lower() in {".tsv", ".txt"}:
            relation = (
                f"read_csv({quote_literal(source)}, delim='\\t', header=true, "
                "all_varchar=true, quote='\"')"
            )
        else:
            raise InputValidationError(
                f"Unsupported table format; expected Parquet or TSV: {source}"
            )
        rows = connection.execute(f"SELECT * FROM {relation}").fetchall()
        fields = [str(column[0]) for column in connection.description]
        return [dict(zip(fields, row)) for row in rows]
    except duckdb.Error as exc:
        raise InputValidationError(f"Could not read table {source}: {exc}") from exc
    finally:
        connection.close()


def require_columns(
    records: Sequence[Mapping[str, Any]],
    required: Sequence[str],
    label: str,
) -> None:
    """Require a non-empty record set containing every named column."""
    if not records:
        raise InputValidationError(f"{label} contains no rows")
    observed = set(records[0])
    missing = sorted(set(required).difference(observed))
    if missing:
        raise InputValidationError(
            f"{label} is missing required columns: {', '.join(missing)}"
        )


def write_tsv(
    path: Path,
    records: Sequence[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    """Write a UTF-8 tab-separated table atomically."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial.{os.getpid()}")
    with temporary.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    field: "" if record.get(field) is None else record.get(field)
                    for field in fieldnames
                }
            )
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(destination)


def write_table(
    *,
    tsv_path: Path,
    parquet_path: Path,
    records: Sequence[Mapping[str, Any]],
    schema: Sequence[tuple[str, str]],
) -> None:
    """Publish matching TSV and typed Parquet tables."""
    fields = tuple(field for field, _ in schema)
    write_tsv(path=tsv_path, records=records, fieldnames=fields)
    destination = Path(parquet_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial.{os.getpid()}")
    column_sql = ", ".join(
        f"{quote_identifier(field)} {data_type}" for field, data_type in schema
    )
    placeholders = ", ".join("?" for _ in fields)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"CREATE TABLE output ({column_sql})")
        if records:
            values = [
                tuple(record.get(field) for field in fields)
                for record in records
            ]
            connection.executemany(
                f"INSERT INTO output VALUES ({placeholders})",
                values,
            )
        connection.execute(
            f"COPY output TO {quote_literal(temporary)} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        temporary.replace(destination)
    except duckdb.Error as exc:
        temporary.unlink(missing_ok=True)
        raise StructuralAlignmentError(
            f"Could not publish Parquet table {destination}: {exc}"
        ) from exc
    finally:
        connection.close()


def safe_filename(value: str, maximum_length: int = 180) -> str:
    """Return a portable filename component for a controlled identifier."""
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in value
    )
    return (cleaned[:maximum_length] or "item").strip(".") or "item"


def configure_logging(path: Path, verbose: bool) -> logging.Logger:
    """Configure file and console logging for one invocation."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    file_handler = logging.FileHandler(destination, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


def close_logger(logger: logging.Logger) -> None:
    """Flush, close and detach every logger handler."""
    for handler in list(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)


def output_inventory(root: Path, excluded_names: frozenset[str]) -> list[dict[str, Any]]:
    """Return deterministic checksums for every regular output file."""
    base = Path(root).expanduser().resolve()
    return [
        {
            "path": str(path.relative_to(base)),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(base.rglob("*"))
        if path.is_file() and path.name not in excluded_names
    ]
