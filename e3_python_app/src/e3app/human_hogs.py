"""Bounded root-level HOG queries for human and plant–human exploration."""

from __future__ import annotations

import logging
from typing import Literal, Sequence

import pandas as pd

from e3app.data import (
    list_relations,
    quote_identifier,
    relation_columns,
)
from e3app.errors import AppError
from e3app.orthology import load_species_taxonomy

LOGGER = logging.getLogger(__name__)

HUMAN_SPECIES = "Homo_sapiens"
ARABIDOPSIS_SPECIES = "Arabidopsis_thaliana"
RICE_SPECIES = "Oryza_sativa"
BARLEY_SPECIES = "Hordeum_vulgare"
HIERARCHICAL_RELATION = "hierarchical_membership"
HOG_MEMBERSHIP_REQUIRED_COLUMNS = {"group_id", "species", "raw_identifier"}
RANKING_RELATION_PREFERENCE = (
    "final_evolutionary_candidate_prioritisation",
    "candidate_master_results",
    "final_candidate_prioritisation",
    "evolutionary_candidate_group_ranking",
    "prestructure_ranking",
)
RANK_COLUMNS = (
    "final_evolutionary_rank",
    "final_rank",
    "prestructure_evolutionary_group_rank",
    "evolutionary_group_rank",
    "computational_rank",
)

HogView = Literal["human", "plant_and_human"]
MemberScope = Literal["human", "all"]


def target_plant_species() -> tuple[str, ...]:
    """Return the curated source labels for the 12 target plant species."""
    taxonomy = load_species_taxonomy()
    plants = taxonomy[taxonomy["role"].astype(str) == "target_plant"]
    labels = plants["source_species_name"].dropna().astype(str)
    return tuple(sorted({label.strip() for label in labels if label.strip()}))


def validate_hog_view(*, view: HogView) -> None:
    """Validate a human-HOG view selector.

    Args:
        view: ``human`` or ``plant_and_human``.

    Raises:
        AppError: If the selector is unsupported.
    """
    if view not in {"human", "plant_and_human"}:
        raise AppError(f"Unsupported human-HOG view: {view}")


def select_hog_ranking_relation(*, connection: object) -> str | None:
    """Select the strongest available HOG-linked candidate-ranking relation."""
    available = set(list_relations(connection))
    for relation in RANKING_RELATION_PREFERENCE:
        if relation not in available:
            continue
        columns = set(relation_columns(connection, relation))
        if "primary_group_id" in columns and any(
            column in columns for column in RANK_COLUMNS
        ):
            return relation
    return None


def human_hog_capability(*, connection: object) -> dict[str, object]:
    """Report whether the complete root-level HOG membership is available."""
    relations = set(list_relations(connection))
    if HIERARCHICAL_RELATION not in relations:
        return {
            "available": False,
            "missing_columns": sorted(HOG_MEMBERSHIP_REQUIRED_COLUMNS),
            "ranking_relation": None,
        }
    columns = set(relation_columns(connection, HIERARCHICAL_RELATION))
    missing = sorted(HOG_MEMBERSHIP_REQUIRED_COLUMNS.difference(columns))
    return {
        "available": not missing,
        "missing_columns": missing,
        "ranking_relation": select_hog_ranking_relation(connection=connection),
    }


def _validate_maximum_rows(*, maximum_rows: int) -> int:
    """Return a defensively bounded row limit."""
    if not 1 <= maximum_rows <= 100_000:
        raise AppError("maximum human-HOG rows must be between 1 and 100000")
    return int(maximum_rows)


def _first_available(
    *, columns: set[str], candidates: Sequence[str]
) -> str | None:
    """Return the first available column from an ordered preference list."""
    return next((column for column in candidates if column in columns), None)


def _string_expression(*, columns: set[str], column: str) -> str:
    """Return a nullable text expression for an optional source column."""
    if column not in columns:
        return "CAST(NULL AS VARCHAR)"
    return f"CAST({quote_identifier(column)} AS VARCHAR)"


def _integer_expression(*, columns: set[str], candidates: Sequence[str]) -> str:
    """Return a nullable integer expression for the first available column."""
    column = _first_available(columns=columns, candidates=candidates)
    if column is None:
        return "CAST(NULL AS BIGINT)"
    return f"TRY_CAST({quote_identifier(column)} AS BIGINT)"


