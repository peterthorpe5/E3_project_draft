"""Configurable evolutionary-group threshold evaluation in DuckDB.

The explorer only re-evaluates evidence already stored in the completed
resource. It never reruns domain, expression, pocket or structural analyses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Literal, Mapping, Sequence

import duckdb
import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError

ThresholdMode = Literal["prestructure", "structural"]
ResultScope = Literal["passing", "pass_near", "all"]

THRESHOLD_RELATION_PREFERENCE = (
    "final_evolutionary_candidate_prioritisation",
    "candidate_master_results",
    "final_candidate_prioritisation",
    "prestructure_ranking",
)


@dataclass(frozen=True)
class ThresholdSettings:
    """Validated settings matching the completed grant-aligned defaults."""

    target_species_fraction: float = 0.90
    mandatory_species_fraction: float = 1.00
    domain_species_fraction: float = 0.80
    expression_species_fraction: float = 0.80
    structural_species_fraction: float = 0.75
    minimum_druggability_score: float = 0.50
    require_domain_evidence: bool = True
    require_expression_evidence: bool = True
    require_conserved_region: bool = True
    require_all_member_mapping: bool = True
    require_strict_3d: bool = True
    include_not_assessed: bool = False
    mode: ThresholdMode = "prestructure"
    result_scope: ResultScope = "passing"


NUMERIC_THRESHOLD_FIELDS = (
    "target_species_fraction",
    "mandatory_species_fraction",
    "domain_species_fraction",
    "expression_species_fraction",
    "structural_species_fraction",
    "minimum_druggability_score",
)

LOGICAL_THRESHOLD_FIELDS = (
    "require_domain_evidence",
    "require_expression_evidence",
    "require_conserved_region",
    "require_all_member_mapping",
    "require_strict_3d",
    "include_not_assessed",
)


def validate_threshold_settings(settings: ThresholdSettings) -> ThresholdSettings:
    """Validate threshold ranges and categorical options.

    Args:
        settings: Candidate threshold settings.

    Returns:
        The validated immutable settings.

    Raises:
        AppError: If any setting is outside its supported domain.
    """
    for field in NUMERIC_THRESHOLD_FIELDS:
        value = getattr(settings, field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AppError(f"{field} must be a number from 0 to 1")
        if not 0.0 <= float(value) <= 1.0:
            raise AppError(f"{field} must be a number from 0 to 1")
    for field in LOGICAL_THRESHOLD_FIELDS:
        if not isinstance(getattr(settings, field), bool):
            raise AppError(f"{field} must be true or false")
    if settings.mode not in ("prestructure", "structural"):
        raise AppError("mode must be prestructure or structural")
    if settings.result_scope not in ("passing", "pass_near", "all"):
        raise AppError("result_scope must be passing, pass_near or all")
    return settings


def threshold_settings_from_mapping(
    values: Mapping[str, object],
    defaults: ThresholdSettings | None = None,
) -> ThresholdSettings:
    """Create complete settings from named values.

    Args:
        values: Named overrides, typically supplied by Streamlit controls.
        defaults: Optional baseline settings.

    Returns:
        Validated settings.

    Raises:
        AppError: If an unknown or invalid setting is supplied.
    """
    baseline = defaults or ThresholdSettings()
    unknown = set(values).difference(asdict(baseline))
    if unknown:
        raise AppError(f"Unknown threshold settings: {', '.join(sorted(unknown))}")
    try:
        settings = replace(baseline, **values)
    except TypeError as exc:
        raise AppError(f"Could not build threshold settings: {exc}") from exc
    return validate_threshold_settings(settings)


def select_threshold_relation(relations: Sequence[str]) -> str | None:
    """Choose the best available relation for evolutionary-group decisions.

    Args:
        relations: Available DuckDB relation names.

    Returns:
        The preferred relation, or ``None`` when no supported source exists.
    """
    return next(
        (name for name in THRESHOLD_RELATION_PREFERENCE if name in relations),
        None,
    )


def group_source_sql(relation: str, available: Sequence[str]) -> str:
    """Return a one-row-per-evolutionary-group source expression.

    The authoritative final evolutionary relation is already group-level.
    Compatibility sources are deterministically deduplicated when group keys
    are present.

    Args:
        relation: Valid relation name.
        available: Columns available in the relation.

    Returns:
        A quoted SQL relation or subquery expression.
    """
    source = quote_identifier(relation)
    if relation == "final_evolutionary_candidate_prioritisation":
        return source
    columns = set(available)
    if "primary_group_id" not in columns:
        return source
    partition = ["primary_group_id"]
    if "primary_group_type" in columns:
        partition.insert(0, "primary_group_type")
    order_columns = [
        column
        for column in (
            "final_evolutionary_rank",
            "final_rank",
            "computational_rank",
            "prestructure_evolutionary_group_rank",
            "cluster_id",
        )
        if column in columns
    ]
    if not order_columns:
        order_columns = ["primary_group_id"]
    partition_sql = ", ".join(quote_identifier(column) for column in partition)
    order_sql = ", ".join(quote_identifier(column) for column in order_columns)
    return (
        "(SELECT * EXCLUDE (_e3_group_row) FROM ("
        f"SELECT *, ROW_NUMBER() OVER (PARTITION BY {partition_sql} "
        f"ORDER BY {order_sql}) AS _e3_group_row FROM {source} "
        "WHERE COALESCE(CAST(primary_group_id AS VARCHAR), '') <> ''"
        ") WHERE _e3_group_row = 1)"
    )


def _numeric_gate(column: str, threshold: float, available: set[str]) -> str:
    """Return SQL for a required numeric minimum gate."""
    if column not in available:
        return "FALSE"
    return (
        f"COALESCE(TRY_CAST({quote_identifier(column)} AS DOUBLE), 0.0) "
        f">= {float(threshold):.12g}"
    )


def _evidence_gate(
    candidates: Sequence[str],
    required: bool,
    available: set[str],
) -> str:
    """Return SQL requiring a non-zero evidence count when enabled."""
    if not required:
        return "TRUE"
    selected = next((column for column in candidates if column in available), None)
    if selected is None:
        return "FALSE"
    return f"COALESCE(TRY_CAST({quote_identifier(selected)} AS DOUBLE), 0.0) > 0"


def _boolean_gate(column: str, required: bool, available: set[str]) -> str:
    """Return SQL for an optional stored boolean gate."""
    if not required:
        return "TRUE"
    if column not in available:
        return "FALSE"
    return f"COALESCE(TRY_CAST({quote_identifier(column)} AS BOOLEAN), FALSE)"


def _status_gate(
    column: str,
    status: str,
    required: bool,
    available: set[str],
) -> str:
    """Return SQL for an optional exact status gate."""
    if not required:
        return "TRUE"
    if column not in available:
        return "FALSE"
    safe_status = status.replace("'", "''")
    return (
        f"COALESCE(CAST({quote_identifier(column)} AS VARCHAR), '') "
        f"= '{safe_status}'"
    )


def build_threshold_evaluation_cte(
    relation: str,
    available: Sequence[str],
    settings: ThresholdSettings,
) -> str:
    """Build SQL common table expressions for configurable gate evaluation.

    Args:
        relation: Candidate relation name.
        available: Available candidate columns.
        settings: Validated threshold settings.

    Returns:
        SQL CTE prefix ending in the ``classified`` relation.
    """
    values = validate_threshold_settings(settings)
    columns = set(available)
    source = group_source_sql(relation, available)
    gates = {
        "target_species": _numeric_gate(
            "target_species_fraction", values.target_species_fraction, columns
        ),
        "mandatory_species": _numeric_gate(
            "mandatory_species_fraction", values.mandatory_species_fraction, columns
        ),
        "domain_evidence": _evidence_gate(
            ("domain_assessed_species_count", "domain_evidence_row_count"),
            values.require_domain_evidence,
            columns,
        ),
        "domain_species": _numeric_gate(
            "domain_species_fraction", values.domain_species_fraction, columns
        ),
        "expression_evidence": _evidence_gate(
            ("expression_assessed_species_count", "expression_evidence_row_count"),
            values.require_expression_evidence,
            columns,
        ),
        "expression_species": _numeric_gate(
            "expression_species_fraction",
            values.expression_species_fraction,
            columns,
        ),
        "conserved_region": _status_gate(
            "conservation_status",
            "CONSERVED_REGION_SUPPORTED",
            values.require_conserved_region,
            columns,
        ),
        "druggability": _numeric_gate(
            "minimum_druggability_score",
            values.minimum_druggability_score,
            columns,
        ),
        "all_member_mapping": _boolean_gate(
            "all_assessed_members_pass_mapping",
            values.require_all_member_mapping,
            columns,
        ),
        "structural_species": _numeric_gate(
            "structural_species_fraction",
            values.structural_species_fraction,
            columns,
        ),
        "strict_3d": _status_gate(
            "three_dimensional_alignment_status",
            "CONSERVED_3D_POCKET_SUPPORTED",
            values.require_strict_3d,
            columns,
        ),
    }
    structural_assessed = "FALSE"
    if "three_dimensional_alignment_status" in columns:
        structural_assessed = (
            "COALESCE(CAST(three_dimensional_alignment_status AS VARCHAR), "
            "'NOT_ASSESSED') <> 'NOT_ASSESSED'"
        )
    recorded_druggability = _boolean_gate(
        "all_assessed_members_pass_druggability", True, columns
    )
    prestructure_names = (
        "target_species",
        "mandatory_species",
        "domain_evidence",
        "domain_species",
        "expression_evidence",
        "expression_species",
    )
    prestructure_pass = " AND ".join(gates[name] for name in prestructure_names)
    prestructure_failures = " + ".join(
        f"CAST(NOT custom_{name}_pass AS INTEGER)" for name in prestructure_names
    )
    structural_names = (
        "conserved_region",
        "druggability",
        "all_member_mapping",
        "structural_species",
        "strict_3d",
    )
    structural_pass = " AND ".join(
        ["custom_prestructure_pass", "custom_structural_assessed"]
        + [f"custom_{name}_pass" for name in structural_names]
    )
    structural_failures = " + ".join(
        ["CAST(NOT custom_prestructure_pass AS INTEGER)"]
        + [f"CAST(NOT custom_{name}_pass AS INTEGER)" for name in structural_names]
    )
    status_sql = (
        "CASE WHEN custom_prestructure_pass THEN 'PASS' "
        f"WHEN ({prestructure_failures}) = 1 THEN 'NEAR_MISS' ELSE 'FAIL' END"
    )
    if values.mode == "structural":
        status_sql = (
            "CASE WHEN NOT custom_structural_assessed THEN "
            "'NOT_STRUCTURALLY_ASSESSED' "
            "WHEN custom_structural_pass THEN 'PASS' "
            f"WHEN ({structural_failures}) = 1 THEN 'NEAR_MISS' "
            "ELSE 'FAIL' END"
        )
    gate_sql = ", ".join(
        f"{expression} AS custom_{name}_pass" for name, expression in gates.items()
    )
    return (
        f"WITH source_rows AS (SELECT * FROM {source}), "
        f"evaluated AS (SELECT *, {gate_sql}, "
        f"{structural_assessed} AS custom_structural_assessed, "
        f"{recorded_druggability} "
        "AS recorded_original_all_member_druggability_pass "
        "FROM source_rows), "
        f"prestructure_decisions AS (SELECT *, ({prestructure_pass}) "
        "AS custom_prestructure_pass FROM evaluated), "
        f"structural_decisions AS (SELECT *, ({structural_pass}) "
        "AS custom_structural_pass FROM prestructure_decisions), "
        f"classified AS (SELECT *, {status_sql} AS custom_status "
        "FROM structural_decisions) "
    )


def threshold_result_columns(
    available: Sequence[str],
    mode: ThresholdMode,
) -> list[str]:
    """Return expanded decision and biological evidence columns.

    Args:
        available: Source relation columns.
        mode: Pre-structure or structurally informed mode.

    Returns:
        Ordered available source columns.
    """
    shared = (
        "final_evolutionary_rank",
        "prestructure_evolutionary_group_rank",
        "evolutionary_group_key",
        "primary_group_type",
        "primary_group_id",
        "lead_cluster_id",
        "cluster_id",
        "contributing_deepclust_cluster_count",
        "contributing_deepclust_cluster_ids",
        "candidate_accession_count",
        "candidate_accessions",
        "orthofinder_orthogroup_ids",
        "orthofinder_hierarchical_group_ids",
        "orthofinder_group_member_count",
        "orthofinder_group_species_count",
        "prestructure_score",
        "best_prestructure_score",
        "mean_prestructure_score",
        "evidence_completeness_fraction",
        "target_species_count",
        "target_species_total",
        "target_species_fraction",
        "target_species_present",
        "target_species_missing",
        "mandatory_species_count",
        "mandatory_species_total",
        "mandatory_species_fraction",
        "mandatory_species_missing",
        "domain_supported_species_count",
        "domain_assessed_species_count",
        "domain_annotation_coverage_fraction",
        "domain_species_fraction",
        "domain_supported_species",
        "domain_annotated_negative_species",
        "domain_unavailable_species",
        "expression_supported_species_count",
        "expression_assessed_species_count",
        "expression_evidence_coverage_fraction",
        "expression_species_fraction",
        "expression_supported_species",
        "expression_assessed_negative_species",
        "expression_unavailable_species",
        "grant_aligned_prestructure_pass",
        "grant_aligned_criteria_status",
        "inclusion_reasons",
        "exclusion_reasons",
        "missing_evidence",
    )
    structural = (
        "final_rank",
        "recommendation_status",
        "grant_aligned_prediction_status",
        "final_score",
        "structural_score",
        "ligandability_score",
        "pocket_conservation_score",
        "three_dimensional_pocket_score",
        "selected_pocket_count",
        "structural_species_fraction",
        "minimum_druggability_score",
        "all_assessed_members_pass_druggability",
        "all_assessed_members_pass_mapping",
        "mean_pocket_plddt_fraction",
        "predictor_agreement_fraction",
        "conservation_status",
        "mean_pairwise_region_overlap",
        "mean_chemical_group_conservation",
        "three_dimensional_position_status",
        "three_dimensional_alignment_status",
        "mean_minimum_tm_score",
        "mean_pocket_overlap_fraction",
        "median_centroid_distance_angstrom",
        "mean_structural_residue_match_fraction",
        "mean_structural_residue_identity_fraction",
        "mean_structural_chemical_group_conservation",
        "grant_aligned_base_pass",
        "grant_aligned_final_pass",
        "structural_exclusion_reasons",
    )
    preferred = shared + structural if mode == "structural" else shared
    selected = [column for column in preferred if column in available]
    return list(dict.fromkeys(selected)) or list(available[:30])


def build_threshold_result_query(
    relation: str,
    available: Sequence[str],
    settings: ThresholdSettings,
    max_rows: int,
) -> str:
    """Build one bounded, ordered threshold-explorer query.

    Args:
        relation: Candidate relation name.
        available: Relation columns.
        settings: Validated threshold settings.
        max_rows: Hard result-row limit.

    Returns:
        Executable DuckDB SQL.
    """
    values = validate_threshold_settings(settings)
    if not 1 <= max_rows <= 10_000:
        raise AppError("maximum threshold rows must be between 1 and 10000")
    source_columns = threshold_result_columns(available, values.mode)
    selected_sql = ", ".join(quote_identifier(column) for column in source_columns)
    gate_columns = [
        "custom_prestructure_pass",
        "custom_structural_pass",
        "custom_structural_assessed",
        "custom_target_species_pass",
        "custom_mandatory_species_pass",
        "custom_domain_evidence_pass",
        "custom_domain_species_pass",
        "custom_expression_evidence_pass",
        "custom_expression_species_pass",
    ]
    if values.mode == "structural":
        gate_columns.extend(
            [
                "custom_conserved_region_pass",
                "custom_druggability_pass",
                "recorded_original_all_member_druggability_pass",
                "custom_all_member_mapping_pass",
                "custom_structural_species_pass",
                "custom_strict_3d_pass",
            ]
        )
    result_filter = {
        "passing": "custom_status = 'PASS'",
        "pass_near": "custom_status IN ('PASS', 'NEAR_MISS')",
        "all": "TRUE",
    }[values.result_scope]
    if values.mode == "structural":
        if values.include_not_assessed:
            result_filter = (
                f"({result_filter} OR custom_status = 'NOT_STRUCTURALLY_ASSESSED')"
            )
        else:
            result_filter = (
                f"({result_filter} AND custom_status <> 'NOT_STRUCTURALLY_ASSESSED')"
            )
    columns = set(available)
    score_column = next(
        (
            column
            for column in (
                "final_score" if values.mode == "structural" else "prestructure_score",
                "best_prestructure_score",
                "mean_prestructure_score",
            )
            if column in columns
        ),
        None,
    )
    score_order = ""
    if score_column:
        score_order = (
            f", COALESCE(TRY_CAST({quote_identifier(score_column)} AS DOUBLE), 0.0) DESC"
        )
    metadata = ", ".join(
        [f"'{values.mode}' AS threshold_mode"]
        + [
            f"{float(getattr(values, field)):.12g} AS threshold_{field}"
            for field in NUMERIC_THRESHOLD_FIELDS
        ]
        + [
            f"{str(getattr(values, field)).upper()} AS threshold_{field}"
            for field in LOGICAL_THRESHOLD_FIELDS[:-1]
        ]
    )
    cte = build_threshold_evaluation_cte(relation, available, values)
    return (
        f"{cte}SELECT ROW_NUMBER() OVER (ORDER BY CASE custom_status "
        "WHEN 'PASS' THEN 0 WHEN 'NEAR_MISS' THEN 1 "
        "WHEN 'NOT_STRUCTURALLY_ASSESSED' THEN 2 ELSE 3 END"
        f"{score_order}) AS custom_list_rank, custom_status, "
        f"{', '.join(gate_columns)}, {metadata}, {selected_sql} "
        f"FROM classified WHERE {result_filter} "
        f"ORDER BY custom_list_rank LIMIT {max_rows}"
    )


def build_threshold_summary_query(
    relation: str,
    available: Sequence[str],
    settings: ThresholdSettings,
) -> str:
    """Build compact summary-count SQL for active thresholds."""
    cte = build_threshold_evaluation_cte(relation, available, settings)
    return (
        f"{cte}SELECT COUNT(*) AS evaluated_count, "
        "SUM(CASE WHEN custom_status = 'PASS' THEN 1 ELSE 0 END) AS pass_count, "
        "SUM(CASE WHEN custom_status = 'NEAR_MISS' THEN 1 ELSE 0 END) "
        "AS near_miss_count, "
        "SUM(CASE WHEN custom_structural_assessed THEN 1 ELSE 0 END) "
        "AS structurally_assessed_count, "
        "SUM(CASE WHEN custom_status = 'NOT_STRUCTURALLY_ASSESSED' "
        "THEN 1 ELSE 0 END) AS not_structurally_assessed_count "
        "FROM classified"
    )


def evaluate_thresholds(
    connection: duckdb.DuckDBPyConnection,
    settings: ThresholdSettings,
    max_rows: int,
) -> tuple[str, pd.DataFrame, dict[str, int]]:
    """Evaluate active thresholds inside DuckDB.

    Args:
        connection: Open read-only resource connection.
        settings: Active threshold settings.
        max_rows: Maximum returned candidate rows.

    Returns:
        Selected relation, candidate data frame and summary counts.

    Raises:
        AppError: If no supported candidate relation exists or SQL fails.
    """
    relation = select_threshold_relation(list_relations(connection))
    if relation is None:
        raise AppError("No supported evolutionary-group candidate relation is available")
    available = relation_columns(connection, relation)
    try:
        result = connection.execute(
            build_threshold_result_query(relation, available, settings, max_rows)
        ).fetchdf()
        summary_row = connection.execute(
            build_threshold_summary_query(relation, available, settings)
        ).fetchone()
    except duckdb.Error as exc:
        raise AppError(f"Could not evaluate candidate thresholds: {exc}") from exc
    summary_columns = (
        "evaluated_count",
        "pass_count",
        "near_miss_count",
        "structurally_assessed_count",
        "not_structurally_assessed_count",
    )
    summary = {
        name: int(value or 0) for name, value in zip(summary_columns, summary_row)
    }
    return relation, result, summary
