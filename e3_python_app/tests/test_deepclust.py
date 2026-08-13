"""Tests for the separate DeepClust and 1KP discovery view."""

from __future__ import annotations

import duckdb
import pytest

from e3app.deepclust import (
    collect_deepclust_metrics,
    collect_deepclust_summary,
    collect_onekp_coverage_distribution,
    parse_seed_queries,
    select_deepclust_relation,
)
from e3app.errors import AppError


def _connection() -> duckdb.DuckDBPyConnection:
    """Return a representative candidate-evidence resource."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE candidate_evidence("
        "representative_id VARCHAR, representative_original_id VARCHAR, "
        "matched_seed_ids_calculated VARCHAR, raw_member_count INTEGER, "
        "strict_member_count INTEGER, strict_member_fraction DOUBLE, "
        "raw_onekp_sample_count INTEGER, raw_onekp_species_count INTEGER, "
        "strict_onekp_sample_count INTEGER, strict_onekp_species_count INTEGER, "
        "strict_named_species_count INTEGER)"
    )
    connection.execute(
        "INSERT INTO candidate_evidence VALUES "
        "('cluster_1', 'onekp_dataset@@scaffold-AAAA-1', 'Q1;Q2', 12, 10, "
        "0.833, 7, 6, 5, 4, 3), "
        "('cluster_2', 'Arabidopsis@@P2', 'Q2', 5, 4, 0.8, 0, 0, 0, 0, 2)"
    )
    connection.execute(
        "CREATE TABLE evolutionary_group_cluster_contributors("
        "cluster_id VARCHAR, primary_group_type VARCHAR, "
        "primary_group_id VARCHAR, evolutionary_group_key VARCHAR)"
    )
    connection.execute(
        "INSERT INTO evolutionary_group_cluster_contributors VALUES "
        "('cluster_1', 'HIERARCHICAL_ORTHOGROUP', 'N0.HOG1', "
        "'HIERARCHICAL_ORTHOGROUP:N0.HOG1')"
    )
    return connection


def test_relation_selection_and_seed_parser_are_explicit() -> None:
    """Only the discovery summary is selected and pasted seeds are deduplicated."""
    assert select_deepclust_relation(relation_names=["candidate_evidence"])
    assert select_deepclust_relation(relation_names=["orthogroup_membership"]) is None
    assert parse_seed_queries("Q1, Q2;Q1\nQ3") == ("Q1", "Q2", "Q3")
    assert parse_seed_queries(["Q1 Q2", "Q3"]) == ("Q1", "Q2", "Q3")


def test_deepclust_metrics_and_distribution_retain_onekp_zeroes() -> None:
    """Metrics distinguish raw/strict 1KP coverage and retain zero bins."""
    with _connection() as connection:
        metrics = collect_deepclust_metrics(connection=connection)
        distribution = collect_onekp_coverage_distribution(connection=connection)
    assert metrics["cluster_count"] == 2
    assert metrics["clusters_with_raw_onekp"] == 1
    assert metrics["clusters_with_strict_onekp"] == 1
    assert metrics["strict_onekp_cluster_species_links"] == 4
    assert distribution["strict_onekp_species_count"].tolist() == [0, 4]


def test_deepclust_filters_seed_coverage_and_links_without_orthology_claim() -> None:
    """Seed filters return cluster summaries and optional evolutionary links."""
    with _connection() as connection:
        selected = collect_deepclust_summary(
            connection=connection,
            seed_queries=("Q1", "Q2"),
            match_mode="all",
            onekp_mode="strict",
            minimum_strict_onekp_species=2,
        )
    assert selected["representative_id"].tolist() == ["cluster_1"]
    assert selected["strict_onekp_species_count"].tolist() == [4]
    assert selected["linked_evolutionary_groups"].tolist() == [
        "HIERARCHICAL_ORTHOGROUP:N0.HOG1"
    ]


def test_deepclust_summary_supports_raw_any_and_literal_cluster_filters() -> None:
    """The alternate filters remain bounded and use literal substring matching."""
    with _connection() as connection:
        selected = collect_deepclust_summary(
            connection=connection,
            seed_queries=("Q1", "not_present"),
            match_mode="any",
            onekp_mode="raw",
            cluster_query="cluster_1",
            maximum_rows=1,
        )
        all_rows = collect_deepclust_summary(
            connection=connection,
            onekp_mode="all",
        )
    assert selected["representative_id"].tolist() == ["cluster_1"]
    assert all_rows["representative_id"].tolist() == ["cluster_1", "cluster_2"]


def test_deepclust_summary_operates_without_optional_group_links() -> None:
    """Absent contributor relations remove link columns rather than cluster rows."""
    with _connection() as connection:
        connection.execute("DROP TABLE evolutionary_group_cluster_contributors")
        selected = collect_deepclust_summary(connection=connection)
    assert selected["representative_id"].tolist() == ["cluster_1", "cluster_2"]
    assert "linked_evolutionary_groups" not in selected.columns


def test_deepclust_validation_rejects_incomplete_and_invalid_requests() -> None:
    """Schema and bounded-filter failures produce controlled application errors."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE candidate_evidence(representative_id VARCHAR)"
        )
        with pytest.raises(AppError, match="missing columns"):
            collect_deepclust_metrics(connection=connection)
    finally:
        connection.close()
    with _connection() as complete:
        for arguments, message in (
            ({"match_mode": "bad"}, "match mode"),
            ({"onekp_mode": "bad"}, "1KP filter"),
            ({"minimum_strict_onekp_species": -1}, "Minimum strict"),
            ({"maximum_rows": 0}, "Maximum DeepClust"),
        ):
            with pytest.raises(AppError, match=message):
                collect_deepclust_summary(
                    connection=complete,
                    **arguments,
                )