def _double_expression(*, columns: set[str], candidates: Sequence[str]) -> str:
    """Return a nullable double expression for the first available column."""
    column = _first_available(columns=columns, candidates=candidates)
    if column is None:
        return "CAST(NULL AS DOUBLE)"
    return f"TRY_CAST({quote_identifier(column)} AS DOUBLE)"


def _boolean_expression(*, columns: set[str], candidates: Sequence[str]) -> str:
    """Return a nullable Boolean expression for the first available column."""
    column = _first_available(columns=columns, candidates=candidates)
    if column is None:
        return "CAST(NULL AS BOOLEAN)"
    return f"TRY_CAST({quote_identifier(column)} AS BOOLEAN)"


def _aggregate_text(*, expression: str, alias: str) -> str:
    """Build a deterministic distinct text aggregation."""
    return (
        f"string_agg(DISTINCT {expression}, ';' ORDER BY {expression}) "
        f"FILTER (WHERE {expression} IS NOT NULL AND trim({expression}) != '') "
        f"AS {quote_identifier(alias)}"
    )


def _membership_cte(*, connection: object) -> str:
    """Build a stable membership CTE over optional source metadata columns."""
    columns = set(relation_columns(connection, HIERARCHICAL_RELATION))
    missing = HOG_MEMBERSHIP_REQUIRED_COLUMNS.difference(columns)
    if missing:
        raise AppError(
            "hierarchical_membership is missing required columns: "
            + ", ".join(sorted(missing))
        )
    optional = (
        "record_type",
        "orthogroup_id",
        "gene_tree_parent_clade",
        "parsed_accession",
        "parsed_entry",
        "review_status",
        "identifier_format",
        "mapping_status",
        "mapping_reason",
        "source_file",
        "source_row",
    )
    expressions = [
        "CAST(group_id AS VARCHAR) AS hog_id",
        "CAST(species AS VARCHAR) AS species",
        "CAST(raw_identifier AS VARCHAR) AS raw_identifier",
    ]
    expressions.extend(
        f"{_string_expression(columns=columns, column=column)} "
        f"AS {quote_identifier(column)}"
        for column in optional
    )
    return (
        "membership AS (SELECT "
        + ", ".join(expressions)
        + f" FROM {quote_identifier(HIERARCHICAL_RELATION)} "
        "WHERE group_id IS NOT NULL "
        "AND starts_with(trim(CAST(group_id AS VARCHAR)), 'N0.HOG') "
        "AND trim(CAST(group_id AS VARCHAR)) != '')"
    )


def _ranking_cte(*, connection: object, ranking_relation: str | None) -> str:
    """Build one optional candidate annotation row per root-level HOG."""
    if ranking_relation is None:
        return (
            "ranked AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, "
            "CAST(NULL AS BIGINT) AS ranking_position, "
            "CAST(NULL AS VARCHAR) AS ranking_statuses, "
            "CAST(NULL AS VARCHAR) AS linked_clusters, "
            "CAST(NULL AS VARCHAR) AS candidate_accessions, "
            "CAST(NULL AS VARCHAR) AS matched_e3_seeds, "
            "CAST(NULL AS VARCHAR) AS seed_protein_names, "
            "CAST(NULL AS DOUBLE) AS final_score, "
            "CAST(NULL AS BOOLEAN) AS prestructure_pass, "
            "CAST(NULL AS BOOLEAN) AS final_pass WHERE FALSE)"
        )
    columns = set(relation_columns(connection, ranking_relation))
    rank = _integer_expression(columns=columns, candidates=RANK_COLUMNS)
    status = _string_expression(
        columns=columns,
        column=_first_available(
            columns=columns,
            candidates=(
                "recommendation_status",
                "custom_status",
                "grant_aligned_criteria_status",
                "criteria_status",
            ),
        )
        or "",
    )
    cluster = _string_expression(
        columns=columns,
        column=_first_available(
            columns=columns,
            candidates=("lead_cluster_id", "cluster_id"),
        )
        or "",
    )
    accessions = _string_expression(
        columns=columns,
        column=_first_available(
            columns=columns,
            candidates=("candidate_accessions", "candidate_accession"),
        )
        or "",
    )
    seeds = _string_expression(
        columns=columns,
        column=_first_available(
            columns=columns,
            candidates=(
                "discovery_matched_seed_ids_calculated",
                "matched_seed_ids_calculated",
            ),
        )
        or "",
    )
    seed_names = _string_expression(
        columns=columns,
        column=_first_available(
            columns=columns,
            candidates=(
                "discovery_seed_protein_names",
                "seed_protein_names",
            ),
        )
        or "",
    )
    score = _double_expression(
        columns=columns,
        candidates=("final_score", "prestructure_score"),
    )
    prestructure = _boolean_expression(
        columns=columns,
        candidates=(
            "grant_aligned_prestructure_pass",
            "grant_aligned_stringent_pass",
        ),
    )
    final = _boolean_expression(
        columns=columns,
        candidates=("grant_aligned_final_pass",),
    )
    type_filter = ""
    if "primary_group_type" in columns:
        type_filter = (
            " AND (upper(CAST(primary_group_type AS VARCHAR)) IN "
            "('HIERARCHICAL_ORTHOGROUP', 'HOG') OR "
            "starts_with(CAST(primary_group_id AS VARCHAR), 'N0.HOG'))"
        )
    aggregations = (
        f"min({rank}) AS ranking_position",
        _aggregate_text(expression=status, alias="ranking_statuses"),
        _aggregate_text(expression=cluster, alias="linked_clusters"),
        _aggregate_text(expression=accessions, alias="candidate_accessions"),
        _aggregate_text(expression=seeds, alias="matched_e3_seeds"),
        _aggregate_text(expression=seed_names, alias="seed_protein_names"),
        f"max({score}) AS final_score",
        f"bool_or(coalesce({prestructure}, FALSE)) AS prestructure_pass",
        f"bool_or(coalesce({final}, FALSE)) AS final_pass",
    )
    return (
        "ranked AS (SELECT CAST(primary_group_id AS VARCHAR) AS hog_id, "
        + ", ".join(aggregations)
        + f" FROM {quote_identifier(ranking_relation)} "
        "WHERE primary_group_id IS NOT NULL "
        "AND trim(CAST(primary_group_id AS VARCHAR)) != ''"
        + type_filter
        + " GROUP BY CAST(primary_group_id AS VARCHAR))"
    )


def _sequence_cte(*, connection: object) -> str:
    """Build optional sequence and candidate-link annotations per HOG member."""
    relation = "candidate_group_member_sequences"
    if relation not in set(list_relations(connection)):
        return _empty_sequence_cte()
    columns = set(relation_columns(connection, relation))
    required = {"group_id", "species", "raw_identifier"}
    if not required.issubset(columns):
        LOGGER.warning(
            "%s is missing human-HOG join columns: %s",
            relation,
            ", ".join(sorted(required.difference(columns))),
        )
        return _empty_sequence_cte()
    cluster = _string_expression(columns=columns, column="cluster_id")
    candidates = _string_expression(
        columns=columns,
        column="candidate_accessions_for_cluster",
    )
    internal_id = _string_expression(columns=columns, column="internal_id")
    source_fasta = _string_expression(columns=columns, column="source_fasta")
    sequence_sha = _string_expression(columns=columns, column="sequence_sha256")
    protein_sequence = _string_expression(columns=columns, column="protein_sequence")
    length = (
        "TRY_CAST(sequence_length AS BIGINT)"
        if "sequence_length" in columns
        else "CAST(NULL AS BIGINT)"
    )
    input_candidate = (
        "TRY_CAST(is_input_candidate AS BOOLEAN)"
        if "is_input_candidate" in columns
        else "CAST(NULL AS BOOLEAN)"
    )
    record_filter = ""
    if "record_type" in columns:
        record_filter = (
            " WHERE upper(CAST(record_type AS VARCHAR)) = "
            "'HIERARCHICAL_ORTHOGROUP'"
        )
    return (
        "sequence_annotations AS (SELECT CAST(group_id AS VARCHAR) AS hog_id, "
        "CAST(species AS VARCHAR) AS species, "
        "CAST(raw_identifier AS VARCHAR) AS raw_identifier, "
        f"{_aggregate_text(expression=cluster, alias='linked_clusters')}, "
        f"{_aggregate_text(expression=candidates, alias='candidate_accessions')}, "
        f"{_aggregate_text(expression=internal_id, alias='internal_ids')}, "
        f"{_aggregate_text(expression=source_fasta, alias='source_fastas')}, "
        f"bool_or(coalesce({input_candidate}, FALSE)) AS is_input_candidate, "
        f"max({length}) AS sequence_length, "
        f"max({sequence_sha}) AS sequence_sha256, "
        f"max({protein_sequence}) AS protein_sequence "
        f"FROM {quote_identifier(relation)}{record_filter} "
        "GROUP BY CAST(group_id AS VARCHAR), CAST(species AS VARCHAR), "
        "CAST(raw_identifier AS VARCHAR))"
    )


def _empty_sequence_cte() -> str:
    """Return a typed empty sequence annotation CTE."""
    return (
        "sequence_annotations AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, "
        "CAST(NULL AS VARCHAR) AS species, "
        "CAST(NULL AS VARCHAR) AS raw_identifier, "
        "CAST(NULL AS VARCHAR) AS linked_clusters, "
        "CAST(NULL AS VARCHAR) AS candidate_accessions, "
        "CAST(NULL AS VARCHAR) AS internal_ids, "
        "CAST(NULL AS VARCHAR) AS source_fastas, "
        "CAST(NULL AS BOOLEAN) AS is_input_candidate, "
        "CAST(NULL AS BIGINT) AS sequence_length, "
        "CAST(NULL AS VARCHAR) AS sequence_sha256, "
        "CAST(NULL AS VARCHAR) AS protein_sequence WHERE FALSE)"
    )


def _alias_cte(*, connection: object) -> str:
    """Build optional gene/protein alias annotations per HOG member accession."""
    relation = "candidate_identifier_aliases"
    if relation not in set(list_relations(connection)):
        return _empty_alias_cte()
    columns = set(relation_columns(connection, relation))
    required = {"primary_group_id", "member_accession", "identifier_value"}
    if not required.issubset(columns):
        return _empty_alias_cte()
    identifier_type = _string_expression(columns=columns, column="identifier_type")
    identifier_value = _string_expression(columns=columns, column="identifier_value")
    species = _string_expression(columns=columns, column="species_column")
    return (
        "aliases AS (SELECT CAST(primary_group_id AS VARCHAR) AS hog_id, "
        "upper(CAST(member_accession AS VARCHAR)) AS member_accession, "
        f"{_aggregate_text(expression=species, alias='alias_species')}, "
        f"{_aggregate_text(expression=identifier_type, alias='identifier_types')}, "
        f"{_aggregate_text(expression=identifier_value, alias='identifier_values')} "
        f"FROM {quote_identifier(relation)} "
        "WHERE primary_group_id IS NOT NULL AND member_accession IS NOT NULL "
        "GROUP BY CAST(primary_group_id AS VARCHAR), "
        "upper(CAST(member_accession AS VARCHAR)))"
    )


def _empty_alias_cte() -> str:
    """Return a typed empty alias annotation CTE."""
    return (
        "aliases AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, "
        "CAST(NULL AS VARCHAR) AS member_accession, "
        "CAST(NULL AS VARCHAR) AS alias_species, "
        "CAST(NULL AS VARCHAR) AS identifier_types, "
        "CAST(NULL AS VARCHAR) AS identifier_values WHERE FALSE)"
    )


def _view_ctes(
    *, connection: object, view: HogView, ranking_relation: str | None
) -> tuple[str, list[object]]:
    """Build shared membership, taxonomy, eligibility and ranking CTEs."""
    validate_hog_view(view=view)
    plants = target_plant_species()
    if not plants:
        raise AppError("The packaged taxonomy manifest contains no target plants")
    plant_values = ", ".join("(?)" for _ in plants)
    eligibility = "AND plant_member_count > 0" if view == "plant_and_human" else ""
    ctes = (
        _membership_cte(connection=connection),
        "human_species(species) AS (VALUES (?))",
        f"target_plants(species) AS (VALUES {plant_values})",
        "member_classes AS (SELECT m.*, m.species = h.species AS is_human, "
        "EXISTS (SELECT 1 FROM target_plants p WHERE p.species = m.species) "
        "AS is_target_plant FROM membership m CROSS JOIN human_species h)",
        "representative_members AS (SELECT hog_id, species, is_human, "
        "coalesce(nullif(trim(parsed_accession), ''), "
        "nullif(trim(parsed_entry), ''), nullif(trim(raw_identifier), '')) "
        "AS representative FROM member_classes)",
        "hog_representatives AS (SELECT hog_id, "
        "coalesce(string_agg(DISTINCT representative, ';' "
        "ORDER BY representative) FILTER (WHERE is_human "
        "AND representative IS NOT NULL), '') "
        "AS human_hog_representatives, "
        "coalesce(string_agg(DISTINCT representative, ';' "
        "ORDER BY representative) FILTER (WHERE species = "
        f"'{ARABIDOPSIS_SPECIES}' AND representative IS NOT NULL), '') "
        "AS arabidopsis_hog_representatives, "
        "coalesce(string_agg(DISTINCT representative, ';' "
        "ORDER BY representative) FILTER (WHERE species = "
        f"'{RICE_SPECIES}' AND representative IS NOT NULL), '') "
        "AS rice_hog_representatives, "
        "coalesce(string_agg(DISTINCT representative, ';' "
        "ORDER BY representative) FILTER (WHERE species = "
        f"'{BARLEY_SPECIES}' AND representative IS NOT NULL), '') "
        "AS barley_hog_representatives "
        "FROM representative_members GROUP BY hog_id)",
        "hog_counts AS (SELECT hog_id, count(*) AS member_count, "
        "count(DISTINCT species) AS species_count, "
        "count(*) FILTER (WHERE is_human) AS human_member_count, "
        "count(*) FILTER (WHERE is_target_plant) AS plant_member_count, "
        "count(DISTINCT species) FILTER (WHERE is_target_plant) "
        "AS plant_species_count FROM member_classes GROUP BY hog_id)",
        "eligible_hogs AS (SELECT * FROM hog_counts "
        f"WHERE human_member_count > 0 {eligibility})",
        _ranking_cte(connection=connection, ranking_relation=ranking_relation),
    )
    return ", ".join(ctes), [HUMAN_SPECIES, *plants]


