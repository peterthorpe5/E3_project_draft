"""Defensive file, checksum and portable table utilities."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from .errors import InputValidationError


def configure_arrow_threads(*, threads: int) -> None:
    """Set explicit limits for the PyArrow compute and I/O thread pools.

    Args:
        threads: Positive number of threads available to Arrow-backed operations.

    Raises:
        ValueError: If ``threads`` is a Boolean or is not positive.
    """

    if isinstance(threads, bool) or not isinstance(threads, int) or threads <= 0:
        raise ValueError("threads must be a positive integer.")
    pa.set_cpu_count(threads)
    pa.set_io_thread_count(threads)


def utc_now_iso() -> str:
    """Return the current UTC time in ISO-8601 form.

    Returns:
        Timezone-aware UTC timestamp.
    """

    return datetime.now(timezone.utc).isoformat()


def sha256_file(*, path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculate a SHA-256 checksum without loading the complete file.

    Args:
        path: Readable input file.
        chunk_size: Number of bytes read per iteration.

    Returns:
        Lower-case hexadecimal SHA-256 digest.

    Raises:
        InputValidationError: If the path is not a readable regular file.
        ValueError: If ``chunk_size`` is not positive.
    """

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")
    source = ensure_readable_file(path=path)
    digest = hashlib.sha256()
    with source.open(mode="rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_readable_file(*, path: Path) -> Path:
    """Resolve and validate a readable, non-empty regular file.

    Args:
        path: Candidate input path.

    Returns:
        Absolute resolved path.

    Raises:
        InputValidationError: If the input is missing, empty or unreadable.
    """

    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise InputValidationError(f"Required file does not exist: {resolved}")
    if resolved.stat().st_size <= 0:
        raise InputValidationError(f"Required file is empty: {resolved}")
    if not os.access(resolved, os.R_OK):
        raise InputValidationError(f"Required file is unreadable: {resolved}")
    return resolved


def atomic_write_text(*, path: Path, text: str) -> None:
    """Write UTF-8 text through a sibling temporary file and atomic rename.

    Args:
        path: Formal destination path.
        text: Complete text content.
    """

    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, mode="w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(*, path: Path, value: Any) -> None:
    """Serialise JSON deterministically and publish it atomically.

    Args:
        path: Formal JSON destination.
        value: JSON-serialisable object.
    """

    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    atomic_write_text(path=path, text=payload)


def canonical_digest(*, value: Any) -> str:
    """Calculate a SHA-256 digest of canonical JSON content.

    Args:
        value: JSON-serialisable object.

    Returns:
        Hexadecimal SHA-256 digest.
    """

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_tsv(
    *,
    path: Path,
    fieldnames: Sequence[str],
    records: Iterable[Mapping[str, Any]],
) -> int:
    """Write dictionaries to a tab-separated table atomically.

    Args:
        path: Formal TSV destination.
        fieldnames: Ordered output column names.
        records: Record iterator.

    Returns:
        Number of data records written.

    Raises:
        ValueError: If no field names are supplied.
    """

    if not fieldnames:
        raise ValueError("At least one TSV field name is required.")
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    count = 0
    try:
        with os.fdopen(descriptor, mode="w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(fieldnames),
                delimiter="\t",
                lineterminator="\n",
                extrasaction="raise",
            )
            writer.writeheader()
            for record in records:
                writer.writerow(
                    {
                        field: "" if record.get(field) is None else record.get(field)
                        for field in fieldnames
                    }
                )
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return count


def tsv_to_parquet(*, tsv_path: Path, parquet_path: Path, block_size: int) -> int:
    """Convert a TSV to Parquet in record batches with atomic publication.

    Args:
        tsv_path: Source tab-separated table.
        parquet_path: Formal Parquet destination.
        block_size: Arrow streaming input block size in bytes.

    Returns:
        Number of Parquet rows written.

    Raises:
        ValueError: If ``block_size`` is not positive.
        InputValidationError: If the TSV is missing or empty.
    """

    if block_size <= 0:
        raise ValueError("block_size must be greater than zero.")
    source = ensure_readable_file(path=tsv_path)
    destination = Path(parquet_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    convert_options = pacsv.ConvertOptions(
        null_values=[],
        strings_can_be_null=False,
    )
    reader = pacsv.open_csv(
        source,
        read_options=pacsv.ReadOptions(block_size=block_size),
        parse_options=pacsv.ParseOptions(delimiter="\t"),
        convert_options=convert_options,
    )
    writer: pq.ParquetWriter | None = None
    row_count = 0
    try:
        for batch in reader:
            table = pa.Table.from_batches([batch])
            if writer is None:
                writer = pq.ParquetWriter(temporary, table.schema, compression="zstd")
            writer.write_table(table)
            row_count += table.num_rows
        if writer is None:
            raise InputValidationError(f"TSV contains no readable batches: {source}")
        writer.close()
        writer = None
        os.replace(temporary, destination)
    except BaseException:
        if writer is not None:
            writer.close()
        temporary.unlink(missing_ok=True)
        raise
    return row_count


def file_record(*, path: Path, include_sha256: bool = True) -> dict[str, Any]:
    """Build a stable path, size and optional checksum record.

    Args:
        path: Formal file path.
        include_sha256: Whether to calculate SHA-256.

    Returns:
        JSON-serialisable file record.
    """

    source = ensure_readable_file(path=path)
    return {
        "path": str(source),
        "bytes": source.stat().st_size,
        "sha256": sha256_file(path=source) if include_sha256 else None,
    }


def link_or_copy(*, source: Path, destination: Path) -> str:
    """Publish a file through a hard link, falling back to a metadata copy.

    Args:
        source: Existing source file.
        destination: New destination path.

    Returns:
        Publication method, ``hard_link`` or ``copy2``.

    Raises:
        FileExistsError: If the destination already exists.
    """

    input_path = ensure_readable_file(path=source)
    output_path = Path(destination).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(f"Publication destination already exists: {output_path}")
    try:
        os.link(input_path, output_path)
        return "hard_link"
    except OSError:
        shutil.copy2(input_path, output_path)
        return "copy2"
