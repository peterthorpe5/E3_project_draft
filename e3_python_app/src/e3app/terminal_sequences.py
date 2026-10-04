"""C-terminal sequence conservation queries for orthology-group members."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Sequence

import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError
from e3app.taxonomy import CompiledTaxonomyFilters

LOGGER = logging.getLogger(__name__)

DEFAULT_TERMINAL_SEQUENCE = "N"
DEFAULT_MINIMUM_MATCH_FRACTION = 0.80
MAX_TERMINAL_SEQUENCE_LENGTH = 50
MAXIMUM_RESULT_ROWS = 100_000
HUMAN_SPECIES = "Homo_sapiens"
ARABIDOPSIS_SPECIES = "Arabidopsis_thaliana"

SEQUENCE_RELATION_PREFERENCE = (
    "orthology_group_member_sequences",
    "candidate_group_member_sequences",
)
REQUIRED_SEQUENCE_COLUMNS = {
    "record_type",
    "group_id",
    "species",
    "raw_identifier",
    "protein_sequence",
}
GROUP_RECORD_TYPES = {
    "hierarchical_orthogroup": "HIERARCHICAL_ORTHOGROUP",
    "orthogroup": "ORTHOGROUP",
}
_PROTEIN_ALPHABET = re.compile(r"^[A-Z]+$")


@dataclass(frozen=True)
class TerminalSequenceCapability:
    """Availability and scope of sequence-bearing orthology membership.

    Attributes:
        available: Whether a supported relation can answer the query.
        relation: Selected relation name, if available.
        candidate_bounded: Whether the relation contains only groups linked to
            the E3 candidate analysis rather than the complete proteome set.
        scope_label: Plain-language scope for display and downloads.
        missing_columns: Required columns absent from the selected relation.
        reason: Explanation when the capability is unavailable.
    """

    available: bool
    relation: str | None
    candidate_bounded: bool
    scope_label: str
    missing_columns: tuple[str, ...]
    reason: str


def normalise_terminal_sequence(*, value: object) -> str:
    """Validate and normalise an exact C-terminal amino-acid sequence.

    Args:
        value: User-supplied one-letter amino-acid sequence.

    Returns:
        Upper-case exact terminal sequence.

    Raises:
        AppError: If the sequence is empty, too long or contains characters
            outside the IUPAC protein alphabet used by the application.
    """
    if value is not None and not isinstance(value, str):
        raise AppError(
            "The C-terminal sequence must be text containing one-letter amino-acid codes"
        )
    text = "" if value is None else value.strip().upper()
    if not text:
        raise AppError("Enter at least one C-terminal amino-acid residue")
    if len(text) > MAX_TERMINAL_SEQUENCE_LENGTH:
        raise AppError(
            "The C-terminal sequence cannot exceed "
            f"{MAX_TERMINAL_SEQUENCE_LENGTH} residues"
        )
    if not _PROTEIN_ALPHABET.fullmatch(text):
        raise AppError(
            "Use only one-letter IUPAC amino-acid codes without spaces, "
            "gaps, stop symbols or wildcards"
        )
    return text


def terminal_sequence_capability(*, connection: object) -> TerminalSequenceCapability:
    """Select the strongest supported sequence-bearing orthology relation.

    Args:
        connection: Open read-only DuckDB connection.

    Returns:
        Capability record identifying the selected relation and its scope.
    """
    available = set(list_relations(connection))
    incomplete: list[tuple[str, tuple[str, ...]]] = []
    for relation in SEQUENCE_RELATION_PREFERENCE:
        if relation not in available:
            continue
        columns = set(relation_columns(connection, relation))
        missing = tuple(sorted(REQUIRED_SEQUENCE_COLUMNS.difference(columns)))
        if missing:
            incomplete.append((relation, missing))
            continue
        candidate_bounded = relation == "candidate_group_member_sequences"
        scope = (
            "E3 candidate-linked OrthoFinder groups"
            if candidate_bounded
            else "all published sequence-bearing OrthoFinder groups"
        )
        return TerminalSequenceCapability(
            available=True,
            relation=relation,
            candidate_bounded=candidate_bounded,
            scope_label=scope,
            missing_columns=(),
            reason="",
        )
    if incomplete:
        relation, missing = incomplete[0]
        reason = (
            f"`{relation}` is missing required columns: " + ", ".join(missing)
        )
        return TerminalSequenceCapability(
            available=False,
            relation=relation,
            candidate_bounded=(relation == "candidate_group_member_sequences"),
            scope_label="unavailable sequence authority",
            missing_columns=missing,
            reason=reason,
        )
    return TerminalSequenceCapability(
        available=False,
        relation=None,
        candidate_bounded=False,
        scope_label="unavailable sequence authority",
        missing_columns=tuple(sorted(REQUIRED_SEQUENCE_COLUMNS)),
        reason=(
            "The loaded release contains no supported sequence-bearing "
            "orthology member relation"
        ),
    )


def _validate_group_type(*, group_type: str) -> str:
    """Return the source record type for a supported group selector."""
    try:
        return GROUP_RECORD_TYPES[group_type]
    except KeyError as exc:
        raise AppError(f"Unsupported OrthoFinder grouping level: {group_type}") from exc


def _normalise_plant_species(
    *, plant_species: Sequence[str], human_species: Sequence[str] = (HUMAN_SPECIES,)
) -> tuple[str, ...]:
    """Return unique plant source labels while excluding reviewed human labels.

    Args:
        plant_species: Exact reviewed source labels defining the denominator.
        human_species: Exact reviewed human source labels to exclude.

    Returns:
        Stable distinct source labels with a non-empty plant denominator.

    Raises:
        AppError: If a string replaces a species list or no plant labels remain.
    """
    if isinstance(plant_species, (str, bytes)):
        raise AppError("Plant species must be supplied as a sequence of source labels")
    labels: list[str] = []
    for value in plant_species:
        label = str(value).strip()
        if (label and label not in labels
                and label not in (*human_species, HUMAN_SPECIES)):
            labels.append(label)
    if not labels:
        raise AppError("No reviewed target-plant species are available for this query")
    return tuple(labels)


def _validate_fraction(*, value: float) -> float:
    """Validate a zero-to-one matching fraction."""
    if isinstance(value, bool):
        raise AppError("The minimum matching fraction must be between 0 and 1")
    try:
        fraction = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AppError("The minimum matching fraction must be between 0 and 1") from exc
    if not 0.0 <= fraction <= 1.0:
        raise AppError("The minimum matching fraction must be between 0 and 1")
    return fraction


def _validate_positive_limit(*, value: int, label: str, maximum: int) -> int:
    """Validate one bounded positive integer query control."""
    if isinstance(value, bool):
        raise AppError(f"{label} must be a positive integer")
    try:
        integer = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AppError(f"{label} must be a positive integer") from exc
    if str(value).strip() != str(integer):
        raise AppError(f"{label} must be a positive integer")
    if integer < 1 or integer > maximum:
        raise AppError(f"{label} must be between 1 and {maximum}")
    return integer


def _optional_text(*, columns: set[str], column: str) -> str:
    """Return a nullable text expression for an optional source column."""
    if column not in columns:
        return "CAST(NULL AS VARCHAR)"
    return f"CAST({quote_identifier(column)} AS VARCHAR)"


def _optional_boolean(*, columns: set[str], column: str) -> str:
    """Return a nullable Boolean expression for an optional source column."""
    if column not in columns:
        return "CAST(NULL AS BOOLEAN)"
    return f"TRY_CAST({quote_identifier(column)} AS BOOLEAN)"


def _optional_integer(*, columns: set[str], column: str) -> str:
    """Return a nullable integer expression for an optional source column."""
    if column not in columns:
        return "CAST(NULL AS BIGINT)"
    return f"TRY_CAST({quote_identifier(column)} AS BIGINT)"


def _member_ctes(
    *,
    connection: object,
    capability: TerminalSequenceCapability,
    plant_species: tuple[str, ...],
    human_species: Sequence[str] = (HUMAN_SPECIES,),
    arabidopsis_species: Sequence[str] = (ARABIDOPSIS_SPECIES,),
) -> tuple[str, list[object]]:
    """Build deduplicated member CTEs and exact species-role parameters.

    Args:
        connection: Open read-only DuckDB connection.
        capability: Validated sequence relation and scientific scope.
        plant_species: Exact plant source labels in the conservation denominator.
        human_species: Reviewed human source labels.
        arabidopsis_species: Reviewed Arabidopsis source labels.

    Returns:
        SQL common-table expressions and ordered role-classification parameters.

    Raises:
        AppError: If the sequence authority is unavailable.
    """
    if not capability.available or capability.relation is None:
        raise AppError(capability.reason)
    columns = set(relation_columns(connection, capability.relation))
    relation = quote_identifier(capability.relation)
    plant_placeholders = ", ".join("?" for _ in plant_species)
    human_expression = (
        "species IN (" + ", ".join("?" for _ in human_species) + ")"
        if human_species else "FALSE"
    )
    arabidopsis_expression = (
        "species IN (" + ", ".join("?" for _ in arabidopsis_species) + ")"
        if arabidopsis_species else "FALSE"
    )
    internal_id = _optional_text(columns=columns, column="internal_id")
    parsed_accession = _optional_text(columns=columns, column="parsed_accession")
    parsed_entry = _optional_text(columns=columns, column="parsed_entry")
    review_status = _optional_text(columns=columns, column="review_status")
    mapping_status = _optional_text(columns=columns, column="mapping_status")
    cluster_id = _optional_text(columns=columns, column="cluster_id")
    candidates = _optional_text(
        columns=columns,
        column="candidate_accessions_for_cluster",
    )
    is_input_candidate = _optional_boolean(
        columns=columns,
        column="is_input_candidate",
    )
    sequence_length = _optional_integer(columns=columns, column="sequence_length")
    description_column = next(
        (name for name in ("protein_description", "protein_name", "protein_names", "description")
         if name in columns),
        "protein_description",
    )
    description = _optional_text(columns=columns, column=description_column)
    sql = f"""
        source_rows AS (
            SELECT
                trim(CAST(group_id AS VARCHAR)) AS group_id,
                trim(CAST(species AS VARCHAR)) AS species,
                trim(CAST(raw_identifier AS VARCHAR)) AS raw_identifier,
                nullif(trim({internal_id}), '') AS internal_id,
                nullif(trim({parsed_accession}), '') AS parsed_accession,
                nullif(trim({parsed_entry}), '') AS parsed_entry,
                nullif(trim({review_status}), '') AS review_status,
                nullif(trim({mapping_status}), '') AS mapping_status,
                nullif(trim({description}), '') AS protein_description,
                nullif(trim({cluster_id}), '') AS cluster_id,
                nullif(trim({candidates}), '') AS candidate_accessions,
                {is_input_candidate} AS is_input_candidate,
                {sequence_length} AS recorded_sequence_length,
                nullif(
                    upper(
                        regexp_replace(
                            CAST(protein_sequence AS VARCHAR),
                            '[[:space:]]',
                            '',
                            'g'
                        )
                    ),
                    ''
                ) AS protein_sequence
            FROM {relation}
            WHERE upper(trim(CAST(record_type AS VARCHAR))) = ?
              AND nullif(trim(CAST(group_id AS VARCHAR)), '') IS NOT NULL
              AND nullif(trim(CAST(species AS VARCHAR)), '') IS NOT NULL
              AND nullif(trim(CAST(raw_identifier AS VARCHAR)), '') IS NOT NULL
        ),
        members AS (
            SELECT
                group_id,
                species,
                coalesce(
                    internal_id,
                    parsed_accession,
                    raw_identifier
                ) AS member_key,
                min(raw_identifier) AS raw_identifier,
                min(parsed_accession) AS parsed_accession,
                min(parsed_entry) AS parsed_entry,
                min(review_status) AS review_status,
                min(mapping_status) AS mapping_status,
                min(protein_description) AS protein_description,
                bool_or(is_input_candidate) AS is_input_candidate,
                string_agg(
                    DISTINCT cluster_id,
                    ';' ORDER BY cluster_id
                ) FILTER (WHERE cluster_id IS NOT NULL) AS source_cluster_ids,
                string_agg(
                    DISTINCT candidate_accessions,
                    ';' ORDER BY candidate_accessions
                ) FILTER (WHERE candidate_accessions IS NOT NULL)
                    AS candidate_accessions,
                max(recorded_sequence_length) AS recorded_sequence_length,
                protein_sequence,
                species IN ({plant_placeholders}) AS is_target_plant,
                {human_expression} AS is_human,
                {arabidopsis_expression} AS is_arabidopsis
            FROM source_rows
            GROUP BY group_id, species, member_key, protein_sequence
        )
    """
    return sql, [*plant_species, *human_species, *arabidopsis_species]


def _taxonomy_group_predicate(
    *, compiled_taxonomy: CompiledTaxonomyFilters | None,
) -> tuple[str, list[object]]:
    """Build parameterised group-membership predicates over the sequence authority.

    Args:
        compiled_taxonomy: Reviewed taxonomy predicates, or no active filtering.

    Returns:
        SQL Boolean expression and ordered bound parameters. Only-in predicates
        reject every outside or unmapped member. Required exact taxa accept any
        reviewed source label for the same taxon.
    """
    if compiled_taxonomy is None or not compiled_taxonomy.active:
        return "TRUE", []
    clauses: list[str] = []
    parameters: list[object] = []
    required_taxa = {
        taxon_id for source, taxon_id in compiled_taxonomy.species_taxon_ids
        if source in compiled_taxonomy.required_exact_species
    }
    required_sets = [
        tuple(source for source, leaf in compiled_taxonomy.species_taxon_ids if leaf == taxon_id)
        for taxon_id in sorted(required_taxa)
    ]
    required_sets.extend(species for _, species in compiled_taxonomy.include_clade_species)
    for species in required_sets:
        placeholders = ", ".join("?" for _ in species)
        clauses.append(
            "EXISTS (SELECT 1 FROM members AS taxon_member "
            "WHERE taxon_member.group_id = combined.group_id "
            f"AND taxon_member.species IN ({placeholders}))"
        )
        parameters.extend(species)
    if compiled_taxonomy.only_allowed_species is not None:
        allowed = set(compiled_taxonomy.only_allowed_species).intersection(
            compiled_taxonomy.mapped_species
        )
        if not allowed:
            clauses.append("FALSE")
        else:
            placeholders = ", ".join("?" for _ in allowed)
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM members AS taxon_member "
                "WHERE taxon_member.group_id = combined.group_id "
                f"AND taxon_member.species NOT IN ({placeholders}))"
            )
            parameters.extend(sorted(allowed))
    if compiled_taxonomy.excluded_species:
        placeholders = ", ".join("?" for _ in compiled_taxonomy.excluded_species)
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM members AS taxon_member "
            "WHERE taxon_member.group_id = combined.group_id "
            f"AND taxon_member.species IN ({placeholders}))"
        )
        parameters.extend(compiled_taxonomy.excluded_species)
    return " AND ".join(clauses), parameters


def collect_terminal_species(*, connection: object, group_type: str) -> tuple[str, ...]:
    """List source species represented in the selected sequence-bearing group type.

    Args:
        connection: Open read-only DuckDB connection.
        group_type: Exact supported HOG or OG grouping selector.

    Returns:
        Sorted distinct non-empty source labels for taxonomy filter compilation.

    Raises:
        AppError: If the grouping or sequence authority is unavailable.
    """
    record_type = _validate_group_type(group_type=group_type)
    capability = terminal_sequence_capability(connection=connection)
    if not capability.available:
        raise AppError(capability.reason)
    query = (
        "SELECT DISTINCT trim(CAST(species AS VARCHAR)) AS species "
        f"FROM {quote_identifier(capability.relation)} "
        "WHERE upper(trim(CAST(record_type AS VARCHAR))) = ? "
        "AND nullif(trim(CAST(species AS VARCHAR)), '') IS NOT NULL ORDER BY species"
    )
    try:
        return tuple(str(row[0]) for row in connection.execute(query, [record_type]).fetchall())
    except Exception as exc:
        LOGGER.exception("Could not list terminal-screen species")
        raise AppError("Could not list C-terminal source species") from exc


def collect_terminal_group_summary(
    *,
    connection: object,
    group_type: str,
    terminal_sequence: object = DEFAULT_TERMINAL_SEQUENCE,
    minimum_match_fraction: float = DEFAULT_MINIMUM_MATCH_FRACTION,
    minimum_species_match_fraction: float = 0.0,
    minimum_sequence_coverage_fraction: float = 0.0,
    minimum_plant_members: int = 2,
    minimum_plant_species: int = 2,
    require_arabidopsis_match: bool = True,
    plant_species: Sequence[str],
    maximum_rows: int = 10_000,
    compiled_taxonomy: CompiledTaxonomyFilters | None = None,
    human_species: Sequence[str] = (HUMAN_SPECIES,),
    arabidopsis_species: Sequence[str] = (ARABIDOPSIS_SPECIES,),
) -> pd.DataFrame:
    """Return orthology groups meeting an exact plant C-terminal screen.

    The primary fraction is calculated across plant members with a published
    sequence. Human rows are retained as a separate comparison and never enter
    the plant denominator.

    Args:
        connection: Open read-only DuckDB connection.
        group_type: ``hierarchical_orthogroup`` or ``orthogroup``.
        terminal_sequence: Exact one-letter sequence required at the C terminus.
        minimum_match_fraction: Minimum matching plant-member fraction.
        minimum_species_match_fraction: Optional matching assessed-species gate.
        minimum_sequence_coverage_fraction: Optional assessed/published plant-member gate.
        minimum_plant_members: Minimum plant members with sequence evidence.
        minimum_plant_species: Minimum represented plant species with sequence
            evidence.
        require_arabidopsis_match: Require at least one matching Arabidopsis
            member for practical follow-up.
        plant_species: Reviewed source labels treated as target plants.
        maximum_rows: Maximum qualifying groups returned.
        compiled_taxonomy: Optional reviewed predicates on all published group members.
        human_species: Exact reviewed source labels for human comparison members.
        arabidopsis_species: Exact reviewed source labels for Arabidopsis members.

    Returns:
        One row per qualifying HOG or OG, ordered by match strength and breadth.
        ``attrs['screen_audit']`` retains source, plant, assessable, taxonomy and
        qualifying group counts before the result limit, including empty screens.

    Raises:
        AppError: If inputs or the loaded release cannot support the query.
    """
    record_type = _validate_group_type(group_type=group_type)
    motif = normalise_terminal_sequence(value=terminal_sequence)
    fraction = _validate_fraction(value=minimum_match_fraction)
    species_fraction = _validate_fraction(value=minimum_species_match_fraction)
    coverage_fraction = _validate_fraction(value=minimum_sequence_coverage_fraction)
    if not isinstance(require_arabidopsis_match, bool):
        raise AppError("The Arabidopsis match requirement must be Boolean")
    minimum_members = _validate_positive_limit(
        value=minimum_plant_members,
        label="Minimum plant members",
        maximum=1_000_000,
    )
    minimum_species = _validate_positive_limit(
        value=minimum_plant_species,
        label="Minimum plant species",
        maximum=1_000_000,
    )
    row_limit = _validate_positive_limit(
        value=maximum_rows,
        label="Maximum result rows",
        maximum=MAXIMUM_RESULT_ROWS,
    )
    plants = _normalise_plant_species(plant_species=plant_species, human_species=human_species)
    capability = terminal_sequence_capability(connection=connection)
    ctes, classification_parameters = _member_ctes(
        connection=connection,
        capability=capability,
        plant_species=plants,
        human_species=human_species,
        arabidopsis_species=arabidopsis_species,
    )
    taxonomy_predicate, taxonomy_parameters = _taxonomy_group_predicate(
        compiled_taxonomy=compiled_taxonomy,
    )
    sql = f"""
        WITH {ctes},
        classified AS (
            SELECT
                *,
                protein_sequence IS NOT NULL AS sequence_available,
                CASE
                    WHEN protein_sequence IS NULL THEN NULL
                    ELSE ends_with(protein_sequence, ?)
                END AS terminal_match
            FROM members
        ),
        group_counts AS (
            SELECT
                group_id,
                count(*) AS total_member_count,
                count(*) FILTER (WHERE is_target_plant) AS plant_member_count,
                count(*) FILTER (
                    WHERE is_target_plant AND sequence_available
                ) AS assessed_plant_member_count,
                count(*) FILTER (
                    WHERE is_target_plant AND NOT sequence_available
                ) AS unavailable_plant_sequence_count,
                count(*) FILTER (
                    WHERE is_target_plant AND terminal_match
                ) AS matching_plant_member_count,
                count(*) FILTER (
                    WHERE is_arabidopsis AND sequence_available
                ) AS arabidopsis_assessed_member_count,
                count(*) FILTER (
                    WHERE is_arabidopsis AND terminal_match
                ) AS arabidopsis_matching_member_count,
                string_agg(DISTINCT coalesce(parsed_accession, raw_identifier), ';'
                    ORDER BY coalesce(parsed_accession, raw_identifier))
                    FILTER (WHERE is_arabidopsis AND terminal_match)
                    AS arabidopsis_matching_identifiers,
                string_agg(DISTINCT coalesce(parsed_accession, raw_identifier), ';'
                    ORDER BY coalesce(parsed_accession, raw_identifier))
                    FILTER (WHERE is_human) AS human_identifiers,
                string_agg(DISTINCT coalesce(parsed_accession, raw_identifier), ';'
                    ORDER BY coalesce(parsed_accession, raw_identifier))
                    FILTER (WHERE is_human AND terminal_match) AS human_matching_identifiers,
                string_agg(DISTINCT source_cluster_ids, ';' ORDER BY source_cluster_ids)
                    AS source_cluster_ids,
                count(*) FILTER (WHERE is_human) AS human_member_count,
                count(*) FILTER (
                    WHERE is_human AND sequence_available
                ) AS human_assessed_member_count,
                count(*) FILTER (
                    WHERE is_human AND terminal_match
                ) AS human_matching_member_count,
                count(*) FILTER (
                    WHERE NOT is_target_plant AND NOT is_human
                ) AS other_member_count
            FROM classified
            GROUP BY group_id
        ),
        species_counts AS (
            SELECT
                group_id,
                species,
                is_target_plant,
                count(*) FILTER (WHERE sequence_available)
                    AS assessed_member_count,
                count(*) FILTER (WHERE terminal_match) AS matching_member_count
            FROM classified
            GROUP BY group_id, species, is_target_plant
        ),
        species_summary AS (
            SELECT
                group_id,
                count(*) FILTER (
                    WHERE is_target_plant AND assessed_member_count > 0
                ) AS assessed_plant_species_count,
                count(*) FILTER (
                    WHERE is_target_plant AND matching_member_count > 0
                ) AS matching_plant_species_count,
                count(*) FILTER (
                    WHERE is_target_plant
                      AND assessed_member_count > 0
                      AND matching_member_count = assessed_member_count
                ) AS fully_matching_plant_species_count,
                string_agg(
                    species,
                    ';' ORDER BY species
                ) FILTER (
                    WHERE is_target_plant AND matching_member_count > 0
                ) AS matching_plant_species,
                string_agg(
                    species,
                    ';' ORDER BY species
                ) FILTER (
                    WHERE is_target_plant
                      AND assessed_member_count > 0
                      AND matching_member_count = 0
                ) AS plant_species_without_a_match
            FROM species_counts
            GROUP BY group_id
        ),
        combined AS (
            SELECT
                counts.group_id,
                ? AS terminal_sequence,
                counts.total_member_count,
                counts.plant_member_count,
                counts.assessed_plant_member_count,
                counts.unavailable_plant_sequence_count,
                counts.matching_plant_member_count,
                counts.assessed_plant_member_count::DOUBLE
                    / nullif(counts.plant_member_count, 0) AS plant_sequence_coverage_fraction,
                counts.matching_plant_member_count::DOUBLE
                    / nullif(counts.assessed_plant_member_count, 0)
                    AS plant_member_match_fraction,
                species.assessed_plant_species_count,
                species.matching_plant_species_count,
                species.fully_matching_plant_species_count,
                species.matching_plant_species_count::DOUBLE
                    / nullif(species.assessed_plant_species_count, 0)
                    AS plant_species_match_fraction,
                species.matching_plant_species,
                species.plant_species_without_a_match,
                counts.arabidopsis_assessed_member_count,
                counts.arabidopsis_matching_member_count,
                counts.arabidopsis_matching_identifiers,
                counts.human_identifiers,
                counts.human_matching_identifiers,
                counts.source_cluster_ids,
                CASE
                    WHEN counts.arabidopsis_assessed_member_count = 0
                        THEN 'UNAVAILABLE'
                    WHEN counts.arabidopsis_matching_member_count
                        = counts.arabidopsis_assessed_member_count
                        THEN 'ALL_MATCH'
                    WHEN counts.arabidopsis_matching_member_count > 0
                        THEN 'SOME_MATCH'
                    ELSE 'NO_MATCH'
                END AS arabidopsis_match_status,
                counts.human_member_count,
                counts.human_assessed_member_count,
                counts.human_matching_member_count,
                CASE
                    WHEN counts.human_assessed_member_count = 0 THEN 'UNAVAILABLE'
                    WHEN counts.human_matching_member_count
                        = counts.human_assessed_member_count THEN 'ALL_MATCH'
                    WHEN counts.human_matching_member_count > 0 THEN 'SOME_MATCH'
                    ELSE 'NO_MATCH'
                END AS human_comparison_status,
                counts.other_member_count
            FROM group_counts AS counts
            JOIN species_summary AS species USING (group_id)
        ),
        evaluated AS (
            SELECT combined.*,
                ({taxonomy_predicate}) AS passes_taxonomy,
                (assessed_plant_member_count >= ?
                 AND assessed_plant_species_count >= ?
                 AND plant_member_match_fraction >= ?
                 AND plant_species_match_fraction >= ?
                 AND plant_sequence_coverage_fraction >= ?
                 AND (NOT ? OR arabidopsis_matching_member_count > 0)) AS passes_terminal
            FROM combined
        ),
        screen_audit AS (
            SELECT count(*) AS source_group_count,
                count(*) FILTER (WHERE plant_member_count > 0) AS plant_group_count,
                count(*) FILTER (WHERE assessed_plant_member_count > 0) AS assessable_group_count,
                count(*) FILTER (WHERE plant_member_count > 0 AND passes_taxonomy)
                    AS taxonomy_group_count,
                count(*) FILTER (WHERE passes_taxonomy AND passes_terminal)
                    AS qualifying_group_count
            FROM evaluated
        ),
        qualifying AS (
            SELECT * EXCLUDE (passes_taxonomy, passes_terminal)
            FROM evaluated
            WHERE passes_taxonomy AND passes_terminal
            ORDER BY plant_member_match_fraction DESC, matching_plant_species_count DESC,
                assessed_plant_member_count DESC, group_id
            LIMIT ?
        )
        SELECT qualifying.*, screen_audit.*
        FROM screen_audit LEFT JOIN qualifying ON TRUE
        ORDER BY
            plant_member_match_fraction DESC,
            matching_plant_species_count DESC,
            assessed_plant_member_count DESC,
            group_id
    """
    parameters = [
        record_type,
        *classification_parameters,
        motif,
        motif,
        *taxonomy_parameters,
        minimum_members,
        minimum_species,
        fraction,
        species_fraction,
        coverage_fraction,
        bool(require_arabidopsis_match),
        row_limit,
    ]
    LOGGER.info(
        "Querying terminal sequence relation=%s group_type=%s motif=%s "
        "minimum_fraction=%.3f minimum_members=%d minimum_species=%d "
        "species_fraction=%.3f coverage_fraction=%.3f require_arabidopsis=%s maximum_rows=%d",
        capability.relation,
        group_type,
        motif,
        fraction,
        minimum_members,
        minimum_species,
        species_fraction,
        coverage_fraction,
        require_arabidopsis_match,
        row_limit,
    )
    try:
        result = connection.execute(sql, parameters).fetchdf()
    except Exception as exc:
        LOGGER.exception("C-terminal group query failed")
        raise AppError(f"Could not query C-terminal group conservation: {exc}") from exc
    audit_columns = (
        "source_group_count", "plant_group_count", "assessable_group_count",
        "taxonomy_group_count", "qualifying_group_count",
    )
    audit = {name: int(result.iloc[0][name]) for name in audit_columns}
    summary = result.loc[result["group_id"].notna()].drop(columns=list(audit_columns))
    summary = summary.reset_index(drop=True)
    audit["returned_group_count"] = len(summary)
    audit["result_limit"] = row_limit
    summary.attrs["screen_audit"] = audit
    LOGGER.info("C-terminal screen counts: %s", audit)
    return summary


def collect_terminal_group_members(
    *,
    connection: object,
    group_type: str,
    group_id: str,
    terminal_sequence: object = DEFAULT_TERMINAL_SEQUENCE,
    plant_species: Sequence[str],
    terminal_context_length: int = 20,
    maximum_rows: int = 100_000,
    human_species: Sequence[str] = (HUMAN_SPECIES,),
    arabidopsis_species: Sequence[str] = (ARABIDOPSIS_SPECIES,),
) -> pd.DataFrame:
    """Return audited member-level terminal evidence for one orthology group.

    Args:
        connection: Open read-only DuckDB connection.
        group_type: ``hierarchical_orthogroup`` or ``orthogroup``.
        group_id: Exact selected group identifier.
        terminal_sequence: Exact one-letter sequence required at the C terminus.
        plant_species: Reviewed source labels treated as target plants.
        terminal_context_length: Number of trailing residues shown in the table.
        maximum_rows: Maximum members returned.
        human_species: Reviewed source labels for human comparison members.
        arabidopsis_species: Reviewed source labels for Arabidopsis members.

    Returns:
        One deduplicated row per sequence-bearing or explicitly unavailable
        group member, including a separate taxonomic role and match state.

    Raises:
        AppError: If the query inputs or loaded relation are invalid.
    """
    record_type = _validate_group_type(group_type=group_type)
    selected_group = str(group_id).strip()
    if not selected_group:
        raise AppError("Select a non-empty OrthoFinder group identifier")
    motif = normalise_terminal_sequence(value=terminal_sequence)
    context_length = _validate_positive_limit(
        value=terminal_context_length,
        label="Terminal context length",
        maximum=1_000,
    )
    row_limit = _validate_positive_limit(
        value=maximum_rows,
        label="Maximum member rows",
        maximum=MAXIMUM_RESULT_ROWS,
    )
    plants = _normalise_plant_species(plant_species=plant_species, human_species=human_species)
    capability = terminal_sequence_capability(connection=connection)
    ctes, classification_parameters = _member_ctes(
        connection=connection,
        capability=capability,
        plant_species=plants,
        human_species=human_species,
        arabidopsis_species=arabidopsis_species,
    )
    sql = f"""
        WITH {ctes}
        SELECT
            group_id,
            species,
            CASE
                WHEN is_target_plant THEN 'TARGET_PLANT'
                WHEN is_human THEN 'HUMAN_COMPARISON'
                ELSE 'OTHER_COMPARISON'
            END AS taxonomic_role,
            member_key,
            raw_identifier,
            parsed_accession,
            parsed_entry,
            protein_description,
            is_human,
            is_arabidopsis,
            review_status,
            mapping_status,
            is_input_candidate,
            source_cluster_ids,
            candidate_accessions,
            recorded_sequence_length,
            length(protein_sequence) AS observed_sequence_length,
            protein_sequence IS NOT NULL AS sequence_available,
            CASE
                WHEN protein_sequence IS NULL THEN NULL
                ELSE ends_with(protein_sequence, ?)
            END AS terminal_match,
            CASE
                WHEN protein_sequence IS NULL THEN NULL
                ELSE right(protein_sequence, ?)
            END AS c_terminal_context,
            protein_sequence
        FROM members
        WHERE group_id = ?
        ORDER BY
            CASE
                WHEN is_arabidopsis THEN 0
                WHEN is_target_plant THEN 1
                WHEN is_human THEN 2
                ELSE 3
            END,
            terminal_match DESC NULLS LAST,
            species,
            parsed_accession NULLS LAST,
            member_key
        LIMIT ?
    """
    parameters = [
        record_type,
        *classification_parameters,
        motif,
        context_length,
        selected_group,
        row_limit,
    ]
    LOGGER.info(
        "Querying terminal sequence members relation=%s group_type=%s "
        "group_id=%s motif=%s maximum_rows=%d",
        capability.relation,
        group_type,
        selected_group,
        motif,
        row_limit,
    )
    try:
        return connection.execute(sql, parameters).fetchdf()
    except Exception as exc:
        LOGGER.exception("C-terminal member query failed")
        raise AppError(f"Could not query C-terminal group members: {exc}") from exc


def terminal_member_fasta_frame(*, members: pd.DataFrame) -> pd.DataFrame:
    """Prepare sequence-bearing terminal-screen members for FASTA export.

    Args:
        members: Member-level output from :func:`collect_terminal_group_members`.

    Returns:
        Sequence-bearing rows with a stable unique ``fasta_identifier`` column.

    Raises:
        AppError: If required columns are missing or identifiers are duplicated.
    """
    required = {
        "group_id",
        "species",
        "member_key",
        "raw_identifier",
        "parsed_accession",
        "protein_sequence",
    }
    missing = sorted(required.difference(members.columns))
    if missing:
        raise AppError("Terminal member table is missing columns: " + ", ".join(missing))
    selected = members.loc[
        members["protein_sequence"].fillna("").astype(str).str.strip().ne("")
    ].copy()
    selected["fasta_identifier"] = (
        selected["group_id"].astype(str)
        + "|"
        + selected["species"].astype(str)
        + "|"
        + selected["member_key"].astype(str)
    )
    if selected["fasta_identifier"].duplicated().any():
        raise AppError("Terminal member FASTA identifiers are not unique")
    return selected.reset_index(drop=True)
