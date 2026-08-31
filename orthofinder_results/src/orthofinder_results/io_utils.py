"""Defensive I/O, checksum, logging and tabular publication helpers."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import logging
import os
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from . import __schema_version__
from .errors import InputValidationError, PublicationError

_LOGGER = logging.getLogger("orthofinder_results.io")
_RELATION_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def configure_logging(*, log_path: Path | None = None, verbose: bool = False) -> None:
    """Configure consistent console and optional file logging.

    Args:
        log_path: Optional persistent log file.
        verbose: Emit debug messages when true.
    """

    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_path is not None:
        destination = Path(log_path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(destination, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def utc_now_iso() -> str:
    """Return the current UTC timestamp in a stable representation.

    Returns:
        ISO-8601 UTC timestamp.
    """

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_persistent_path(*, path: Path, role: str) -> Path:
    """Resolve a path and reject implicit system-temporary storage.

    Args:
        path: User-declared path.
        role: Human-readable path role.

    Returns:
        Resolved path.

    Raises:
        InputValidationError: If the path is under a prohibited system temporary directory.
    """

    resolved = Path(path).expanduser().resolve()
    prohibited = (Path("/tmp"), Path("/private/tmp"))
    if any(resolved == root or root in resolved.parents for root in prohibited):
        raise InputValidationError(
            f"{role} must use explicit persistent storage, not a system temporary directory: "
            f"{resolved}"
        )
    return resolved


def sha256_file(*, path: Path, block_size: int = 1024 * 1024) -> str:
    """Calculate a SHA-256 digest without loading a file into memory.

    Args:
        path: File to digest.
        block_size: Number of bytes read per block.

    Returns:
        Lower-case hexadecimal SHA-256 digest.

    Raises:
        ValueError: If ``block_size`` is not positive.
        InputValidationError: If the source is not a regular file.
    """

    if block_size <= 0:
        raise ValueError("block_size must be positive.")
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise InputValidationError(f"Cannot checksum missing file: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def file_record(*, path: Path, relative_to: Path | None = None) -> dict[str, Any]:
    """Return portable size and checksum provenance for a file.

    Args:
        path: File to inventory.
        relative_to: Optional root used for the published path.

    Returns:
        Path, size and SHA-256 record.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise InputValidationError(f"Cannot inventory missing file: {source}")
    display_path = source
    if relative_to is not None:
        display_path = Path(os.path.relpath(source, Path(relative_to).expanduser().resolve()))
    return {
        "path": str(display_path),
        "size_bytes": source.stat().st_size,
        "sha256": sha256_file(path=source),
    }


def atomic_write_text(*, path: Path, text: str) -> None:
    """Write UTF-8 text through a same-directory temporary file.

    Args:
        path: Final file path.
        text: Complete text content.
    """

    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.writing")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, destination)


def atomic_write_json(*, path: Path, record: Mapping[str, Any]) -> None:
    """Write a deterministic JSON object atomically.

    Args:
        path: Final JSON path.
        record: JSON-serialisable mapping.
    """

    atomic_write_text(path=path, text=json.dumps(record, indent=2, sort_keys=True) + "\n")


def open_text(*, path: Path, mode: str) -> TextIO:
    """Open UTF-8 text, transparently handling a ``.gz`` suffix.

    Args:
        path: Plain-text or gzip-compressed file path.
        mode: Text operation: ``r``, ``w`` or ``a``.

    Returns:
        Open text handle. The caller owns the context lifetime.

    Raises:
        ValueError: If the requested mode is unsupported.
    """

    if mode not in {"r", "w", "a"}:
        raise ValueError("mode must be 'r', 'w' or 'a'.")
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix == ".gz":
        return gzip.open(
            resolved,
            mode=f"{mode}t",
            compresslevel=6,
            encoding="utf-8",
            newline="",
        )
    return resolved.open(mode=mode, encoding="utf-8", newline="")


def write_tsv(
    *,
    path: Path,
    fieldnames: tuple[str, ...],
    records: Iterable[Mapping[str, Any]],
) -> int:
    """Write a tab-separated authority and return its row count.

    Args:
        path: Destination TSV path.
        fieldnames: Ordered output columns.
        records: Row mappings.

    Returns:
        Number of data rows written.

    Raises:
        ValueError: If no fields are declared.
    """

    if not fieldnames:
        raise ValueError("At least one TSV field is required.")
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with open_text(path=destination, mode="w") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for record in records:
            writer.writerow({field: _tsv_scalar(record.get(field)) for field in fieldnames})
            row_count += 1
    return row_count


