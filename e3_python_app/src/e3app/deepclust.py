"""Bounded DeepClust and 1KP sequence-neighbourhood summaries."""

from __future__ import annotations

import re
from typing import Literal, Sequence

import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError

OneKPMode = Literal["all", "raw", "strict"]
MatchMode = Literal["any", "all"]

DEEPCLUST_RELATION = "candidate_evidence"
REQUIRED_COLUMNS = {
    "representative_id",
    "matched_seed_ids_calculated",
    "raw_member_count",
    "strict_member_count",
    "raw_onekp_sample_count",
    "raw_onekp_species_count",
    "strict_onekp_sample_count",
    "strict_onekp_species_count",
}
PREFERRED_COLUMNS = (
    "representative_id",
    "representative_original_id",
    "representative_entry",
    "representative_source_file_sample_id",
    "representative_sample_id",
    "representative_species",
    "representative_onekp_sample_code",
    "matched_seed_ids_calculated",
    "seed_categories",
    "seed_protein_names",
    "raw_member_count",
    "strict_member_count",
    "strict_member_fraction",
    "raw_onekp_sample_count",
    "raw_onekp_species_count",
    "strict_onekp_sample_count",
    "strict_onekp_species_count",
    "raw_named_proteome_count",
    "raw_named_species_count",
    "strict_named_proteome_count",
    "strict_named_species_count",
    "strict_named_proteome_ids",
    "minimum_observed_pident",
    "median_observed_pident",
    "minimum_member_coverage",
    "median_member_coverage",
)


def select_deepclust_relation(*, relation_names: Sequence[str]) -> str | None:
    """Return the compact discovery-evidence relation when it is available."""
    return DEEPCLUST_RELATION if DEEPCLUST_RELATION in set(relation_names) else None


def _available_columns(*, connection: object, relation: str) -> list[str]:
    """Validate and return the candidate-evidence column names."""
    columns = relation_columns(connection, relation)
    missing = sorted(REQUIRED_COLUMNS.difference(columns))
    if missing:
        raise AppError(
            f"{relation} cannot support the 1KP view; missing columns: "
            f"{', '.join(missing)}"
        )
    return columns


def parse_seed_queries(value: str | Sequence[str]) -> tuple[str, ...]:
    """Return unique seed identifiers from pasted whitespace or delimiters."""
    values = [value] if isinstance(value, str) else list(value)
    tokens: list[str] = []
    for item in values:
        tokens.extend(re.split(r"[\s,;]+", str(item).strip()))
    return tuple(dict.fromkeys(token for token in tokens if token))


def collect_deepclust_metrics(
    *, connection: object, relation: str = DEEPCLUST_RELATION
) -> dict[str, int]:
    """Calculate cluster-link metrics without collecting member-level data."""
    _available_columns(connection=connection, relation=relation)
    query = f"""
        SELECT
            COUNT(*)::BIGINT AS cluster_count,
            COALESCE(SUM(raw_member_count), 0)::BIGINT AS raw_cluster_member_links,
            COALESCE(SUM(strict_member_count), 0)::BIGINT AS strict_cluster_member_links,
            COUNT(*) FILTER (WHERE raw_onekp_sample_count > 0)::BIGINT
                AS clusters_with_raw_onekp,
            COUNT(*) FILTER (WHERE strict_onekp_sample_count > 0)::BIGINT
                AS clusters_with_strict_onekp,
            COALESCE(SUM(strict_onekp_sample_count), 0)::BIGINT
                AS strict_onekp_cluster_sample_links,
            COALESCE(SUM(strict_onekp_species_count), 0)::BIGINT
                AS strict_onekp_cluster_species_links
        FROM {quote_identifier(relation)}
    """
    row = connection.execute(query).fetchone()
    names = [str(item[0]) for item in connection.description]
    if row is None:
        return {name: 0 for name in names}
    return {name: int(value or 0) for name, value in zip(names, row)}


def collect_onekp_coverage_distribution(
    *, connection: object, relation: str = DEEPCLUST_RELATION
) -> pd.DataFrame:
    """Return a compact distribution of strict parsed 1KP species per cluster."""
    _available_columns(connection=connection, relation=relation)
    query = f"""
        SELECT strict_onekp_species_count,
               COUNT(*)::BIGINT AS cluster_count,
               COALESCE(SUM(strict_member_count), 0)::BIGINT
                   AS strict_cluster_member_links
        FROM {quote_identifier(relation)}
        GROUP BY strict_onekp_species_count
        ORDER BY strict_onekp_species_count
    """
    return connection.execute(query).fetchdf()


