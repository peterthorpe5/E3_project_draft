"""Tests for evolutionary-group threshold sensitivity analysis."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from e3app.data import open_read_only
from e3app.errors import AppError
from e3app.thresholds import (
    RECORDED_MINIMUM_DRUGGABILITY_SCORE,
    ThresholdSettings,
    build_threshold_result_query,
    build_threshold_summary_query,
    collect_member_druggability_scores,
    compare_final_druggability_passes,
    evaluate_thresholds,
    final_druggability_settings,
    final_druggability_source_missing_columns,
    group_source_sql,
    paired_threshold_settings,
    select_member_druggability_relation,
    select_threshold_relation,
    threshold_result_columns,
    threshold_settings_from_mapping,
    validate_threshold_settings,
)


@pytest.fixture
def threshold_db(tmp_path: Path) -> Path:
    """Create a four-group structural sensitivity fixture."""
    path = tmp_path / "thresholds.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE final_evolutionary_candidate_prioritisation("
            "final_evolutionary_rank INTEGER, primary_group_type VARCHAR, "
            "primary_group_id VARCHAR, lead_cluster_id VARCHAR, "
            "target_species_fraction DOUBLE, mandatory_species_fraction DOUBLE, "
            "domain_assessed_species_count INTEGER, domain_species_fraction DOUBLE, "
            "expression_assessed_species_count INTEGER, "
            "expression_species_fraction DOUBLE, structural_species_fraction DOUBLE, "
            "minimum_druggability_score DOUBLE, "
            "all_assessed_members_pass_druggability BOOLEAN, "
            "all_assessed_members_pass_mapping BOOLEAN, conservation_status VARCHAR, "
            "three_dimensional_alignment_status VARCHAR, "
            "prestructure_score DOUBLE, final_score DOUBLE, "
            "candidate_accessions VARCHAR)"
        )
        connection.execute(
            "INSERT INTO final_evolutionary_candidate_prioritisation VALUES "
            "(1, 'HIERARCHICAL_ORTHOGROUP', 'N0.HOG0001', 'cluster_1', "
            "1, 1, 12, 1, 10, 1, 1, 0.7, true, true, "
            "'CONSERVED_REGION_SUPPORTED', 'CONSERVED_3D_POCKET_SUPPORTED', "
            "0.9, 0.9, 'P1;P2'), "
            "(2, 'HIERARCHICAL_ORTHOGROUP', 'N0.HOG0002', 'cluster_2', "
            "1, 1, 12, 1, 10, 1, 1, 0.325, false, true, "
            "'CONSERVED_REGION_SUPPORTED', 'CONSERVED_3D_POCKET_SUPPORTED', "
            "0.85, 0.8, 'P3;P4'), "
            "(3, 'HIERARCHICAL_ORTHOGROUP', 'N0.HOG0003', 'cluster_3', "
            "1, 1, 12, 1, 10, 0.6, 0, 0, false, false, "
            "'NO_STRUCTURAL_EVIDENCE', 'NOT_ASSESSED', 0.8, 0.6, 'P5'), "
            "(4, 'HIERARCHICAL_ORTHOGROUP', 'N0.HOG0004', 'cluster_4', "
            "1, 1, 12, 1, 10, 1, 0, 0, false, false, "
            "'NO_STRUCTURAL_EVIDENCE', 'NOT_ASSESSED', 0.75, 0.5, 'P6')"
        )
    return path


def test_threshold_defaults_and_validation() -> None:
    """Defaults match the completed run and invalid overrides fail clearly."""
    defaults = validate_threshold_settings(ThresholdSettings())
    assert defaults.target_species_fraction == 0.90
    assert defaults.mandatory_species_fraction == 1.00
    assert defaults.domain_species_fraction == 0.80
    assert defaults.expression_species_fraction == 0.80
    assert defaults.structural_species_fraction == 0.75
    assert defaults.minimum_druggability_score == 0.50
    assert RECORDED_MINIMUM_DRUGGABILITY_SCORE == 0.50
    assert defaults.require_strict_3d
    assert threshold_settings_from_mapping(
        {"mode": "structural", "minimum_druggability_score": 0.325}
    ).mode == "structural"
    with pytest.raises(AppError, match="Unknown"):
        threshold_settings_from_mapping({"not_a_setting": 1})
    with pytest.raises(AppError, match="0 to 1"):
        validate_threshold_settings(replace(defaults, target_species_fraction=1.1))
    with pytest.raises(AppError, match="0 to 1"):
        validate_threshold_settings(
            replace(defaults, target_species_fraction=True)  # type: ignore[arg-type]
        )
    with pytest.raises(AppError, match="true or false"):
        validate_threshold_settings(
            replace(defaults, require_strict_3d="yes")  # type: ignore[arg-type]
        )
    with pytest.raises(AppError, match="mode"):
        validate_threshold_settings(
            replace(defaults, mode="unknown")  # type: ignore[arg-type]
        )
    with pytest.raises(AppError, match="result_scope"):
        validate_threshold_settings(
            replace(defaults, result_scope="unknown")  # type: ignore[arg-type]
        )


def test_paired_threshold_settings_differ_only_by_mode() -> None:
    """Both displayed lists must use the same user-selected controls."""
    prestructure, structural = paired_threshold_settings(
        values={
            "mode": "structural",
            "target_species_fraction": 0.75,
            "minimum_druggability_score": 0.35,
            "result_scope": "pass_near",
        }
    )
    assert prestructure.mode == "prestructure"
    assert structural.mode == "structural"
    differing = {
        field
        for field in prestructure.__dataclass_fields__
        if getattr(prestructure, field) != getattr(structural, field)
    }
    assert differing == {"mode"}
    assert prestructure.target_species_fraction == 0.75
    assert structural.minimum_druggability_score == 0.35


def test_focused_final_druggability_settings_change_only_the_last_gate() -> None:
    """The recommendation slider retains every other recorded requirement."""
    recorded = final_druggability_settings(
        minimum_druggability_score=RECORDED_MINIMUM_DRUGGABILITY_SCORE
    )
    relaxed = final_druggability_settings(minimum_druggability_score=0.325)
    assert recorded.mode == relaxed.mode == "structural"
    assert recorded.result_scope == relaxed.result_scope == "passing"
    differing = {
        field
        for field in recorded.__dataclass_fields__
        if getattr(recorded, field) != getattr(relaxed, field)
    }
    assert differing == {"minimum_druggability_score"}


def test_focused_final_druggability_source_validation() -> None:
    """Compatibility sources cannot silently produce misleading zero passes."""
    complete = [
        "target_species_fraction",
        "mandatory_species_fraction",
        "domain_species_fraction",
        "expression_species_fraction",
        "structural_species_fraction",
        "minimum_druggability_score",
        "all_assessed_members_pass_mapping",
        "conservation_status",
        "three_dimensional_alignment_status",
        "domain_assessed_species_count",
        "expression_evidence_row_count",
    ]
    assert final_druggability_source_missing_columns(complete) == []
    missing = final_druggability_source_missing_columns(["primary_group_id"])
    assert "minimum_druggability_score" in missing
    assert "domain_assessed_species_count or domain_evidence_row_count" in missing


def test_threshold_relation_and_group_source_selection() -> None:
    """Evolutionary authority is preferred and fallbacks are deduplicated."""
    assert select_threshold_relation(
        [
            "candidate_master_results",
            "final_evolutionary_candidate_prioritisation",
        ]
    ) == "final_evolutionary_candidate_prioritisation"
    assert select_threshold_relation(["unrelated"]) is None
    assert select_member_druggability_relation(
        ["ranked_member_pockets", "selected_pockets"]
    ) == "selected_pockets"
    assert select_member_druggability_relation(["unrelated"]) is None
    final_source = group_source_sql(
        "final_evolutionary_candidate_prioritisation",
        ["primary_group_id"],
    )
    assert final_source == '"final_evolutionary_candidate_prioritisation"'
    fallback = group_source_sql(
        "candidate_master_results",
        ["primary_group_type", "primary_group_id", "final_rank"],
    )
    assert "ROW_NUMBER() OVER" in fallback
    assert "primary_group_type" in fallback
    raw = group_source_sql("candidate_master_results", ["cluster_id"])
    assert raw == '"candidate_master_results"'
    no_rank = group_source_sql(
        "candidate_master_results",
        ["primary_group_id"],
    )
    assert "ORDER BY \"primary_group_id\"" in no_rank


def test_collect_member_druggability_scores_prefers_selected_pockets(
    recommendation_threshold_db: Path,
) -> None:
    """Member-score collection is bounded and retains selected pockets only."""
    with open_read_only(recommendation_threshold_db) as connection:
        relation, rows = collect_member_druggability_scores(
            connection=connection,
            cluster_ids=("cluster_2", "cluster_1", "cluster_2", ""),
            max_rows=20,
        )
    assert relation == "selected_pockets"
    assert rows["cluster_id"].tolist() == [
        "cluster_1",
        "cluster_1",
        "cluster_2",
        "cluster_2",
    ]
    assert rows["druggability_score"].tolist() == [0.7, 0.9, 0.8, 0.325]
    with duckdb.connect(":memory:") as connection:
        relation, empty = collect_member_druggability_scores(
            connection=connection,
            cluster_ids=(),
        )
    assert relation == ""
    assert empty.empty


def test_ranked_member_pocket_fallback_requires_explicit_rank() -> None:
    """Alternative pockets cannot be mixed into final-gate distributions."""
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE ranked_member_pockets(cluster_id VARCHAR, "
            "member_accession VARCHAR, druggability_score DOUBLE, "
            "selection_rank INTEGER)"
        )
        connection.execute(
            "INSERT INTO ranked_member_pockets VALUES "
            "('c1', 'P1', 0.7, 1), ('c1', 'P1', 0.9, 2)"
        )
        relation, rows = collect_member_druggability_scores(
            connection=connection,
            cluster_ids=("c1",),
        )
        assert relation == "ranked_member_pockets"
        assert rows["druggability_score"].tolist() == [0.7]
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE ranked_member_pockets(cluster_id VARCHAR, "
            "member_accession VARCHAR, druggability_score DOUBLE)"
        )
        with pytest.raises(AppError, match="safe rank-one"):
            collect_member_druggability_scores(
                connection=connection,
                cluster_ids=("c1",),
            )


def test_member_druggability_collection_rejects_unsafe_sources() -> None:
    """Invalid limits, schemas and unselected alternatives fail explicitly."""
    with duckdb.connect(":memory:") as connection:
        with pytest.raises(AppError, match="between 1 and 100000"):
            collect_member_druggability_scores(
                connection=connection,
                cluster_ids=("c1",),
                max_rows=0,
            )
        with pytest.raises(AppError, match="at most 2000"):
            collect_member_druggability_scores(
                connection=connection,
                cluster_ids=tuple(f"c{index}" for index in range(2001)),
            )
        with pytest.raises(AppError, match="No member-level"):
            collect_member_druggability_scores(
                connection=connection,
                cluster_ids=("c1",),
            )
        connection.execute(
            "CREATE TABLE selected_pockets(cluster_id VARCHAR, "
            "candidate_accession VARCHAR)"
        )
        with pytest.raises(AppError, match="missing member druggability"):
            collect_member_druggability_scores(
                connection=connection,
                cluster_ids=("c1",),
            )
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE selected_pockets(cluster_id VARCHAR, "
            "druggability_score DOUBLE)"
        )
        with pytest.raises(AppError, match="no recognised member accession"):
            collect_member_druggability_scores(
                connection=connection,
                cluster_ids=("c1",),
            )


@pytest.mark.parametrize(
    ("rank_column", "rank_value"),
    (("pocket_rank", "1"), ("selected_for_scoring", "true")),
)
def test_ranked_member_pocket_fallback_accepts_safe_selection_fields(
    rank_column: str,
    rank_value: str,
) -> None:
    """Each explicit rank-one compatibility field is supported."""
    rank_type = "BOOLEAN" if rank_column == "selected_for_scoring" else "INTEGER"
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE ranked_member_pockets(cluster_id VARCHAR, "
            "member_accession VARCHAR, species_column VARCHAR, "
            "druggability_score DOUBLE, "
            f"{rank_column} {rank_type})"
        )
        connection.execute(
            "INSERT INTO ranked_member_pockets VALUES "
            f"('c1', 'P1', 'A', 0.7, {rank_value})"
        )
        _, rows = collect_member_druggability_scores(
            connection=connection,
            cluster_ids=("c1",),
        )
    assert rows.loc[0, "species"] == "A"
    assert pd.isna(rows.loc[0, "pocket_number"])


def test_threshold_sql_is_bounded_and_informative(threshold_db: Path) -> None:
    """Generated SQL records settings, gates and a hard row limit."""
    with open_read_only(threshold_db) as connection:
        available = [
            row[0]
            for row in connection.execute(
                "DESCRIBE final_evolutionary_candidate_prioritisation"
            ).fetchall()
        ]
        settings = ThresholdSettings(
            mode="structural",
            result_scope="pass_near",
            minimum_druggability_score=0.30,
        )
        query = build_threshold_result_query(
            "final_evolutionary_candidate_prioritisation",
            available,
            settings,
            25,
        )
        assert "custom_status" in query
        assert "threshold_minimum_druggability_score" in query
        assert "LIMIT 25" in query
        assert "recorded_original_all_member_druggability_pass" in query
        summary = build_threshold_summary_query(
            "final_evolutionary_candidate_prioritisation",
            available,
            settings,
        )
        assert "not_structurally_assessed_count" in summary
        assert "candidate_accessions" in threshold_result_columns(
            available, "structural"
        )
        assert threshold_result_columns(["odd"], "prestructure") == ["odd"]
        permissive = build_threshold_result_query(
            "final_evolutionary_candidate_prioritisation",
            available,
            ThresholdSettings(
                mode="structural",
                result_scope="all",
                require_domain_evidence=False,
                require_expression_evidence=False,
                require_conserved_region=False,
                require_all_member_mapping=False,
                require_strict_3d=False,
                include_not_assessed=True,
            ),
            25,
        )
        assert "OR custom_status = 'NOT_STRUCTURALLY_ASSESSED'" in permissive
    with pytest.raises(AppError, match="between"):
        build_threshold_result_query(
            "final_evolutionary_candidate_prioritisation",
            [],
            ThresholdSettings(),
            10_001,
        )


def test_threshold_evaluation_reclassifies_druggability_near_miss(
    threshold_db: Path,
) -> None:
    """The 0.325 near-miss becomes a pass below its score threshold."""
    with open_read_only(threshold_db) as connection:
        _, prestructure, pre_summary = evaluate_thresholds(
            connection,
            ThresholdSettings(mode="prestructure", result_scope="all"),
            10,
        )
        assert pre_summary["pass_count"] == 3
        assert pre_summary["near_miss_count"] == 1
        assert len(prestructure) == 4

        _, strict, strict_summary = evaluate_thresholds(
            connection,
            ThresholdSettings(mode="structural", result_scope="pass_near"),
            10,
        )
        assert strict["custom_status"].tolist() == ["PASS", "NEAR_MISS"]
        assert strict["primary_group_id"].tolist() == [
            "N0.HOG0001",
            "N0.HOG0002",
        ]
        assert strict_summary["structurally_assessed_count"] == 2

        _, relaxed, relaxed_summary = evaluate_thresholds(
            connection,
            ThresholdSettings(
                mode="structural",
                result_scope="passing",
                minimum_druggability_score=0.30,
            ),
            10,
        )
        assert relaxed["primary_group_id"].tolist() == [
            "N0.HOG0001",
            "N0.HOG0002",
        ]
        assert relaxed_summary["pass_count"] == 2
        second = relaxed[relaxed["primary_group_id"] == "N0.HOG0002"].iloc[0]
        assert not second["recorded_original_all_member_druggability_pass"]
        assert second["custom_druggability_pass"]

        _, boundary, _ = evaluate_thresholds(
            connection,
            final_druggability_settings(minimum_druggability_score=0.325),
            10,
        )
        assert boundary["primary_group_id"].tolist() == [
            "N0.HOG0001",
            "N0.HOG0002",
        ]


def test_final_druggability_comparison_labels_entrants_and_leavers() -> None:
    """Focused sensitivity comparison preserves the selected pass list."""
    recorded = pd.DataFrame(
        {
            "primary_group_type": ["HOG", "HOG"],
            "primary_group_id": ["G1", "G2"],
            "minimum_druggability_score": [0.7, 0.6],
            "final_score": [0.9, 0.8],
        }
    )
    relaxed = pd.DataFrame(
        {
            "primary_group_type": ["HOG", "HOG"],
            "primary_group_id": ["G1", "G3"],
            "minimum_druggability_score": [0.7, 0.3],
            "final_score": [0.9, 0.75],
        }
    )
    annotated, changes = compare_final_druggability_passes(
        recorded=recorded,
        selected=relaxed,
    )
    assert annotated["sensitivity_change"].tolist() == [
        "RECORDED_PASS",
        "ENTERS_AT_SELECTED_THRESHOLD",
    ]
    assert set(changes["sensitivity_change"]) == {
        "ENTERS_AT_SELECTED_THRESHOLD",
        "LEAVES_AT_SELECTED_THRESHOLD",
    }
    assert set(changes["primary_group_id"]) == {"G2", "G3"}

    empty_recorded = recorded.iloc[0:0].copy()
    entering_only, entering_changes = compare_final_druggability_passes(
        recorded=empty_recorded,
        selected=relaxed.iloc[[1]].copy(),
    )
    assert entering_only["sensitivity_change"].tolist() == [
        "ENTERS_AT_SELECTED_THRESHOLD"
    ]
    assert entering_changes["primary_group_id"].tolist() == ["G3"]

    empty_selected, empty_changes = compare_final_druggability_passes(
        recorded=empty_recorded,
        selected=relaxed.iloc[0:0].copy(),
    )
    assert empty_selected.empty
    assert empty_changes.empty
    with pytest.raises(AppError, match="stable candidate identity"):
        compare_final_druggability_passes(
            recorded=pd.DataFrame({"score": [1.0]}),
            selected=pd.DataFrame({"score": [1.0]}),
        )


def test_threshold_evaluation_reports_missing_relation(tmp_path: Path) -> None:
    """A resource without a candidate authority fails with controlled guidance."""
    path = tmp_path / "empty.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE TABLE unrelated(value INTEGER)")
    with open_read_only(path) as connection:
        with pytest.raises(AppError, match="No supported"):
            evaluate_thresholds(connection, ThresholdSettings(), 10)
