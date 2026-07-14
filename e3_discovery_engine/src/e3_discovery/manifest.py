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
    """Describe one proteome input and its biological provenance.

    Attributes:
        sample_id: Unique workflow-safe identifier for the proteome sample.
        fasta_path: Absolute or resolved path to the protein FASTA file.
        species: Optional scientific species name.
        taxon_id: Optional taxonomy identifier.
        proteome_id: Optional source-database proteome or assembly identifier.
        metadata: Additional manifest fields retained without interpretation.
    """

    sample_id: str
    fasta_path: Path
    species: str = ""
    taxon_id: str = ""
    proteome_id: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)


def _normalise_row(row: Mapping[str, str]) -> Dict[str, str]:
    """Trim manifest field names and values and replace null values with blanks.

    Args:
        row: Raw row mapping returned by ``csv.DictReader``.

    Returns:
        A new dictionary containing stripped string keys and values.
    """
    return {str(key).strip(): str(value or "").strip() for key, value in row.items()}


def read_sample_manifest(path: Path) -> List[SampleRecord]:
    """Read, resolve and validate a proteome sample manifest.

    Relative FASTA paths are resolved against the manifest directory. Standard
    biological fields are assigned explicitly and all source columns, plus the
    original row number, are retained as metadata.

    Args:
        path: Tab-separated sample-manifest path.

    Returns:
        Validated :class:`SampleRecord` objects in manifest order.

    Raises:
        FileNotFoundError: If the manifest or a referenced FASTA is absent.
        DataValidationError: If required columns, identifiers, paths or records
            fail validation.
    """

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
    """Validate proteome sample identifiers and source paths.

    The function requires at least one record, unique workflow-safe sample IDs,
    unique existing FASTA paths, and rejects common macOS sidecar files.

    Args:
        records: Sample records to validate.

    Returns:
        None.

    Raises:
        FileNotFoundError: If a referenced FASTA file does not exist.
        DataValidationError: If records are empty, duplicated or malformed.
    """

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
    """Write validated sample records as a normalised TSV manifest.

    Standard fields are written first, followed by sorted additional metadata
    columns. Metadata values cannot override the canonical standard fields.

    Args:
        records: Sample records to validate and serialise.
        path: Destination manifest TSV.

    Returns:
        Number of sample rows written.

    Raises:
        FileNotFoundError: If a referenced FASTA file does not exist.
        DataValidationError: If records fail validation.
        OSError: If the manifest cannot be written or replaced.
    """

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
