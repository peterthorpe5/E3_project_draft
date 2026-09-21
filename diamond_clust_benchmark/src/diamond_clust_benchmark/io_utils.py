"""Small atomic I/O helpers used throughout the benchmark package."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def ensure_parent(path: Path) -> Path:
    """Create the parent directory of a path.

    Args:
        path: File path whose parent directory is required.

    Returns:
        The normalised input path.
    """

    normalised = Path(path)
    normalised.parent.mkdir(parents=True, exist_ok=True)
    return normalised


def write_json(path: Path, payload: object) -> None:
    """Write indented JSON atomically.

    Args:
        path: Destination JSON path.
        payload: JSON-serialisable value.
    """

    destination = ensure_parent(Path(path))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_tsv(
    path: Path,
    rows: Iterable[Mapping[str, object]],
    fieldnames: Sequence[str],
) -> None:
    """Write dictionaries as an atomic tab-delimited table.

    Args:
        path: Destination table path.
        rows: Row mappings.
        fieldnames: Ordered output columns.

    Raises:
        ValueError: If no field names are supplied.
    """

    if not fieldnames:
        raise ValueError("fieldnames cannot be empty")
    destination = ensure_parent(Path(path))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                delimiter="\t",
                fieldnames=list(fieldnames),
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
