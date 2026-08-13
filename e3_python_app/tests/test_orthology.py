"""Tests for bounded OrthoFinder and E3 seed-group exploration."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from e3app.errors import AppError
from e3app.orthology import (
    collect_orthology_group_summary,
    collect_orthology_metrics,
    collect_orthology_size_distribution,
    collect_orthology_species,
    collect_seed_group_members,
    collect_seed_identifiers,
    load_species_taxonomy,
    select_orthology_relation,
    summarise_seed_groups,
)


@pytest.fixture
def orthology_connection() -> duckdb.DuckDBPyConnection:
    """Create a small membership resource with duplicated cluster links."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE hierarchical_membership("
        "record_type VARCHAR, group_id VARCHAR, species VARCHAR, "
        "raw_identifier VARCHAR)"
    )
    connection.execute(
        "INSERT INTO hierarchical_membership VALUES "
        "('HIERARCHICAL_ORTHOGROUP', 'HOG1', 'species_a', 'A1'), "
        "('HIERARCHICAL_ORTHOGROUP', 'HOG1', 'species_b', 'B1'), "
        "('HIERARCHICAL_ORTHOGROUP', 'HOG1', 'species_c', 'C1'), "
        "('HIERARCHICAL_ORTHOGROUP', 'HOG2', 'species_a', 'A2'), "
        "('HIERARCHICAL_ORTHOGROUP', 'HOG3', 'species_b', 'B3'), "
        "('HIERARCHICAL_ORTHOGROUP', 'HOG3', 'species_c', 'C3')"
    )
    connection.execute(
        "CREATE TABLE candidate_group_member_sequences("
        "cluster_id VARCHAR, record_type VARCHAR, group_id VARCHAR, "
        "species VARCHAR, internal_id VARCHAR, raw_identifier VARCHAR, "
        "parsed_accession VARCHAR, parsed_entry VARCHAR, review_status VARCHAR, "
        "mapping_status VARCHAR, is_input_candidate BOOLEAN, "
        "candidate_accessions_for_cluster VARCHAR, sequence_length INTEGER, "
        "protein_sequence VARCHAR)"
    )
    connection.execute(
        "INSERT INTO candidate_group_member_sequences VALUES "
        "('cluster_1', 'HIERARCHICAL_ORTHOGROUP', 'HOG1', 'species_a', "
        "'ia', 'A1', 'SEED_A', '', 'REVIEWED', 'MATCHED', true, "
        "'SEED_A;SEED_B', 4, 'AAAA'), "
        "('cluster_1', 'HIERARCHICAL_ORTHOGROUP', 'HOG1', 'species_b', "
        "'ib', 'B1', 'B1', '', 'UNREVIEWED', 'MATCHED', false, "
        "'SEED_A;SEED_B', 4, 'BBBB'), "
        "('cluster_2', 'HIERARCHICAL_ORTHOGROUP', 'HOG1', 'species_b', "
        "'ib', 'B1', 'B1', '', 'UNREVIEWED', 'MATCHED', false, "
        "'SEED_C', 4, 'BBBB'), "
        "('cluster_3', 'HIERARCHICAL_ORTHOGROUP', 'HOG3', 'species_b', "
        "'ib3', 'B3', 'SEED_C', '', 'REVIEWED', 'MATCHED', true, "
        "'SEED_C', 4, 'CCCC')"
    )
    try:
        yield connection
    finally:
        connection.close()


