"""Tests for resource-wide enriched HOG results."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from e3app.enriched_hogs import (
    ENRICHED_HOG_MEMBERS,
    ENRICHED_HOG_OVERVIEW,
    collect_enriched_hog_results,
    enriched_hog_capability,
    enriched_hog_columns,
    validate_enriched_hog_result,
)
from e3app.errors import AppError


@pytest.fixture
def enriched_hog_connection() -> duckdb.DuckDBPyConnection:
    """Create membership-only, ranked-only and multiply ranked HOGs."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE hierarchical_membership("
        "group_id VARCHAR, species VARCHAR, raw_identifier VARCHAR, "
        "parsed_accession VARCHAR, parsed_entry VARCHAR, "
        "orthogroup_id VARCHAR, gene_tree_parent_clade VARCHAR)"
    )
    connection.execute(
        "INSERT INTO hierarchical_membership VALUES "
        "('N0.HOG1', 'Homo_sapiens', 'sp|HUM1|HUMAN_ONE', "
        "'HUM1', 'HUMAN_ONE', 'OG1', 'clade1'), "
        "('N0.HOG1', 'Arabidopsis_thaliana', 'sp|AT1|ARATH_ONE', "
        "'AT1', 'ARATH_ONE', 'OG1', 'clade1'), "
        "('N0.HOG1', 'Oryza_sativa', 'sp|OS1|RICE_ONE', "
        "'OS1', 'RICE_ONE', 'OG1', 'clade1'), "
        "('N0.HOG1', 'Hordeum_vulgare', 'sp|HV1|BARLEY_ONE', "
        "'HV1', 'BARLEY_ONE', 'OG1', 'clade1'), "
        "('N0.HOG2', 'Zea_mays', 'MAIZE1', 'MAIZE1', '', 'OG2', 'clade2')"
    )
    connection.execute(
        "CREATE TABLE final_evolutionary_candidate_prioritisation("
        "primary_group_id VARCHAR, prestructure_evolutionary_group_rank INTEGER, "
        "final_evolutionary_rank INTEGER, lead_cluster_id VARCHAR, "
        "candidate_accessions VARCHAR, domain_species_fraction DOUBLE, "
        "recommendation_status VARCHAR, hog_species_count INTEGER, "
        "three_dimensional_position_status VARCHAR, "
        "three_dimensional_alignment_status VARCHAR, conservation_status VARCHAR, "
        "minimum_druggability_score DOUBLE, "
        "all_assessed_members_pass_druggability BOOLEAN, "
        "structural_species_fraction DOUBLE, mean_minimum_tm_score DOUBLE, "
        "mean_pocket_overlap_fraction DOUBLE, "
        "median_centroid_distance_angstrom DOUBLE, "
        "mean_structural_residue_match_fraction DOUBLE, "
        "mean_structural_chemical_group_conservation DOUBLE)"
    )
    connection.execute(
        "INSERT INTO final_evolutionary_candidate_prioritisation VALUES "
        "('N0.HOG1', 3, 1, 'cluster_1', 'HUM1;AT1', 0.8, 'PASS', 99, "
        "'SAME_3D_POCKET_POSITION_SUPPORTED', 'CONSERVED_3D_POCKET_SUPPORTED', "
        "'CONSERVED_REGION_SUPPORTED', 0.61, TRUE, 0.75, 0.58, 0.70, 2.1, 0.65, 0.72), "
        "('N0.HOG1', 4, 2, 'cluster_1b', 'HUM1', 0.7, 'FAIL', 98, "
        "'THREE_DIMENSIONAL_POSITION_NOT_SUPPORTED', "
        "'THREE_DIMENSIONAL_POCKET_NOT_SUPPORTED', 'INSUFFICIENT_STRUCTURES', "
        "0.4, FALSE, 0.25, 0.4, 0.3, 7.0, 0.2, 0.3), "
        "('N0.HOG3', 2, 5, 'cluster_3', 'OTHER1', 0.6, 'PASS', 97, "
        "'NOT_ASSESSED', 'NOT_ASSESSED', 'NO_STRUCTURAL_EVIDENCE', NULL, "
        "FALSE, 0.0, NULL, NULL, NULL, NULL, NULL)"
    )
    connection.execute(
        "CREATE TABLE selected_pockets(primary_group_id VARCHAR, "
        "candidate_accession VARCHAR, species_column VARCHAR, pocket_number INTEGER, "
        "druggability_score DOUBLE, passes_druggability_threshold BOOLEAN, "
        "mapping_fraction DOUBLE, conservative_fraction_plddt_ge_70 DOUBLE, "
        "predictor_agreement DOUBLE, structural_evidence_status VARCHAR)"
    )
    connection.execute(
        "INSERT INTO selected_pockets VALUES "
        "('N0.HOG1', 'HUM1', 'Homo_sapiens', 1, 0.72, TRUE, 0.8, 0.9, 1.0, 'SELECTED'), "
        "('N0.HOG1', 'AT1', 'Arabidopsis_thaliana', 2, 0.61, TRUE, 0.7, 0.8, 1.0, 'SELECTED')"
    )
    try:
        yield connection
    finally:
        connection.close()


