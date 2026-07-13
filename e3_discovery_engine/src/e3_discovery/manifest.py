"""Sample-manifest parsing and validation."""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

from e3_discovery.exceptions import DataValidationError
from e3_discovery.io_utils import atomic_text_writer

LOGGER = logging.getLogger(__name__)

_SAMPLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class SampleRecord:
    """Description of one proteome FASTA and its biological metadata."""

    sample_id: str
    fasta_path: Path
    species: str = ""
    taxon_id: str = ""
    proteome_id: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)


def _normalise_row(row: Mapping[str, str]) -> Dict[str, str]:
    return {str(key).strip(): str(value or "").strip() for key, value in row.items()}


def read_sample_manifest(path: Path) -> List[SampleRecord]:
    """Read a TSV manifest while retaining arbitrary extra metadata columns."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Sample manifest does not exist: {source}")
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {"sample_id", "fasta_path"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise DataValidationError(
                "Sample manifest must contain sample_id and fasta_path columns"
            )
        records = []
        for row_number, row in enumerate(reader, start=2):
            clean = _normalise_row(row)
            fasta = Path(clean["fasta_path"]).expanduser()
            if not fasta.is_absolute():
                fasta = source.resolve().parent / fasta
            records.append(
                SampleRecord(
                    sample_id=clean["sample_id"],
                    fasta_path=fasta.resolve(),
                    species=clean.get("species", ""),
                    taxon_id=clean.get("taxon_id", ""),
                    proteome_id=clean.get("proteome_id", ""),
                    metadata={**clean, "manifest_row": str(row_number)},
                )
            )
    validate_sample_records(records)
    LOGGER.info("Loaded %d proteome samples from %s", len(records), source)
    return records


def validate_sample_records(records: Iterable[SampleRecord]) -> None:
    """Validate identifiers, paths, and duplicates in sample records."""

    materialised = list(records)
    if not materialised:
        raise DataValidationError("Sample manifest contains no records")

    sample_ids = set()
    paths = set()
    for record in materialised:
        if not record.sample_id:
            raise DataValidationError("sample_id cannot be empty")
        if not _SAMPLE_ID_PATTERN.fullmatch(record.sample_id):
            raise DataValidationError(
                "sample_id may contain only letters, digits, '.', '_' and '-': "
                f"{record.sample_id}"
            )
        if record.sample_id in sample_ids:
            raise DataValidationError(f"Duplicate sample_id: {record.sample_id}")
        sample_ids.add(record.sample_id)

        if record.fasta_path in paths:
            raise DataValidationError(
                f"The same FASTA path appears more than once: {record.fasta_path}"
            )
        paths.add(record.fasta_path)
        if not record.fasta_path.is_file():
            raise FileNotFoundError(
                f"FASTA for sample {record.sample_id} does not exist: "
                f"{record.fasta_path}"
            )
        if record.fasta_path.name.startswith(("._", ".DS_Store")):
            raise DataValidationError(
                f"macOS sidecar file cannot be used as FASTA: {record.fasta_path}"
            )


def write_sample_manifest(records: Iterable[SampleRecord], path: Path) -> int:
    """Write a normalised sample manifest with standard fields first."""

    materialised = list(records)
    validate_sample_records(materialised)
    extras = sorted(
        {
            key
            for record in materialised
            for key in record.metadata
            if key
            not in {"sample_id", "fasta_path", "species", "taxon_id", "proteome_id"}
        }
    )
    fields = [
        "sample_id",
        "fasta_path",
        "species",
        "taxon_id",
        "proteome_id",
        *extras,
    ]
    with atomic_text_writer(path, newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for record in materialised:
            writer.writerow(
                {
                    **dict(record.metadata),
                    "sample_id": record.sample_id,
                    "fasta_path": str(record.fasta_path),
                    "species": record.species,
                    "taxon_id": record.taxon_id,
                    "proteome_id": record.proteome_id,
                }
            )
    return len(materialised)
