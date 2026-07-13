"""File-system and delimited-text helpers with atomic output handling."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, TextIO

from e3_discovery.exceptions import DataValidationError


def ensure_parent(path: Path) -> Path:
    """Create the parent directory for *path* and return the normalised path."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


@contextmanager
def atomic_text_writer(path: Path, newline: str = "") -> Iterator[TextIO]:
    """Yield a temporary text handle and atomically replace *path* on success."""

    output = ensure_parent(Path(path))
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline=newline,
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            yield handle
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def atomic_binary_path(path: Path) -> Iterator[Path]:
    """Yield a temporary binary output path and atomically replace *path*."""

    output = ensure_parent(Path(path))
    descriptor, name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        if not temporary.exists():
            raise DataValidationError(
                f"Expected temporary output was not created: {temporary}"
            )
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def open_text_auto(path: Path) -> TextIO:
    """Open plain or gzip-compressed text input using UTF-8 decoding."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Input file does not exist: {source}")
    if source.name.endswith(".gz"):
        return gzip.open(source, mode="rt", encoding="utf-8", newline="")
    return source.open(mode="r", encoding="utf-8", newline="")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 checksum of a file without loading it into memory."""

    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1 byte")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def detect_delimiter(path: Path, sample_size: int = 8192) -> str:
    """Detect comma or tab delimiters, falling back to file extension."""

    with open_text_auto(path) as handle:
        sample = handle.read(sample_size)
    if not sample.strip():
        raise DataValidationError(f"Delimited input is empty: {path}")
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t").delimiter
    except csv.Error:
        return "\t" if str(path).lower().endswith((".tsv", ".txt")) else ","


def read_delimited(path: Path) -> List[Dict[str, str]]:
    """Read a small CSV or TSV file into dictionaries, preserving all columns."""

    delimiter = detect_delimiter(path)
    with open_text_auto(path) as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if not reader.fieldnames:
            raise DataValidationError(f"Missing header row: {path}")
        return [dict(row) for row in reader]


def write_tsv(records: Iterable[Mapping[str, Any]], path: Path) -> int:
    """Write dictionaries to a UTF-8 TSV using the union of record fields."""

    materialised = [dict(record) for record in records]
    fieldnames: List[str] = []
    seen = set()
    for record in materialised:
        for field in record:
            if field not in seen:
                fieldnames.append(field)
                seen.add(field)

    with atomic_text_writer(path, newline="") as handle:
        if not fieldnames:
            handle.write("")
            return 0
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(materialised)
    return len(materialised)


def json_dumps_sorted(value: Mapping[str, Any]) -> str:
    """Serialise metadata deterministically for storage in Parquet tables."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def require_nonempty_file(path: Path, label: str = "output") -> Path:
    """Validate that an expected file exists and contains at least one byte."""

    candidate = Path(path)
    if not candidate.is_file():
        raise DataValidationError(f"Missing {label}: {candidate}")
    if candidate.stat().st_size == 0:
        raise DataValidationError(f"Empty {label}: {candidate}")
    return candidate


def read_text(path: Path) -> str:
    """Return UTF-8 text from a plain or gzip-compressed input file."""

    with open_text_auto(path) as handle:
        return handle.read()


def text_stream(content: str) -> io.StringIO:
    """Create a StringIO object; mainly useful for deterministic tests."""

    return io.StringIO(content)
