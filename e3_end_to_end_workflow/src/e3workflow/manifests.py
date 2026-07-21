"""Controlled input-manifest validation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from e3workflow.errors import ManifestError
from e3workflow.io_utils import read_tsv, sha256_file

TRUE_VALUES = frozenset({"1", "true", "yes"})
FALSE_VALUES = frozenset({"0", "false", "no"})
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def parse_boolean(value: str, label: str) -> bool:
    """Parse a strict human-readable Boolean field."""

    normalised = value.strip().lower()
    if normalised in TRUE_VALUES:
        return True
    if normalised in FALSE_VALUES:
        return False
    raise ManifestError(f"{label} must be one of true/false, yes/no, or 1/0; received {value!r}")


def _require_columns(fields: Iterable[str], required: set[str], path: Path) -> None:
    """Require a complete manifest header."""

    missing = required.difference(fields)
    if missing:
        raise ManifestError(f"Missing columns in {path}: {', '.join(sorted(missing))}")


def validate_proteomes(path: Path, verify_checksums: bool) -> list[dict[str, str]]:
    """Validate species/proteome rows and optionally their file checksums."""

    fields, rows = read_tsv(path)
    _require_columns(
        fields,
        {"species_id", "scientific_name", "fasta_path", "fasta_sha256", "include"},
        path,
    )
    if not rows:
        raise ManifestError(f"Proteome manifest contains no rows: {path}")
    seen = set()
    included = []
    for line_number, row in enumerate(rows, start=2):
        species_id = row["species_id"].strip()
        if not species_id or species_id in seen:
            raise ManifestError(f"Empty or duplicate species_id at {path}:{line_number}")
        seen.add(species_id)
        if not row["scientific_name"].strip():
            raise ManifestError(f"Missing scientific_name at {path}:{line_number}")
        if not parse_boolean(row["include"], f"{path}:{line_number} include"):
            continue
        fasta = Path(row["fasta_path"]).expanduser()
        fasta = (path.parent / fasta).resolve() if not fasta.is_absolute() else fasta.resolve()
        if not fasta.is_file():
            raise ManifestError(f"Included FASTA does not exist at {path}:{line_number}: {fasta}")
        expected = row["fasta_sha256"].strip().lower()
        if verify_checksums:
            if not SHA256_PATTERN.fullmatch(expected):
                raise ManifestError(f"Invalid fasta_sha256 at {path}:{line_number}")
            observed = sha256_file(fasta)
            if observed != expected:
                raise ManifestError(
                    f"FASTA checksum mismatch at {path}:{line_number}: {expected} != {observed}"
                )
        record = dict(row)
        record["resolved_fasta_path"] = str(fasta)
        included.append(record)
    if not included:
        raise ManifestError("Proteome manifest selects zero included proteomes")
    return included


def validate_accessions(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    """Validate a non-empty accession table with no duplicate accessions."""

    fields, rows = read_tsv(path)
    _require_columns(fields, required_columns | {"accession"}, path)
    if not rows:
        raise ManifestError(f"Accession manifest contains no rows: {path}")
    seen = set()
    for line_number, row in enumerate(rows, start=2):
        accession = row["accession"].strip()
        if not accession or accession in seen:
            raise ManifestError(f"Empty or duplicate accession at {path}:{line_number}")
        seen.add(accession)
        for column in required_columns:
            if not row[column].strip():
                raise ManifestError(f"Missing {column} at {path}:{line_number}")
    return rows


def validate_shortlist(path: Path) -> list[dict[str, str]]:
    """Validate the human-reviewed ligandability gate."""

    required = {"decision", "approved_by", "approved_at_utc", "rationale"}
    rows = validate_accessions(path, required)
    allowed = {"approve", "defer", "reject"}
    decisions = {row["decision"].strip().lower() for row in rows}
    invalid = decisions.difference(allowed)
    if invalid:
        raise ManifestError(f"Unsupported shortlist decisions: {', '.join(sorted(invalid))}")
    if "approve" not in decisions:
        raise ManifestError("Shortlist contains no approved accessions")
    return rows

