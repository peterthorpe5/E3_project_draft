"""Streaming FASTA preparation and sequence metadata capture."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    MutableSequence,
    Optional,
    Sequence,
    Tuple,
)

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
        source_record_index: One-based record number in the source FASTA.
        header_line: One-based source line containing the FASTA header.
    """

    identifier: str
    description: str
    sequence: str
    source_record_index: int = 0
    header_line: int = 0


@dataclass(frozen=True)
class SkippedFastaRecord:
    """Describe one deliberately excluded malformed FASTA record.

    Attributes:
        source_file_sample_id: Manifest sample identifier for the source file.
        source_file_species: Manifest species label for the source file.
        source_path: FASTA file containing the excluded record.
        source_record_index: One-based record number in the source FASTA.
        header_line: One-based line containing the FASTA header.
        header: Complete source header without the leading ``>``.
        identifier: Normalised first header token when available.
        issue_type: Stable machine-readable reason for exclusion.
        details: Human-readable explanation of the exclusion.
    """

    source_file_sample_id: str
    source_file_species: str
    source_path: str
    source_record_index: int
    header_line: int
    header: str
    identifier: str
    issue_type: str
    details: str

    def as_dict(self) -> Dict[str, object]:
        """Return the issue as a deterministic TSV-ready mapping.

        Returns:
            Mapping containing all source-location and issue fields.
        """

        return {
            "source_file_sample_id": self.source_file_sample_id,
            "source_file_species": self.source_file_species,
            "source_path": self.source_path,
            "source_record_index": self.source_record_index,
            "header_line": self.header_line,
            "header": self.header,
            "identifier": self.identifier,
            "issue_type": self.issue_type,
            "details": self.details,
        }


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


def iter_fasta(
    path: Path,
    empty_sequence_policy: str = "error",
    skipped_records: Optional[MutableSequence[SkippedFastaRecord]] = None,
    maximum_skipped_empty_sequences: int = 0,
) -> Iterator[FastaRecord]:
    """Stream validated records from a plain or gzip-compressed FASTA file.

    Empty sequences remain fatal by default. A caller may explicitly request
    ``empty_sequence_policy="skip"`` for a known source with a small number of
    header-only records. Every skipped record is then captured with its source
    record number, header line and identifier. The iterator stops if the number
    skipped exceeds ``maximum_skipped_empty_sequences``.

    Args:
        path: Input FASTA or ``.gz``-compressed FASTA path.
        empty_sequence_policy: ``error`` or ``skip``.
        skipped_records: Optional mutable collection receiving skipped-record
            audit entries.
        maximum_skipped_empty_sequences: Maximum allowed empty records when the
            policy is ``skip``. Zero retains strict behaviour.

    Yields:
        :class:`FastaRecord` objects in source-file order.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If the empty-sequence settings are invalid.
        DataValidationError: If headers, record order, sequences or the skipped
            record safeguard are invalid.
    """

    if empty_sequence_policy not in {"error", "skip"}:
        raise ValueError(
            "empty_sequence_policy must be either 'error' or 'skip'"
        )
    if maximum_skipped_empty_sequences < 0:
        raise ValueError("maximum_skipped_empty_sequences cannot be negative")
    if empty_sequence_policy == "error" and maximum_skipped_empty_sequences:
        raise ValueError(
            "maximum_skipped_empty_sequences must be zero when policy is error"
        )

    current_header: Optional[str] = None
    current_header_line = 0
    source_record_index = 0
    sequence_parts: List[str] = []
    skipped_empty_count = 0

    def finish_current_record() -> Optional[FastaRecord]:
        """Validate the current record or capture an allowed empty record.

        Returns:
            Validated record, or ``None`` when no record exists or an allowed
            empty record was skipped.

        Raises:
            DataValidationError: If the record is invalid or the configured
                empty-record safeguard is exceeded.
        """

        nonlocal skipped_empty_count
        if current_header is None:
            return None
        try:
            return _record_from_parts(
                current_header,
                sequence_parts,
                source_record_index=source_record_index,
                header_line=current_header_line,
            )
        except DataValidationError as error:
            if str(error) != "Protein sequence is empty":
                raise DataValidationError(
                    f"{error} at {path}:{current_header_line}; "
                    f"record {source_record_index}; header={current_header!r}"
                ) from error
            message = (
                f"Protein sequence is empty at {path}:{current_header_line}; "
                f"record {source_record_index}; header={current_header!r}"
            )
            if empty_sequence_policy == "error":
                raise DataValidationError(message) from error
            skipped_empty_count += 1
            issue = SkippedFastaRecord(
                source_file_sample_id="",
                source_file_species="",
                source_path=str(Path(path).resolve()),
                source_record_index=source_record_index,
                header_line=current_header_line,
                header=current_header,
                identifier=normalise_sequence_id(current_header),
                issue_type="empty_sequence",
                details="Header-only FASTA record contained no amino-acid sequence",
            )
            if skipped_records is not None:
                skipped_records.append(issue)
            LOGGER.warning(
                "Skipping empty FASTA record %d in %s at header line %d: %s",
                source_record_index,
                path,
                current_header_line,
                current_header,
            )
            if skipped_empty_count > maximum_skipped_empty_sequences:
                raise DataValidationError(
                    f"Skipped empty FASTA record safeguard exceeded for {path}: "
                    f"{skipped_empty_count} found, maximum allowed is "
                    f"{maximum_skipped_empty_sequences}"
                ) from error
            return None

    with open_text_auto(path) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            if line.startswith(">"):
                record = finish_current_record()
                if record is not None:
                    yield record
                source_record_index += 1
                current_header_line = line_number
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
    record = finish_current_record()
    if record is not None:
        yield record


