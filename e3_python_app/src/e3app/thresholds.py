"""Configurable evolutionary-group threshold evaluation in DuckDB.

The explorer only re-evaluates evidence already stored in the completed
resource. It never reruns domain, expression, pocket or structural analyses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import logging
from typing import Literal, Mapping, Sequence

import duckdb
import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)

ThresholdMode = Literal["prestructure", "structural"]
ResultScope = Literal["passing", "pass_near", "all"]

RECORDED_MINIMUM_DRUGGABILITY_SCORE = 0.50

FINAL_DRUGGABILITY_REQUIRED_COLUMNS = (
    "target_species_fraction",
    "mandatory_species_fraction",
    "domain_species_fraction",
    "expression_species_fraction",
    "structural_species_fraction",
    "minimum_druggability_score",
    "all_assessed_members_pass_mapping",
    "conservation_status",
    "three_dimensional_alignment_status",
)

FINAL_DRUGGABILITY_EVIDENCE_COLUMN_FAMILIES = (
    ("domain_assessed_species_count", "domain_evidence_row_count"),
    ("expression_assessed_species_count", "expression_evidence_row_count"),
)

FINAL_DRUGGABILITY_IDENTITY_COLUMN_GROUPS = (
    ("evolutionary_group_key",),
    ("primary_group_type", "primary_group_id"),
    ("primary_group_id",),
    ("lead_cluster_id",),
    ("cluster_id",),
)

THRESHOLD_RELATION_PREFERENCE = (
    "final_evolutionary_candidate_prioritisation",
    "candidate_master_results",
    "final_candidate_prioritisation",
    "prestructure_ranking",
)

MEMBER_DRUGGABILITY_RELATION_PREFERENCE = (
    "selected_pockets",
    "ranked_member_pockets",
)

THRESHOLD_HOG_TEXT_COLUMNS = (
    "human_hog_representatives",
    "arabidopsis_hog_representatives",
    "human_hog_accessions",
    "human_hog_entries",
    "human_hog_raw_identifiers",
    "arabidopsis_hog_accessions",
    "arabidopsis_hog_entries",
    "arabidopsis_hog_raw_identifiers",
    "hog_species_present",
    "hog_orthogroup_ids",
    "hog_gene_tree_parent_clades",
    "hog_review_statuses",
    "hog_mapping_statuses",
)
THRESHOLD_HOG_COUNT_COLUMNS = (
    "hog_member_count",
    "hog_species_count",
    "hog_human_member_count",
    "hog_arabidopsis_member_count",
)
THRESHOLD_HOG_ANNOTATION_COLUMNS = (
    *THRESHOLD_HOG_TEXT_COLUMNS,
    *THRESHOLD_HOG_COUNT_COLUMNS,
    "hog_membership_available",
)


@dataclass(frozen=True)
class ThresholdSettings:
    """Validated settings matching the completed grant-aligned defaults."""

    target_species_fraction: float = 0.90
    mandatory_species_fraction: float = 1.00
    domain_species_fraction: float = 0.80
    expression_species_fraction: float = 0.80
    structural_species_fraction: float = 0.75
    minimum_druggability_score: float = RECORDED_MINIMUM_DRUGGABILITY_SCORE
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


def paired_threshold_settings(
    *,
    values: Mapping[str, object],
    defaults: ThresholdSettings | None = None,
) -> tuple[ThresholdSettings, ThresholdSettings]:
    """Build matched pre-structure and structural explorer settings.

    Both settings retain the same thresholds and result scope; only their
    evaluation mode differs. A supplied ``mode`` value is deliberately ignored
    so a stale UI state cannot make the paired result sets inconsistent.

    Args:
        values: Shared named threshold overrides.
        defaults: Optional baseline settings.

    Returns:
        Pre-structure settings followed by structural settings.
    """
    shared_values = dict(values)
    shared_values.pop("mode", None)
    prestructure = threshold_settings_from_mapping(
        {**shared_values, "mode": "prestructure"},
        defaults=defaults,
    )
    structural = threshold_settings_from_mapping(
        {**shared_values, "mode": "structural"},
        defaults=defaults,
    )
    return prestructure, structural


def final_druggability_settings(
    *,
    minimum_druggability_score: float,
    result_scope: ResultScope = "passing",
) -> ThresholdSettings:
    """Return settings that vary only the final druggability threshold.

    Every other gate remains at the recorded production setting. The returned
    settings always use structural mode because the all-members druggability
    requirement is a structural-stage gate.

    Args:
        minimum_druggability_score: Inclusive minimum score required for every
            assessed member.
        result_scope: Candidate statuses to return from the evaluation query.

    Returns:
        Validated structural threshold settings.
    """
    return threshold_settings_from_mapping(
        {
            "minimum_druggability_score": minimum_druggability_score,
            "mode": "structural",
            "result_scope": result_scope,
        }
    )


def final_druggability_source_missing_columns(
    available: Sequence[str],
) -> list[str]:
    """Return missing fields needed for a valid final-gate sensitivity run.

    Args:
        available: Columns in the selected evolutionary-group relation.

    Returns:
        Missing fields or evidence-column alternatives. An empty list means
        that the relation can support the focused sensitivity analysis.
    """
    columns = set(available)
    missing = [
        column
        for column in FINAL_DRUGGABILITY_REQUIRED_COLUMNS
        if column not in columns
    ]
    for family in FINAL_DRUGGABILITY_EVIDENCE_COLUMN_FAMILIES:
        if not any(column in columns for column in family):
            missing.append(" or ".join(family))
    return missing


def _final_druggability_identity_columns(
    *,
    recorded_columns: Sequence[str],
    selected_columns: Sequence[str],
) -> tuple[str, ...]:
    """Choose stable identity columns shared by two pass lists."""
    shared = set(recorded_columns).intersection(selected_columns)
    for group in FINAL_DRUGGABILITY_IDENTITY_COLUMN_GROUPS:
        if set(group).issubset(shared):
            return group
    raise AppError(
        "Final-gate sensitivity results do not contain a stable candidate identity"
    )


def _final_druggability_identity_keys(
    *,
    frame: pd.DataFrame,
    columns: Sequence[str],
) -> pd.Series:
    """Build null-safe deterministic identity keys for candidate rows."""
    if frame.empty:
        return pd.Series(index=frame.index, dtype="string")
    values = frame.loc[:, list(columns)].astype("string").fillna("")
    return values.agg("\x1f".join, axis=1).astype("string")


def compare_final_druggability_passes(
    *,
    recorded: pd.DataFrame,
    selected: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Annotate a sensitivity pass list and identify entrants and leavers.

    Args:
        recorded: Groups passing every recorded gate at the authoritative 0.50
            minimum-member druggability threshold.
        selected: Groups passing the same gates at the selected threshold.

    Returns:
        A tuple containing the annotated selected pass list and a concise table
        of groups whose pass status differs from the recorded result.

    Raises:
        AppError: If either argument is not a data frame or no stable shared
            candidate identifier is available.
    """
    if not isinstance(recorded, pd.DataFrame) or not isinstance(
        selected, pd.DataFrame
    ):
        raise AppError("Final-gate pass lists must be pandas data frames")
    identity_columns = _final_druggability_identity_columns(
        recorded_columns=recorded.columns,
        selected_columns=selected.columns,
    )
    recorded_keys = _final_druggability_identity_keys(
        frame=recorded,
        columns=identity_columns,
    )
    selected_keys = _final_druggability_identity_keys(
        frame=selected,
        columns=identity_columns,
    )
    recorded_key_set = set(recorded_keys.tolist())
    selected_key_set = set(selected_keys.tolist())

    annotated = selected.copy()
    annotated.insert(
        min(2, len(annotated.columns)),
        "sensitivity_change",
        [
            "RECORDED_PASS"
            if key in recorded_key_set
            else "ENTERS_AT_SELECTED_THRESHOLD"
            for key in selected_keys
        ],
    )

    entering = annotated.loc[
        annotated["sensitivity_change"] == "ENTERS_AT_SELECTED_THRESHOLD"
    ].copy()
    leaving = recorded.loc[~recorded_keys.isin(selected_key_set)].copy()
    leaving.insert(
        min(2, len(leaving.columns)),
        "sensitivity_change",
        "LEAVES_AT_SELECTED_THRESHOLD",
    )
    changes = pd.concat([entering, leaving], ignore_index=True, sort=False)
    concise_columns = [
        column
        for column in (
            "sensitivity_change",
            "final_evolutionary_rank",
            "final_rank",
            *identity_columns,
            "lead_cluster_id",
            "candidate_accessions",
            "minimum_druggability_score",
            "final_score",
        )
        if column in changes.columns
    ]
    return annotated, changes.loc[:, list(dict.fromkeys(concise_columns))]


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