def test_select_relation_and_collect_release_metrics(
    orthology_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Metrics retain all source memberships and distinguish seeded groups."""
    assert select_orthology_relation(
        relation_names=["hierarchical_membership"],
        group_type="hierarchical_orthogroup",
    ) == "hierarchical_membership"
    metrics = collect_orthology_metrics(
        connection=orthology_connection,
        relation="hierarchical_membership",
    )
    assert metrics == {
        "input_sequences": 6,
        "input_species": 3,
        "group_count": 3,
        "seeded_group_count": 2,
        "all_species_group_count": 1,
        "largest_group_size": 3,
        "largest_group_id": "HOG1",
    }
    assert collect_orthology_species(
        connection=orthology_connection,
        relation="hierarchical_membership",
    ) == ["species_a", "species_b", "species_c"]
    assert select_orthology_relation(
        relation_names=[],
        group_type="orthogroup",
    ) is None
    with pytest.raises(AppError, match="Unsupported"):
        select_orthology_relation(
            relation_names=[],
            group_type="bad",  # type: ignore[arg-type]
        )


def test_group_summary_filters_species_breadth_taxonomy_and_seed(
    orthology_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Species filters use exact labels and all requested labels must occur."""
    all_species = collect_orthology_group_summary(
        connection=orthology_connection,
        relation="hierarchical_membership",
        breadth="all_species",
    )
    assert all_species["group_id"].tolist() == ["HOG1"]
    selected = collect_orthology_group_summary(
        connection=orthology_connection,
        relation="hierarchical_membership",
        required_species=("species_b", "species_c"),
        taxonomy_species=("species_a",),
        seeded_only=True,
    )
    assert selected["group_id"].tolist() == ["HOG1"]
    assert selected.loc[0, "contains_e3_seed_evidence"]
    single = collect_orthology_group_summary(
        connection=orthology_connection,
        relation="hierarchical_membership",
        breadth="one_species",
    )
    assert single["group_id"].tolist() == ["HOG2"]
    distribution = collect_orthology_size_distribution(
        connection=orthology_connection,
        relation="hierarchical_membership",
    )
    assert int(distribution["group_count"].sum()) == 3
    assert "One species only" in set(distribution["species_breadth"])
    with pytest.raises(AppError, match="Unsupported species-breadth"):
        collect_orthology_group_summary(
            connection=orthology_connection,
            relation="hierarchical_membership",
            breadth="bad",
        )
    with pytest.raises(AppError, match="between 1 and 100000"):
        collect_orthology_group_summary(
            connection=orthology_connection,
            relation="hierarchical_membership",
            maximum_rows=0,
        )


def test_seed_search_matches_any_or_all_and_deduplicates_members(
    orthology_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Seed lookup returns every group member once despite multiple clusters."""
    assert collect_seed_identifiers(connection=orthology_connection) == [
        "SEED_A",
        "SEED_B",
        "SEED_C",
    ]
    members = collect_seed_group_members(
        connection=orthology_connection,
        seed_identifiers=("SEED_A", "SEED_B"),
        group_type="hierarchical_orthogroup",
        match_mode="all",
    )
    assert members["primary_group_id"].tolist() == ["HOG1", "HOG1"]
    assert members["raw_identifier"].tolist() == ["A1", "B1"]
    assert members.loc[1, "linked_deepclust_clusters"] == "cluster_1;cluster_2"
    filtered = collect_seed_group_members(
        connection=orthology_connection,
        seed_identifiers=("SEED_C",),
        group_type="hierarchical_orthogroup",
        species=("species_b",),
    )
    assert set(filtered["primary_group_id"]) == {"HOG1", "HOG3"}
    any_members = collect_seed_group_members(
        connection=orthology_connection,
        seed_identifiers=("SEED_A", "SEED_C"),
        group_type="hierarchical_orthogroup",
        match_mode="any",
    )
    assert set(any_members["primary_group_id"]) == {"HOG1", "HOG3"}
    summary = summarise_seed_groups(members=members)
    assert summary.loc[0, "member_count"] == 2
    assert summary.loc[0, "species_count"] == 2
    with pytest.raises(AppError, match="Select at least one"):
        collect_seed_group_members(
            connection=orthology_connection,
            seed_identifiers=(),
            group_type="hierarchical_orthogroup",
        )
    with pytest.raises(AppError, match="must be 'any' or 'all'"):
        collect_seed_group_members(
            connection=orthology_connection,
            seed_identifiers=("SEED_A",),
            group_type="hierarchical_orthogroup",
            match_mode="bad",  # type: ignore[arg-type]
        )
    with pytest.raises(AppError, match="Unsupported"):
        collect_seed_group_members(
            connection=orthology_connection,
            seed_identifiers=("SEED_A",),
            group_type="bad",  # type: ignore[arg-type]
        )
    with pytest.raises(AppError, match="between 1 and 100000"):
        collect_seed_group_members(
            connection=orthology_connection,
            seed_identifiers=("SEED_A",),
            group_type="hierarchical_orthogroup",
            maximum_rows=0,
        )


def test_curated_taxonomy_manifest_preserves_authoritative_labels() -> None:
    """The bundled manifest is intentionally limited to curated named species."""
    taxonomy = load_species_taxonomy()
    assert len(taxonomy) == 13
    tomato = taxonomy[
        taxonomy["canonical_species_name"] == "Solanum lycopersicum"
    ].iloc[0]
    assert tomato["source_species_name"] == "Lycopersicon_esculentum"
    assert int(tomato["taxon_id"]) == 4081


def test_seed_summary_rejects_incomplete_frames() -> None:
    """Pure summary validation prevents silent loss of group identity."""
    with pytest.raises(AppError, match="missing columns"):
        summarise_seed_groups(members=pd.DataFrame({"species": ["a"]}))
    empty = summarise_seed_groups(
        members=pd.DataFrame(
            columns=(
                "primary_group_type",
                "primary_group_id",
                "matched_seed_identifiers",
                "species",
                "raw_identifier",
            )
        )
    )
    assert empty.empty
    assert "member_count" in empty.columns


def test_unseeded_and_empty_membership_resources_remain_explicit() -> None:
    """Missing seed relations and empty sources return zeros, not negatives."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE hierarchical_membership("
        "group_id VARCHAR, species VARCHAR, raw_identifier VARCHAR)"
    )
    try:
        assert collect_seed_identifiers(connection=connection) == []
        assert collect_orthology_metrics(
            connection=connection,
            relation="hierarchical_membership",
        )["group_count"] == 0
        seeded = collect_orthology_group_summary(
            connection=connection,
            relation="hierarchical_membership",
            seeded_only=True,
        )
        assert seeded.empty
        assert "contains_e3_seed_evidence" in seeded.columns
        with pytest.raises(AppError, match="no sequence-bearing"):
            collect_seed_group_members(
                connection=connection,
                seed_identifiers=("SEED_A",),
                group_type="hierarchical_orthogroup",
            )
    finally:
        connection.close()


def test_orthology_schema_validation_is_defensive() -> None:
    """Incomplete relations fail before scientific summaries are attempted."""
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE bad_membership(group_id VARCHAR)")
    try:
        with pytest.raises(AppError, match="missing required columns"):
            collect_orthology_species(
                connection=connection,
                relation="bad_membership",
            )
    finally:
        connection.close()