def collect_human_hog_summary(
    *,
    connection: object,
    view: HogView = "human",
    maximum_rows: int = 100_000,
) -> pd.DataFrame:
    """Collect one richly annotated row per qualifying root-level HOG.

    Args:
        connection: Open read-only DuckDB connection.
        view: All human HOGs or the plant-and-human subset.
        maximum_rows: Defensive maximum number of HOG rows.

    Returns:
        Ranked and composition-annotated root-level HOG summary.
    """
    limit = _validate_maximum_rows(maximum_rows=maximum_rows)
    capability = human_hog_capability(connection=connection)
    if not capability["available"]:
        raise AppError(
            "Human-HOG exploration requires complete hierarchical_membership; "
            "missing columns: "
            + ", ".join(capability["missing_columns"])
        )
    ranking_relation = capability["ranking_relation"]
    ctes, parameters = _view_ctes(
        connection=connection,
        view=view,
        ranking_relation=ranking_relation,
    )
    query = f"""
        WITH {ctes}, summaries AS (
            SELECT c.hog_id, c.member_count, c.species_count,
                   c.human_member_count, c.plant_member_count,
                   c.plant_species_count,
                   string_agg(DISTINCT m.species, ';' ORDER BY m.species)
                       AS species_present,
                   string_agg(DISTINCT m.species, ';' ORDER BY m.species)
                       FILTER (WHERE m.is_target_plant) AS plant_species_present,
                   string_agg(DISTINCT coalesce(m.parsed_accession, ''), ';'
                              ORDER BY coalesce(m.parsed_accession, ''))
                       FILTER (WHERE m.is_human
                               AND coalesce(m.parsed_accession, '') != '')
                       AS human_accessions,
                   string_agg(DISTINCT coalesce(m.parsed_entry, ''), ';'
                              ORDER BY coalesce(m.parsed_entry, ''))
                       FILTER (WHERE m.is_human
                               AND coalesce(m.parsed_entry, '') != '')
                       AS human_entries,
                   string_agg(DISTINCT m.raw_identifier, ';'
                              ORDER BY m.raw_identifier)
                       FILTER (WHERE m.is_human) AS human_raw_identifiers
            FROM eligible_hogs c
            INNER JOIN member_classes m USING (hog_id)
            GROUP BY c.hog_id, c.member_count, c.species_count,
                     c.human_member_count, c.plant_member_count,
                     c.plant_species_count
        )
        SELECT s.hog_id,
               h.human_hog_representatives,
               h.arabidopsis_hog_representatives,
               h.rice_hog_representatives,
               h.barley_hog_representatives,
               s.member_count, s.species_count, s.human_member_count,
               s.plant_member_count, s.plant_species_count,
               s.species_present, s.plant_species_present,
               s.human_accessions, s.human_entries,
               s.human_raw_identifiers,
               CASE WHEN r.hog_id IS NULL THEN 'NOT_IN_CANDIDATE_RANKING'
                    ELSE 'RANKED' END AS ranking_availability,
               r.ranking_position, r.ranking_statuses, r.linked_clusters,
               r.candidate_accessions, r.matched_e3_seeds,
               r.seed_protein_names, r.final_score,
               r.prestructure_pass, r.final_pass,
               {"'" + ranking_relation + "'" if ranking_relation else "''"}
                   AS ranking_source
        FROM summaries s
        INNER JOIN hog_representatives h USING (hog_id)
        LEFT JOIN ranked r USING (hog_id)
        ORDER BY r.ranking_position NULLS LAST, s.hog_id
        LIMIT {limit}
    """
    return connection.execute(query, parameters).fetchdf()


