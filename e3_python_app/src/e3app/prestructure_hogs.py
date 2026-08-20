"""Authoritative top-N pre-structure ranking for root-level HOGs."""

from __future__ import annotations

import logging
from typing import Sequence

import duckdb
import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)

HIERARCHICAL_RELATION = "hierarchical_membership"
HUMAN_SPECIES = "Homo_sapiens"
ARABIDOPSIS_SPECIES = "Arabidopsis_thaliana"
RICE_SPECIES = "Oryza_sativa"
BARLEY_SPECIES = "Hordeum_vulgare"
PRESTRUCTURE_HOG_RELATION_PREFERENCE = (
    "final_evolutionary_candidate_prioritisation",
    "evolutionary_candidate_group_ranking",
    "candidate_master_results",
    "final_candidate_prioritisation",
    "prestructure_ranking",
)
PRESTRUCTURE_HOG_RANK_COLUMNS = (
    "prestructure_evolutionary_group_rank",
    "evolutionary_group_rank",
)
PRESTRUCTURE_HOG_PASS_COLUMNS = (
    "grant_aligned_prestructure_pass",
    "grant_aligned_stringent_pass",
)
STRUCTURAL_REVIEW_COLUMN_MARKERS = (
    "druggability",
    "ligandability",
    "pocket",
    "structural",
    "three_dimensional",
    "sensitivity_",
    "alignment",
    "conservation",
    "centroid_distance",
    "minimum_tm_score",
    "predictor_agreement",
    "plddt",
    "alphafold",
    "colabfold",
    "foldseek",
    "usalign",
    "tm_align",
    "model",
    "mmcif",
    "pdb",
)
STRUCTURAL_REVIEW_EXCLUDED_COLUMNS = frozenset(
    {
        "final_evolutionary_rank",
        "final_rank",
        "stringent_rank",
        "boss_review_status",
        "recommendation_status",
        "grant_aligned_prediction_status",
        "final_score",
        "grant_aligned_base_pass",
        "grant_aligned_final_pass",
        "conservation_status",
        "all_assessed_members_pass_mapping",
        "computational_structure_selected",
        "lead_computational_structure_selected",
        "mean_pairwise_region_overlap",
        "mean_chemical_group_conservation",
    }
)


def prestructure_hog_capability(*, connection: object) -> dict[str, object]:
    """Resolve an authoritative group-level pre-structure ranking source.

    Args:
        connection: Open read-only DuckDB connection.

    Returns:
        Availability, relation, rank-column and optional pass-column metadata.
        Cluster-level ``computational_rank`` is deliberately not accepted as a
        HOG rank.
    """
    available_relations = set(list_relations(connection))
    for relation in PRESTRUCTURE_HOG_RELATION_PREFERENCE:
        if relation not in available_relations:
            continue
        columns = set(relation_columns(connection, relation))
        rank_column = next(
            (
                column
                for column in PRESTRUCTURE_HOG_RANK_COLUMNS
                if column in columns
            ),
            None,
        )
        pass_column = next(
            (
                column
                for column in PRESTRUCTURE_HOG_PASS_COLUMNS
                if column in columns
            ),
            None,
        )
        if "primary_group_id" in columns and rank_column is not None:
            return {
                "available": True,
                "relation": relation,
                "rank_column": rank_column,
                "pass_column": pass_column,
            }
    return {
        "available": False,
        "relation": None,
        "rank_column": None,
        "pass_column": None,
    }


def prestructure_review_columns(*, available: Sequence[str]) -> list[str]:
    """Select source columns which cannot expose structural-stage evidence.

    Args:
        available: Source relation columns in their published order.

    Returns:
        Pre-structure and provenance columns, with the authoritative HOG rank
        and identifier placed first.
    """
    safe = [
        column
        for column in available
        if column not in STRUCTURAL_REVIEW_EXCLUDED_COLUMNS
        and not any(
            marker in column.casefold()
            for marker in STRUCTURAL_REVIEW_COLUMN_MARKERS
        )
    ]
    preferred = (
        "prestructure_evolutionary_group_rank",
        "evolutionary_group_rank",
        "primary_group_id",
        "prestructure_score",
        "best_prestructure_score",
        "mean_prestructure_score",
        "minimum_prestructure_score",
        "grant_aligned_prestructure_pass",
        "grant_aligned_stringent_pass",
    )
    ordered = [column for column in preferred if column in safe]
    ordered.extend(column for column in safe if column not in ordered)
    return ordered


