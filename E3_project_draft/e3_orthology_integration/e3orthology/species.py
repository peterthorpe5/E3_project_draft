"""Manifest-driven target-species reconciliation."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .errors import InputValidationError
from .io_utils import ensure_readable_file

_SPECIES_FIELDS = (
    "canonical_species_name",
    "source_species_name",
    "taxon_id",
    "required",
    "role",
    "aliases",
)


@dataclass(frozen=True)
class SpeciesManifestRecord:
    """One expected or optional species supplied through the manifest."""

    canonical_species_name: str
    source_species_name: str
    taxon_id: str
    required: bool
    role: str
    aliases: tuple[str, ...]


def parse_boolean(*, value: str, field_name: str) -> bool:
    """Parse a strict text Boolean.

    Args:
        value: Text value.
        field_name: Field label used in errors.

    Returns:
        Parsed Boolean.

    Raises:
        InputValidationError: If the value is not an accepted Boolean token.
    """

    normalised = value.strip().lower()
    if normalised in {"true", "yes", "1"}:
        return True
    if normalised in {"false", "no", "0"}:
        return False
    raise InputValidationError(f"{field_name} must be true or false; observed {value!r}")


def load_species_manifest(*, path: Path) -> list[SpeciesManifestRecord]:
    """Load and validate a tab-separated species manifest.

    Args:
        path: Species manifest TSV.

    Returns:
        Ordered species records.

    Raises:
        InputValidationError: If columns, values or canonical names are invalid.
    """

    source = ensure_readable_file(path=path)
    records: list[SpeciesManifestRecord] = []
    seen: set[str] = set()
    with source.open(mode="r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != list(_SPECIES_FIELDS):
            raise InputValidationError(
                f"Species manifest columns must be {_SPECIES_FIELDS}; observed {reader.fieldnames}"
            )
        for line_number, row in enumerate(reader, start=2):
            canonical = row["canonical_species_name"].strip()
            source_name = row["source_species_name"].strip()
            role = row["role"].strip()
            if not canonical or not source_name or not role:
                raise InputValidationError(
                    f"Species manifest line {line_number} has an empty required value."
                )
            if canonical in seen:
                raise InputValidationError(
                    f"Duplicate canonical species {canonical!r} at line {line_number}."
                )
            seen.add(canonical)
            aliases = tuple(alias.strip() for alias in row["aliases"].split(";") if alias.strip())
            records.append(
                SpeciesManifestRecord(
                    canonical_species_name=canonical,
                    source_species_name=source_name,
                    taxon_id=row["taxon_id"].strip(),
                    required=parse_boolean(
                        value=row["required"],
                        field_name=f"required at line {line_number}",
                    ),
                    role=role,
                    aliases=aliases,
                )
            )
    if not records:
        raise InputValidationError(f"Species manifest contains no records: {source}")
    return records


def assess_species_coverage(
    *,
    discovered_species: Iterable[str],
    manifest_records: Iterable[SpeciesManifestRecord],
) -> list[dict[str, str]]:
    """Match discovered OrthoFinder species against explicit names and aliases.

    Args:
        discovered_species: Species columns found in the OrthoFinder output.
        manifest_records: Expected or optional manifest records.

    Returns:
        One coverage record per manifest species.
    """

    discovered = {name.strip() for name in discovered_species if name.strip()}
    coverage: list[dict[str, str]] = []
    for record in manifest_records:
        accepted_names = {record.source_species_name, *record.aliases}
        matches = sorted(discovered & accepted_names)
        if len(matches) > 1:
            status = "AMBIGUOUS_ALIAS_MATCH"
            reason = "multiple_source_names_present"
        elif matches:
            status = "PRESENT"
            reason = "explicit_source_or_alias_match"
        elif record.required:
            status = "MISSING_REQUIRED"
            reason = "required_species_not_analysed"
        else:
            status = "MISSING_OPTIONAL"
            reason = "optional_species_not_analysed"
        coverage.append(
            {
                "canonical_species_name": record.canonical_species_name,
                "source_species_name": record.source_species_name,
                "taxon_id": record.taxon_id,
                "required": str(record.required).lower(),
                "role": record.role,
                "aliases": ";".join(record.aliases),
                "matched_source_name": ";".join(matches),
                "status": status,
                "reason": reason,
            }
        )
    return coverage


def species_name_from_fasta(*, fasta_name: str) -> str:
    """Remove recognised FASTA suffixes while preserving the source label.

    Args:
        fasta_name: Original FASTA filename from ``SpeciesIDs.txt``.

    Returns:
        Source species label without a recognised FASTA suffix.

    Raises:
        InputValidationError: If the filename is empty.
    """

    name = Path(fasta_name.strip()).name
    if not name:
        raise InputValidationError("FASTA filename must not be empty.")
    lower_name = name.lower()
    for suffix in (".fasta.gz", ".faa.gz", ".fa.gz", ".fasta", ".faa", ".fa"):
        if lower_name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem
