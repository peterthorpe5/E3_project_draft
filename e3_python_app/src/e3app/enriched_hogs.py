"""Virtual, resource-wide HOG views for the complete-results browser."""

from __future__ import annotations

import logging
from typing import Literal, Sequence, cast

import duckdb
import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError
from e3app.human_hogs import (
    ARABIDOPSIS_SPECIES,
    BARLEY_SPECIES,
    HIERARCHICAL_RELATION,
    HOG_MEMBERSHIP_REQUIRED_COLUMNS,
    HUMAN_SPECIES,
    RANK_COLUMNS,
    RICE_SPECIES,
    select_hog_ranking_relation,
    target_plant_species,
)

LOGGER = logging.getLogger(__name__)

ENRICHED_HOG_OVERVIEW = "__enriched_hog_overview__"
ENRICHED_HOG_MEMBERS = "__enriched_hog_members__"
ENRICHED_HOG_LABELS = {
    ENRICHED_HOG_OVERVIEW: "Enriched HOG overview (joined across the resource)",
    ENRICHED_HOG_MEMBERS: "Enriched HOG member detail (joined across the resource)",
}

EnrichedHogResult = Literal[
    "__enriched_hog_overview__",
    "__enriched_hog_members__",
]

HOG_OVERVIEW_COLUMNS = (
    "hog_id",
    "hog_prestructure_rank",
    "hog_poststructure_rank",
    "human_hog_representatives",
    "arabidopsis_hog_representatives",
    "rice_hog_representatives",
    "barley_hog_representatives",
    "hog_three_dimensional_position_status",
    "hog_three_dimensional_alignment_status",
    "hog_conservation_status",
    "hog_same_3d_pocket_position_supported",
    "hog_conserved_3d_pocket_supported",
    "hog_minimum_druggability_score",
    "hog_all_assessed_members_pass_druggability",
    "hog_structural_species_fraction",
    "hog_mean_minimum_tm_score",
    "hog_mean_pocket_overlap_fraction",
    "hog_median_centroid_distance_angstrom",
    "hog_mean_structural_residue_match_fraction",
    "hog_mean_structural_chemical_group_conservation",
    "human_hog_accessions",
    "human_hog_entries",
    "human_hog_raw_identifiers",
    "arabidopsis_hog_accessions",
    "arabidopsis_hog_entries",
    "arabidopsis_hog_raw_identifiers",
    "rice_hog_accessions",
    "rice_hog_entries",
    "rice_hog_raw_identifiers",
    "barley_hog_accessions",
    "barley_hog_entries",
    "barley_hog_raw_identifiers",
    "hog_member_count",
    "hog_species_count",
    "hog_human_member_count",
    "hog_arabidopsis_member_count",
    "hog_rice_member_count",
    "hog_barley_member_count",
    "hog_target_plant_member_count",
    "hog_target_plant_species_count",
    "hog_species_present",
    "hog_target_plant_species_present",
    "hog_orthogroup_ids",
    "hog_gene_tree_parent_clades",
    "hog_record_types",
    "hog_review_statuses",
    "hog_mapping_statuses",
    "hog_mapping_reasons",
    "hog_identifier_formats",
    "hog_membership_source_files",
    "hog_membership_available",
    "hog_ranking_available",
    "hog_ranking_source",
    "hog_ranking_source_row_count",
)

MEMBER_POCKET_RELATION_PREFERENCE = (
    "selected_pockets",
    "pocket_conservation_members",
    "ranked_member_pockets",
)
MEMBER_STRUCTURAL_COLUMNS = (
    "member_structure_assessed",
    "member_structural_source",
    "member_structural_accession",
    "member_structural_species",
    "member_pocket_number",
    "member_druggability_score",
    "member_passes_druggability_threshold",
    "member_pocket_mapping_fraction",
    "member_pocket_plddt_fraction",
    "member_predictor_agreement",
    "member_pocket_component_selected",
    "member_structural_evidence_status",
)

PRESTRUCTURE_RANK_COLUMNS = (
    "prestructure_evolutionary_group_rank",
    "evolutionary_group_rank",
    "computational_rank",
)
POSTSTRUCTURE_RANK_COLUMNS = (
    "final_evolutionary_rank",
    "final_rank",
)


def validate_enriched_hog_result(*, result: str) -> EnrichedHogResult:
    """Validate a virtual HOG result key.

    Args:
        result: Virtual result key selected in the complete-results browser.

    Returns:
        The validated result key.

    Raises:
        AppError: If the result key is unsupported.
    """
    if result not in ENRICHED_HOG_LABELS:
        raise AppError(f"Unsupported enriched HOG result: {result}")
    return cast(EnrichedHogResult, result)


def enriched_hog_capability(*, connection: object) -> dict[str, object]:
    """Report which resource-wide HOG joins can be constructed.

    Args:
        connection: Open read-only DuckDB connection.

    Returns:
        Membership and ranking availability metadata.
    """
    relations = set(list_relations(connection=connection))
    membership_columns: list[str] = []
    membership_available = False
    if HIERARCHICAL_RELATION in relations:
        membership_columns = relation_columns(
            connection=connection,
            relation=HIERARCHICAL_RELATION,
        )
        membership_available = HOG_MEMBERSHIP_REQUIRED_COLUMNS.issubset(
            membership_columns
        )
    ranking_relation = select_hog_ranking_relation(connection=connection)
    ranking_columns = (
        relation_columns(connection=connection, relation=ranking_relation)
        if ranking_relation is not None
        else []
    )
    member_structural_relation = next(
        (
            relation
            for relation in MEMBER_POCKET_RELATION_PREFERENCE
            if relation in relations
            and {"primary_group_id", "candidate_accession"}.issubset(
                relation_columns(connection=connection, relation=relation)
            )
        ),
        None,
    )
    member_structural_columns = (
        relation_columns(
            connection=connection,
            relation=member_structural_relation,
        )
        if member_structural_relation is not None
        else []
    )
    return {
        "available": membership_available or ranking_relation is not None,
        "membership_available": membership_available,
        "membership_columns": membership_columns,
        "ranking_relation": ranking_relation,
        "ranking_columns": ranking_columns,
        "member_structural_relation": member_structural_relation,
        "member_structural_columns": member_structural_columns,
    }


def _ranking_column_mapping(
    *, ranking_columns: Sequence[str]
) -> tuple[tuple[str, str], ...]:
    """Map every source ranking field to a collision-free output field."""
    reserved = set(HOG_OVERVIEW_COLUMNS)
    mapping: list[tuple[str, str]] = []
    for source in ranking_columns:
        if source == "primary_group_id":
            continue
        output = source
        if output in reserved or output.startswith("member_"):
            output = f"ranking_{source}"
        suffix = 2
        candidate = output
        while candidate in reserved:
            candidate = f"{output}_{suffix}"
            suffix += 1
        reserved.add(candidate)
        mapping.append((source, candidate))
    return tuple(mapping)


def _member_column_mapping(
    *, membership_columns: Sequence[str]
) -> tuple[tuple[str, str], ...]:
    """Map every membership source field to an explicit member field."""
    return tuple(
        (column, f"member_{column}")
        for column in membership_columns
        if column != "group_id"
    )


def enriched_hog_columns(
    *, connection: object, result: str
) -> list[str]:
    """Return every selectable field for a virtual enriched HOG result.

    Args:
        connection: Open read-only DuckDB connection.
        result: Enriched overview or member-detail key.

    Returns:
        Ordered output field names.

    Raises:
        AppError: If no HOG-linked source is available.
    """
    selected_result = validate_enriched_hog_result(result=result)
    capability = enriched_hog_capability(connection=connection)
    if not capability["available"]:
        raise AppError("No root-HOG membership or HOG-linked ranking is available")
    columns = list(HOG_OVERVIEW_COLUMNS)
    if selected_result == ENRICHED_HOG_MEMBERS:
        columns.extend(
            output
            for _, output in _member_column_mapping(
                membership_columns=capability["membership_columns"],
            )
        )
        columns.extend(MEMBER_STRUCTURAL_COLUMNS)
    columns.extend(
        output
        for _, output in _ranking_column_mapping(
            ranking_columns=capability["ranking_columns"],
        )
    )
    return columns


def _nullable_text_expression(*, columns: set[str], column: str) -> str:
    """Return a nullable text expression for an optional membership field."""
    if column not in columns:
        return "CAST(NULL AS VARCHAR)"
    return f"CAST({quote_identifier(column)} AS VARCHAR)"


def _membership_ctes(
    *, capability: dict[str, object]
) -> tuple[str, list[object]]:
    """Build root-HOG membership and summary CTEs."""
    if not capability["membership_available"]:
        return (
            "membership AS (SELECT CAST(NULL AS VARCHAR) AS hog_id WHERE FALSE), "
            "membership_summary AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, "
            "CAST(NULL AS BIGINT) AS hog_member_count, "
            "CAST(NULL AS BIGINT) AS hog_species_count, "
            "CAST(NULL AS BIGINT) AS hog_human_member_count, "
            "CAST(NULL AS BIGINT) AS hog_arabidopsis_member_count, "
            "CAST(NULL AS BIGINT) AS hog_rice_member_count, "
            "CAST(NULL AS BIGINT) AS hog_barley_member_count, "
            "CAST(NULL AS BIGINT) AS hog_target_plant_member_count, "
            "CAST(NULL AS BIGINT) AS hog_target_plant_species_count, "
            "CAST(NULL AS VARCHAR) AS hog_species_present, "
            "CAST(NULL AS VARCHAR) AS hog_target_plant_species_present, "
            "CAST(NULL AS VARCHAR) AS human_hog_representatives, "
            "CAST(NULL AS VARCHAR) AS arabidopsis_hog_representatives, "
            "CAST(NULL AS VARCHAR) AS rice_hog_representatives, "
            "CAST(NULL AS VARCHAR) AS barley_hog_representatives, "
            "CAST(NULL AS VARCHAR) AS human_hog_accessions, "
            "CAST(NULL AS VARCHAR) AS human_hog_entries, "
            "CAST(NULL AS VARCHAR) AS human_hog_raw_identifiers, "
            "CAST(NULL AS VARCHAR) AS arabidopsis_hog_accessions, "
            "CAST(NULL AS VARCHAR) AS arabidopsis_hog_entries, "
            "CAST(NULL AS VARCHAR) AS arabidopsis_hog_raw_identifiers, "
            "CAST(NULL AS VARCHAR) AS rice_hog_accessions, "
            "CAST(NULL AS VARCHAR) AS rice_hog_entries, "
            "CAST(NULL AS VARCHAR) AS rice_hog_raw_identifiers, "
            "CAST(NULL AS VARCHAR) AS barley_hog_accessions, "
            "CAST(NULL AS VARCHAR) AS barley_hog_entries, "
            "CAST(NULL AS VARCHAR) AS barley_hog_raw_identifiers, "
            "CAST(NULL AS VARCHAR) AS hog_orthogroup_ids, "
            "CAST(NULL AS VARCHAR) AS hog_gene_tree_parent_clades, "
            "CAST(NULL AS VARCHAR) AS hog_record_types, "
            "CAST(NULL AS VARCHAR) AS hog_review_statuses, "
            "CAST(NULL AS VARCHAR) AS hog_mapping_statuses, "
            "CAST(NULL AS VARCHAR) AS hog_mapping_reasons, "
            "CAST(NULL AS VARCHAR) AS hog_identifier_formats, "
            "CAST(NULL AS VARCHAR) AS hog_membership_source_files WHERE FALSE)",
            [],
        )
    membership_columns = list(capability["membership_columns"])
    column_set = set(membership_columns)
    selected = [
        "CAST(group_id AS VARCHAR) AS hog_id",
        *(
            quote_identifier(column)
            for column in membership_columns
            if column != "group_id"
        ),
    ]
    representative = (
        "coalesce(nullif(trim("
        + _nullable_text_expression(
            columns=column_set,
            column="parsed_accession",
        )
        + "), ''), nullif(trim("
        + _nullable_text_expression(columns=column_set, column="parsed_entry")
        + "), ''), nullif(trim(CAST(raw_identifier AS VARCHAR)), ''))"
    )
    orthogroup = _nullable_text_expression(
        columns=column_set,
        column="orthogroup_id",
    )
    parent = _nullable_text_expression(
        columns=column_set,
        column="gene_tree_parent_clade",
    )
    parsed_accession = _nullable_text_expression(
        columns=column_set,
        column="parsed_accession",
    )
    parsed_entry = _nullable_text_expression(
        columns=column_set,
        column="parsed_entry",
    )
    raw_identifier = "CAST(raw_identifier AS VARCHAR)"
    membership_summaries = (
        ("record_type", "hog_record_types"),
        ("review_status", "hog_review_statuses"),
        ("mapping_status", "hog_mapping_statuses"),
        ("mapping_reason", "hog_mapping_reasons"),
        ("identifier_format", "hog_identifier_formats"),
        ("source_file", "hog_membership_source_files"),
    )
    membership_summary_sql = ", ".join(
        "coalesce(string_agg(DISTINCT "
        + _nullable_text_expression(columns=column_set, column=column)
        + ", ';' ORDER BY "
        + _nullable_text_expression(columns=column_set, column=column)
        + ") FILTER (WHERE "
        + _nullable_text_expression(columns=column_set, column=column)
        + " IS NOT NULL AND trim("
        + _nullable_text_expression(columns=column_set, column=column)
        + ") != ''), '') AS "
        + alias
        for column, alias in membership_summaries
    )
    plants = target_plant_species()
    if not plants:
        raise AppError("The packaged taxonomy manifest contains no target plants")
    plant_values = ", ".join("(?)" for _ in plants)
    query = (
        "membership AS (SELECT "
        + ", ".join(selected)
        + f" FROM {quote_identifier(HIERARCHICAL_RELATION)} "
        "WHERE group_id IS NOT NULL AND "
        "starts_with(trim(CAST(group_id AS VARCHAR)), 'N0.HOG')), "
        f"target_plants(species) AS (VALUES {plant_values}), "
        "member_classes AS (SELECT m.*, "
        "CAST(species AS VARCHAR) = 'Homo_sapiens' AS is_human, "
        f"CAST(species AS VARCHAR) = '{ARABIDOPSIS_SPECIES}' AS is_arabidopsis, "
        f"CAST(species AS VARCHAR) = '{RICE_SPECIES}' AS is_rice, "
        f"CAST(species AS VARCHAR) = '{BARLEY_SPECIES}' AS is_barley, "
        "EXISTS (SELECT 1 FROM target_plants p "
        "WHERE p.species = CAST(m.species AS VARCHAR)) AS is_target_plant, "
        f"{representative} AS representative FROM membership m), "
        "membership_summary AS (SELECT hog_id, "
        "count(*) AS hog_member_count, "
        "count(DISTINCT CAST(species AS VARCHAR)) AS hog_species_count, "
        "count(*) FILTER (WHERE is_human) AS hog_human_member_count, "
        "count(*) FILTER (WHERE is_arabidopsis) "
        "AS hog_arabidopsis_member_count, "
        "count(*) FILTER (WHERE is_rice) AS hog_rice_member_count, "
        "count(*) FILTER (WHERE is_barley) AS hog_barley_member_count, "
        "count(*) FILTER (WHERE is_target_plant) "
        "AS hog_target_plant_member_count, "
        "count(DISTINCT CAST(species AS VARCHAR)) "
        "FILTER (WHERE is_target_plant) AS hog_target_plant_species_count, "
        "coalesce(string_agg(DISTINCT CAST(species AS VARCHAR), ';' "
        "ORDER BY CAST(species AS VARCHAR)), '') AS hog_species_present, "
        "coalesce(string_agg(DISTINCT CAST(species AS VARCHAR), ';' "
        "ORDER BY CAST(species AS VARCHAR)) FILTER (WHERE is_target_plant), '') "
        "AS hog_target_plant_species_present, "
        "coalesce(string_agg(DISTINCT representative, ';' "
        "ORDER BY representative) FILTER (WHERE is_human "
        "AND representative IS NOT NULL), '') AS human_hog_representatives, "
        "coalesce(string_agg(DISTINCT representative, ';' "
        "ORDER BY representative) FILTER (WHERE is_arabidopsis "
        "AND representative IS NOT NULL), '') "
        "AS arabidopsis_hog_representatives, "
        "coalesce(string_agg(DISTINCT representative, ';' "
        "ORDER BY representative) FILTER (WHERE is_rice "
        "AND representative IS NOT NULL), '') AS rice_hog_representatives, "
        "coalesce(string_agg(DISTINCT representative, ';' "
        "ORDER BY representative) FILTER (WHERE is_barley "
        "AND representative IS NOT NULL), '') AS barley_hog_representatives, "
        f"coalesce(string_agg(DISTINCT {parsed_accession}, ';' "
        f"ORDER BY {parsed_accession}) FILTER (WHERE is_human AND "
        f"{parsed_accession} IS NOT NULL AND trim({parsed_accession}) != ''), '') "
        "AS human_hog_accessions, "
        f"coalesce(string_agg(DISTINCT {parsed_entry}, ';' "
        f"ORDER BY {parsed_entry}) FILTER (WHERE is_human AND "
        f"{parsed_entry} IS NOT NULL AND trim({parsed_entry}) != ''), '') "
        "AS human_hog_entries, "
        f"coalesce(string_agg(DISTINCT {raw_identifier}, ';' "
        f"ORDER BY {raw_identifier}) FILTER (WHERE is_human AND "
        f"trim({raw_identifier}) != ''), '') AS human_hog_raw_identifiers, "
        f"coalesce(string_agg(DISTINCT {parsed_accession}, ';' "
        f"ORDER BY {parsed_accession}) FILTER (WHERE is_arabidopsis AND "
        f"{parsed_accession} IS NOT NULL AND trim({parsed_accession}) != ''), '') "
        "AS arabidopsis_hog_accessions, "
        f"coalesce(string_agg(DISTINCT {parsed_entry}, ';' "
        f"ORDER BY {parsed_entry}) FILTER (WHERE is_arabidopsis AND "
        f"{parsed_entry} IS NOT NULL AND trim({parsed_entry}) != ''), '') "
        "AS arabidopsis_hog_entries, "
        f"coalesce(string_agg(DISTINCT {raw_identifier}, ';' "
        f"ORDER BY {raw_identifier}) FILTER (WHERE is_arabidopsis AND "
        f"trim({raw_identifier}) != ''), '') "
        "AS arabidopsis_hog_raw_identifiers, "
        f"coalesce(string_agg(DISTINCT {parsed_accession}, ';' "
        f"ORDER BY {parsed_accession}) FILTER (WHERE is_rice AND "
        f"{parsed_accession} IS NOT NULL AND trim({parsed_accession}) != ''), '') "
        "AS rice_hog_accessions, "
        f"coalesce(string_agg(DISTINCT {parsed_entry}, ';' "
        f"ORDER BY {parsed_entry}) FILTER (WHERE is_rice AND "
        f"{parsed_entry} IS NOT NULL AND trim({parsed_entry}) != ''), '') "
        "AS rice_hog_entries, "
        f"coalesce(string_agg(DISTINCT {raw_identifier}, ';' "
        f"ORDER BY {raw_identifier}) FILTER (WHERE is_rice AND "
        f"trim({raw_identifier}) != ''), '') AS rice_hog_raw_identifiers, "
        f"coalesce(string_agg(DISTINCT {parsed_accession}, ';' "
        f"ORDER BY {parsed_accession}) FILTER (WHERE is_barley AND "
        f"{parsed_accession} IS NOT NULL AND trim({parsed_accession}) != ''), '') "
        "AS barley_hog_accessions, "
        f"coalesce(string_agg(DISTINCT {parsed_entry}, ';' "
        f"ORDER BY {parsed_entry}) FILTER (WHERE is_barley AND "
        f"{parsed_entry} IS NOT NULL AND trim({parsed_entry}) != ''), '') "
        "AS barley_hog_entries, "
        f"coalesce(string_agg(DISTINCT {raw_identifier}, ';' "
        f"ORDER BY {raw_identifier}) FILTER (WHERE is_barley AND "
        f"trim({raw_identifier}) != ''), '') AS barley_hog_raw_identifiers, "
        f"coalesce(string_agg(DISTINCT {orthogroup}, ';' "
        f"ORDER BY {orthogroup}) FILTER (WHERE {orthogroup} IS NOT NULL "
        f"AND trim({orthogroup}) != ''), '') AS hog_orthogroup_ids, "
        f"coalesce(string_agg(DISTINCT {parent}, ';' ORDER BY {parent}) "
        f"FILTER (WHERE {parent} IS NOT NULL AND trim({parent}) != ''), '') "
        "AS hog_gene_tree_parent_clades, "
        f"{membership_summary_sql} FROM member_classes GROUP BY hog_id)"
    )
    return query, list(plants)


def _ranking_cte(*, capability: dict[str, object]) -> str:
    """Build a deterministic complete source-ranking row per HOG."""
    relation = capability["ranking_relation"]
    if relation is None:
        return (
            "ranking_rows AS (SELECT CAST(NULL AS VARCHAR) "
            "AS primary_group_id, CAST(NULL AS BIGINT) "
            "AS _e3_hog_ranking_source_row_count WHERE FALSE)"
        )
    columns = list(capability["ranking_columns"])
    order_columns = [
        column
        for column in (
            *RANK_COLUMNS,
            "lead_cluster_id",
            "cluster_id",
            "candidate_accessions",
        )
        if column in columns
    ]
    order_sql = ", ".join(
        f"{quote_identifier(column)} NULLS LAST"
        for column in dict.fromkeys(order_columns)
    )
    return (
        "rank_source AS (SELECT *, count(*) OVER (PARTITION BY "
        "CAST(primary_group_id AS VARCHAR)) "
        "AS _e3_hog_ranking_source_row_count, ROW_NUMBER() OVER (PARTITION BY "
        f"CAST(primary_group_id AS VARCHAR) ORDER BY {order_sql}) "
        f"AS _e3_hog_ranking_row FROM {quote_identifier(str(relation))} "
        "WHERE primary_group_id IS NOT NULL AND "
        "starts_with(trim(CAST(primary_group_id AS VARCHAR)), 'N0.HOG')), "
        "ranking_rows AS (SELECT * EXCLUDE (_e3_hog_ranking_row) "
        "FROM rank_source WHERE _e3_hog_ranking_row = 1)"
    )


def _member_structural_cte(*, capability: dict[str, object]) -> str:
    """Build one strict selected-pocket evidence row per HOG member."""
    relation = capability["member_structural_relation"]
    if relation is None:
        return (
            "member_structural_rows AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, "
            "CAST(NULL AS VARCHAR) AS candidate_accession, "
            "CAST(NULL AS VARCHAR) AS species, CAST(NULL AS BIGINT) AS pocket_number, "
            "CAST(NULL AS DOUBLE) AS druggability_score, "
            "CAST(NULL AS BOOLEAN) AS passes_druggability_threshold, "
            "CAST(NULL AS DOUBLE) AS mapping_fraction, "
            "CAST(NULL AS DOUBLE) AS pocket_plddt_fraction, "
            "CAST(NULL AS DOUBLE) AS predictor_agreement, "
            "CAST(NULL AS BOOLEAN) AS component_selected, "
            "CAST(NULL AS VARCHAR) AS structural_evidence_status WHERE FALSE)"
        )
    columns = set(capability["member_structural_columns"])

    def optional(column: str, sql_type: str, *alternatives: str) -> str:
        source = next(
            (name for name in (column, *alternatives) if name in columns),
            None,
        )
        if source is None:
            return f"CAST(NULL AS {sql_type})"
        return f"TRY_CAST({quote_identifier(source)} AS {sql_type})"

    order_columns = [
        column
        for column in (
            "is_strict_selected",
            "selection_rank",
            "pocket_number",
            "cluster_id",
        )
        if column in columns
    ]
    order_sql = ", ".join(
        f"{quote_identifier(column)} "
        + ("DESC" if column == "is_strict_selected" else "ASC")
        + " NULLS LAST"
        for column in order_columns
    ) or "candidate_accession"
    return (
        "member_structural_source AS (SELECT "
        "CAST(primary_group_id AS VARCHAR) AS hog_id, "
        "CAST(candidate_accession AS VARCHAR) AS candidate_accession, "
        f"{optional('species_column', 'VARCHAR')} AS species, "
        f"{optional('pocket_number', 'BIGINT')} AS pocket_number, "
        f"{optional('druggability_score', 'DOUBLE')} AS druggability_score, "
        f"{optional('passes_druggability_threshold', 'BOOLEAN')} "
        "AS passes_druggability_threshold, "
        f"{optional('mapping_fraction', 'DOUBLE')} AS mapping_fraction, "
        f"{optional('pocket_plddt_fraction', 'DOUBLE', 'conservative_fraction_plddt_ge_70')} "
        "AS pocket_plddt_fraction, "
        f"{optional('predictor_agreement', 'DOUBLE')} AS predictor_agreement, "
        f"{optional('component_selected', 'BOOLEAN', 'is_strict_selected')} "
        "AS component_selected, "
        f"{optional('structural_evidence_status', 'VARCHAR', 'selection_status')} "
        "AS structural_evidence_status, ROW_NUMBER() OVER (PARTITION BY "
        "CAST(primary_group_id AS VARCHAR), "
        "upper(trim(CAST(candidate_accession AS VARCHAR))) "
        f"ORDER BY {order_sql}) "
        f"AS _e3_member_structural_row FROM {quote_identifier(str(relation))}), "
        "member_structural_rows AS (SELECT * EXCLUDE (_e3_member_structural_row) "
        "FROM member_structural_source WHERE _e3_member_structural_row = 1)"
    )


