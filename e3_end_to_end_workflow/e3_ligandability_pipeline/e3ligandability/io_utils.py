"""Safe file-system and tabular I/O helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq


_ACCESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def ensure_directory(path: Path) -> Path:
    """Create and return an absolute directory path.

    Args:
        path: Directory path to create.

    Returns:
        Resolved directory path.
    """

    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically using a temporary sibling file.

    Args:
        path: Destination path.
        text: UTF-8 text to write.
    """

    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    """Serialise JSON deterministically and write it atomically.

    Args:
        path: Destination JSON path.
        payload: JSON-serialisable object.
    """

    text = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    atomic_write_text(path, f"{text}\n")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculate the SHA-256 digest of a file without loading it into memory.

    Args:
        path: File to hash.
        chunk_size: Number of bytes read per iteration.

    Returns:
        Lower-case hexadecimal SHA-256 digest.

    Raises:
        FileNotFoundError: If the input file does not exist.
        ValueError: If chunk size is not positive.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Cannot hash missing file: {source}")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")

    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def validate_accession(accession: str) -> str:
    """Normalise and validate an accession used in paths and identifiers.

    Args:
        accession: Raw accession string.

    Returns:
        Stripped accession.

    Raises:
        ValueError: If the accession is empty or contains unsafe characters.
    """

    normalised = accession.strip()
    if not normalised:
        raise ValueError("Accession cannot be empty.")
    if not _ACCESSION_PATTERN.fullmatch(normalised):
        raise ValueError(
            "Accession contains unsupported characters or is too long: "
            f"{normalised!r}"
        )
    return normalised


def _detect_delimiter(path: Path) -> str:
    """Detect tab or comma delimiters from a file suffix or sample.

    Args:
        path: Candidate delimited-text file.

    Returns:
        Delimiter character.
    """

    suffix = path.suffix.lower()
    if suffix in {".tsv", ".tab"}:
        return "\t"
    if suffix == ".csv":
        return ","

    sample = path.read_text(encoding="utf-8", errors="strict")[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
    except csv.Error:
        return "\t"
    return dialect.delimiter


def read_accession_records(
    path: Path,
    accession_column: str = "accession",
) -> list[dict[str, str]]:
    """Read accession records from plain text, TSV or CSV input.

    Plain-text input is interpreted as one accession per non-empty,
    non-comment line. Delimited input must contain the configured accession
    column. Duplicate accessions are rejected because silent duplication would
    duplicate downstream work and outputs.

    Args:
        path: Input file.
        accession_column: Required accession column for delimited input.

    Returns:
        Ordered accession records represented as string dictionaries.

    Raises:
        FileNotFoundError: If the input file is absent.
        ValueError: If the input is empty, malformed or contains duplicates.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Accession input does not exist: {source}")

    suffix = source.suffix.lower()
    records: list[dict[str, str]] = []

    if suffix == ".txt":
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            accession = validate_accession(stripped)
            records.append(
                {
                    accession_column: accession,
                    "input_line_number": str(line_number),
                }
            )
    else:
        delimiter = _detect_delimiter(source)
        with source.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if reader.fieldnames is None:
                raise ValueError(f"Input has no header: {source}")
            if accession_column not in reader.fieldnames:
                raise ValueError(
                    f"Missing accession column {accession_column!r} in {source}"
                )
            for line_number, row in enumerate(reader, start=2):
                accession = validate_accession(row.get(accession_column, ""))
                cleaned = {
                    str(key): "" if value is None else str(value).strip()
                    for key, value in row.items()
                    if key is not None
                }
                cleaned[accession_column] = accession
                cleaned["input_line_number"] = str(line_number)
                records.append(cleaned)

    if not records:
        raise ValueError(f"No accessions were found in {source}")

    seen: set[str] = set()
    duplicates: list[str] = []
    for record in records:
        accession = record[accession_column]
        if accession in seen:
            duplicates.append(accession)
        seen.add(accession)
    if duplicates:
        duplicate_text = ", ".join(sorted(set(duplicates)))
        raise ValueError(f"Duplicate accessions are not allowed: {duplicate_text}")

    return records


def _normalise_cell(value: Any) -> Any:
    """Convert nested values to deterministic JSON for flat tabular outputs.

    Args:
        value: Arbitrary record value.

    Returns:
        A scalar value suitable for CSV and Arrow conversion.
    """

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (dict, list, tuple, set)):
        serialisable = sorted(value) if isinstance(value, set) else value
        return json.dumps(serialisable, sort_keys=True, ensure_ascii=False)
    return value


def normalise_records(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Normalise heterogeneous dictionaries into one stable table schema.

    Args:
        records: Ordered records.

    Returns:
        Ordered field names and normalised rows.
    """

    fields = sorted({str(key) for record in records for key in record})
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.append(
            {
                field: _normalise_cell(record.get(field))
                for field in fields
            }
        )

    for field in fields:
        values = [row[field] for row in rows if row[field] is not None]
        families = {
            "bool" if isinstance(value, bool)
            else "int" if isinstance(value, int)
            else "float" if isinstance(value, float)
            else "str"
            for value in values
        }
        if families and families.issubset({"int", "float"}):
            if "float" in families:
                for row in rows:
                    if row[field] is not None:
                        row[field] = float(row[field])
        elif len(families) > 1:
            for row in rows:
                if row[field] is not None:
                    row[field] = str(row[field])
    return fields, rows


def write_tsv_records(
    path: Path,
    records: Sequence[Mapping[str, Any]],
    fieldnames: Sequence[str] | None = None,
) -> None:
    """Write records atomically as UTF-8 tab-delimited text.

    Args:
        path: Destination TSV path.
        records: Ordered records.
        fieldnames: Optional explicit field order.
    """

    destination = Path(path).expanduser().resolve()
    if fieldnames is None:
        fields, rows = normalise_records(records)
    else:
        fields = list(fieldnames)
        rows = [
            {field: _normalise_cell(record.get(field)) for field in fields}
            for record in records
        ]

    temporary = destination.with_name(f".{destination.name}.tmp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fields,
                delimiter="\t",
                lineterminator="\n",
                extrasaction="raise",
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def write_parquet_records(
    path: Path,
    records: Sequence[Mapping[str, Any]],
) -> None:
    """Write records atomically as Zstandard-compressed Parquet.

    Args:
        path: Destination Parquet path.
        records: Ordered records.
    """

    destination = Path(path).expanduser().resolve()
    fields, rows = normalise_records(records)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    table = pa.Table.from_pylist(rows, schema=None)
    if not rows:
        table = pa.table({field: pa.array([], type=pa.string()) for field in fields})
    try:
        pq.write_table(table, temporary, compression="zstd")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def flatten(iterables: Iterable[Iterable[Any]]) -> list[Any]:
    """Flatten one level of nested iterables into a list.

    Args:
        iterables: Nested iterable values.

    Returns:
        Flattened list preserving encounter order.
    """

    return [item for iterable in iterables for item in iterable]