def collect_human_hog_members(
    *,
    connection: object,
    view: HogView = "human",
    member_scope: MemberScope = "all",
    maximum_rows: int = 100_000,
) -> pd.DataFrame:
    """Collect human or complete co-membership rows for qualifying HOGs.

    Args:
        connection: Open read-only DuckDB connection.
        view: All human HOGs or the plant-and-human subset.
        member_scope: Human rows only or all HOG co-members.
        maximum_rows: Defensive maximum number of member rows.

    Returns:
        Membership rows enriched with ranking, sequence and alias evidence.
    """
    validate_hog_view(view=view)
    if member_scope not in {"human", "all"}:
        raise AppError(f"Unsupported human-HOG member scope: {member_scope}")
    limit = _validate_maximum_rows(maximum_rows=maximum_rows)
    capability = human_hog_capability(connection=connection)
    if not capability["available"]:
        raise AppError("Human-HOG membership is unavailable in this release")
    ranking_relation = capability["ranking_relation"]
    ctes, parameters = _view_ctes(
        connection=connection,
        view=view,
        ranking_relation=ranking_relation,
    )
    ctes = ", ".join(
        (
            ctes,
            _sequence_cte(connection=connection),
            _alias_cte(connection=connection),
        )
    )
    member_filter = "WHERE m.is_human" if member_scope == "human" else ""
    query = f"""
        WITH {ctes}
        SELECT m.hog_id,
               h.human_hog_representatives,
               h.arabidopsis_hog_representatives,
               h.rice_hog_representatives,
               h.barley_hog_representatives,
               CASE WHEN r.hog_id IS NULL THEN 'NOT_IN_CANDIDATE_RANKING'
                    ELSE 'RANKED' END AS ranking_availability,
               r.ranking_position, r.ranking_statuses, r.final_score,
               r.prestructure_pass, r.final_pass,
               r.linked_clusters AS ranked_linked_clusters,
               r.candidate_accessions AS ranked_candidate_accessions,
               r.matched_e3_seeds, r.seed_protein_names,
               CASE WHEN m.is_human THEN 'HUMAN'
                    WHEN m.is_target_plant THEN 'TARGET_PLANT'
                    ELSE 'OTHER_ORTHOFINDER_INPUT' END AS member_class,
               m.species, m.is_human, m.is_target_plant,
               m.raw_identifier, m.parsed_accession, m.parsed_entry,
               m.review_status, m.identifier_format, m.mapping_status,
               m.mapping_reason, m.orthogroup_id,
               m.gene_tree_parent_clade, m.source_file, m.source_row,
               s.linked_clusters AS sequence_linked_clusters,
               s.candidate_accessions AS sequence_candidate_accessions,
               s.internal_ids, s.source_fastas, s.is_input_candidate,
               s.sequence_length, s.sequence_sha256, s.protein_sequence,
               a.identifier_types AS available_alias_types,
               a.identifier_values AS available_aliases
        FROM member_classes m
        INNER JOIN eligible_hogs e USING (hog_id)
        INNER JOIN hog_representatives h USING (hog_id)
        LEFT JOIN ranked r USING (hog_id)
        LEFT JOIN sequence_annotations s
          ON s.hog_id = m.hog_id AND s.species = m.species
         AND s.raw_identifier = m.raw_identifier
        LEFT JOIN aliases a
          ON a.hog_id = m.hog_id
         AND a.member_accession = upper(coalesce(m.parsed_accession, ''))
        {member_filter}
        ORDER BY r.ranking_position NULLS LAST, m.hog_id,
                 CASE WHEN m.is_human THEN 0
                      WHEN m.is_target_plant THEN 1 ELSE 2 END,
                 m.species, m.raw_identifier
        LIMIT {limit}
    """
    return connection.execute(query, parameters).fetchdf()
