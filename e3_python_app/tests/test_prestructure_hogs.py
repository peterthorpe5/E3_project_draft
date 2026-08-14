"""Tests for the independent structural-review HOG shortlist."""

from __future__ import annotations

import duckdb
import pytest

from e3app.errors import AppError
from e3app.prestructure_hogs import (
    collect_prestructure_ranked_hogs,
    prestructure_hog_capability,
    prestructure_review_columns,
)


@pytest.fixture
def prestructure_hog_connection() -> duckdb.DuckDBPyConnection:
    """Create ranked HOGs, a non-HOG group and representative members."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE final_evolutionary_candidate_prioritisation("
        "prestructure_evolutionary_group_rank INTEGER, "
        "final_evolutionary_rank INTEGER, primary_group_id VARCHAR, "
        "lead_cluster_id VARCHAR, candidate_accessions VARCHAR, "
        "prestructure_score DOUBLE, grant_aligned_prestructure_pass BOOLEAN, "
        "final_score DOUBLE, selected_pocket_count INTEGER)"
    )
    connection.execute(
        "INSERT INTO final_evolutionary_candidate_prioritisation VALUES "
        "(3, 1, 'N0.HOG3', 'cluster_3', 'P3', 0.70, true, 0.99, 3), "
        "(1, 3, 'N0.HOG1', 'cluster_1', 'P1', 0.95, false, 0.10, 0), "
        "(2, 2, 'N0.HOG2', 'cluster_2', 'P2', 0.80, true, 0.50, 1), "
        "(0, 4, 'OG0001', 'cluster_0', 'P0', 0.99, true, 0.80, 2), "
        "(2, 5, 'N0.HOG2', 'cluster_2b', 'P2B', 0.79, false, 0.95, 4)"
    )
    connection.execute(
        "CREATE TABLE hierarchical_membership("
        "group_id VARCHAR, species VARCHAR, raw_identifier VARCHAR, "
        "parsed_accession VARCHAR, parsed_entry VARCHAR)"
    )
    connection.execute(
        "INSERT INTO hierarchical_membership VALUES "
        "('N0.HOG1', 'Homo_sapiens', 'sp|H1|HUMAN_ONE', 'H1', 'HUMAN_ONE'), "
        "('N0.HOG1', 'Homo_sapiens', 'sp|H2|HUMAN_TWO', 'H2', 'HUMAN_TWO'), "
        "('N0.HOG1', 'Arabidopsis_thaliana', 'sp|AT1|ARATH_ONE', "
        "'AT1', 'ARATH_ONE'), "
        "('N0.HOG2', 'Homo_sapiens', 'sp|H3|HUMAN_THREE', 'H3', "
        "'HUMAN_THREE')"
    )
    try:
        yield connection
    finally:
        connection.close()


def test_prestructure_hog_capability_requires_a_group_level_rank(
    prestructure_hog_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Source selection rejects final-only or cluster-level ranks."""
    capability = prestructure_hog_capability(
        connection=prestructure_hog_connection
    )
    assert capability == {
        "available": True,
        "relation": "final_evolutionary_candidate_prioritisation",
        "rank_column": "prestructure_evolutionary_group_rank",
        "pass_column": "grant_aligned_prestructure_pass",
    }
    missing = duckdb.connect(":memory:")
    try:
        missing.execute(
            "CREATE TABLE prestructure_ranking("
            "primary_group_id VARCHAR, computational_rank INTEGER)"
        )
        assert prestructure_hog_capability(connection=missing)["available"] is False
    finally:
        missing.close()


def test_top_n_hogs_use_prestructure_rank_and_hide_structural_fields(
    prestructure_hog_connection: duckdb.DuckDBPyConnection,
) -> None:
    """The full shortlist retains failed gates but excludes structural evidence."""
    result = collect_prestructure_ranked_hogs(
        connection=prestructure_hog_connection,
        maximum_hogs=2,
    )
    assert result["primary_group_id"].tolist() == ["N0.HOG1", "N0.HOG2"]
    assert result["prestructure_evolutionary_group_rank"].tolist() == [1, 2]
    assert result["grant_aligned_prestructure_pass"].tolist() == [False, True]
    assert "final_evolutionary_rank" not in result.columns
    assert "final_score" not in result.columns
    assert "selected_pocket_count" not in result.columns
    assert result.loc[0, "human_hog_representatives"] == "H1;H2"
    assert result.loc[0, "arabidopsis_hog_representatives"] == "AT1"
    assert result.loc[1, "human_hog_representatives"] == "H3"
    assert result.loc[1, "arabidopsis_hog_representatives"] == ""


def test_prestructure_pass_filter_is_optional(
    prestructure_hog_connection: duckdb.DuckDBPyConnection,
) -> None:
    """The team may restrict the shortlist without making the gate compulsory."""
    result = collect_prestructure_ranked_hogs(
        connection=prestructure_hog_connection,
        maximum_hogs=2,
        passes_only=True,
    )
    assert result["primary_group_id"].tolist() == ["N0.HOG2", "N0.HOG3"]
    assert result["prestructure_evolutionary_group_rank"].tolist() == [2, 3]
    assert result["grant_aligned_prestructure_pass"].tolist() == [True, True]


def test_prestructure_review_columns_preserve_all_non_structural_evidence() -> None:
    """Pre-structure evidence remains rich while known structural fields are removed."""
    selected = prestructure_review_columns(
        available=(
            "candidate_accessions",
            "final_score",
            "expression_score",
            "prestructure_evolutionary_group_rank",
            "primary_group_id",
            "three_dimensional_alignment_status",
            "sensitivity_alignment_status",
            "conservation_rescued_accession_count",
            "alphafold_model_path",
            "discovery_seed_protein_names",
        )
    )
    assert selected == [
        "prestructure_evolutionary_group_rank",
        "primary_group_id",
        "candidate_accessions",
        "expression_score",
        "discovery_seed_protein_names",
    ]


def test_prestructure_hog_collection_validates_limits_and_sources() -> None:
    """Invalid row limits and unavailable authoritative ranks fail clearly."""
    connection = duckdb.connect(":memory:")
    try:
        with pytest.raises(AppError, match="between 1 and 10000"):
            collect_prestructure_ranked_hogs(
                connection=connection,
                maximum_hogs=0,
            )
        with pytest.raises(AppError, match="boolean"):
            collect_prestructure_ranked_hogs(
                connection=connection,
                passes_only=1,
            )
        with pytest.raises(AppError, match="authoritative"):
            collect_prestructure_ranked_hogs(connection=connection)
        connection.execute(
            "CREATE TABLE prestructure_ranking("
            "primary_group_id VARCHAR, "
            "prestructure_evolutionary_group_rank INTEGER)"
        )
        with pytest.raises(AppError, match="pass field"):
            collect_prestructure_ranked_hogs(
                connection=connection,
                passes_only=True,
            )
    finally:
        connection.close()
