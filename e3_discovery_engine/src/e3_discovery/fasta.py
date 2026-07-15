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
from e3_discovery.sequence_metadata import sequence_biological_metadata

LOGGER = logging.getLogger(__name__)

_INTERNAL_ID_SAFE = re.compile(r"[^A-Za-z0-9_.:@|+-]")


@dataclass(frozen=True)
class FastaRecord:
    """Store one parsed and validated protein FASTA record.

    Attributes:
        identifier: Normalised first token from the FASTA header.
        description: Remaining free-text FASTA header description.
        sequence: Uppercase validated amino-acid sequence.
    """

    identifier: str
    description: str
    sequence: str


def normalise_sequence_id(identifier: str) -> str:
    """Convert a raw FASTA identifier into a stable FASTA-safe token.

    Only the first whitespace-delimited token is retained and unsupported
    characters are replaced with underscores.

    Args:
        identifier: Raw FASTA identifier or full header text.

    Returns:
        A non-empty identifier suitable for generated FASTA files.

    Raises:
        DataValidationError: If no identifier token remains after trimming.
    """

    token = str(identifier).strip().split()[0] if str(identifier).strip() else ""
    if not token:
        raise DataValidationError("FASTA identifier is empty")
    return _INTERNAL_ID_SAFE.sub("_", token)


def extract_entry(identifier: str) -> str:
    """Extract a UniProt accession from an identifier when possible.

    ``sp|ACCESSION|NAME`` and ``tr|ACCESSION|NAME`` identifiers return the
    middle accession. Other identifiers return their normalised token unchanged.

    Args:
        identifier: Raw or normalised sequence identifier.

    Returns:
        UniProt accession when recognised, otherwise the normalised identifier.

    Raises:
        DataValidationError: If the identifier is empty.
    """

    token = normalise_sequence_id(identifier)
    parts = token.split("|")
    if len(parts) >= 3 and parts[0] in {"sp", "tr"} and parts[1]:
        return parts[1]
    return token


def validate_protein_sequence(sequence: str) -> str:
    """Normalise and validate an amino-acid sequence.

    Whitespace is removed, letters are uppercased and all remaining characters
    must occur in the package protein alphabet.

    Args:
        sequence: Raw amino-acid sequence text.

    Returns:
        A non-empty uppercase sequence without whitespace.

    Raises:
        DataValidationError: If the sequence is empty or contains unsupported
            characters.
    """

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
    """Stream validated records from a plain or gzip-compressed FASTA file.

    Args:
        path: Input FASTA or ``.gz``-compressed FASTA path.

    Yields:
        :class:`FastaRecord` objects in source-file order.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        DataValidationError: If headers, record order or sequences are invalid.
    """

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
    """Build a validated FASTA record from one header and sequence fragments.

    Args:
        header: FASTA header text without the leading ``>`` character.
        sequence_parts: Ordered sequence lines belonging to the record.

    Returns:
        A normalised and validated :class:`FastaRecord`.

    Raises:
        DataValidationError: If the identifier or assembled sequence is invalid.
    """
    identifier = normalise_sequence_id(header)
    description = header[len(header.split()[0]):].strip()
    sequence = validate_protein_sequence("".join(sequence_parts))
    return FastaRecord(identifier, description, sequence)


