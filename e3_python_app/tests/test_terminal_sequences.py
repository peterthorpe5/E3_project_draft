"""Tests for orthology-aware C-terminal sequence conservation."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

import e3app.terminal_sequences as terminal_module
from e3app.errors import AppError
from e3app.taxonomy import (
    CompiledTaxonomyFilters,
    compile_taxonomy_filters,
    load_taxonomy_authority,
    taxonomy_filters,
)
from e3app.terminal_sequences import (
    collect_terminal_group_members,
    collect_terminal_group_summary,
    collect_terminal_species,
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


def test_screen_counts_are_unlimited_and_retained_for_empty_results(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """A bounded result cannot be mistaken for the full qualifying-group count."""
    result = collect_terminal_group_summary(
        connection=terminal_connection, group_type="hierarchical_orthogroup",
        plant_species=PLANTS, minimum_match_fraction=0.5,
        require_arabidopsis_match=False, maximum_rows=1,
    )
    assert len(result) == 1
    assert result.attrs["screen_audit"] == {
        "source_group_count": 2, "plant_group_count": 2, "assessable_group_count": 2,
        "taxonomy_group_count": 2, "qualifying_group_count": 2,
        "returned_group_count": 1, "result_limit": 1,
    }
    empty = collect_terminal_group_summary(
        connection=terminal_connection, group_type="hierarchical_orthogroup",
        plant_species=PLANTS, minimum_match_fraction=1.0,
    )
    assert empty.empty
    assert empty.attrs["screen_audit"]["qualifying_group_count"] == 0
    assert empty.attrs["screen_audit"]["source_group_count"] == 2
    assert "group_id" in empty.columns
    terminal_connection.execute("DELETE FROM candidate_group_member_sequences")
    no_source = collect_terminal_group_summary(
        connection=terminal_connection, group_type="hierarchical_orthogroup", plant_species=PLANTS,
    )
    assert no_source.empty
    assert no_source.attrs["screen_audit"]["source_group_count"] == 0


def test_species_and_sequence_coverage_gates_are_independent(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Optional gates detect species breadth and incomplete sequence coverage separately."""
    normal = collect_terminal_group_summary(
        connection=terminal_connection, group_type="hierarchical_orthogroup", plant_species=PLANTS,
    )
    assert normal.loc[0, "plant_sequence_coverage_fraction"] == pytest.approx(5 / 6)
    for kwargs in (
        {"minimum_species_match_fraction": 0.81},
        {"minimum_sequence_coverage_fraction": 0.84},
    ):
        filtered = collect_terminal_group_summary(
            connection=terminal_connection, group_type="hierarchical_orthogroup",
            plant_species=PLANTS, **kwargs,
        )
        assert filtered.empty
    accepted = collect_terminal_group_summary(
        connection=terminal_connection, group_type="hierarchical_orthogroup",
        plant_species=PLANTS, minimum_species_match_fraction=0.8,
        minimum_sequence_coverage_fraction=0.8,
    )
    assert len(accepted) == 1


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"required_exact_taxon_ids": [9606]}, ["N0.HOG1"]),
        ({"required_exact_taxon_ids": [3702, 4530]}, ["N0.HOG1", "N0.HOG2"]),
        ({"include_clade_taxon_ids": [4479]}, ["N0.HOG1", "N0.HOG2"]),
        ({"only_clade_taxon_ids": [33090]}, ["N0.HOG2"]),
        ({"excluded_exact_taxon_ids": [9606]}, ["N0.HOG2"]),
        ({"excluded_clade_taxon_ids": [33208]}, ["N0.HOG2"]),
        ({"include_clade_taxon_ids": [4479], "excluded_exact_taxon_ids": [9606]}, ["N0.HOG2"]),
    ],
)
def test_taxonomy_filters_apply_to_all_published_members_before_limiting(
    terminal_connection: duckdb.DuckDBPyConnection, filters: dict[str, list[int]],
    expected: list[str],
) -> None:
    """Taxonomic predicates test membership, independent of terminal sequence status."""
    authority = load_taxonomy_authority()
    # The release uses an accepted tomato name rather than the packaged source alias.
    taxonomy = authority.species_taxonomy.copy()
    taxonomy.loc[
        taxonomy["source_species_name"] == "Lycopersicon_esculentum", "source_species_name"
    ] = "Solanum_lycopersicum"
    compiled = compile_taxonomy_filters(
        filters=taxonomy_filters(**filters), species_taxonomy=taxonomy,
        available_species=collect_terminal_species(
            connection=terminal_connection, group_type="hierarchical_orthogroup",
        ),
        taxonomy_nodes=authority.taxonomy_nodes,
    )
    result = collect_terminal_group_summary(
        connection=terminal_connection, group_type="hierarchical_orthogroup",
        plant_species=PLANTS, minimum_match_fraction=0.5,
        require_arabidopsis_match=False, compiled_taxonomy=compiled,
    )
    assert result["group_id"].tolist() == expected
    assert result.attrs["screen_audit"]["qualifying_group_count"] == len(expected)
    if expected == ["N0.HOG1"]:
        assert result.loc[0, "plant_member_match_fraction"] == 0.8


