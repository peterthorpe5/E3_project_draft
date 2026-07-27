"""Source-file manifest creation for the E3 PROTAC rebuild."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Dict, List, Optional

from e3parquet.io_utils import (
    guess_file_format,
    guess_logical_role,
    iter_source_files,
    normalise_relative_path,
    sha256_file,
)

LOGGER = logging.getLogger(__name__)


def build_file_manifest(
    raw_root: Path,
    checksum: bool = True,
    include_hidden: bool = False,
) -> List[Dict[str, object]]:
    """Build a metadata manifest for all selected inherited files.

    Parameters
    ----------
    raw_root:
        Root of the curated inherited source copy.
    checksum:
        Whether to calculate SHA256 checksums. Recommended for provenance.
    include_hidden:
        Whether to include macOS hidden/resource-fork files.

    Returns
    -------
    list of dict
        One record per source file.
    """
    raw_root = raw_root.resolve()
    if not raw_root.exists():
        raise FileNotFoundError(f"Raw root does not exist: {raw_root}")
    if not raw_root.is_dir():
        raise NotADirectoryError(f"Raw root is not a directory: {raw_root}")

    records: List[Dict[str, object]] = []
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    LOGGER.info("Scanning source files under %s", raw_root)

    for path in iter_source_files(raw_root, include_hidden=include_hidden):
        rel_path = normalise_relative_path(path.relative_to(raw_root))
        stat_result = path.stat()
        sha256: Optional[str] = None
        if checksum:
            sha256 = sha256_file(path)
        record: Dict[str, object] = {
            "relative_path": rel_path,
            "file_name": path.name,
            "suffix": path.suffix.lower(),
            "file_format": guess_file_format(path),
            "logical_role_guess": guess_logical_role(rel_path),
            "size_bytes": stat_result.st_size,
            "mtime_utc": dt.datetime.fromtimestamp(
                stat_result.st_mtime, tz=dt.timezone.utc
            ).isoformat(),
            "sha256": sha256 or "",
            "source_root": str(raw_root),
            "manifest_created_utc": ingested_at,
        }
        records.append(record)

    LOGGER.info("Manifest contains %d source files", len(records))
    return records


def manifest_by_relative_path(
    manifest: List[Dict[str, object]],
) -> Dict[str, Dict[str, object]]:
    """Index manifest records by relative path."""
    return {str(record["relative_path"]): record for record in manifest}