def _empty_representatives_cte() -> str:
    """Return a typed empty HOG-representative CTE."""
    return (
        "hog_representatives AS (SELECT CAST(NULL AS VARCHAR) AS hog_id, "
        "CAST(NULL AS VARCHAR) AS human_hog_representatives, "
        "CAST(NULL AS VARCHAR) AS arabidopsis_hog_representatives, "
        "CAST(NULL AS VARCHAR) AS rice_hog_representatives, "
        "CAST(NULL AS VARCHAR) AS barley_hog_representatives "
        "WHERE FALSE)"
    )


def _representatives_ctes(*, connection: object) -> str:
    """Build optional human, Arabidopsis, rice and barley annotations."""
    if HIERARCHICAL_RELATION not in set(list_relations(connection)):
        return _empty_representatives_cte()
    columns = set(relation_columns(connection, HIERARCHICAL_RELATION))
    required = {"group_id", "species", "raw_identifier"}
    if not required.issubset(columns):
        return _empty_representatives_cte()
    parsed_accession = (
        "CAST(parsed_accession AS VARCHAR)"
        if "parsed_accession" in columns
        else "CAST(NULL AS VARCHAR)"
    )
    parsed_entry = (
        "CAST(parsed_entry AS VARCHAR)"
        if "parsed_entry" in columns
        else "CAST(NULL AS VARCHAR)"
    )
    return (
        "membership_representatives AS (SELECT "
        "CAST(group_id AS VARCHAR) AS hog_id, "
        "CAST(species AS VARCHAR) AS species, "
        f"coalesce(nullif(trim({parsed_accession}), ''), "
        f"nullif(trim({parsed_entry}), ''), "
        "nullif(trim(CAST(raw_identifier AS VARCHAR)), '')) AS representative "
        f"FROM {quote_identifier(HIERARCHICAL_RELATION)} "
        "WHERE group_id IS NOT NULL AND "
        "starts_with(trim(CAST(group_id AS VARCHAR)), 'N0.HOG')), "
        "hog_representatives AS (SELECT hog_id, "
        "coalesce(string_agg(DISTINCT representative, ';' "
        "ORDER BY representative) FILTER (WHERE species = "
        f"'{HUMAN_SPECIES}' AND representative IS NOT NULL), '') "
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
        "FROM membership_representatives GROUP BY hog_id)"
    )


def _ranked_row_order(*, available: Sequence[str], rank_column: str) -> str:
    """Return deterministic row ordering for duplicate source HOG rows."""
    choices = (
        (rank_column, "ASC"),
        ("prestructure_score", "DESC"),
        ("best_prestructure_score", "DESC"),
        ("mean_prestructure_score", "DESC"),
        ("lead_computational_rank", "ASC"),
        ("lead_cluster_id", "ASC"),
        ("cluster_id", "ASC"),
        ("candidate_accessions", "ASC"),
    )
    selected = list(
        dict.fromkeys(
            (column, direction)
            for column, direction in choices
            if column in available
        )
    )
    return ", ".join(
        f"{quote_identifier(column)} {direction} NULLS LAST"
        for column, direction in selected
    )


