"""Tests for orthology-aware C-terminal sequence conservation."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

import e3app.terminal_sequences as terminal_module
from e3app.errors import AppError
from e3app.terminal_sequences import (
    collect_terminal_group_members,
    collect_terminal_group_summary,
    normalise_terminal_sequence,
    terminal_member_fasta_frame,
    terminal_sequence_capability,
)

PLANTS = (
    "Arabidopsis_thaliana",
    "Oryza_sativa",
    "Zea_mays",
    "Hordeum_vulgare",
    "Solanum_lycopersicum",
    "Triticum_aestivum",
)


@pytest.fixture
def terminal_connection() -> duckdb.DuckDBPyConnection:
    """Create candidate-bounded HOG and OG sequence evidence."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE candidate_group_member_sequences(
            cluster_id VARCHAR,
            record_type VARCHAR,
            group_id VARCHAR,
            species VARCHAR,
            internal_id VARCHAR,
            raw_identifier VARCHAR,
            parsed_accession VARCHAR,
            parsed_entry VARCHAR,
            review_status VARCHAR,
            mapping_status VARCHAR,
            is_input_candidate BOOLEAN,
            candidate_accessions_for_cluster VARCHAR,
            sequence_length INTEGER,
            protein_sequence VARCHAR
        )
        """
    )
    rows = [
        (
            "c1", "HIERARCHICAL_ORTHOGROUP", "N0.HOG1", "Arabidopsis_thaliana",
            "a1", "sp|A1|A1_ARATH", "A1", "A1_ARATH", "REVIEWED", "MAPPED",
            True, "A1", 4, "AAAN",
        ),
        (
            "c2", "HIERARCHICAL_ORTHOGROUP", "N0.HOG1", "Arabidopsis_thaliana",
            "a1", "sp|A1|A1_ARATH", "A1", "A1_ARATH", "REVIEWED", "MAPPED",
            False, "A2", 4, "AAAN",
        ),
        (
            "c1", "HIERARCHICAL_ORTHOGROUP", "N0.HOG1", "Oryza_sativa",
            "r1", "sp|R1|R1_ORYSA", "R1", "R1_ORYSA", "REVIEWED", "MAPPED",
            False, "A1", 4, "AAAN",
        ),
        (
            "c1", "HIERARCHICAL_ORTHOGROUP", "N0.HOG1", "Zea_mays",
            "z1", "sp|Z1|Z1_MAIZE", "Z1", "Z1_MAIZE", "REVIEWED", "MAPPED",
            False, "A1", 4, "AAGN",
        ),
        (
            "c1", "HIERARCHICAL_ORTHOGROUP", "N0.HOG1", "Hordeum_vulgare",
            "b1", "sp|B1|B1_HORVU", "B1", "B1_HORVU", "REVIEWED", "MAPPED",
            False, "A1", 4, "AAAN",
        ),
        (
            "c1", "HIERARCHICAL_ORTHOGROUP", "N0.HOG1", "Solanum_lycopersicum",
            "t1", "sp|T1|T1_SOLLC", "T1", "T1_SOLLC", "REVIEWED", "MAPPED",
            False, "A1", 4, "AAAQ",
        ),
        (
            "c1", "HIERARCHICAL_ORTHOGROUP", "N0.HOG1", "Triticum_aestivum",
            "w1", "sp|W1|W1_WHEAT", "W1", "W1_WHEAT", "REVIEWED", "MAPPED",
            False, "A1", None, None,
        ),
        (
            "c1", "HIERARCHICAL_ORTHOGROUP", "N0.HOG1", "Homo_sapiens",
            "h1", "sp|H1|H1_HUMAN", "H1", "H1_HUMAN", "REVIEWED", "MAPPED",
            False, "A1", 4, "AAAQ",
        ),
        (
            "c3", "HIERARCHICAL_ORTHOGROUP", "N0.HOG2", "Arabidopsis_thaliana",
            "a2", "sp|A2|A2_ARATH", "A2", "A2_ARATH", "REVIEWED", "MAPPED",
            True, "A2", 4, "AAAQ",
        ),
        (
            "c3", "HIERARCHICAL_ORTHOGROUP", "N0.HOG2", "Oryza_sativa",
            "r2", "sp|R2|R2_ORYSA", "R2", "R2_ORYSA", "REVIEWED", "MAPPED",
            False, "A2", 4, "AAAN",
        ),
        (
            "c1", "ORTHOGROUP", "OG1", "Arabidopsis_thaliana", "a1",
            "sp|A1|A1_ARATH", "A1", "A1_ARATH", "REVIEWED", "MAPPED",
            True, "A1", 4, "AAAN",
        ),
        (
            "c1", "ORTHOGROUP", "OG1", "Oryza_sativa", "r1",
            "sp|R1|R1_ORYSA", "R1", "R1_ORYSA", "REVIEWED", "MAPPED",
            False, "A1", 4, "AAAN",
        ),
    ]
    connection.executemany(
        "INSERT INTO candidate_group_member_sequences VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    try:
        yield connection
    finally:
        connection.close()


def test_terminal_sequence_normalisation_is_exact_and_defensive() -> None:
    """Single and multi-residue sequences normalise without wildcard matching."""
    assert normalise_terminal_sequence(value=" n ") == "N"
    assert normalise_terminal_sequence(value="gn") == "GN"
    assert normalise_terminal_sequence(value="JOUXZ") == "JOUXZ"
    with pytest.raises(AppError, match="at least one"):
        normalise_terminal_sequence(value=" ")
    with pytest.raises(AppError, match="one-letter"):
        normalise_terminal_sequence(value="N*")
    with pytest.raises(AppError, match="cannot exceed"):
        normalise_terminal_sequence(value="N" * 51)


def test_capability_reports_candidate_scope_and_prefers_full_relation(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Capability text does not overstate candidate-bounded sequence coverage."""
    capability = terminal_sequence_capability(connection=terminal_connection)
    assert capability.available
    assert capability.relation == "candidate_group_member_sequences"
    assert capability.candidate_bounded
    assert "candidate-linked" in capability.scope_label

    terminal_connection.execute(
        "CREATE VIEW orthology_group_member_sequences AS "
        "SELECT * FROM candidate_group_member_sequences"
    )
    full = terminal_sequence_capability(connection=terminal_connection)
    assert full.relation == "orthology_group_member_sequences"
    assert not full.candidate_bounded