def _record_from_parts(
    header: str,
    sequence_parts: Sequence[str],
    source_record_index: int = 0,
    header_line: int = 0,
) -> FastaRecord:
    """Build a validated FASTA record from one header and sequence fragments.

    Args:
        header: FASTA header text without the leading ``>`` character.
        sequence_parts: Ordered sequence lines belonging to the record.
        source_record_index: One-based source record number when known.
        header_line: One-based source header line when known.

    Returns:
        A normalised and validated :class:`FastaRecord`.

    Raises:
        DataValidationError: If the identifier or assembled sequence is invalid.
    """

    identifier = normalise_sequence_id(header)
    description = header[len(header.split()[0]):].strip()
    sequence = validate_protein_sequence("".join(sequence_parts))
    return FastaRecord(
        identifier,
        description,
        sequence,
        source_record_index=source_record_index,
        header_line=header_line,
    )


def _sample_empty_sequence_settings(sample: SampleRecord) -> Tuple[str, int]:
    """Resolve per-sample empty-record handling from manifest metadata.

    Args:
        sample: Source sample record with optional policy metadata.

    Returns:
        Pair of empty-sequence policy and maximum permitted skipped records.

    Raises:
        DataValidationError: If metadata values are unsupported or inconsistent.
    """

    policy = str(
        sample.metadata.get("empty_sequence_policy", "error")
    ).strip().lower()
    if policy not in {"error", "skip"}:
        raise DataValidationError(
            f"Unsupported empty_sequence_policy {policy!r} for sample "
            f"{sample.sample_id}"
        )
    raw_maximum = str(
        sample.metadata.get("maximum_skipped_empty_sequences", "0")
    ).strip()
    try:
        maximum = int(raw_maximum or "0")
    except ValueError as error:
        raise DataValidationError(
            "maximum_skipped_empty_sequences must be an integer for sample "
            f"{sample.sample_id}: {raw_maximum!r}"
        ) from error
    if maximum < 0:
        raise DataValidationError(
            "maximum_skipped_empty_sequences cannot be negative for sample "
            f"{sample.sample_id}"
        )
    if policy == "error" and maximum:
        raise DataValidationError(
            "maximum_skipped_empty_sequences must be zero when policy is "
            f"error for sample {sample.sample_id}"
        )
    if policy == "skip" and maximum < 1:
        raise DataValidationError(
            "empty_sequence_policy skip requires a positive "
            f"maximum_skipped_empty_sequences for sample {sample.sample_id}"
        )
    return policy, maximum


def _write_skipped_fasta_records(
    records: Iterable[SkippedFastaRecord],
    output_path: Path,
) -> int:
    """Write skipped FASTA records with a header even when there are no rows.

    Args:
        records: Skipped-record audit entries.
        output_path: Destination QC TSV.

    Returns:
        Number of skipped-record data rows written.

    Raises:
        OSError: If the atomic output cannot be written.
    """

    materialised = list(records)
    fields = [
        "source_file_sample_id",
        "source_file_species",
        "source_path",
        "source_record_index",
        "header_line",
        "header",
        "identifier",
        "issue_type",
        "details",
    ]
    with atomic_text_writer(output_path, newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        for record in materialised:
            writer.writerow(record.as_dict())
    return len(materialised)


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
    skipped_records_tsv: Optional[Path] = None,
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
        skipped_records_tsv: Optional QC TSV for deliberately excluded FASTA
            records. The file includes a header even when no records are skipped.
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
    total_skipped_records = 0
    all_skipped_records: List[SkippedFastaRecord] = []
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
                    empty_policy, maximum_skipped = (
                        _sample_empty_sequence_settings(sample)
                    )
                    sample_skipped_records: List[SkippedFastaRecord] = []
                    for record in iter_fasta(
                        sample.fasta_path,
                        empty_sequence_policy=empty_policy,
                        skipped_records=sample_skipped_records,
                        maximum_skipped_empty_sequences=maximum_skipped,
                    ):
                        record_index = record.source_record_index
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
                    enriched_skipped_records = [
                        SkippedFastaRecord(
                            source_file_sample_id=sample.sample_id,
                            source_file_species=sample.species,
                            source_path=issue.source_path,
                            source_record_index=issue.source_record_index,
                            header_line=issue.header_line,
                            header=issue.header,
                            identifier=issue.identifier,
                            issue_type=issue.issue_type,
                            details=issue.details,
                        )
                        for issue in sample_skipped_records
                    ]
                    all_skipped_records.extend(enriched_skipped_records)
                    sample_skipped_count = len(enriched_skipped_records)
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
                            "source_record_count": (
                                sample_count + sample_skipped_count
                            ),
                            "sequence_count": sample_count,
                            "skipped_record_count": sample_skipped_count,
                            "empty_sequence_policy": empty_policy,
                            "maximum_skipped_empty_sequences": maximum_skipped,
                            "total_residues": sample_residues,
                        }
                    )
                    total_sequences += sample_count
                    total_residues += sample_residues
                    total_header_parse_failures += (
                        header_parse_failure_count
                    )
                    total_skipped_records += sample_skipped_count
                    LOGGER.info(
                        "Prepared sample %s: %d sequences, %d residues, "
                        "%d skipped records",
                        sample.sample_id,
                        sample_count,
                        sample_residues,
                        sample_skipped_count,
                    )
                _flush_sequence_rows(writer, sequence_rows)
        finally:
            writer.close()

    write_tsv(summaries, sample_summary_tsv)
    if skipped_records_tsv is not None:
        _write_skipped_fasta_records(
            all_skipped_records,
            skipped_records_tsv,
        )
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
        "skipped_record_count": total_skipped_records,
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