def select_member_druggability_relation(relations: Sequence[str]) -> str | None:
    """Choose the best member-level selected-pocket relation.

    Args:
        relations: Available DuckDB relation names.

    Returns:
        Preferred relation, or ``None`` when member-level pocket scores are not
        available.
    """
    return next(
        (
            name
            for name in MEMBER_DRUGGABILITY_RELATION_PREFERENCE
            if name in relations
        ),
        None,
    )


def collect_member_druggability_scores(
    *,
    connection: duckdb.DuckDBPyConnection,
    cluster_ids: Sequence[str],
    max_rows: int = 10_000,
) -> tuple[str, pd.DataFrame]:
    """Collect selected-pocket druggability values for lead clusters.

    The preferred ``selected_pockets`` relation already contains one retained
    pocket per assessed member. A ranked-pocket fallback is accepted only when
    it contains an explicit selection-rank or selected-for-scoring field, so
    alternative pockets cannot be silently mixed into the strict distribution.

    Args:
        connection: Open read-only resource connection.
        cluster_ids: Exact lead DeepClust identifiers to include.
        max_rows: Hard result-row limit.

    Returns:
        Selected relation name and standardised member-level score rows.

    Raises:
        AppError: If inputs are invalid or no safe member-level score relation
            is available.
    """
    if not 1 <= max_rows <= 100_000:
        raise AppError("maximum member druggability rows must be between 1 and 100000")
    identifiers = list(
        dict.fromkeys(
            str(value).strip() for value in cluster_ids if str(value).strip()
        )
    )
    if not identifiers:
        return "", pd.DataFrame(
            columns=(
                "cluster_id",
                "member_accession",
                "species",
                "pocket_number",
                "druggability_score",
            )
        )
    if len(identifiers) > 2_000:
        raise AppError("member druggability query accepts at most 2000 clusters")
    relation = select_member_druggability_relation(list_relations(connection))
    if relation is None:
        raise AppError("No member-level selected-pocket druggability relation is available")
    available = set(relation_columns(connection, relation))
    required = {"cluster_id", "druggability_score"}
    missing = sorted(required.difference(available))
    if missing:
        raise AppError(
            f"{relation} is missing member druggability fields: "
            + ", ".join(missing)
        )
    accession_column = next(
        (
            column
            for column in (
                "member_accession",
                "candidate_accession",
                "parsed_accession",
                "accession",
            )
            if column in available
        ),
        None,
    )
    if accession_column is None:
        raise AppError(f"{relation} has no recognised member accession field")

    selection_filter = "TRUE"
    if relation == "ranked_member_pockets":
        if "selection_rank" in available:
            selection_filter = "TRY_CAST(selection_rank AS INTEGER) = 1"
        elif "pocket_rank" in available:
            selection_filter = "TRY_CAST(pocket_rank AS INTEGER) = 1"
        elif "selected_for_scoring" in available:
            selection_filter = (
                "COALESCE(TRY_CAST(selected_for_scoring AS BOOLEAN), FALSE)"
            )
        else:
            raise AppError(
                "ranked_member_pockets lacks a safe rank-one selection field"
            )

    species_sql = (
        "COALESCE(NULLIF(trim(CAST(species_column AS VARCHAR)), ''), 'Unknown')"
        if "species_column" in available
        else "'Unknown'"
    )
    pocket_sql = (
        "TRY_CAST(pocket_number AS INTEGER)"
        if "pocket_number" in available
        else "NULL::INTEGER"
    )
    placeholders = ", ".join("?" for _ in identifiers)
    query = (
        "SELECT CAST(cluster_id AS VARCHAR) AS cluster_id, "
        f"CAST({quote_identifier(accession_column)} AS VARCHAR) "
        "AS member_accession, "
        f"{species_sql} AS species, {pocket_sql} AS pocket_number, "
        "TRY_CAST(druggability_score AS DOUBLE) AS druggability_score "
        f"FROM {quote_identifier(relation)} WHERE "
        f"CAST(cluster_id AS VARCHAR) IN ({placeholders}) "
        "AND TRY_CAST(druggability_score AS DOUBLE) BETWEEN 0.0 AND 1.0 "
        f"AND ({selection_filter}) "
        "ORDER BY cluster_id, member_accession "
        f"LIMIT {int(max_rows)}"
    )
    try:
        frame = connection.execute(query, identifiers).fetchdf()
    except duckdb.Error as exc:
        raise AppError(f"Could not collect member druggability scores: {exc}") from exc
    return relation, frame


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
        "stringent_rank",
        "structurally_supported_rank",
        "boss_review_status",
        "evolutionary_group_key",
        "primary_group_type",
        "primary_group_id",
        "lead_cluster_id",
        "lead_computational_rank",
        "cluster_id",
        "contributing_deepclust_cluster_count",
        "contributing_deepclust_cluster_ids",
        "candidate_accession_count",
        "candidate_accessions",
        "alternative_group_count",
        "orthofinder_orthogroup_ids",
        "orthofinder_hierarchical_group_ids",
        "orthofinder_group_member_count",
        "orthofinder_group_species_count",
        "prestructure_score",
        "best_prestructure_score",
        "mean_prestructure_score",
        "minimum_prestructure_score",
        "discovery_score",
        "orthology_score",
        "domain_score",
        "expression_score",
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
        "domain_unavailable_species_count",
        "domain_annotation_coverage_fraction",
        "domain_species_fraction",
        "domain_supported_species",
        "domain_annotated_negative_species",
        "domain_unavailable_species",
        "expression_supported_species_count",
        "expression_available_species_count",
        "expression_assessed_species_count",
        "expression_unavailable_species_count",
        "expression_evidence_coverage_fraction",
        "expression_species_fraction",
        "expression_supported_species",
        "expression_assessed_negative_species",
        "expression_unavailable_species",
        "reviewed_seed_fraction",
        "ubiquitin_go_positive_seed_fraction",
        "exclusion_flag_fraction",
        "discovery_known_e3_sequence_count",
        "discovery_known_e3_seed_count",
        "discovery_known_e3_seed_ids",
        "discovery_matched_seed_sequence_count",
        "discovery_matched_seed_id_count",
        "discovery_matched_seed_ids_calculated",
        "discovery_seed_categories",
        "discovery_seed_review_statuses",
        "discovery_seed_ubiquitin_go_statuses",
        "discovery_seed_organisms",
        "discovery_seed_protein_names",
        "discovery_reviewed_seed_count",
        "discovery_ubiquitin_go_positive_seed_count",
        "discovery_seed_with_exclusion_go_term_count",
        "discovery_raw_member_count",
        "discovery_strict_member_count",
        "discovery_strict_nonseed_candidate_count",
        "discovery_strict_member_fraction",
        "discovery_strict_nonseed_fraction",
        "discovery_raw_species_count_calculated",
        "discovery_strict_species_count",
        "discovery_strict_onekp_species_count",
        "domain_evidence_row_count",
        "expression_evidence_row_count",
        "grant_aligned_prestructure_pass",
        "grant_aligned_stringent_pass",
        "grant_aligned_criteria_status",
        "computational_structure_selected",
        "inclusion_reasons",
        "exclusion_reasons",
        "missing_evidence",
        "profile_name",
        "interpretation",
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


def _threshold_membership_text_expression(
    *,
    available: set[str],
    column: str,
) -> str:
    """Return a nullable text expression for one membership field."""
    if column not in available:
        return "CAST(NULL AS VARCHAR)"
    return f"CAST({quote_identifier(column)} AS VARCHAR)"


def build_threshold_hog_annotation_query(
    *,
    membership_columns: Sequence[str],
    group_count: int,
) -> str:
    """Build a bounded root-HOG membership annotation query.

    Args:
        membership_columns: Available ``hierarchical_membership`` fields.
        group_count: Number of requested HOG identifiers and placeholders.

    Returns:
        Parameterised DuckDB SQL returning one annotation row per requested HOG.

    Raises:
        AppError: If required membership fields or the group count are invalid.
    """
    if not 1 <= group_count <= 10_000:
        raise AppError("threshold HOG group count must be between 1 and 10000")
    available = set(membership_columns)
    required = {"group_id", "species", "raw_identifier"}
    missing = sorted(required.difference(available))
    if missing:
        raise AppError(
            "hierarchical membership lacks fields: " + ", ".join(missing)
        )
    parsed_accession = _threshold_membership_text_expression(
        available=available,
        column="parsed_accession",
    )
    parsed_entry = _threshold_membership_text_expression(
        available=available,
        column="parsed_entry",
    )
    raw_identifier = "CAST(raw_identifier AS VARCHAR)"
    representative = (
        f"coalesce(nullif(trim({parsed_accession}), ''), "
        f"nullif(trim({parsed_entry}), ''), "
        f"nullif(trim({raw_identifier}), ''))"
    )
    orthogroup = _threshold_membership_text_expression(
        available=available,
        column="orthogroup_id",
    )
    parent = _threshold_membership_text_expression(
        available=available,
        column="gene_tree_parent_clade",
    )
    review = _threshold_membership_text_expression(
        available=available,
        column="review_status",
    )
    mapping = _threshold_membership_text_expression(
        available=available,
        column="mapping_status",
    )
    placeholders = ", ".join("?" for _ in range(group_count))
    return f"""
        WITH members AS (
            SELECT CAST(group_id AS VARCHAR) AS primary_group_id,
                   CAST(species AS VARCHAR) AS species,
                   {raw_identifier} AS raw_identifier,
                   {parsed_accession} AS parsed_accession,
                   {parsed_entry} AS parsed_entry,
                   {representative} AS representative,
                   {orthogroup} AS orthogroup_id,
                   {parent} AS gene_tree_parent_clade,
                   {review} AS review_status,
                   {mapping} AS mapping_status
            FROM hierarchical_membership
            WHERE CAST(group_id AS VARCHAR) IN ({placeholders})
        )
        SELECT primary_group_id,
               coalesce(string_agg(DISTINCT representative, ';'
                   ORDER BY representative) FILTER (
                       WHERE species = 'Homo_sapiens'
                         AND representative IS NOT NULL
                   ), '') AS human_hog_representatives,
               coalesce(string_agg(DISTINCT representative, ';'
                   ORDER BY representative) FILTER (
                       WHERE species = 'Arabidopsis_thaliana'
                         AND representative IS NOT NULL
                   ), '') AS arabidopsis_hog_representatives,
               coalesce(string_agg(DISTINCT parsed_accession, ';'
                   ORDER BY parsed_accession) FILTER (
                       WHERE species = 'Homo_sapiens'
                         AND nullif(trim(parsed_accession), '') IS NOT NULL
                   ), '') AS human_hog_accessions,
               coalesce(string_agg(DISTINCT parsed_entry, ';'
                   ORDER BY parsed_entry) FILTER (
                       WHERE species = 'Homo_sapiens'
                         AND nullif(trim(parsed_entry), '') IS NOT NULL
                   ), '') AS human_hog_entries,
               coalesce(string_agg(DISTINCT raw_identifier, ';'
                   ORDER BY raw_identifier) FILTER (
                       WHERE species = 'Homo_sapiens'
                   ), '') AS human_hog_raw_identifiers,
               coalesce(string_agg(DISTINCT parsed_accession, ';'
                   ORDER BY parsed_accession) FILTER (
                       WHERE species = 'Arabidopsis_thaliana'
                         AND nullif(trim(parsed_accession), '') IS NOT NULL
                   ), '') AS arabidopsis_hog_accessions,
               coalesce(string_agg(DISTINCT parsed_entry, ';'
                   ORDER BY parsed_entry) FILTER (
                       WHERE species = 'Arabidopsis_thaliana'
                         AND nullif(trim(parsed_entry), '') IS NOT NULL
                   ), '') AS arabidopsis_hog_entries,
               coalesce(string_agg(DISTINCT raw_identifier, ';'
                   ORDER BY raw_identifier) FILTER (
                       WHERE species = 'Arabidopsis_thaliana'
                   ), '') AS arabidopsis_hog_raw_identifiers,
               count(*) AS hog_member_count,
               count(DISTINCT species) AS hog_species_count,
               count(*) FILTER (WHERE species = 'Homo_sapiens')
                   AS hog_human_member_count,
               count(*) FILTER (WHERE species = 'Arabidopsis_thaliana')
                   AS hog_arabidopsis_member_count,
               coalesce(string_agg(DISTINCT species, ';' ORDER BY species), '')
                   AS hog_species_present,
               coalesce(string_agg(DISTINCT orthogroup_id, ';'
                   ORDER BY orthogroup_id) FILTER (
                       WHERE nullif(trim(orthogroup_id), '') IS NOT NULL
                   ), '') AS hog_orthogroup_ids,
               coalesce(string_agg(DISTINCT gene_tree_parent_clade, ';'
                   ORDER BY gene_tree_parent_clade) FILTER (
                       WHERE nullif(trim(gene_tree_parent_clade), '') IS NOT NULL
                   ), '') AS hog_gene_tree_parent_clades,
               coalesce(string_agg(DISTINCT review_status, ';'
                   ORDER BY review_status) FILTER (
                       WHERE nullif(trim(review_status), '') IS NOT NULL
                   ), '') AS hog_review_statuses,
               coalesce(string_agg(DISTINCT mapping_status, ';'
                   ORDER BY mapping_status) FILTER (
                       WHERE nullif(trim(mapping_status), '') IS NOT NULL
                   ), '') AS hog_mapping_statuses,
               TRUE AS hog_membership_available
        FROM members
        GROUP BY primary_group_id
    """