def test_capability_fails_closed_for_missing_sequence_columns() -> None:
    """An incomplete relation is unavailable instead of silently inferred."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE candidate_group_member_sequences(group_id VARCHAR)"
    )
    capability = terminal_sequence_capability(connection=connection)
    connection.close()
    assert not capability.available
    assert "missing required columns" in capability.reason
    assert "protein_sequence" in capability.missing_columns

    empty = duckdb.connect(":memory:")
    absent = terminal_sequence_capability(connection=empty)
    assert not absent.available
    assert absent.relation is None
    with pytest.raises(AppError, match="no supported"):
        collect_terminal_group_summary(
            connection=empty,
            group_type="hierarchical_orthogroup",
            plant_species=PLANTS,
        )
    empty.close()


def test_minimal_relation_supports_missing_optional_metadata() -> None:
    """Only the documented core columns are required for the scientific screen."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE candidate_group_member_sequences("
        "record_type VARCHAR, group_id VARCHAR, species VARCHAR, "
        "raw_identifier VARCHAR, protein_sequence VARCHAR)"
    )
    connection.execute(
        "INSERT INTO candidate_group_member_sequences VALUES "
        "('HIERARCHICAL_ORTHOGROUP', 'N0.MINIMAL', "
        "'Arabidopsis_thaliana', 'minimal_member', 'MN')"
    )
    summary = collect_terminal_group_summary(
        connection=connection,
        group_type="hierarchical_orthogroup",
        terminal_sequence="N",
        minimum_match_fraction=1.0,
        minimum_plant_members=1,
        minimum_plant_species=1,
        require_arabidopsis_match=True,
        plant_species=(
            "",
            "Homo_sapiens",
            "Arabidopsis_thaliana",
            "Arabidopsis_thaliana",
        ),
    )
    assert summary["group_id"].tolist() == ["N0.MINIMAL"]
    members = collect_terminal_group_members(
        connection=connection,
        group_type="hierarchical_orthogroup",
        group_id="N0.MINIMAL",
        terminal_sequence="N",
        plant_species=("Arabidopsis_thaliana",),
    )
    connection.close()
    assert pd.isna(members.loc[0, "parsed_accession"])
    assert bool(members.loc[0, "terminal_match"])


