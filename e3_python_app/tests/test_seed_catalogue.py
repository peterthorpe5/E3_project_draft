"""Tests for the exact and annotated E3 seed catalogue."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from e3app.errors import AppError
from e3app.seed_catalogue import (
    build_seed_catalogue_query,
    collect_seed_catalogue,
    filter_seed_catalogue,
    seed_catalogue_capability,
)


@pytest.fixture
def seed_connection() -> duckdb.DuckDBPyConnection:
    """Create seed evidence with one exact sequence match."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE candidate_evidence("
        "cluster_id VARCHAR, matched_seed_ids_calculated VARCHAR, "
        "seed_protein_names VARCHAR, seed_categories VARCHAR, "
        "seed_review_statuses VARCHAR, seed_ubiquitin_go_statuses VARCHAR, "
        "seed_organisms VARCHAR)"
    )
    connection.execute(
        "INSERT INTO candidate_evidence VALUES "
        "('cluster_1', 'S1;S2', 'Seed one;Seed two', 'U-box', 'reviewed', "
        "'positive', 'Arabidopsis thaliana'), "
        "('cluster_2', 'S1', 'Seed one', 'U-box', 'reviewed', 'positive', "
        "'Arabidopsis thaliana')"
    )
    connection.execute(
        "CREATE TABLE known_e3_seeds("
        "seed_id VARCHAR, source_value VARCHAR, source_column VARCHAR, "
        "source_row INTEGER, source_path VARCHAR, seed_metadata_json VARCHAR)"
    )
    connection.execute(
        "INSERT INTO known_e3_seeds VALUES "
        "('S1', 'S1', 'accession', 2, 'seeds.tsv', "
        "'{\"protein_names\":\"Seed one\",\"e3_category\":\"U-box\","
        "\"organism\":\"Arabidopsis thaliana\",\"taxon_id\":\"3702\"}'), "
        "('S2', 'S2', 'accession', 3, 'seeds.tsv', "
        "'{\"protein_names\":\"Seed two\",\"category\":\"BTB\"}')"
    )
    connection.execute(
        "CREATE TABLE candidate_group_member_sequences("
        "parsed_accession VARCHAR, raw_identifier VARCHAR, species VARCHAR, "
        "protein_sequence VARCHAR, is_input_candidate BOOLEAN)"
    )
    connection.execute(
        "INSERT INTO candidate_group_member_sequences VALUES "
        "('S1', 'sp|S1|SEED_ONE', 'Arabidopsis_thaliana', 'MAAA', false), "
        "('OTHER', 'OTHER', 'Homo_sapiens', 'MBBB', false)"
    )
    try:
        yield connection
    finally:
        connection.close()


def test_seed_catalogue_collects_annotations_and_available_sequence(
    seed_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Seed identifiers remain distinct and exact mapped sequence is retained."""
    capability = seed_catalogue_capability(connection=seed_connection)
    assert capability["available"]
    assert capability["mode"] == "authority"
    assert capability["relation"] == "known_e3_seeds"
    assert capability["sequence_available"]
    result = collect_seed_catalogue(
        connection=seed_connection,
        maximum_rows=10,
    )
    assert result["seed_id"].tolist() == ["S1", "S2"]
    first = result.loc[result["seed_id"] == "S1"].iloc[0]
    assert first["source_cluster_count"] == 2
    assert first["source_cluster_ids"] == "cluster_1;cluster_2"
    assert first["seed_protein_names"] == "Seed one"
    assert first["seed_category"] == "U-box"
    assert first["seed_taxon_id"] == "3702"
    assert first["associated_seed_protein_names"] == ""
    assert first["annotation_scope"] == "exact seed authority row"
    assert first["protein_sequence"] == "MAAA"
    assert first["protein_sequence_length"] == 4
    assert first["sequence_available"]
    second = result.loc[result["seed_id"] == "S2"].iloc[0]
    assert second["protein_sequence"] == ""
    assert not second["sequence_available"]


def test_seed_catalogue_falls_back_to_cluster_associated_annotations() -> None:
    """Older resources remain useful without overstating annotation scope."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE candidate_evidence("
            "cluster_id VARCHAR, matched_seed_ids_calculated VARCHAR, "
            "seed_protein_names VARCHAR)"
        )
        connection.execute(
            "INSERT INTO candidate_evidence VALUES "
            "('cluster_1', 'S1;S2', 'Seed one;Seed two'), "
            "('cluster_2', 'S1', 'Seed one')"
        )
        capability = seed_catalogue_capability(connection=connection)
        assert capability["mode"] == "cluster_summary"
        result = collect_seed_catalogue(
            connection=connection,
            maximum_rows=10,
        )
    finally:
        connection.close()
    first = result.loc[result["seed_id"] == "S1"].iloc[0]
    assert "Seed one" in first["associated_seed_protein_names"]
    assert first["seed_protein_names"] == ""
    assert first["annotation_scope"].startswith("cluster-associated")