def test_enriched_hog_overview_joins_representatives_and_both_rankings(
    enriched_hog_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Overview keeps all HOGs and exposes canonical plus source rank fields."""
    columns = enriched_hog_columns(
        connection=enriched_hog_connection,
        result=ENRICHED_HOG_OVERVIEW,
    )
    assert "human_hog_representatives" in columns
    assert "arabidopsis_hog_representatives" in columns
    assert "rice_hog_representatives" in columns
    assert "barley_hog_representatives" in columns
    assert "hog_three_dimensional_position_status" in columns
    assert "hog_three_dimensional_alignment_status" in columns
    assert "hog_minimum_druggability_score" in columns
    assert "human_hog_raw_identifiers" in columns
    assert "arabidopsis_hog_entries" in columns
    assert "hog_mapping_statuses" in columns
    assert "hog_prestructure_rank" in columns
    assert "hog_poststructure_rank" in columns
    assert "prestructure_evolutionary_group_rank" in columns
    assert "final_evolutionary_rank" in columns
    assert "domain_species_fraction" in columns
    assert "ranking_hog_species_count" in columns

    result = collect_enriched_hog_results(
        connection=enriched_hog_connection,
        result=ENRICHED_HOG_OVERVIEW,
        selected_columns=columns,
        maximum_rows=100,
    )
    assert result["hog_id"].tolist() == ["N0.HOG1", "N0.HOG3", "N0.HOG2"]
    hog1 = result[result["hog_id"] == "N0.HOG1"].iloc[0]
    assert hog1["human_hog_representatives"] == "HUM1"
    assert hog1["arabidopsis_hog_representatives"] == "AT1"
    assert hog1["rice_hog_representatives"] == "OS1"
    assert hog1["barley_hog_representatives"] == "HV1"
    assert hog1["human_hog_entries"] == "HUMAN_ONE"
    assert hog1["arabidopsis_hog_raw_identifiers"] == "sp|AT1|ARATH_ONE"
    assert int(hog1["hog_prestructure_rank"]) == 3
    assert int(hog1["hog_poststructure_rank"]) == 1
    assert int(hog1["hog_ranking_source_row_count"]) == 2
    assert hog1["lead_cluster_id"] == "cluster_1"
    assert int(hog1["ranking_hog_species_count"]) == 99
    assert bool(hog1["hog_same_3d_pocket_position_supported"])
    assert bool(hog1["hog_conserved_3d_pocket_supported"])
    assert float(hog1["hog_minimum_druggability_score"]) == pytest.approx(0.61)
    hog2 = result[result["hog_id"] == "N0.HOG2"].iloc[0]
    assert bool(hog2["hog_membership_available"])
    assert not bool(hog2["hog_ranking_available"])
    hog3 = result[result["hog_id"] == "N0.HOG3"].iloc[0]
    assert not bool(hog3["hog_membership_available"])
    assert bool(hog3["hog_ranking_available"])


def test_enriched_hog_member_detail_repeats_complete_hog_context(
    enriched_hog_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Member rows retain source membership fields and HOG-level ranks."""
    columns = enriched_hog_columns(
        connection=enriched_hog_connection,
        result=ENRICHED_HOG_MEMBERS,
    )
    assert "member_species" in columns
    assert "member_raw_identifier" in columns
    assert "member_structural_readiness_rank" in columns
    assert "member_structural_readiness_status" in columns
    assert "member_druggability_score" in columns
    selected = [
        "hog_id",
        "hog_prestructure_rank",
        "hog_poststructure_rank",
        "human_hog_representatives",
        "arabidopsis_hog_representatives",
        "rice_hog_representatives",
        "barley_hog_representatives",
        "member_species",
        "member_raw_identifier",
        "member_structural_readiness_rank",
        "member_structural_readiness_status",
        "member_structure_assessed",
        "member_druggability_score",
    ]
    result = collect_enriched_hog_results(
        connection=enriched_hog_connection,
        result=ENRICHED_HOG_MEMBERS,
        selected_columns=selected,
        maximum_rows=100,
    )
    hog1 = result[result["hog_id"] == "N0.HOG1"]
    assert hog1["member_species"].tolist() == [
        "Homo_sapiens",
        "Arabidopsis_thaliana",
        "Hordeum_vulgare",
        "Oryza_sativa",
    ]
    assert set(hog1["hog_poststructure_rank"]) == {1}
    assert hog1["member_structural_readiness_rank"].astype(int).tolist() == [
        1,
        2,
        3,
        4,
    ]
    human = hog1[hog1["member_species"] == "Homo_sapiens"].iloc[0]
    assert bool(human["member_structure_assessed"])
    assert float(human["member_druggability_score"]) == pytest.approx(0.72)
    assert human["member_structural_readiness_status"] == (
        "STRUCTURAL_POCKET_EVIDENCE"
    )
    ranked_only = result[result["hog_id"] == "N0.HOG3"].iloc[0]
    assert ranked_only["member_species"] is None
    assert pd.isna(ranked_only["member_structural_readiness_rank"])
    assert ranked_only["member_structural_readiness_status"] == "NO_MEMBER_RECORD"


def test_enriched_hog_validation_rejects_bad_requests() -> None:
    """Unsupported results, absent sources, columns and limits fail explicitly."""
    with pytest.raises(AppError, match="Unsupported"):
        validate_enriched_hog_result(result="other")
    empty = duckdb.connect(":memory:")
    try:
        assert not enriched_hog_capability(connection=empty)["available"]
        with pytest.raises(AppError, match="No root-HOG"):
            enriched_hog_columns(
                connection=empty,
                result=ENRICHED_HOG_OVERVIEW,
            )
    finally:
        empty.close()


def test_enriched_hog_collection_validates_columns_and_bounds(
    enriched_hog_connection: duckdb.DuckDBPyConnection,
) -> None:
    """The bounded collector accepts only explicit available fields."""
    with pytest.raises(AppError, match="Select at least one"):
        collect_enriched_hog_results(
            connection=enriched_hog_connection,
            result=ENRICHED_HOG_OVERVIEW,
            selected_columns=[],
        )
    with pytest.raises(AppError, match="Unknown"):
        collect_enriched_hog_results(
            connection=enriched_hog_connection,
            result=ENRICHED_HOG_OVERVIEW,
            selected_columns=["not_a_field"],
        )
    with pytest.raises(AppError, match="between 1 and 100000"):
        collect_enriched_hog_results(
            connection=enriched_hog_connection,
            result=ENRICHED_HOG_OVERVIEW,
            selected_columns=["hog_id"],
            maximum_rows=0,
        )


def test_enriched_hog_overview_accepts_ranking_only_resources() -> None:
    """A HOG-linked ranking remains useful without membership metadata."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE candidate_master_results("
            "primary_group_id VARCHAR, final_rank INTEGER, final_score DOUBLE)"
        )
        connection.execute(
            "INSERT INTO candidate_master_results VALUES ('N0.HOG9', 4, 0.75)"
        )
        capability = enriched_hog_capability(connection=connection)
        assert capability["available"]
        assert not capability["membership_available"]
        result = collect_enriched_hog_results(
            connection=connection,
            result=ENRICHED_HOG_OVERVIEW,
            selected_columns=[
                "hog_id",
                "hog_poststructure_rank",
                "human_hog_representatives",
                "final_score",
            ],
        )
        assert result.loc[0, "hog_id"] == "N0.HOG9"
        assert int(result.loc[0, "hog_poststructure_rank"]) == 4
        assert result.loc[0, "human_hog_representatives"] == ""
    finally:
        connection.close()


def test_enriched_hog_overview_accepts_membership_only_resources() -> None:
    """Unranked HOG membership remains visible without invented rank values."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE hierarchical_membership("
            "group_id VARCHAR, species VARCHAR, raw_identifier VARCHAR)"
        )
        connection.execute(
            "INSERT INTO hierarchical_membership VALUES "
            "('N0.HOG8', 'Homo_sapiens', 'sp|H8|HUMAN_EIGHT')"
        )
        result = collect_enriched_hog_results(
            connection=connection,
            result=ENRICHED_HOG_OVERVIEW,
            selected_columns=[
                "hog_id",
                "hog_poststructure_rank",
                "human_hog_representatives",
                "hog_ranking_available",
            ],
        )
        assert result.loc[0, "hog_id"] == "N0.HOG8"
        assert result.loc[0, "human_hog_representatives"] == (
            "sp|H8|HUMAN_EIGHT"
        )
        assert not bool(result.loc[0, "hog_ranking_available"])
        assert result["hog_poststructure_rank"].isna().all()
    finally:
        connection.close()
