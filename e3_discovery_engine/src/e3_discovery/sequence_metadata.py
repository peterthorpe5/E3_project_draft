"""Per-sequence biological metadata extraction from FASTA identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from e3_discovery.exceptions import DataValidationError
from e3_discovery.manifest import SampleRecord

_ONEKP_PATTERN = re.compile(
    r"^scaffold-(?P<sample_code>[A-Za-z0-9]{4})-"
    r"(?P<scaffold_number>[0-9]+)-(?P<species>.+)$"
)
_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on"})


@dataclass(frozen=True)
class SequenceBiologicalMetadata:
    """Describe biological metadata assigned to one sequence record.

    Attributes:
        source_file_sample_id: Manifest sample identifier for the source FASTA.
        source_file_species: Manifest species label for the source FASTA.
        biological_sample_id: Per-sequence biological sample identifier.
        biological_species: Per-sequence species label.
        biological_taxon_id: Per-sequence taxonomy identifier when available.
        onekp_sample_code: Four-character 1KP sample code when parsed.
        header_parser: Parser selected through the sample manifest.
        header_parse_status: ``parsed``, ``not_requested`` or ``unparsed``.
    """

    source_file_sample_id: str
    source_file_species: str
    biological_sample_id: str
    biological_species: str
    biological_taxon_id: str
    onekp_sample_code: str
    header_parser: str
    header_parse_status: str


def normalise_species_label(value: str) -> str:
    """Convert an identifier-style species label to readable text.

    Underscores are converted to spaces, repeated whitespace is collapsed and
    leading or trailing separators are removed.

    Args:
        value: Raw species label extracted from a sequence identifier.

    Returns:
        Normalised species label, or an empty string when ``value`` is blank.
    """

    text = str(value or "").strip().strip("-_")
    return " ".join(text.replace("_", " ").split())


def parse_onekp_scaffold_identifier(identifier: str) -> tuple[str, str]:
    """Parse a 1KP scaffold identifier into sample code and species.

    The supported inherited format is
    ``scaffold-CODE-NUMBER-Genus_species``. The four-character sample code and
    source species are retained without attempting external taxonomy lookup.

    Args:
        identifier: FASTA identifier token without the leading ``>``.

    Returns:
        Pair containing the four-character 1KP sample code and species label.

    Raises:
        DataValidationError: If the identifier does not match the inherited 1KP
            scaffold convention or the species label is empty.
    """

    match = _ONEKP_PATTERN.fullmatch(str(identifier).strip())
    if not match:
        raise DataValidationError(
            "1KP identifier does not match "
            "scaffold-CODE-NUMBER-Genus_species: "
            f"{identifier}"
        )
    species = normalise_species_label(match.group("species"))
    if not species:
        raise DataValidationError(
            f"1KP identifier contains no usable species label: {identifier}"
        )
    return match.group("sample_code").upper(), species


def metadata_flag_is_true(value: object) -> bool:
    """Interpret a manifest metadata value as a Boolean flag.

    Args:
        value: Manifest metadata value such as ``true``, ``1`` or ``yes``.

    Returns:
        ``True`` for recognised affirmative values and ``False`` otherwise.
    """

    return str(value or "").strip().lower() in _TRUE_VALUES


def sequence_biological_metadata(
    sample: SampleRecord,
    identifier: str,
) -> SequenceBiologicalMetadata:
    """Resolve biological metadata for one FASTA record.

    Most samples use their manifest metadata unchanged. Samples with
    ``header_parser=onekp_scaffold`` derive a biological sample code and species
    from each 1KP scaffold identifier while retaining the source-file sample.

    Args:
        sample: Source FASTA sample record from the manifest.
        identifier: Parsed FASTA identifier token.

    Returns:
        Immutable per-sequence biological metadata.

    Raises:
        DataValidationError: If the selected parser is unsupported, or strict
            1KP parsing is requested and the identifier cannot be parsed.
    """

    parser_name = str(sample.metadata.get("header_parser", "manifest")).strip()
    parser_name = parser_name.lower() or "manifest"
    if parser_name in {"manifest", "none"}:
        return SequenceBiologicalMetadata(
            source_file_sample_id=sample.sample_id,
            source_file_species=sample.species,
            biological_sample_id=sample.sample_id,
            biological_species=sample.species,
            biological_taxon_id=sample.taxon_id,
            onekp_sample_code="",
            header_parser="manifest",
            header_parse_status="not_requested",
        )
    if parser_name != "onekp_scaffold":
        raise DataValidationError(
            f"Unsupported header_parser {parser_name!r} for sample "
            f"{sample.sample_id}"
        )
    try:
        sample_code, species = parse_onekp_scaffold_identifier(identifier)
    except DataValidationError:
        if metadata_flag_is_true(sample.metadata.get("header_parser_strict")):
            raise
        return SequenceBiologicalMetadata(
            source_file_sample_id=sample.sample_id,
            source_file_species=sample.species,
            biological_sample_id=sample.sample_id,
            biological_species=sample.species,
            biological_taxon_id=sample.taxon_id,
            onekp_sample_code="",
            header_parser=parser_name,
            header_parse_status="unparsed",
        )
    return SequenceBiologicalMetadata(
        source_file_sample_id=sample.sample_id,
        source_file_species=sample.species,
        biological_sample_id=sample_code,
        biological_species=species,
        biological_taxon_id="",
        onekp_sample_code=sample_code,
        header_parser=parser_name,
        header_parse_status="parsed",
    )