def collect_prestructure_ranked_hogs(
    *,
    connection: duckdb.DuckDBPyConnection,
    maximum_hogs: int = 200,
    passes_only: bool = False,
) -> pd.DataFrame:
    """Collect HOGs for an independent structural-review shortlist.

    The recorded rank integrates discovery, orthology/species, domain and
    expression evidence. Structural-stage fields and tie-breaks are excluded.
    The recorded stringent pre-structure gate is an optional filter.

    Args:
        connection: Open read-only DuckDB connection.
        maximum_hogs: Number of ranked HOGs to return, from 1 to 10,000.
        passes_only: Require the recorded group-level pre-structure pass.

    Returns:
        One richly annotated row per ranked root-level HOG.

    Raises:
        AppError: If no authoritative HOG rank exists, a requested pass field
            is unavailable, the arguments are invalid or DuckDB cannot execute
            the bounded query.
    """
    if not 1 <= maximum_hogs <= 10_000:
        raise AppError("maximum ranked HOGs must be between 1 and 10000")
    if not isinstance(passes_only, bool):
        raise AppError("passes_only must be a boolean")
    capability = prestructure_hog_capability(connection=connection)
    if not capability["available"]:
        raise AppError(
            "No relation contains both primary_group_id and an authoritative "
            "pre-structure evolutionary-group rank"
        )
    relation = str(capability["relation"])
    rank_column = str(capability["rank_column"])
    available = relation_columns(connection, relation)
    selected_columns = prestructure_review_columns(available=available)
    if not selected_columns:
        raise AppError("No non-structural fields are available for the shortlist")
    pass_column = capability["pass_column"]
    if passes_only and pass_column is None:
        raise AppError(
            "The source has no group-level recorded pre-structure pass field"
        )
    eligibility_filter = ""
    if passes_only:
        eligibility_filter = (
            " AND coalesce(TRY_CAST("
            f"{quote_identifier(str(pass_column))} AS BOOLEAN), FALSE)"
        )
    row_order = _ranked_row_order(
        available=available,
        rank_column=rank_column,
    )
    source_select = ", ".join(
        quote_identifier(column) for column in selected_columns
    )
    representatives = _representatives_ctes(connection=connection)
    query = f"""
        WITH ranked_source AS (
            SELECT * EXCLUDE (_e3_hog_row)
            FROM (
                SELECT {source_select}, ROW_NUMBER() OVER (
                    PARTITION BY CAST(primary_group_id AS VARCHAR)
                    ORDER BY {row_order}
                ) AS _e3_hog_row
                FROM {quote_identifier(relation)}
                WHERE primary_group_id IS NOT NULL
                  AND starts_with(
                      trim(CAST(primary_group_id AS VARCHAR)), 'N0.HOG'
                  )
                  AND TRY_CAST({quote_identifier(rank_column)} AS BIGINT)
                      IS NOT NULL
                  {eligibility_filter}
            )
            WHERE _e3_hog_row = 1
        ), top_hogs AS (
            SELECT * FROM ranked_source
            ORDER BY TRY_CAST({quote_identifier(rank_column)} AS BIGINT),
                     CAST(primary_group_id AS VARCHAR)
            LIMIT {int(maximum_hogs)}
        ), {representatives}
        SELECT t.*,
               coalesce(h.human_hog_representatives, '')
                   AS human_hog_representatives,
               coalesce(h.arabidopsis_hog_representatives, '')
                   AS arabidopsis_hog_representatives,
               coalesce(h.rice_hog_representatives, '')
                   AS rice_hog_representatives,
               coalesce(h.barley_hog_representatives, '')
                   AS barley_hog_representatives
        FROM top_hogs t
        LEFT JOIN hog_representatives h
          ON h.hog_id = CAST(t.primary_group_id AS VARCHAR)
        ORDER BY TRY_CAST(t.{quote_identifier(rank_column)} AS BIGINT),
                 CAST(t.primary_group_id AS VARCHAR)
    """
    try:
        result = connection.execute(query).fetchdf()
    except duckdb.Error as exc:
        LOGGER.exception(
            "Could not collect pre-structure ranked HOGs from %s",
            relation,
        )
        raise AppError(f"Could not collect pre-structure ranked HOGs: {exc}") from exc
    LOGGER.info(
        "Collected %s independent structural-review HOGs from %s passes_only=%s",
        len(result),
        relation,
        passes_only,
    )
    return result
