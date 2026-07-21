"""Small, auditable file and logging helpers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from e3workflow.errors import WorkflowError


def utc_now() -> str:
    """Return the current UTC time in a stable ISO-8601 representation."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculate a SHA-256 digest without loading a whole file into memory.

    Args:
        path: Existing regular file.
        chunk_size: Positive read size in bytes.

    Returns:
        Lower-case hexadecimal digest.

    Raises:
        WorkflowError: If the input or chunk size is invalid.
    """

    if chunk_size < 1:
        raise WorkflowError("chunk_size must be a positive integer")
    if not path.is_file():
        raise WorkflowError(f"Cannot checksum missing file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically on the destination filesystem.

    Args:
        path: Formal output path.
        text: UTF-8 content.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Serialise a mapping as deterministic, atomically published JSON."""

    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object from an existing file."""

    if not path.is_file():
        raise WorkflowError(f"JSON file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Could not read JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise WorkflowError(f"Expected a JSON object in {path}")
    return payload


def write_tsv(path: Path, rows: Iterable[Mapping[str, Any]], columns: Sequence[str]) -> None:
    """Write dictionaries to a stable tab-separated table."""

    if not columns or len(set(columns)) != len(columns):
        raise WorkflowError("TSV columns must be a non-empty unique sequence")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(columns),
        delimiter="\t",
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    atomic_write_text(path, buffer.getvalue())


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a UTF-8 TSV with a unique, non-empty header."""

    if not path.is_file():
        raise WorkflowError(f"TSV file does not exist: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        if not fields or any(not field for field in fields) or len(set(fields)) != len(fields):
            raise WorkflowError(f"TSV header is empty or contains duplicate fields: {path}")
        rows = [dict(row) for row in reader]
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise WorkflowError(f"TSV contains malformed rows: {path}")
    return fields, rows


def configure_logging(log_path: Path, verbose: bool = False) -> logging.Logger:
    """Configure isolated console and file logging for one command."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("e3workflow")
    close_logger(logger)
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


def close_logger(logger: logging.Logger) -> None:
    """Flush, close, and remove every handler from one logger."""

    for handler in list(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)


def inventory_files(
    root: Path,
    excluded_names: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Return checksums and sizes for regular files below a directory."""

    if not root.is_dir():
        raise WorkflowError(f"Cannot inventory missing directory: {root}")
    records = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if path.name in excluded_names:
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records