def test_only_clade_rejects_unmapped_members_with_unavailable_sequences(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Unavailable termini do not conceal outside/unmapped group membership."""
    authority = load_taxonomy_authority()
    terminal_connection.execute(
        "INSERT INTO candidate_group_member_sequences(record_type, group_id, species, "
        "raw_identifier, protein_sequence) VALUES "
        "('HIERARCHICAL_ORTHOGROUP', 'N0.HOG2', 'Unmapped_species', 'unknown1', NULL)"
    )
    compiled = compile_taxonomy_filters(
        filters=taxonomy_filters(only_clade_taxon_ids=[33090]),
        species_taxonomy=authority.species_taxonomy,
        available_species=collect_terminal_species(
            connection=terminal_connection, group_type="hierarchical_orthogroup",
        ), taxonomy_nodes=authority.taxonomy_nodes,
    )
    result = collect_terminal_group_summary(
        connection=terminal_connection, group_type="hierarchical_orthogroup",
        plant_species=PLANTS, minimum_match_fraction=0.5,
        require_arabidopsis_match=False, compiled_taxonomy=compiled,
    )
    assert result.empty
    assert result.attrs["screen_audit"]["taxonomy_group_count"] == 0


def test_custom_source_labels_resolve_human_and_arabidopsis_by_reviewed_taxonomy(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Renaming a workflow species label cannot change its experimental/comparison role."""
    terminal_connection.execute(
        "UPDATE candidate_group_member_sequences SET species = 'arath_input' "
        "WHERE species = 'Arabidopsis_thaliana'"
    )
    terminal_connection.execute(
        "UPDATE candidate_group_member_sequences SET species = 'human_input' "
        "WHERE species = 'Homo_sapiens'"
    )
    plants = tuple("arath_input" if value == "Arabidopsis_thaliana" else value for value in PLANTS)
    result = collect_terminal_group_summary(
        connection=terminal_connection, group_type="hierarchical_orthogroup",
        plant_species=(*plants, "human_input"), human_species=("human_input",),
        arabidopsis_species=("arath_input",),
    )
    assert result["group_id"].tolist() == ["N0.HOG1"]
    assert result.loc[0, "plant_member_match_fraction"] == 0.8
    assert result.loc[0, "arabidopsis_matching_identifiers"] == "A1"
    assert result.loc[0, "human_identifiers"] == "H1"
    members = collect_terminal_group_members(
        connection=terminal_connection, group_type="hierarchical_orthogroup", group_id="N0.HOG1",
        plant_species=plants, human_species=("human_input",), arabidopsis_species=("arath_input",),
    )
    assert members.loc[members["parsed_accession"] == "H1", "taxonomic_role"].item() == (
        "HUMAN_COMPARISON"
    )


def test_required_exact_taxon_accepts_one_of_multiple_reviewed_source_aliases(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Exact species requirements do not demand every alternate source label of one taxon."""
    authority = load_taxonomy_authority()
    alias = authority.species_taxonomy.loc[
        authority.species_taxonomy["source_species_name"] == "Arabidopsis_thaliana"
    ].copy()
    alias["source_species_name"] = "arath_second_input"
    taxonomy = pd.concat(objs=[authority.species_taxonomy, alias], ignore_index=True)
    compiled = compile_taxonomy_filters(
        filters=taxonomy_filters(required_exact_taxon_ids=[3702]), species_taxonomy=taxonomy,
        available_species=(*PLANTS, "Homo_sapiens", "arath_second_input"),
        taxonomy_nodes=authority.taxonomy_nodes,
    )
    result = collect_terminal_group_summary(
        connection=terminal_connection, group_type="hierarchical_orthogroup",
        plant_species=PLANTS, compiled_taxonomy=compiled,
    )
    assert result["group_id"].tolist() == ["N0.HOG1"]


def test_optional_description_fields_and_missing_seed_flags_remain_nullable() -> None:
    """A minimal future full authority may provide names without E3 seed annotations."""
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE orthology_group_member_sequences(record_type VARCHAR, group_id VARCHAR, "
            "species VARCHAR, raw_identifier VARCHAR, protein_sequence VARCHAR, "
            "protein_names VARCHAR)"
        )
        connection.execute(
            "INSERT INTO orthology_group_member_sequences VALUES "
            "('HIERARCHICAL_ORTHOGROUP', 'N0.NAME', 'Arabidopsis_thaliana', "
            "'id1', 'MN', 'Protein name')"
        )
        members = collect_terminal_group_members(
            connection=connection, group_type="hierarchical_orthogroup", group_id="N0.NAME",
            plant_species=PLANTS, human_species=(), arabidopsis_species=(),
        )
        assert members.loc[0, "protein_description"] == "Protein name"
        assert pd.isna(members.loc[0, "is_input_candidate"])
        assert not members.loc[0, "is_human"]
        assert not members.loc[0, "is_arabidopsis"]


@pytest.mark.parametrize("value", [True, 1.5, float("inf"), float("nan"), "1.5"])
def test_integer_controls_reject_non_integral_and_non_finite_values(
    terminal_connection: duckdb.DuckDBPyConnection, value: object,
) -> None:
    """Member/result limits cannot silently truncate a non-integral control."""
    with pytest.raises(AppError, match="positive integer"):
        collect_terminal_group_summary(
            connection=terminal_connection, group_type="hierarchical_orthogroup",
            plant_species=PLANTS, maximum_rows=value,
        )


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -0.1, 1.1])
def test_optional_fraction_controls_are_defensive(
    terminal_connection: duckdb.DuckDBPyConnection, value: object,
) -> None:
    """Independent species/coverage gates reject invalid fractions before query execution."""
    with pytest.raises(AppError, match="between 0 and 1"):
        collect_terminal_group_summary(
            connection=terminal_connection, group_type="hierarchical_orthogroup",
            plant_species=PLANTS, minimum_species_match_fraction=value,
        )


def test_species_listing_uses_exact_group_type_and_missing_authority_fails(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Taxonomy choices are compiled from the active HOG or OG membership only."""
    og_species = collect_terminal_species(connection=terminal_connection, group_type="orthogroup")
    assert og_species == ("Arabidopsis_thaliana", "Oryza_sativa")
    with duckdb.connect(":memory:") as connection:
        with pytest.raises(AppError, match="no supported"):
            collect_terminal_species(connection=connection, group_type="orthogroup")


def test_species_listing_wraps_database_errors(
    terminal_connection: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed data read has a controlled diagnostic rather than an uncaught traceback."""
    capability = terminal_sequence_capability(connection=terminal_connection)
    monkeypatch.setattr(
        terminal_module, "terminal_sequence_capability", lambda **_kwargs: capability,
    )
    terminal_connection.close()
    with pytest.raises(AppError, match="list C-terminal"):
        collect_terminal_species(connection=terminal_connection, group_type="orthogroup")


def test_only_predicate_with_no_mapped_allowed_species_is_false() -> None:
    """An empty reviewed only-in scope cannot admit every group."""
    compiled = CompiledTaxonomyFilters(
        required_exact_species=(), include_clade_species=(), only_allowed_species=(),
        excluded_species=(), mapped_species=(), selected_scope_species=(), species_taxon_ids=(),
    )
    assert terminal_module._taxonomy_group_predicate(compiled_taxonomy=compiled) == ("FALSE", [])


def test_invalid_sequence_species_list_and_arabidopsis_switch_are_rejected(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Text and Boolean controls cannot be silently coerced into biological input."""
    with pytest.raises(AppError, match="must be text"):
        normalise_terminal_sequence(value=True)
    with pytest.raises(AppError, match="sequence of source labels"):
        collect_terminal_group_summary(
            connection=terminal_connection, group_type="hierarchical_orthogroup",
            plant_species="Arabidopsis_thaliana",
        )
    with pytest.raises(AppError, match="must be Boolean"):
        collect_terminal_group_summary(
            connection=terminal_connection, group_type="hierarchical_orthogroup",
            plant_species=PLANTS, require_arabidopsis_match="False",
        )