def _overview_expressions(
    *, capability: dict[str, object]
) -> list[str]:
    """Return canonical HOG-level enrichment expressions."""
    ranking_relation = capability["ranking_relation"]
    source = "" if ranking_relation is None else str(ranking_relation)
    safe_source = source.replace("'", "''")
    ranking_columns = set(capability["ranking_columns"])

    def value_expression(
        *, candidates: Sequence[str], sql_type: str
    ) -> str:
        """Return the first available typed ranking expression."""
        column = next(
            (candidate for candidate in candidates if candidate in ranking_columns),
            None,
        )
        if column is None:
            return f"CAST(NULL AS {sql_type})"
        return f"TRY_CAST(r.{quote_identifier(column)} AS {sql_type})"

    def rank_expression(*, candidates: Sequence[str]) -> str:
        """Return the first available ranking expression."""
        column = next(
            (candidate for candidate in candidates if candidate in ranking_columns),
            None,
        )
        if column is None:
            return "CAST(NULL AS BIGINT)"
        return f"TRY_CAST(r.{quote_identifier(column)} AS BIGINT)"

    def support_expression(*, candidates: Sequence[str], supported_status: str) -> str:
        """Return nullable support, preserving unavailable/not-assessed states."""
        status = value_expression(candidates=candidates, sql_type="VARCHAR")
        return (
            f"CASE WHEN {status} IS NULL OR {status} = 'NOT_ASSESSED' "
            f"THEN CAST(NULL AS BOOLEAN) ELSE {status} = '{supported_status}' END"
        )

    position_status = value_expression(
        candidates=("three_dimensional_position_status",), sql_type="VARCHAR"
    )
    alignment_status = value_expression(
        candidates=("three_dimensional_alignment_status",), sql_type="VARCHAR"
    )
    same_position_supported = support_expression(
        candidates=("three_dimensional_position_status",),
        supported_status="SAME_3D_POCKET_POSITION_SUPPORTED",
    )
    conserved_pocket_supported = support_expression(
        candidates=("three_dimensional_alignment_status",),
        supported_status="CONSERVED_3D_POCKET_SUPPORTED",
    )
    all_members_druggable = value_expression(
        candidates=("all_assessed_members_pass_druggability",), sql_type="BOOLEAN"
    )
    residue_match = value_expression(
        candidates=("mean_structural_residue_match_fraction",), sql_type="DOUBLE"
    )
    chemical_conservation = value_expression(
        candidates=("mean_structural_chemical_group_conservation",), sql_type="DOUBLE"
    )

    return [
        "u.hog_id AS hog_id",
        f"{rank_expression(candidates=PRESTRUCTURE_RANK_COLUMNS)} "
        "AS hog_prestructure_rank",
        f"{rank_expression(candidates=POSTSTRUCTURE_RANK_COLUMNS)} "
        "AS hog_poststructure_rank",
        "coalesce(s.human_hog_representatives, '') "
        "AS human_hog_representatives",
        "coalesce(s.arabidopsis_hog_representatives, '') "
        "AS arabidopsis_hog_representatives",
        "coalesce(s.rice_hog_representatives, '') AS rice_hog_representatives",
        "coalesce(s.barley_hog_representatives, '') AS barley_hog_representatives",
        f"{position_status} AS hog_three_dimensional_position_status",
        f"{alignment_status} AS hog_three_dimensional_alignment_status",
        f"{value_expression(candidates=('conservation_status',), sql_type='VARCHAR')} "
        "AS hog_conservation_status",
        f"{same_position_supported} "
        "AS hog_same_3d_pocket_position_supported",
        f"{conserved_pocket_supported} "
        "AS hog_conserved_3d_pocket_supported",
        f"{value_expression(candidates=('minimum_druggability_score',), sql_type='DOUBLE')} "
        "AS hog_minimum_druggability_score",
        f"{all_members_druggable} AS hog_all_assessed_members_pass_druggability",
        f"{value_expression(candidates=('structural_species_fraction',), sql_type='DOUBLE')} "
        "AS hog_structural_species_fraction",
        f"{value_expression(candidates=('mean_minimum_tm_score',), sql_type='DOUBLE')} "
        "AS hog_mean_minimum_tm_score",
        f"{value_expression(candidates=('mean_pocket_overlap_fraction',), sql_type='DOUBLE')} "
        "AS hog_mean_pocket_overlap_fraction",
        f"{value_expression(candidates=('median_centroid_distance_angstrom',), sql_type='DOUBLE')} "
        "AS hog_median_centroid_distance_angstrom",
        f"{residue_match} AS hog_mean_structural_residue_match_fraction",
        f"{chemical_conservation} AS hog_mean_structural_chemical_group_conservation",
        "coalesce(s.human_hog_accessions, '') AS human_hog_accessions",
        "coalesce(s.human_hog_entries, '') AS human_hog_entries",
        "coalesce(s.human_hog_raw_identifiers, '') "
        "AS human_hog_raw_identifiers",
        "coalesce(s.arabidopsis_hog_accessions, '') "
        "AS arabidopsis_hog_accessions",
        "coalesce(s.arabidopsis_hog_entries, '') AS arabidopsis_hog_entries",
        "coalesce(s.arabidopsis_hog_raw_identifiers, '') "
        "AS arabidopsis_hog_raw_identifiers",
        "coalesce(s.rice_hog_accessions, '') AS rice_hog_accessions",
        "coalesce(s.rice_hog_entries, '') AS rice_hog_entries",
        "coalesce(s.rice_hog_raw_identifiers, '') AS rice_hog_raw_identifiers",
        "coalesce(s.barley_hog_accessions, '') AS barley_hog_accessions",
        "coalesce(s.barley_hog_entries, '') AS barley_hog_entries",
        "coalesce(s.barley_hog_raw_identifiers, '') AS barley_hog_raw_identifiers",
        "coalesce(s.hog_member_count, 0) AS hog_member_count",
        "coalesce(s.hog_species_count, 0) AS hog_species_count",
        "coalesce(s.hog_human_member_count, 0) AS hog_human_member_count",
        "coalesce(s.hog_arabidopsis_member_count, 0) "
        "AS hog_arabidopsis_member_count",
        "coalesce(s.hog_rice_member_count, 0) AS hog_rice_member_count",
        "coalesce(s.hog_barley_member_count, 0) AS hog_barley_member_count",
        "coalesce(s.hog_target_plant_member_count, 0) "
        "AS hog_target_plant_member_count",
        "coalesce(s.hog_target_plant_species_count, 0) "
        "AS hog_target_plant_species_count",
        "coalesce(s.hog_species_present, '') AS hog_species_present",
        "coalesce(s.hog_target_plant_species_present, '') "
        "AS hog_target_plant_species_present",
        "coalesce(s.hog_orthogroup_ids, '') AS hog_orthogroup_ids",
        "coalesce(s.hog_gene_tree_parent_clades, '') "
        "AS hog_gene_tree_parent_clades",
        "coalesce(s.hog_record_types, '') AS hog_record_types",
        "coalesce(s.hog_review_statuses, '') AS hog_review_statuses",
        "coalesce(s.hog_mapping_statuses, '') AS hog_mapping_statuses",
        "coalesce(s.hog_mapping_reasons, '') AS hog_mapping_reasons",
        "coalesce(s.hog_identifier_formats, '') AS hog_identifier_formats",
        "coalesce(s.hog_membership_source_files, '') "
        "AS hog_membership_source_files",
        "s.hog_id IS NOT NULL AS hog_membership_available",
        "r.primary_group_id IS NOT NULL AS hog_ranking_available",
        f"CASE WHEN r.primary_group_id IS NULL THEN '' ELSE '{safe_source}' END "
        "AS hog_ranking_source",
        "coalesce(r._e3_hog_ranking_source_row_count, 0) "
        "AS hog_ranking_source_row_count",
    ]


