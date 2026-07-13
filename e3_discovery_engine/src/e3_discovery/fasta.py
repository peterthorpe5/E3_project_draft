"""Streaming FASTA preparation and sequence metadata capture."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

from e3_discovery.constants import PROTEIN_ALPHABET
from e3_discovery.exceptions import DataValidationError
from e3_discovery.io_utils import (
    atomic_binary_path,
    atomic_text_writer,
    json_dumps_sorted,
    open_text_auto,
    sha256_file,
    write_tsv,
)
from e3_discovery.manifest import SampleRecord, validate_sample_records

LOGGER = logging.getLogger(__name__)

_INTERNAL_ID_SAFE = re.compile(r"[^A-Za-z0-9_.:@|+-]")


@dataclass(frozen=True)
class FastaRecord:
    """One FASTA record with header and validated sequence text."""

    identifier: str
    description: str
    sequence: str


def normalise_sequence_id(identifier: str) -> str:
    """Return a FASTA-safe identifier without whitespace."""

    token = str(identifier).strip().split()[0] if str(identifier).strip() else ""
    if not token:
        raise DataValidationError("FASTA identifier is empty")
    return _INTERNAL_ID_SAFE.sub("_", token)


def extract_entry(identifier: str) -> str:
    """Extract a UniProt-style entry accession where possible."""

    token = normalise_sequence_id(identifier)
    parts = token.split("|")
    if len(parts) >= 3 and parts[0] in {"sp", "tr"} and parts[1]:
        return parts[1]
    return token


def validate_protein_sequence(sequence: str) -> str:
    """Normalise and validate an amino-acid sequence."""

    clean = "".join(str(sequence).split()).upper()
    if not clean:
        raise DataValidationError("Protein sequence is empty")
    invalid = sorted(set(clean).difference(PROTEIN_ALPHABET))
    if invalid:
        raise DataValidationError(
            "Protein sequence contains unsupported characters: "
            + ", ".join(invalid)
        )
    return clean


def iter_fasta(path: Path) -> Iterator[FastaRecord]:
    """Stream FASTA records from plain or gzip-compressed input."""

    current_header: Optional[str] = None
    sequence_parts: List[str] = []
    with open_text_auto(path) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            if line.startswith(">"):
                if current_header is not None:
                    yield _record_from_parts(current_header, sequence_parts)
                current_header = line[1:].strip()
                if not current_header:
                    raise DataValidationError(
                        f"Empty FASTA header at {path}:{line_number}"
                    )
                sequence_parts = []
            else:
                if current_header is None:
                    raise DataValidationError(
                        f"Sequence before first FASTA header at {path}:{line_number}"
                    )
                sequence_parts.append(line)
    if current_header is not None:
        yield _record_from_parts(current_header, sequence_parts)


def _record_from_parts(header: str, sequence_parts: Sequence[str]) -> FastaRecord:
    identifier = normalise_sequence_id(header)
    description = header[len(header.split()[0]):].strip()
    sequence = validate_protein_sequence("".join(sequence_parts))
    return FastaRecord(identifier, description, sequence)


def make_internal_id(
    sample_id: str,
    original_id: str,
    identifier_mode: str,
) -> str:
    """Create a globally unique sequence identifier for the combined database."""

    if identifier_mode == "preserve":
        return normalise_sequence_id(original_id)
    if identifier_mode == "prefix_sample":
        sample = normalise_sequence_id(sample_id)
        original = normalise_sequence_id(original_id)
        return f"{sample}@@{original}"
    raise ValueError(
        "identifier_mode must be either 'preserve' or 'prefix_sample'"
    )


def sequence_schema() -> pa.Schema:
    """Return the stable Arrow schema used for sequence metadata."""

    return pa.schema(
        [
            ("internal_id", pa.string()),
            ("sample_id", pa.string()),
            ("species", pa.string()),
            ("taxon_id", pa.string()),
            ("proteome_id", pa.string()),
            ("original_id", pa.string()),
            ("entry", pa.string()),
            ("description", pa.string()),
            ("sequence", pa.string()),
            ("sequence_length", pa.int64()),
            ("sequence_md5", pa.string()),
            ("source_path", pa.string()),
            ("source_sha256", pa.string()),
            ("record_index", pa.int64()),
            ("sample_metadata_json", pa.string()),
        ]
    )


def _flush_sequence_rows(
    writer: pq.ParquetWriter,
    rows: List[Mapping[str, object]],
) -> None:
    if not rows:
        return
    table = pa.Table.from_pylist(rows, schema=sequence_schema())
    writer.write_table(table)
    rows.clear()


def prepare_combined_fasta(
    samples: Iterable[SampleRecord],
    combined_fasta: Path,
    sequence_parquet: Path,
    sample_summary_tsv: Path,
    identifier_mode: str = "prefix_sample",
    batch_size: int = 100_000,
    compute_checksums: bool = True,
) -> Dict[str, int]:
    """Create a combined FASTA and streaming sequence Parquet table.

    Source FASTA files are never modified. Duplicate internal identifiers are
    rejected before a completed output is published.
    """

    materialised = list(samples)
    validate_sample_records(materialised)
    LOGGER.info(
        "Preparing %d proteome FASTA files using identifier mode %s",
        len(materialised),
        identifier_mode,
    )
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    seen_ids = set()
    sequence_rows: List[Mapping[str, object]] = []
    summaries: List[Dict[str, object]] = []
    total_sequences = 0
    total_residues = 0

    with atomic_binary_path(sequence_parquet) as parquet_tmp:
        writer = pq.ParquetWriter(
            parquet_tmp,
            sequence_schema(),
            compression="zstd",
            use_dictionary=True,
        )
        try:
            with atomic_text_writer(combined_fasta, newline="\n") as fasta_out:
                for sample in materialised:
                    LOGGER.info(
                        "Reading sample %s from %s",
                        sample.sample_id,
                        sample.fasta_path,
                    )
                    source_checksum = (
                        sha256_file(sample.fasta_path) if compute_checksums else ""
                    )
                    sample_count = 0
                    sample_residues = 0
                    metadata_json = json_dumps_sorted(dict(sample.metadata))
                    for record_index, record in enumerate(
                        iter_fasta(sample.fasta_path),
                        start=1,
                    ):
                        internal_id = make_internal_id(
                            sample.sample_id,
                            record.identifier,
                            identifier_mode,
                        )
                        if internal_id in seen_ids:
                            raise DataValidationError(
                                "Duplicate internal sequence identifier: "
                                f"{internal_id}. Use prefix_sample mode or fix "
                                "the source identifiers."
                            )
                        seen_ids.add(internal_id)
                        sequence = record.sequence
                        length = len(sequence)
                        digest = hashlib.md5(
                            sequence.encode("ascii"), usedforsecurity=False
                        ).hexdigest()
                        fasta_out.write(
                            f">{internal_id} original_id={record.identifier} "
                            f"sample_id={sample.sample_id}\n"
                        )
                        for start in range(0, length, 80):
                            fasta_out.write(sequence[start:start + 80] + "\n")
                        sequence_rows.append(
                            {
                                "internal_id": internal_id,
                                "sample_id": sample.sample_id,
                                "species": sample.species,
                                "taxon_id": sample.taxon_id,
                                "proteome_id": sample.proteome_id,
                                "original_id": record.identifier,
                                "entry": extract_entry(record.identifier),
                                "description": record.description,
                                "sequence": sequence,
                                "sequence_length": length,
                                "sequence_md5": digest,
                                "source_path": str(sample.fasta_path),
                                "source_sha256": source_checksum,
                                "record_index": record_index,
                                "sample_metadata_json": metadata_json,
                            }
                        )
                        if len(sequence_rows) >= batch_size:
                            _flush_sequence_rows(writer, sequence_rows)
                        sample_count += 1
                        sample_residues += length
                    if sample_count == 0:
                        raise DataValidationError(
                            f"No FASTA records found for sample {sample.sample_id}"
                        )
                    summaries.append(
                        {
                            "sample_id": sample.sample_id,
                            "species": sample.species,
                            "taxon_id": sample.taxon_id,
                            "proteome_id": sample.proteome_id,
                            "fasta_path": str(sample.fasta_path),
                            "source_sha256": source_checksum,
                            "sequence_count": sample_count,
                            "total_residues": sample_residues,
                        }
                    )
                    total_sequences += sample_count
                    total_residues += sample_residues
                    LOGGER.info(
                        "Prepared sample %s: %d sequences, %d residues",
                        sample.sample_id,
                        sample_count,
                        sample_residues,
                    )
                _flush_sequence_rows(writer, sequence_rows)
        finally:
            writer.close()

    write_tsv(summaries, sample_summary_tsv)
    LOGGER.info(
        "Prepared combined FASTA: %d samples, %d sequences, %d residues",
        len(materialised),
        total_sequences,
        total_residues,
    )
    return {
        "sample_count": len(materialised),
        "sequence_count": total_sequences,
        "total_residues": total_residues,
    }


def write_fasta_records(
    records: Iterable[Tuple[str, str]],
    output_path: Path,
) -> int:
    """Write identifier/sequence pairs to FASTA using 80-character wrapping."""

    count = 0
    with atomic_text_writer(output_path, newline="\n") as handle:
        for identifier, sequence in records:
            clean_id = normalise_sequence_id(identifier)
            clean_sequence = validate_protein_sequence(sequence)
            handle.write(f">{clean_id}\n")
            for start in range(0, len(clean_sequence), 80):
                handle.write(clean_sequence[start:start + 80] + "\n")
            count += 1
    return count