def _add_empty_threshold_hog_annotations(*, frame: pd.DataFrame) -> pd.DataFrame:
    """Add stable blank HOG annotation fields to a threshold result."""
    result = frame.copy()
    for column in THRESHOLD_HOG_TEXT_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    for column in THRESHOLD_HOG_COUNT_COLUMNS:
        if column not in result.columns:
            result[column] = 0
    if "hog_membership_available" not in result.columns:
        result["hog_membership_available"] = False
    return result


def enrich_threshold_results(
    *,
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Add human, Arabidopsis and HOG composition to threshold rows.

    Args:
        connection: Open read-only resource connection.
        frame: Bounded threshold result containing ``primary_group_id``.

    Returns:
        Threshold rows enriched from root-level membership when available.
    """
    result = _add_empty_threshold_hog_annotations(frame=frame)
    if frame.empty or "primary_group_id" not in frame.columns:
        return result
    if "hierarchical_membership" not in set(list_relations(connection)):
        return result
    groups = sorted(
        {
            str(value).strip()
            for value in frame["primary_group_id"].dropna().tolist()
            if str(value).strip()
        }
    )
    if not groups:
        return result
    membership_columns = relation_columns(connection, "hierarchical_membership")
    try:
        query = build_threshold_hog_annotation_query(
            membership_columns=membership_columns,
            group_count=len(groups),
        )
        annotations = connection.execute(query, groups).fetchdf()
    except (AppError, duckdb.Error) as exc:
        LOGGER.warning("Threshold HOG annotations are unavailable: %s", exc)
        return result
    new_columns = [
        column
        for column in THRESHOLD_HOG_ANNOTATION_COLUMNS
        if column not in frame.columns
    ]
    if not new_columns:
        return frame
    base = frame.copy()
    enriched = base.merge(
        annotations[["primary_group_id", *new_columns]],
        how="left",
        on="primary_group_id",
        validate="many_to_one",
    )
    for column in THRESHOLD_HOG_TEXT_COLUMNS:
        if column in enriched.columns:
            enriched[column] = enriched[column].fillna("")
    for column in THRESHOLD_HOG_COUNT_COLUMNS:
        if column in enriched.columns:
            enriched[column] = pd.to_numeric(
                enriched[column],
                errors="coerce",
            ).fillna(0).astype("Int64")
    if "hog_membership_available" in enriched.columns:
        enriched["hog_membership_available"] = (
            enriched["hog_membership_available"].fillna(False).astype(bool)
        )
    return enriched


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
        result = enrich_threshold_results(
            connection=connection,
            frame=result,
        )
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