def test_minimal_seed_authority_retains_raw_identifier_sequence() -> None:
    """An authority-only release works without metadata, links or parsed IDs."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE known_e3_seeds(seed_id VARCHAR)")
        connection.execute("INSERT INTO known_e3_seeds VALUES ('RAW_SEED')")
        connection.execute(
            "CREATE TABLE candidate_group_member_sequences("
            "raw_identifier VARCHAR, protein_sequence VARCHAR)"
        )
        connection.execute(
            "INSERT INTO candidate_group_member_sequences VALUES "
            "('RAW_SEED', 'MPEPTIDE')"
        )
        result = collect_seed_catalogue(
            connection=connection,
            maximum_rows=10,
        )
    finally:
        connection.close()
    assert result.loc[0, "seed_id"] == "RAW_SEED"
    assert result.loc[0, "seed_protein_names"] == ""
    assert result.loc[0, "source_cluster_count"] == 0
    assert result.loc[0, "sequence_species"] == ""
    assert result.loc[0, "protein_sequence"] == "MPEPTIDE"


def test_seed_capability_skips_incomplete_preferred_relations() -> None:
    """Source selection continues past relations lacking seed identifiers."""
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE known_e3_seeds(value VARCHAR)")
        connection.execute("CREATE TABLE candidate_evidence(cluster_id VARCHAR)")
        connection.execute(
            "CREATE TABLE e3_cluster_candidate_evidence("
            "representative_id VARCHAR, known_e3_seed_ids VARCHAR)"
        )
        capability = seed_catalogue_capability(connection=connection)
    finally:
        connection.close()
    assert capability["mode"] == "cluster_summary"
    assert capability["relation"] == "e3_cluster_candidate_evidence"
    assert not capability["sequence_available"]


def test_seed_catalogue_filter_accepts_pasted_terms() -> None:
    """Several literal identifiers or annotations can select catalogue rows."""
    frame = pd.DataFrame(
        data={
            "seed_id": ["S1", "S2", "S3"],
            "associated_seed_protein_names": ["Alpha", "Beta", "Gamma"],
            "protein_sequence": ["MA", "MB", "MC"],
        }
    )
    selected = filter_seed_catalogue(frame=frame, query="S1\nBeta")
    assert selected["seed_id"].tolist() == ["S1", "S2"]
    assert filter_seed_catalogue(frame=frame, query="").equals(frame)


def test_seed_catalogue_validates_source_and_limits() -> None:
    """Unavailable seed evidence and unsafe row bounds fail explicitly."""
    connection = duckdb.connect(":memory:")
    try:
        capability = seed_catalogue_capability(connection=connection)
        assert not capability["available"]
        with pytest.raises(AppError, match="No E3 seed evidence"):
            collect_seed_catalogue(connection=connection)
        capability["available"] = True
        with pytest.raises(AppError, match="between 1 and 100000"):
            build_seed_catalogue_query(
                capability=capability,
                maximum_rows=0,
            )
        with pytest.raises(AppError, match="between 1 and 100000"):
            build_seed_catalogue_query(
                capability=capability,
                maximum_rows=100_001,
            )
    finally:
        connection.close()


def test_seed_catalogue_wraps_duckdb_query_failures(
    seed_connection: duckdb.DuckDBPyConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtime SQL errors are translated into the app's controlled exception."""
    monkeypatch.setattr(
        "e3app.seed_catalogue.build_seed_catalogue_query",
        lambda **_: "SELECT * FROM relation_that_does_not_exist",
    )
    with pytest.raises(AppError, match="Could not collect the E3 seed catalogue"):
        collect_seed_catalogue(connection=seed_connection)
