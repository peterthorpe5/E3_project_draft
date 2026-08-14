"""Tests for human and plant–human root-level HOG exploration."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from e3app.errors import AppError
from e3app.human_hogs import (
    collect_human_hog_members,
    collect_human_hog_summary,
    human_hog_capability,
    select_hog_ranking_relation,
    target_plant_species,
    validate_hog_view,
)
from e3app.streamlit_app import _filter_hog_frame, _human_hog_member_fasta


@pytest.fixture
def human_hog_connection() -> duckdb.DuckDBPyConnection:
    """Create human-only, plant–human and plant-only HOG examples."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE hierarchical_membership("
        "record_type VARCHAR, group_id VARCHAR, orthogroup_id VARCHAR, "
        "gene_tree_parent_clade VARCHAR, species VARCHAR, raw_identifier VARCHAR, "
        "parsed_accession VARCHAR, parsed_entry VARCHAR, review_status VARCHAR, "
        "identifier_format VARCHAR, mapping_status VARCHAR, mapping_reason VARCHAR, "
        "source_file VARCHAR, source_row INTEGER)"
    )
    connection.execute(
        "INSERT INTO hierarchical_membership VALUES "
        "('HIERARCHICAL_ORTHOGROUP', 'N0.HOG1', 'OG1', 'n1', "
        "'Homo_sapiens', 'sp|HUM1|HUMAN_ONE', 'HUM1', 'HUMAN_ONE', "
        "'REVIEWED', 'UNIPROT', 'MAPPED', '', 'N0.tsv', 2), "
        "('HIERARCHICAL_ORTHOGROUP', 'N0.HOG1', 'OG1', 'n1', "
        "'Homo_sapiens', 'sp|HUM1B|HUMAN_ONE_B', 'HUM1B', 'HUMAN_ONE_B', "
        "'REVIEWED', 'UNIPROT', 'MAPPED', '', 'N0.tsv', 2), "
        "('HIERARCHICAL_ORTHOGROUP', 'N0.HOG1', 'OG1', 'n1', "
        "'Arabidopsis_thaliana', 'sp|PLANT1|PLANT_ONE', 'PLANT1', "
        "'PLANT_ONE', 'REVIEWED', 'UNIPROT', 'MAPPED', '', 'N0.tsv', 2), "
        "('HIERARCHICAL_ORTHOGROUP', 'N0.HOG1', 'OG1', 'n1', "
        "'Zea_mays', 'PLANT2', 'PLANT2', '', 'UNREVIEWED', 'BARE', "
        "'MAPPED', '', 'N0.tsv', 2), "
        "('HIERARCHICAL_ORTHOGROUP', 'N0.HOG2', 'OG2', 'n2', "
        "'Homo_sapiens', 'sp|HUM2|HUMAN_TWO', 'HUM2', 'HUMAN_TWO', "
        "'REVIEWED', 'UNIPROT', 'MAPPED', '', 'N0.tsv', 3), "
        "('HIERARCHICAL_ORTHOGROUP', 'N0.HOG3', 'OG3', 'n3', "
        "'Arabidopsis_thaliana', 'PLANT3', 'PLANT3', '', 'UNREVIEWED', "
        "'BARE', 'MAPPED', '', 'N0.tsv', 4)"
    )
    connection.execute(
        "CREATE TABLE final_evolutionary_candidate_prioritisation("
        "final_evolutionary_rank INTEGER, primary_group_type VARCHAR, "
        "primary_group_id VARCHAR, lead_cluster_id VARCHAR, "
        "candidate_accessions VARCHAR, matched_seed_ids_calculated VARCHAR, "
        "seed_protein_names VARCHAR, recommendation_status VARCHAR, "
        "final_score DOUBLE, grant_aligned_prestructure_pass BOOLEAN, "
        "grant_aligned_final_pass BOOLEAN)"
    )
    connection.execute(
        "INSERT INTO final_evolutionary_candidate_prioritisation VALUES "
        "(7, 'HIERARCHICAL_ORTHOGROUP', 'N0.HOG1', 'cluster_1', "
        "'HUM1;PLANT1', 'SEED1', 'Example ligase', 'REVIEW', 0.81, true, false)"
    )
    connection.execute(
        "CREATE TABLE candidate_group_member_sequences("
        "cluster_id VARCHAR, record_type VARCHAR, group_id VARCHAR, species VARCHAR, "
        "internal_id VARCHAR, source_fasta VARCHAR, raw_identifier VARCHAR, "
        "candidate_accessions_for_cluster VARCHAR, is_input_candidate BOOLEAN, "
        "sequence_length INTEGER, sequence_sha256 VARCHAR, protein_sequence VARCHAR)"
    )
    connection.execute(
        "INSERT INTO candidate_group_member_sequences VALUES "
        "('cluster_1', 'HIERARCHICAL_ORTHOGROUP', 'N0.HOG1', 'Homo_sapiens', "
        "'12_1', 'Species12.fa', 'sp|HUM1|HUMAN_ONE', 'HUM1;PLANT1', true, "
        "4, 'abc', 'AAAA')"
    )
    connection.execute(
        "CREATE TABLE candidate_identifier_aliases("
        "primary_group_id VARCHAR, member_accession VARCHAR, species_column VARCHAR, "
        "identifier_type VARCHAR, identifier_value VARCHAR)"
    )
    connection.execute(
        "INSERT INTO candidate_identifier_aliases VALUES "
        "('N0.HOG1', 'HUM1', 'Homo_sapiens', 'gene_name', 'HUWE1')"
    )
    try:
        yield connection
    finally:
        connection.close()


