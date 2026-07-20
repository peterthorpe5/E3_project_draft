"""Explicit OrthoFinder and UniProt identifier parsing."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from .errors import InputValidationError
from .io_utils import ensure_readable_file

_UNIPROT_PIPE_PATTERN = re.compile(
    r"^(?P<review_status>sp|tr)\|(?P<accession>[^|\s]+)\|(?P<entry>[^|\s]+)$"
)
_BARE_ACCESSION_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{2,31}$")
_INTERNAL_ID_PATTERN = re.compile(r"^(?P<species_index>\d+)_(?P<sequence_index>\d+)$")


@dataclass(frozen=True)
class ParsedIdentifier:
    """Normalised representation of one raw sequence identifier."""

    raw_identifier: str
    parsed_accession: str | None
    parsed_entry: str | None
    review_status: str | None
    identifier_format: str
    mapping_status: str
    mapping_reason: str

    def to_record(self) -> dict[str, str | None]:
        """Return a dictionary suitable for TSV or Parquet output.

        Returns:
            Dataclass fields as a new dictionary.
        """

        return asdict(self)


@dataclass(frozen=True)
class SequenceIdentifierRecord:
    """OrthoFinder internal identifier mapped to its retained source header."""

    internal_id: str
    species_index: int
    source_fasta: str
    raw_header: str
    parsed: ParsedIdentifier
    source_line: int

    def to_record(self) -> dict[str, str | int | None]:
        """Return a flat portable record.

        Returns:
            Ordered-value mapping for table output.
        """

        return {
            "internal_id": self.internal_id,
            "species_index": self.species_index,
            "source_fasta": self.source_fasta,
            "raw_header": self.raw_header,
            **self.parsed.to_record(),
            "source_line": self.source_line,
        }


def parse_identifier(*, value: str) -> ParsedIdentifier:
    """Parse a raw FASTA first token without silently rewriting it.

    Args:
        value: Raw identifier or complete FASTA header.

    Returns:
        Parsed identifier with an explicit format and status.
    """

    stripped = value.strip()
    first_token = stripped.split(maxsplit=1)[0] if stripped else ""
    pipe_match = _UNIPROT_PIPE_PATTERN.fullmatch(first_token)
    if pipe_match:
        review_code = pipe_match.group("review_status")
        return ParsedIdentifier(
            raw_identifier=first_token,
            parsed_accession=pipe_match.group("accession"),
            parsed_entry=pipe_match.group("entry"),
            review_status="reviewed" if review_code == "sp" else "unreviewed",
            identifier_format="UNIPROT_PIPE",
            mapping_status="PARSED",
            mapping_reason="controlled_uniprot_pipe_parser",
        )
    if _BARE_ACCESSION_PATTERN.fullmatch(first_token):
        return ParsedIdentifier(
            raw_identifier=first_token,
            parsed_accession=first_token,
            parsed_entry=None,
            review_status=None,
            identifier_format="BARE_TOKEN",
            mapping_status="PARSED",
            mapping_reason="controlled_bare_token_parser",
        )
    return ParsedIdentifier(
        raw_identifier=first_token,
        parsed_accession=None,
        parsed_entry=None,
        review_status=None,
        identifier_format="UNKNOWN",
        mapping_status="NOT_PARSED",
        mapping_reason="identifier_did_not_match_a_supported_format",
    )


def parse_species_ids(*, path: Path) -> dict[int, str]:
    """Parse OrthoFinder ``SpeciesIDs.txt`` with duplicate validation.

    Args:
        path: OrthoFinder species mapping file.

    Returns:
        Species index to original FASTA name.

    Raises:
        InputValidationError: If any line is malformed or duplicated.
    """

    source = ensure_readable_file(path=path)
    species: dict[int, str] = {}
    with source.open(mode="r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.rstrip("\n")
            if not stripped:
                continue
            index_text, separator, fasta_name = stripped.partition(": ")
            if not separator or not index_text.isdigit() or not fasta_name.strip():
                raise InputValidationError(
                    f"Malformed SpeciesIDs line {line_number} in {source}: {stripped!r}"
                )
            index = int(index_text)
            if index in species:
                raise InputValidationError(
                    f"Duplicate species index {index} at line {line_number} in {source}"
                )
            species[index] = fasta_name.strip()
    if not species:
        raise InputValidationError(f"SpeciesIDs contains no records: {source}")
    return species


def iter_sequence_ids(
    *,
    path: Path,
    species_by_index: dict[int, str],
) -> Iterator[SequenceIdentifierRecord]:
    """Yield validated records from OrthoFinder ``SequenceIDs.txt``.

    Args:
        path: OrthoFinder sequence mapping file.
        species_by_index: Validated species index mapping.

    Yields:
        Parsed internal-to-source identifier records.

    Raises:
        InputValidationError: If a line, internal identifier or species is invalid.
    """

    source = ensure_readable_file(path=path)
    seen_internal_ids: set[str] = set()
    with source.open(mode="r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.rstrip("\n")
            if not stripped:
                continue
            internal_id, separator, raw_header = stripped.partition(": ")
            match = _INTERNAL_ID_PATTERN.fullmatch(internal_id)
            if not separator or match is None or not raw_header.strip():
                raise InputValidationError(
                    f"Malformed SequenceIDs line {line_number} in {source}: {stripped!r}"
                )
            if internal_id in seen_internal_ids:
                raise InputValidationError(
                    f"Duplicate internal identifier {internal_id!r} in {source}"
                )
            seen_internal_ids.add(internal_id)
            species_index = int(match.group("species_index"))
            if species_index not in species_by_index:
                raise InputValidationError(
                    f"Unknown species index {species_index} at line {line_number} in {source}"
                )
            yield SequenceIdentifierRecord(
                internal_id=internal_id,
                species_index=species_index,
                source_fasta=species_by_index[species_index],
                raw_header=raw_header.strip(),
                parsed=parse_identifier(value=raw_header),
                source_line=line_number,
            )