def _build_enriched_hog_query(
    *,
    connection: object,
    result: str,
    selected_columns: Sequence[str],
    maximum_rows: int,
) -> tuple[str, list[object]]:
    """Build one bounded enriched HOG overview or member-detail query."""
    selected_result = validate_enriched_hog_result(result=result)
    if not 1 <= maximum_rows <= 100_000:
        raise AppError("maximum enriched HOG rows must be between 1 and 100000")
    available = enriched_hog_columns(
        connection=connection,
        result=selected_result,
    )
    selected = list(dict.fromkeys(selected_columns))
    if not selected:
        raise AppError("Select at least one enriched HOG column")
    missing = sorted(set(selected).difference(available))
    if missing:
        raise AppError("Unknown enriched HOG columns: " + ", ".join(missing))
    capability = enriched_hog_capability(connection=connection)
    membership_ctes, parameters = _membership_ctes(capability=capability)
    ranking_ctes = _ranking_cte(capability=capability)
    member_structural_ctes = _member_structural_cte(capability=capability)
    universe = (
        "hog_universe AS (SELECT hog_id FROM membership_summary UNION "
        "SELECT CAST(primary_group_id AS VARCHAR) AS hog_id FROM ranking_rows)"
    )
    expressions = _overview_expressions(capability=capability)
    from_sql = (
        "FROM hog_universe u LEFT JOIN membership_summary s USING (hog_id) "
        "LEFT JOIN ranking_rows r ON CAST(r.primary_group_id AS VARCHAR) = u.hog_id"
    )
    if selected_result == ENRICHED_HOG_MEMBERS:
        expressions.extend(
            f"m.{quote_identifier(source)} AS {quote_identifier(output)}"
            for source, output in _member_column_mapping(
                membership_columns=capability["membership_columns"],
            )
        )
        expressions.extend(
            (
                "p.hog_id IS NOT NULL AS member_structure_assessed",
                "CASE WHEN p.hog_id IS NULL THEN '' ELSE '"
                + str(capability["member_structural_relation"] or "").replace("'", "''")
                + "' END AS member_structural_source",
                "coalesce(p.candidate_accession, '') AS member_structural_accession",
                "coalesce(p.species, '') AS member_structural_species",
                "p.pocket_number AS member_pocket_number",
                "p.druggability_score AS member_druggability_score",
                "p.passes_druggability_threshold AS member_passes_druggability_threshold",
                "p.mapping_fraction AS member_pocket_mapping_fraction",
                "p.pocket_plddt_fraction AS member_pocket_plddt_fraction",
                "p.predictor_agreement AS member_predictor_agreement",
                "p.component_selected AS member_pocket_component_selected",
                "coalesce(p.structural_evidence_status, '') "
                "AS member_structural_evidence_status",
            )
        )
        from_sql += (
            " LEFT JOIN member_classes m USING (hog_id) "
            "LEFT JOIN member_structural_rows p ON p.hog_id = m.hog_id "
            "AND upper(trim(p.candidate_accession)) = "
            "upper(trim(m.representative))"
        )
    expressions.extend(
        f"r.{quote_identifier(source)} AS {quote_identifier(output)}"
        for source, output in _ranking_column_mapping(
            ranking_columns=capability["ranking_columns"],
        )
    )
    selected_sql = ", ".join(quote_identifier(column) for column in selected)
    order = (
        "hog_poststructure_rank NULLS LAST, "
        "hog_prestructure_rank NULLS LAST, hog_id"
    )
    if selected_result == ENRICHED_HOG_MEMBERS:
        member_species = next(
            (
                output
                for source, output in _member_column_mapping(
                    membership_columns=capability["membership_columns"],
                )
                if source == "species"
            ),
            None,
        )
        if member_species is not None:
            order += f", {quote_identifier(member_species)} NULLS LAST"
    query = (
        f"WITH {membership_ctes}, {ranking_ctes}, {member_structural_ctes}, "
        f"{universe}, enriched AS ("
        "SELECT "
        + ", ".join(expressions)
        + f" {from_sql}) SELECT {selected_sql} FROM enriched "
        f"ORDER BY {order} LIMIT {int(maximum_rows)}"
    )
    return query, parameters


def collect_enriched_hog_results(
    *,
    connection: duckdb.DuckDBPyConnection,
    result: str,
    selected_columns: Sequence[str],
    maximum_rows: int = 1000,
) -> pd.DataFrame:
    """Collect a bounded resource-wide HOG result.

    Args:
        connection: Open read-only DuckDB connection.
        result: Enriched overview or member-detail key.
        selected_columns: Explicit output fields to retain.
        maximum_rows: Hard returned-row cap.

    Returns:
        Joined HOG rows with complete source-ranking fields.

    Raises:
        AppError: If capability, columns, bounds or SQL execution are invalid.
    """
    query, parameters = _build_enriched_hog_query(
        connection=connection,
        result=result,
        selected_columns=selected_columns,
        maximum_rows=maximum_rows,
    )
    try:
        frame = connection.execute(query, parameters).fetchdf()
    except duckdb.Error as exc:
        LOGGER.exception("Could not collect the enriched HOG result %s", result)
        raise AppError(f"Could not collect enriched HOG results: {exc}") from exc
    LOGGER.info("Collected %s rows from enriched HOG result %s", len(frame), result)
    return frame
