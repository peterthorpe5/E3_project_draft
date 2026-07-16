"""FASTA parsing utilities for the E3 PROTAC rebuild."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from e3parquet.io_utils import (
    FASTA_SUFFIXES,
    normalise_relative_path,
    path_has_hidden_or_macos_sidecar_part,
)

LOGGER = logging.getLogger(__name__)


def infer_accession_from_header(header: str) -> str:
    """Infer a useful accession/token from a FASTA header.

    The full header is always preserved separately. This helper only provides
    a convenience identifier for joins and exploratory querying.
    """
    first_token = header.split()[0] if header.strip() else ""
    if "|" in first_token:
        parts = [part for part in first_token.split("|") if part]
        if len(parts) >= 2:
            return parts[1]
        if parts:
            return parts[0]
    return first_token


def parse_fasta_file(
    fasta_path: Path,
    raw_root: Path,
    manifest_record: Optional[Mapping[str, object]] = None,
) -> List[Dict[str, object]]:
    """Parse a FASTA file into long records with source metadata."""
    records: List[Dict[str, object]] = []
    rel_path = normalise_relative_path(fasta_path.relative_to(raw_root))
    ingested_at = dt.datetime.now(dt.timezone.utc).isoformat()

    header: Optional[str] = None
    sequence_parts: List[str] = []
    record_number = 0

    def emit_record() -> None:
        """Append the current FASTA record to the parsed output list."""
        nonlocal record_number, header, sequence_parts
        if header is None:
            return
        sequence = "".join(sequence_parts).replace(" ", "").replace("\t", "")
        record_number += 1
        record = {
            "sequence_record_number": record_number,
            "inferred_accession": infer_accession_from_header(header),
            "fasta_header": header,
            "sequence": sequence,
            "sequence_length": len(sequence),
            "sequence_md5": hashlib.md5(sequence.encode("utf-8")).hexdigest(),
            "_source_file": rel_path,
            "_source_file_sha256": str(manifest_record.get("sha256", ""))
            if manifest_record
            else "",
            "_source_file_size_bytes": str(
                manifest_record.get("size_bytes", "")
            )
            if manifest_record
            else "",
            "_source_file_mtime_utc": str(manifest_record.get("mtime_utc", ""))
            if manifest_record
            else "",
            "_ingested_at_utc": ingested_at,
        }
        records.append(record)

    with fasta_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\n\r")
            if not line:
                continue
            if line.startswith(">"):
                emit_record()
                header = line[1:].strip()
                sequence_parts = []
            else:
                sequence_parts.append(line.strip())
        emit_record()

    LOGGER.debug("Parsed %d FASTA records from %s", len(records), rel_path)
    return records


def iter_fasta_files(raw_root: Path) -> Iterable[Path]:
    """Yield FASTA files under a raw root."""
    for path in sorted(raw_root.rglob("*")):
        if path.is_file() and path.suffix.lower() in FASTA_SUFFIXES:
            if path_has_hidden_or_macos_sidecar_part(path):
                continue
            yield path