def make_internal_id(
    sample_id: str,
    original_id: str,
    identifier_mode: str,
) -> str:
    """Create the sequence identifier used in the combined protein database.

    ``preserve`` retains the normalised source identifier. ``prefix_sample``
    prefixes it with the sample identifier and ``@@`` to avoid cross-proteome
    collisions.

    Args:
        sample_id: Unique sample identifier from the manifest.
        original_id: Source FASTA identifier.
        identifier_mode: ``preserve`` or ``prefix_sample``.

    Returns:
        A normalised internal sequence identifier.

    Raises:
        DataValidationError: If either identifier is empty after normalisation.
        ValueError: If ``identifier_mode`` is unsupported.
    """

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
    """Define the stable Arrow schema for prepared sequence metadata.

    Returns:
        A ``pyarrow.Schema`` covering identifiers, biological metadata,
        sequence values, checksums and source-record provenance.
    """

    return pa.schema(
        [
            ("internal_id", pa.string()),
            ("source_file_sample_id", pa.string()),
            ("source_file_species", pa.string()),
            ("sample_id", pa.string()),
            ("species", pa.string()),
            ("taxon_id", pa.string()),
            ("proteome_id", pa.string()),
            ("onekp_sample_code", pa.string()),
            ("header_parser", pa.string()),
            ("header_parse_status", pa.string()),
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
    """Write buffered sequence records to an open Parquet writer.

    The supplied list is cleared after a successful write so it can be reused as
    the next streaming batch.

    Args:
        writer: Open Parquet writer using :func:`sequence_schema`.
        rows: Mutable list of sequence-record mappings.

    Returns:
        None.

    Raises:
        ValueError: If rows cannot be converted to the required Arrow schema.
        OSError: If the Parquet batch cannot be written.
    """
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
    """Prepare deterministic combined FASTA and sequence-metadata outputs.

    Source FASTA files are streamed without modification. The function validates
    sample records, creates globally unique internal identifiers, rejects
    duplicates, computes sequence and optional source checksums, writes sequence
    metadata in Parquet batches, and writes one per-sample QC summary table.
    Outputs are published atomically only after successful completion.

    Args:
        samples: Proteome sample records to process in the supplied order.
        combined_fasta: Destination combined protein FASTA.
        sequence_parquet: Destination sequence-record Parquet table.
        sample_summary_tsv: Destination per-sample summary TSV.
        identifier_mode: Internal identifier policy, normally ``prefix_sample``.
        batch_size: Maximum sequence records held before each Parquet write.
        compute_checksums: Whether to calculate SHA-256 for each source FASTA.

    Returns:
        Counts for processed samples, protein sequences and amino-acid residues.

    Raises:
        ValueError: If ``batch_size`` or ``identifier_mode`` is invalid.
        FileNotFoundError: If a manifest FASTA path is missing.
        DataValidationError: If samples, identifiers or protein records fail
            validation, or a source FASTA contains no records.
        OSError: If outputs cannot be written.
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
    total_header_parse_failures = 0
    biological_sample_ids = set()
    biological_species = set()

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
                    header_parse_success_count = 0
                    header_parse_failure_count = 0
                    sample_biological_ids = set()
                    sample_biological_species = set()
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
                        record_metadata = sequence_biological_metadata(
                            sample,
                            record.identifier,
                        )
                        if record_metadata.header_parse_status == "parsed":
                            header_parse_success_count += 1
                        elif record_metadata.header_parse_status == "unparsed":
                            header_parse_failure_count += 1
                        sample_biological_ids.add(
                            record_metadata.biological_sample_id
                        )
                        if record_metadata.biological_species:
                            sample_biological_species.add(
                                record_metadata.biological_species
                            )
                        biological_sample_ids.add(
                            record_metadata.biological_sample_id
                        )
                        if record_metadata.biological_species:
                            biological_species.add(
                                record_metadata.biological_species
                            )
                        sequence = record.sequence
                        length = len(sequence)
                        digest = hashlib.md5(
                            sequence.encode("ascii"), usedforsecurity=False
                        ).hexdigest()
                        fasta_out.write(
                            f">{internal_id} original_id={record.identifier} "
                            f"source_file_sample_id={sample.sample_id} "
                            f"biological_sample_id="
                            f"{record_metadata.biological_sample_id}\n"
                        )
                        for start in range(0, length, 80):
                            fasta_out.write(sequence[start:start + 80] + "\n")
                        sequence_rows.append(
                            {
                                "internal_id": internal_id,
                                "source_file_sample_id": (
                                    record_metadata.source_file_sample_id
                                ),
                                "source_file_species": (
                                    record_metadata.source_file_species
                                ),
                                "sample_id": (
                                    record_metadata.biological_sample_id
                                ),
                                "species": record_metadata.biological_species,
                                "taxon_id": (
                                    record_metadata.biological_taxon_id
                                ),
                                "proteome_id": sample.proteome_id,
                                "onekp_sample_code": (
                                    record_metadata.onekp_sample_code
                                ),
                                "header_parser": record_metadata.header_parser,
                                "header_parse_status": (
                                    record_metadata.header_parse_status
                                ),
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
                            "source_file_sample_id": sample.sample_id,
                            "source_file_species": sample.species,
                            "taxon_id": sample.taxon_id,
                            "proteome_id": sample.proteome_id,
                            "header_parser": str(
                                sample.metadata.get(
                                    "header_parser",
                                    "manifest",
                                )
                            ),
                            "header_parse_success_count": (
                                header_parse_success_count
                            ),
                            "header_parse_failure_count": (
                                header_parse_failure_count
                            ),
                            "biological_sample_count": len(
                                sample_biological_ids
                            ),
                            "biological_species_count": len(
                                sample_biological_species
                            ),
                            "fasta_path": str(sample.fasta_path),
                            "source_sha256": source_checksum,
                            "sequence_count": sample_count,
                            "total_residues": sample_residues,
                        }
                    )
                    total_sequences += sample_count
                    total_residues += sample_residues
                    total_header_parse_failures += (
                        header_parse_failure_count
                    )
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
        "source_file_count": len(materialised),
        "sample_count": len(materialised),
        "biological_sample_count": len(biological_sample_ids),
        "biological_species_count": len(biological_species),
        "header_parse_failure_count": total_header_parse_failures,
        "sequence_count": total_sequences,
        "total_residues": total_residues,
    }


def write_fasta_records(
    records: Iterable[Tuple[str, str]],
    output_path: Path,
) -> int:
    """Write identifier-sequence pairs as an atomic, wrapped FASTA file.

    Args:
        records: Iterable of ``(identifier, sequence)`` pairs.
        output_path: Destination FASTA path.

    Returns:
        Number of FASTA records written.

    Raises:
        DataValidationError: If an identifier or sequence is invalid.
        OSError: If the FASTA output cannot be written or replaced.
    """

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
