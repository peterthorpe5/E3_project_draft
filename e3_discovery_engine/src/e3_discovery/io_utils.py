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
    """Create an output path's parent directories when necessary.

    Args:
        path: Intended file path.

    Returns:
        The path normalised as a :class:`pathlib.Path` instance.

    Raises:
        OSError: If a parent directory cannot be created.
    """

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


@contextmanager
def atomic_text_writer(path: Path, newline: str = "") -> Iterator[TextIO]:
    """Provide a UTF-8 text handle that is atomically published on success.

    A temporary file is created beside the destination. It replaces the target
    only after the context exits normally; failures remove the temporary file and
    preserve any existing destination.

    Args:
        path: Final destination path.
        newline: Newline handling forwarded to the temporary text file.

    Yields:
        Writable UTF-8 text handle for the temporary file.

    Raises:
        OSError: If temporary-file creation, writing or atomic replacement fails.
    """

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
    """Provide a temporary path for atomically published binary output.

    The caller writes binary data to the yielded path. On normal exit, the
    temporary output must exist and is atomically moved to the destination.

    Args:
        path: Final destination path.

    Yields:
        Temporary path on the same filesystem as the destination.

    Raises:
        DataValidationError: If the caller does not create the temporary output.
        OSError: If temporary-file creation or atomic replacement fails.
    """

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
    """Open plain or gzip-compressed text input with UTF-8 decoding.

    Args:
        path: Existing plain-text or ``.gz`` input path.

    Returns:
        A readable text handle that the caller must close.

    Raises:
        FileNotFoundError: If the input file does not exist.
        OSError: If the file cannot be opened or decompressed.
    """

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Input file does not exist: {source}")
    if source.name.endswith(".gz"):
        return gzip.open(source, mode="rt", encoding="utf-8", newline="")
    return source.open(mode="r", encoding="utf-8", newline="")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculate a file's SHA-256 checksum using bounded memory.

    Args:
        path: File whose raw bytes will be hashed.
        chunk_size: Number of bytes read per iteration.

    Returns:
        Lowercase hexadecimal SHA-256 digest.

    Raises:
        ValueError: If ``chunk_size`` is smaller than one byte.
        FileNotFoundError: If ``path`` does not exist.
        OSError: If the file cannot be read.
    """

    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1 byte")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def detect_delimiter(path: Path, sample_size: int = 8192) -> str:
    """Detect comma or tab delimiters in a small text-table sample.

    CSV sniffer detection is attempted first. Ambiguous files fall back to tab
    for ``.tsv`` and ``.txt`` paths, otherwise comma.

    Args:
        path: Delimited text input path.
        sample_size: Maximum characters inspected for delimiter detection.

    Returns:
        A comma or tab delimiter string.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        DataValidationError: If the input contains no non-whitespace text.
    """

    with open_text_auto(path) as handle:
        sample = handle.read(sample_size)
    if not sample.strip():
        raise DataValidationError(f"Delimited input is empty: {path}")
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t").delimiter
    except csv.Error:
        return "\t" if str(path).lower().endswith((".tsv", ".txt")) else ","


def read_delimited(path: Path) -> List[Dict[str, str]]:
    """Read a small comma- or tab-delimited table into row dictionaries.

    This helper deliberately materialises the entire table and is intended for
    configuration and seed metadata rather than large alignment outputs.

    Args:
        path: CSV or TSV input path.

    Returns:
        Row dictionaries preserving every source column.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        DataValidationError: If delimiter detection fails on an empty file or the
            table has no header row.
    """

    delimiter = detect_delimiter(path)
    with open_text_auto(path) as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if not reader.fieldnames:
            raise DataValidationError(f"Missing header row: {path}")
        return [dict(row) for row in reader]


def write_tsv(records: Iterable[Mapping[str, Any]], path: Path) -> int:
    """Write mapping records to an atomic UTF-8 TSV file.

    Output columns follow first appearance across the materialised records. An
    empty iterable creates an empty file without a header.

    Args:
        records: Iterable of row mappings.
        path: Destination TSV path.

    Returns:
        Number of data rows written.

    Raises:
        ValueError: If a row contains fields outside the constructed union.
        OSError: If the output cannot be written or replaced.
    """

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
    """Serialise a mapping as compact deterministic JSON.

    Args:
        value: Mapping whose keys and values are JSON serialisable.

    Returns:
        JSON text with sorted keys and compact separators.

    Raises:
        TypeError: If a value is not JSON serialisable.
    """

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def require_nonempty_file(path: Path, label: str = "output") -> Path:
    """Verify that a required file exists and contains at least one byte.

    Args:
        path: File path to validate.
        label: Human-readable file role used in error messages.

    Returns:
        The validated path as a :class:`pathlib.Path`.

    Raises:
        DataValidationError: If the file is absent or empty.
    """

    candidate = Path(path)
    if not candidate.is_file():
        raise DataValidationError(f"Missing {label}: {candidate}")
    if candidate.stat().st_size == 0:
        raise DataValidationError(f"Empty {label}: {candidate}")
    return candidate


def read_text(path: Path) -> str:
    """Read all UTF-8 text from a plain or gzip-compressed file.

    Args:
        path: Existing text input path.

    Returns:
        Complete decoded file content.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        OSError: If the file cannot be opened, decompressed or read.
    """

    with open_text_auto(path) as handle:
        return handle.read()


def text_stream(content: str) -> io.StringIO:
    """Create an in-memory text stream from a string.

    Args:
        content: Initial text content.

    Returns:
        A seekable ``io.StringIO`` object positioned at the beginning.
    """

    return io.StringIO(content)