def test_group_summary_uses_plant_members_and_keeps_human_separate(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """The default 80% screen deduplicates links and excludes human from plants."""
    result = collect_terminal_group_summary(
        connection=terminal_connection,
        group_type="hierarchical_orthogroup",
        terminal_sequence="N",
        minimum_match_fraction=0.80,
        minimum_plant_members=2,
        minimum_plant_species=2,
        require_arabidopsis_match=True,
        plant_species=PLANTS,
        maximum_rows=100,
    )
    assert result["group_id"].tolist() == ["N0.HOG1"]
    row = result.iloc[0]
    assert row["plant_member_count"] == 6
    assert row["assessed_plant_member_count"] == 5
    assert row["unavailable_plant_sequence_count"] == 1
    assert row["matching_plant_member_count"] == 4
    assert row["plant_member_match_fraction"] == pytest.approx(0.8)
    assert row["assessed_plant_species_count"] == 5
    assert row["matching_plant_species_count"] == 4
    assert row["arabidopsis_match_status"] == "ALL_MATCH"
    assert row["human_comparison_status"] == "NO_MATCH"
    assert "Solanum_lycopersicum" in row["plant_species_without_a_match"]


def test_group_summary_supports_multi_residue_sequences_and_og_view(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Exact multi-residue endings and the legacy OG selector are supported."""
    multi = collect_terminal_group_summary(
        connection=terminal_connection,
        group_type="hierarchical_orthogroup",
        terminal_sequence="GN",
        minimum_match_fraction=0.10,
        minimum_plant_members=2,
        minimum_plant_species=2,
        require_arabidopsis_match=False,
        plant_species=PLANTS,
    )
    assert multi.loc[multi["group_id"] == "N0.HOG1", "terminal_sequence"].item() == "GN"
    assert multi.loc[
        multi["group_id"] == "N0.HOG1", "matching_plant_member_count"
    ].item() == 1

    orthogroups = collect_terminal_group_summary(
        connection=terminal_connection,
        group_type="orthogroup",
        terminal_sequence="N",
        minimum_match_fraction=1.0,
        minimum_plant_members=2,
        minimum_plant_species=2,
        require_arabidopsis_match=True,
        plant_species=PLANTS,
    )
    assert orthogroups["group_id"].tolist() == ["OG1"]


def test_member_detail_preserves_scope_status_and_builds_fasta(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Selected-group members expose exact terminal context and unique FASTA IDs."""
    members = collect_terminal_group_members(
        connection=terminal_connection,
        group_type="hierarchical_orthogroup",
        group_id="N0.HOG1",
        terminal_sequence="N",
        plant_species=PLANTS,
        terminal_context_length=3,
    )
    assert len(members) == 7
    arabidopsis = members.loc[members["parsed_accession"] == "A1"].iloc[0]
    assert arabidopsis["taxonomic_role"] == "TARGET_PLANT"
    assert bool(arabidopsis["terminal_match"])
    assert arabidopsis["c_terminal_context"] == "AAN"
    assert arabidopsis["source_cluster_ids"] == "c1;c2"
    human = members.loc[members["parsed_accession"] == "H1"].iloc[0]
    assert human["taxonomic_role"] == "HUMAN_COMPARISON"
    missing = members.loc[members["parsed_accession"] == "W1"].iloc[0]
    assert not bool(missing["sequence_available"])
    assert pd.isna(missing["terminal_match"])

    fasta = terminal_member_fasta_frame(members=members)
    assert len(fasta) == 6
    assert fasta["fasta_identifier"].is_unique
    assert fasta["fasta_identifier"].str.startswith("N0.HOG1|").all()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"group_type": "bad"}, "Unsupported"),
        ({"minimum_match_fraction": 1.1}, "between 0 and 1"),
        ({"minimum_plant_members": 0}, "between 1"),
        ({"minimum_plant_species": 0}, "between 1"),
        ({"maximum_rows": 0}, "between 1"),
        ({"plant_species": ()}, "No reviewed target-plant"),
    ],
)
def test_group_summary_rejects_invalid_controls(
    terminal_connection: duckdb.DuckDBPyConnection,
    overrides: dict[str, object],
    message: str,
) -> None:
    """Invalid scientific and query controls fail with a useful message."""
    arguments: dict[str, object] = {
        "connection": terminal_connection,
        "group_type": "hierarchical_orthogroup",
        "terminal_sequence": "N",
        "minimum_match_fraction": 0.8,
        "minimum_plant_members": 2,
        "minimum_plant_species": 2,
        "require_arabidopsis_match": True,
        "plant_species": PLANTS,
        "maximum_rows": 100,
    }
    arguments.update(overrides)
    with pytest.raises(AppError, match=message):
        collect_terminal_group_summary(**arguments)  # type: ignore[arg-type]