def _linked_group_sql(*, connection: object) -> tuple[str, str]:
    """Return optional evolutionary-group selections and join SQL."""
    relation_names = set(list_relations(connection))
    candidates = (
        "evolutionary_group_cluster_contributors",
        "final_evolutionary_group_cluster_contributors",
    )
    relation = next((name for name in candidates if name in relation_names), None)
    if relation is None:
        return "", ""
    columns = set(relation_columns(connection, relation))
    if not {"cluster_id", "primary_group_id"}.issubset(columns):
        return "", ""
    type_expression = (
        "primary_group_type" if "primary_group_type" in columns else "''"
    )
    key_expression = (
        "evolutionary_group_key"
        if "evolutionary_group_key" in columns
        else "primary_group_id"
    )
    selection = (
        ", linked.linked_evolutionary_groups, linked.linked_group_types"
    )
    join = f"""
        LEFT JOIN (
            SELECT cluster_id,
                   string_agg(DISTINCT {quote_identifier(key_expression)}, ';'
                              ORDER BY {quote_identifier(key_expression)})
                       AS linked_evolutionary_groups,
                   string_agg(DISTINCT {type_expression}, ';'
                              ORDER BY {type_expression}) AS linked_group_types
            FROM {quote_identifier(relation)}
            GROUP BY cluster_id
        ) AS linked ON linked.cluster_id = evidence.representative_id
    """
    return selection, join


def collect_deepclust_summary(
    *,
    connection: object,
    relation: str = DEEPCLUST_RELATION,
    seed_queries: Sequence[str] = (),
    match_mode: MatchMode = "any",
    onekp_mode: OneKPMode = "all",
    minimum_strict_onekp_species: int = 0,
    cluster_query: str = "",
    maximum_rows: int = 1000,
) -> pd.DataFrame:
    """Return filtered E3-seeded DeepClust neighbourhood summaries."""
    columns = _available_columns(connection=connection, relation=relation)
    if match_mode not in ("any", "all"):
        raise AppError(f"Unsupported seed match mode: {match_mode}")
    if onekp_mode not in ("all", "raw", "strict"):
        raise AppError(f"Unsupported 1KP filter: {onekp_mode}")
    if not 0 <= int(minimum_strict_onekp_species) <= 1_000_000:
        raise AppError("Minimum strict 1KP species must be between 0 and 1,000,000")
    if not 1 <= int(maximum_rows) <= 100_000:
        raise AppError("Maximum DeepClust rows must be between 1 and 100,000")
    seeds = parse_seed_queries(seed_queries)
    filters = ["COALESCE(evidence.strict_onekp_species_count, 0) >= ?"]
    parameters: list[object] = [int(minimum_strict_onekp_species)]
    if onekp_mode == "raw":
        filters.append("COALESCE(evidence.raw_onekp_sample_count, 0) > 0")
    elif onekp_mode == "strict":
        filters.append("COALESCE(evidence.strict_onekp_sample_count, 0) > 0")
    if cluster_query.strip():
        filters.append("strpos(lower(evidence.representative_id), lower(?)) > 0")
        parameters.append(cluster_query.strip())
    if seeds:
        clauses = []
        for seed in seeds:
            clauses.append(
                "list_contains(string_split(lower(COALESCE("
                "evidence.matched_seed_ids_calculated, '')), ';'), lower(?))"
            )
            parameters.append(seed)
        operator = " AND " if match_mode == "all" else " OR "
        filters.append("(" + operator.join(clauses) + ")")
    selected = [column for column in PREFERRED_COLUMNS if column in columns]
    selections = ", ".join(
        f"evidence.{quote_identifier(column)}" for column in selected
    )
    linked_selection, linked_join = _linked_group_sql(connection=connection)
    query = f"""
        SELECT {selections}{linked_selection}
        FROM {quote_identifier(relation)} AS evidence
        {linked_join}
        WHERE {' AND '.join(filters)}
        ORDER BY evidence.strict_onekp_species_count DESC,
                 evidence.strict_member_count DESC,
                 evidence.representative_id
        LIMIT ?
    """
    parameters.append(int(maximum_rows))
    return connection.execute(query, parameters).fetchdf()
