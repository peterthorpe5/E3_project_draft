"""Cleanup helpers for inherited macOS sidecar files."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from e3parquet.io_utils import path_has_hidden_or_macos_sidecar_part

LOGGER = logging.getLogger(__name__)


def find_macos_sidecar_files(root: Path) -> List[Path]:
    """Return macOS sidecar files under a root in deterministic order."""
    if not root.exists():
        return []
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path_has_hidden_or_macos_sidecar_part(path)
    ]


def clean_macos_sidecar_files(root: Path, delete: bool = False) -> List[Dict[str, str]]:
    """Report or delete macOS sidecar files below a root.

    Parameters
    ----------
    root:
        Directory to scan.
    delete:
        When false, only report files. When true, delete matching files.

    Returns
    -------
    list of dict
        One record per sidecar file.
    """
    records: List[Dict[str, str]] = []
    for path in find_macos_sidecar_files(root):
        rel_path = path.relative_to(root).as_posix()
        status = "would_delete"
        error = ""
        if delete:
            try:
                path.unlink()
                status = "deleted"
                LOGGER.info("Deleted macOS sidecar file: %s", path)
            except OSError as exc:
                status = "failed"
                error = str(exc)
                LOGGER.exception("Failed deleting macOS sidecar file: %s", path)
        records.append({"relative_path": rel_path, "status": status, "error": error})
    return records