def test_member_and_fasta_validation_fail_closed(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Blank groups, invalid bounds and malformed FASTA inputs are rejected."""
    with pytest.raises(AppError, match="non-empty"):
        collect_terminal_group_members(
            connection=terminal_connection,
            group_type="hierarchical_orthogroup",
            group_id=" ",
            plant_species=PLANTS,
        )
    with pytest.raises(AppError, match="between 1"):
        collect_terminal_group_members(
            connection=terminal_connection,
            group_type="hierarchical_orthogroup",
            group_id="N0.HOG1",
            plant_species=PLANTS,
            terminal_context_length=0,
        )
    with pytest.raises(AppError, match="missing columns"):
        terminal_member_fasta_frame(members=pd.DataFrame({"group_id": ["G"]}))

    members = collect_terminal_group_members(
        connection=terminal_connection,
        group_type="hierarchical_orthogroup",
        group_id="N0.HOG1",
        plant_species=PLANTS,
    )
    duplicated = pd.concat([members.iloc[[0]], members.iloc[[0]]], ignore_index=True)
    with pytest.raises(AppError, match="not unique"):
        terminal_member_fasta_frame(members=duplicated)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"minimum_match_fraction": object()}, "between 0 and 1"),
        ({"minimum_plant_members": True}, "positive integer"),
        ({"minimum_plant_members": object()}, "positive integer"),
    ],
)
def test_non_numeric_controls_fail_closed(
    terminal_connection: duckdb.DuckDBPyConnection,
    overrides: dict[str, object],
    message: str,
) -> None:
    """Non-numeric scientific controls cannot leak into a DuckDB query."""
    arguments: dict[str, object] = {
        "connection": terminal_connection,
        "group_type": "hierarchical_orthogroup",
        "plant_species": PLANTS,
    }
    arguments.update(overrides)
    with pytest.raises(AppError, match=message):
        collect_terminal_group_summary(**arguments)  # type: ignore[arg-type]


def test_query_failures_are_wrapped_with_context(
    terminal_connection: duckdb.DuckDBPyConnection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected database failures become controlled application errors."""
    monkeypatch.setattr(
        terminal_module,
        "_member_ctes",
        lambda **_kwargs: ("broken SQL", []),
    )
    with pytest.raises(AppError, match="group conservation"):
        collect_terminal_group_summary(
            connection=terminal_connection,
            group_type="hierarchical_orthogroup",
            plant_species=PLANTS,
        )
    with pytest.raises(AppError, match="group members"):
        collect_terminal_group_members(
            connection=terminal_connection,
            group_type="hierarchical_orthogroup",
            group_id="N0.HOG1",
            plant_species=PLANTS,
        )
