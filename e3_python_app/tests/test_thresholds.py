"""Tests for evolutionary-group threshold sensitivity analysis."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

from e3app.data import open_read_only
from e3app.errors import AppError
from e3app.thresholds import (
    ThresholdSettings,
    build_threshold_result_query,
    build_threshold_summary_query,
    evaluate_thresholds,
    group_source_sql,
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


def test_threshold_relation_and_group_source_selection() -> None:
    """Evolutionary authority is preferred and fallbacks are deduplicated."""
    assert select_threshold_relation(
        [
            "candidate_master_results",
            "final_evolutionary_candidate_prioritisation",
        ]
    ) == "final_evolutionary_candidate_prioritisation"
    assert select_threshold_relation(["unrelated"]) is None
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


def test_threshold_evaluation_reports_missing_relation(tmp_path: Path) -> None:
    """A resource without a candidate authority fails with controlled guidance."""
    path = tmp_path / "empty.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE TABLE unrelated(value INTEGER)")
    with open_read_only(path) as connection:
        with pytest.raises(AppError, match="No supported"):
            evaluate_thresholds(connection, ThresholdSettings(), 10)