def read_tsv(*, path: Path) -> Iterable[dict[str, str]]:
    """Yield rows from a validated tab-separated file.

    Args:
        path: Input TSV path.

    Yields:
        String-valued row mappings.

    Raises:
        InputValidationError: If the file is absent or has no header.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise InputValidationError(f"TSV file does not exist: {source}")
    with open_text(path=source, mode="r") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise InputValidationError(f"TSV file has no header: {source}")
        yield from reader


def tsv_to_parquet(
    *,
    tsv_path: Path,
    parquet_path: Path,
    column_types: Mapping[str, str] | None = None,
    block_size: int = 16 * 1024 * 1024,
) -> int:
    """Stream a TSV authority into a typed Parquet table.

    Args:
        tsv_path: Source TSV path.
        parquet_path: Destination Parquet path.
        column_types: Optional Arrow scalar type overrides. Unlisted columns
            are explicitly stored as strings.
        block_size: Streaming input block size in bytes.

    Returns:
        Number of converted data rows.

    Raises:
        PublicationError: If the TSV contains no readable record batches.
    """

    if block_size <= 0:
        raise ValueError("block_size must be positive.")
    import pyarrow as pa
    import pyarrow.csv as pacsv
    import pyarrow.parquet as pq

    source = Path(tsv_path).expanduser().resolve()
    destination = Path(parquet_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        raise PublicationError(f"TSV file does not exist: {source}")
    with open_text(path=source, mode="r") as handle:
        headings = next(csv.reader(handle, delimiter="\t"), None)
    if headings is None:
        raise PublicationError(f"TSV file has no header: {source}")
    if not headings or any(not heading for heading in headings):
        raise PublicationError(f"TSV file has an empty column heading: {source}")
    duplicate_headings = sorted(
        heading for heading in set(headings) if headings.count(heading) > 1
    )
    if duplicate_headings:
        raise PublicationError(
            f"TSV file has duplicate column headings {duplicate_headings}: {source}"
        )
    declared_types = dict(column_types or {})
    unknown_columns = sorted(set(declared_types) - set(headings))
    if unknown_columns:
        raise PublicationError(
            f"Arrow types were declared for absent TSV columns {unknown_columns}: {source}"
        )
    arrow_types = {
        name: _arrow_type(type_name=declared_types.get(name, "string"), pa_module=pa)
        for name in headings
    }
    input_stream = pa.input_stream(str(source), compression="detect")
    try:
        reader = pacsv.open_csv(
            input_stream,
            read_options=pacsv.ReadOptions(block_size=block_size, use_threads=False),
            parse_options=pacsv.ParseOptions(delimiter="\t", quote_char=False),
            convert_options=pacsv.ConvertOptions(
                column_types=arrow_types,
                strings_can_be_null=False,
            ),
        )
    except Exception:
        input_stream.close()
        raise
    writer: pq.ParquetWriter | None = None
    row_count = 0
    try:
        for batch in reader:
            if writer is None:
                writer = pq.ParquetWriter(destination, batch.schema, compression="zstd")
            writer.write_batch(batch)
            row_count += batch.num_rows
    finally:
        if writer is not None:
            writer.close()
        input_stream.close()
    if writer is None:
        schema = pa.schema(
            [pa.field(name, arrow_types.get(name, pa.string())) for name in headings]
        )
        empty = pa.Table.from_batches([], schema=schema)
        pq.write_table(empty, destination, compression="zstd")
    return row_count


def create_duckdb(*, database_path: Path, parquet_tables: Mapping[str, Path]) -> None:
    """Create a portable DuckDB containing materialised Parquet relations.

    Args:
        database_path: Destination DuckDB file.
        parquet_tables: Relation names and source Parquet paths.

    Raises:
        PublicationError: If a relation name is unsafe or a Parquet source is absent.
    """

    import duckdb

    destination = Path(database_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    connection = duckdb.connect(str(destination))
    try:
        for relation, parquet_path in sorted(parquet_tables.items()):
            if _RELATION_PATTERN.fullmatch(relation) is None:
                raise PublicationError(f"Unsafe DuckDB relation name: {relation!r}")
            source = Path(parquet_path).expanduser().resolve()
            if not source.is_file():
                raise PublicationError(f"Missing Parquet source for {relation}: {source}")
            connection.execute(
                f'CREATE TABLE "{relation}" AS SELECT * FROM read_parquet(?)',
                [str(source)],
            )
        connection.execute(
            "CREATE TABLE resource_metadata AS "
            "SELECT ?::VARCHAR AS created_at_utc, ?::INTEGER AS schema_version",
            [utc_now_iso(), __schema_version__],
        )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()


def _tsv_scalar(value: Any) -> Any:
    """Convert optional and Boolean values to unambiguous TSV scalars.

    Args:
        value: Arbitrary scalar.

    Returns:
        TSV-safe scalar.
    """

    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _arrow_type(*, type_name: str, pa_module: Any) -> Any:
    """Resolve a controlled Arrow scalar type name.

    Args:
        type_name: Supported logical type name.
        pa_module: Imported :mod:`pyarrow` module.

    Returns:
        Arrow data type.

    Raises:
        ValueError: If a type name is unsupported.
    """

    factories = {
        "string": pa_module.string,
        "int64": pa_module.int64,
        "float64": pa_module.float64,
        "bool": pa_module.bool_,
    }
    if type_name not in factories:
        raise ValueError(f"Unsupported Arrow type name: {type_name!r}")
    return factories[type_name]()