def test_human_hog_summary_retains_ranked_and_unranked_groups(
    human_hog_connection: duckdb.DuckDBPyConnection,
) -> None:
    """All human HOGs remain visible and candidate ranks are optional."""
    capability = human_hog_capability(connection=human_hog_connection)
    assert capability["available"]
    assert capability["ranking_relation"] == (
        "final_evolutionary_candidate_prioritisation"
    )
    summary = collect_human_hog_summary(
        connection=human_hog_connection,
        view="human",
    )
    assert summary["hog_id"].tolist() == ["N0.HOG1", "N0.HOG2"]
    ranked = summary[summary["hog_id"] == "N0.HOG1"].iloc[0]
    assert int(ranked["ranking_position"]) == 7
    assert ranked["human_accessions"] == "HUM1;HUM1B"
    assert ranked["human_hog_representatives"] == "HUM1;HUM1B"
    assert ranked["arabidopsis_hog_representatives"] == "PLANT1"
    unranked = summary[summary["hog_id"] == "N0.HOG2"].iloc[0]
    assert unranked["ranking_availability"] == "NOT_IN_CANDIDATE_RANKING"
    assert unranked["human_hog_representatives"] == "HUM2"
    assert unranked["arabidopsis_hog_representatives"] == ""


def test_plant_and_human_view_requires_both_lineages(
    human_hog_connection: duckdb.DuckDBPyConnection,
) -> None:
    """The cross-lineage view excludes human-only and plant-only HOGs."""
    summary = collect_human_hog_summary(
        connection=human_hog_connection,
        view="plant_and_human",
    )
    assert summary["hog_id"].tolist() == ["N0.HOG1"]
    assert int(summary.loc[0, "plant_species_count"]) == 2
    assert summary.loc[0, "plant_species_present"] == "Arabidopsis_thaliana;Zea_mays"


def test_member_tables_include_human_aliases_sequences_and_co_members(
    human_hog_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Human annotations and every HOG co-member remain independently auditable."""
    human = collect_human_hog_members(
        connection=human_hog_connection,
        view="human",
        member_scope="human",
    )
    assert set(human["parsed_accession"]) == {"HUM1", "HUM1B", "HUM2"}
    human_one = human[human["parsed_accession"] == "HUM1"].iloc[0]
    assert human_one["available_aliases"] == "HUWE1"
    assert human_one["protein_sequence"] == "AAAA"
    all_members = collect_human_hog_members(
        connection=human_hog_connection,
        view="plant_and_human",
        member_scope="all",
    )
    assert set(all_members["member_class"]) == {"HUMAN", "TARGET_PLANT"}
    assert len(all_members) == 4
    assert set(all_members["human_hog_representatives"]) == {"HUM1;HUM1B"}
    assert set(all_members["arabidopsis_hog_representatives"]) == {"PLANT1"}


def test_human_hog_validation_is_defensive() -> None:
    """Unsupported views, limits and missing relations fail explicitly."""
    assert len(target_plant_species()) == 12
    with pytest.raises(AppError, match="Unsupported"):
        validate_hog_view(view="bad")  # type: ignore[arg-type]
    connection = duckdb.connect(":memory:")
    try:
        assert select_hog_ranking_relation(connection=connection) is None
        capability = human_hog_capability(connection=connection)
        assert not capability["available"]
        with pytest.raises(AppError, match="requires complete"):
            collect_human_hog_summary(connection=connection)
    finally:
        connection.close()


def test_hog_display_filter_and_fasta_retain_complete_context() -> None:
    """Display helpers match literal identifiers and export published sequences."""
    members = pd.DataFrame(
        {
            "hog_id": ["N0.HOG1", "N0.HOG2"],
            "human_hog_representatives": ["HUM1", "HUM2"],
            "arabidopsis_hog_representatives": ["AT1", "AT2"],
            "species": ["Homo_sapiens", "Arabidopsis_thaliana"],
            "parsed_accession": ["HUM1", "AT2"],
            "parsed_entry": ["HUMAN_ONE", "PLANT_TWO"],
            "raw_identifier": ["sp|HUM1|HUMAN_ONE", "AT2"],
            "protein_sequence": ["AAAA", ""],
        }
    )
    selected = _filter_hog_frame(frame=members, query="human_one")
    assert selected["hog_id"].tolist() == ["N0.HOG1"]
    selected_by_representative = _filter_hog_frame(frame=members, query="AT1")
    assert selected_by_representative["hog_id"].tolist() == ["N0.HOG1"]
    fasta = _human_hog_member_fasta(members=members)
    assert b">N0.HOG1|Homo_sapiens|HUM1" in fasta
    assert b"AAAA" in fasta
    assert _human_hog_member_fasta(
        members=members.drop(columns="protein_sequence")
    ) == b""
