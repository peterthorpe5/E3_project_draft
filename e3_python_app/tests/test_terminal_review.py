"""Tests for readable conservation evidence and exact, nullable annotation joins."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from test_terminal_sequences import PLANTS, terminal_connection

import e3app.terminal_review as review
from e3app.errors import AppError
from e3app.taxonomy import load_taxonomy_authority
from e3app.terminal_review import (
    annotate_terminal_members,
    enrich_terminal_group_summary,
    filter_terminal_members,
    terminal_member_display,
    terminal_screen_provenance,
    terminal_species_labels,
    terminal_species_summary,
    terminal_summary_display,
)
from e3app.terminal_sequences import collect_terminal_group_members, collect_terminal_group_summary


@pytest.fixture
def annotated_connection(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> duckdb.DuckDBPyConnection:
    """Add linked seed, group ranking and exact member domain evidence."""
    terminal_connection.execute(
        "CREATE TABLE candidate_master_results(primary_group_id VARCHAR, "
        "primary_group_type VARCHAR, final_rank INTEGER, "
        "prestructure_evolutionary_group_rank INTEGER)"
    )
    terminal_connection.execute(
        "INSERT INTO candidate_master_results VALUES "
        "('N0.HOG1', 'HIERARCHICAL_ORTHOGROUP', 17, 4), "
        "('N0.HOG1', 'HIERARCHICAL_ORTHOGROUP', 18, 4), "
        "('N0.HOG1', 'ORTHOGROUP', 1, 1)"
    )
    terminal_connection.execute(
        "CREATE TABLE candidate_evidence(representative_id VARCHAR, "
        "seed_protein_names VARCHAR, seed_categories VARCHAR, matched_seed_ids_calculated VARCHAR)"
    )
    terminal_connection.execute(
        "INSERT INTO candidate_evidence VALUES ('c1', 'Seed protein one', 'RING', 'A1'), "
        "('c2', 'Seed protein two', 'RING', 'A2'), ('elsewhere', 'Unrelated', 'HECT', 'X1')"
    )
    terminal_connection.execute(
        "CREATE TABLE domain_summary(cluster_id VARCHAR, primary_group_id VARCHAR, "
        "primary_group_type VARCHAR, species_column VARCHAR, member_accession VARCHAR, "
        "domain_support_status VARCHAR, e3_families VARCHAR, e3_domain_accessions VARCHAR)"
    )
    terminal_connection.execute(
        "INSERT INTO domain_summary VALUES "
        "('c1', 'N0.HOG1', 'HIERARCHICAL_ORTHOGROUP', 'Arabidopsis_thaliana', 'A1', "
        "'SUPPORTED', 'RING', 'PF00097'), "
        "('c2', 'N0.HOG1', 'HIERARCHICAL_ORTHOGROUP', 'Arabidopsis_thaliana', 'A1', "
        "'SUPPORTED', 'RING', 'PF00097'), "
        "('c1', 'N0.HOG1', 'HIERARCHICAL_ORTHOGROUP', 'Oryza_sativa', 'R1', "
        "'ANNOTATION_UNAVAILABLE', NULL, NULL), "
        "('c1', 'WRONG_GROUP', 'HIERARCHICAL_ORTHOGROUP', 'Arabidopsis_thaliana', 'A1', "
        "'WRONG_GROUP', 'HECT', 'WRONG'), "
        "('wrong_cluster', 'N0.HOG1', 'HIERARCHICAL_ORTHOGROUP', 'Arabidopsis_thaliana', 'A1', "
        "'WRONG_CLUSTER', 'HECT', 'WRONG'), "
        "('c1', 'N0.HOG1', 'HIERARCHICAL_ORTHOGROUP', 'Homo_sapiens', 'A1', "
        "'WRONG_SPECIES', 'HECT', 'WRONG'), "
        "('c1', 'N0.HOG1', 'ORTHOGROUP', 'Arabidopsis_thaliana', 'A1', "
        "'WRONG_TYPE', 'HECT', 'WRONG')"
    )
    return terminal_connection


def _summary(*, connection: object) -> pd.DataFrame:
    """Collect the known 80% plant screen used by review tests."""
    return collect_terminal_group_summary(
        connection=connection, group_type="hierarchical_orthogroup", plant_species=PLANTS,
    )


def _members(*, connection: object) -> pd.DataFrame:
    """Collect complete member states for the known selected group."""
    return collect_terminal_group_members(
        connection=connection, group_type="hierarchical_orthogroup", group_id="N0.HOG1",
        plant_species=PLANTS,
    )


def test_species_labels_keep_accepted_names_taxon_ids_and_source_labels() -> None:
    """A renamed tomato label and custom alias retain their reviewed accepted name."""
    taxonomy = load_taxonomy_authority().species_taxonomy
    labels = terminal_species_labels(species_taxonomy=taxonomy)
    assert "taxon 3702" in labels["Arabidopsis_thaliana"]
    tomato = labels["Lycopersicon_esculentum"]
    assert "Solanum lycopersicum" in tomato
    assert "source: Lycopersicon_esculentum" in tomato
    alias = taxonomy.iloc[[0]].copy()
    alias["source_species_name"] = "workflow_species_001"
    assert any(
        "source: workflow_species_001" in value
        for value in terminal_species_labels(species_taxonomy=alias).values()
    )


@pytest.mark.parametrize(
    "invalid", ["duplicate", "missing", "null", "bad_id", "empty", "fractional", "boolean"],
)
def test_species_labels_reject_invalid_authorities(invalid: str) -> None:
    """Unreviewed or malformed mappings cannot become species choices."""
    taxonomy = load_taxonomy_authority().species_taxonomy.iloc[[0]].copy()
    if invalid == "duplicate":
        taxonomy = pd.concat(objs=[taxonomy, taxonomy], ignore_index=True)
    elif invalid == "missing":
        taxonomy = taxonomy.drop(columns=["taxon_id"])
    elif invalid == "null":
        taxonomy["canonical_species_name"] = pd.NA
    elif invalid == "bad_id":
        taxonomy["taxon_id"] = "not_an_id"
    elif invalid == "fractional":
        taxonomy["taxon_id"] = 1.5
    elif invalid == "boolean":
        taxonomy["taxon_id"] = True
    else:
        taxonomy["source_species_name"] = ""
    with pytest.raises(AppError, match="taxonomy"):
        terminal_species_labels(species_taxonomy=taxonomy)


def test_tokens_and_display_fraction_preserve_missingness() -> None:
    """Null text is not emitted as an identifier or as a numeric zero."""
    assert review._text_tokens(values=[None, pd.NA, "a;b", " b ; c ;", ""]) == ("a", "b", "c")
    assert review._fraction_label(numerator=pd.NA, denominator=2) == "Unavailable"
    assert review._fraction_label(numerator=0, denominator=0) == "Unavailable"
    assert review._fraction_label(numerator=0, denominator=2) == "0/2 (0.0%)"


def test_summary_annotations_preserve_order_counts_and_rank_provenance(
    annotated_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Existing ranks and E3 neighbourhood labels are joined without changing the screen."""
    summary = _summary(connection=annotated_connection)
    enriched = enrich_terminal_group_summary(
        connection=annotated_connection, summary=summary, group_type="hierarchical_orthogroup",
    )
    assert enriched["group_id"].tolist() == summary["group_id"].tolist()
    assert enriched.attrs == summary.attrs
    row = enriched.iloc[0]
    assert row["hog_poststructure_rank"] == 17
    assert row["hog_prestructure_rank"] == 4
    assert row["ranking_source_row_count"] == 2
    assert row["ranking_source"] == "candidate_master_results"
    assert row["linked_seed_identifiers"] == "A1;A2"
    assert row["linked_seed_protein_descriptions"] == "Seed protein one;Seed protein two"
    assert "Unrelated" not in row["linked_seed_protein_descriptions"]
    assert summary.columns.isin(values=["hog_poststructure_rank"]).sum() == 0
    compact = terminal_summary_display(summary=enriched)
    assert compact.iloc[0]["Plant proteins matching / assessed"] == "4/5 (80.0%)"
    assert compact.iloc[0]["Plant species matching / assessed"] == "4/5 (80.0%)"
    assert compact.iloc[0]["Plant sequences available / published"] == "5/6 (83.3%)"
    assert compact.iloc[0]["Arabidopsis matching IDs"] == "A1"
    assert compact.iloc[0]["Human IDs"] == "H1"
    assert compact.iloc[0]["Human comparison"] == "No assessed match"


def test_optional_annotations_remain_nullable_on_minimal_resources(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Unavailable annotation authorities do not turn into evidence of absence."""
    result = enrich_terminal_group_summary(
        connection=terminal_connection, summary=_summary(connection=terminal_connection),
        group_type="hierarchical_orthogroup",
    )
    assert result["hog_poststructure_rank"].isna().all()
    assert result["linked_cluster_e3_families"].isna().all()
    assert result["linked_seed_protein_descriptions"].isna().all()
    annotations = annotate_terminal_members(
        connection=terminal_connection, members=_members(connection=terminal_connection),
        species_taxonomy=load_taxonomy_authority().species_taxonomy,
        group_type="hierarchical_orthogroup",
    )
    assert annotations["domain_support_status"].isna().all()
    assert annotations["domain_annotation_source"].isna().all()


def test_member_annotation_requires_exact_species_cluster_and_group_identity(
    annotated_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Annotations from another accession context cannot contaminate a member."""
    members = _members(connection=annotated_connection)
    annotated = annotate_terminal_members(
        connection=annotated_connection, members=members,
        species_taxonomy=load_taxonomy_authority().species_taxonomy,
        group_type="hierarchical_orthogroup",
    )
    assert len(annotated) == len(members)
    arabidopsis = annotated.loc[annotated["parsed_accession"] == "A1"].iloc[0]
    assert arabidopsis["ncbi_taxon_id"] == 3702
    assert arabidopsis["accepted_species_name"] == "Arabidopsis thaliana"
    assert arabidopsis["domain_support_status"] == "SUPPORTED"
    assert arabidopsis["e3_families"] == "RING"
    assert arabidopsis["e3_domain_accessions"] == "PF00097"
    assert arabidopsis["domain_annotation_source"] == "domain_summary"
    maize = annotated.loc[annotated["parsed_accession"] == "Z1"].iloc[0]
    assert pd.isna(maize["domain_support_status"])
    assert pd.isna(maize["domain_annotation_source"])
    rice = annotated.loc[annotated["parsed_accession"] == "R1"].iloc[0]
    assert rice["domain_support_status"] == "ANNOTATION_UNAVAILABLE"
    displayed = terminal_member_display(members=annotated)
    assert "Protein description" in displayed.columns
    assert "protein_sequence" not in displayed.columns
    assert set(displayed["Match state"]) == {
        "Exact match", "Assessed non-match", "Sequence unavailable",
    }


@pytest.mark.parametrize(
    ("match_filter", "role_filter", "expected"),
    [
        ("all", "all", {"A1", "R1", "Z1", "B1", "T1", "W1", "H1"}),
        ("match", "all", {"A1", "R1", "Z1", "B1"}),
        ("non_match", "all", {"T1", "H1"}),
        ("unavailable", "all", {"W1"}),
        ("all", "human", {"H1"}),
        ("all", "arabidopsis", {"A1"}),
        ("match", "plant", {"A1", "R1", "Z1", "B1"}),
        ("all", "other", set()),
    ],
)
def test_preview_filters_keep_unavailable_sequences_out_of_non_matches(
    terminal_connection: duckdb.DuckDBPyConnection,
    match_filter: str, role_filter: str, expected: set[str],
) -> None:
    """Presentation filters never reinterpret unknown sequences as negative evidence."""
    members = _members(connection=terminal_connection)
    filtered = filter_terminal_members(
        members=members, match_filter=match_filter, role_filter=role_filter,
    )
    assert set(filtered["parsed_accession"]) == expected
    assert len(members) == 7


def test_species_filter_and_invalid_preview_controls(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Preview species are exact source labels and unsupported filters fail clearly."""
    members = _members(connection=terminal_connection)
    selected = filter_terminal_members(members=members, species=("Oryza_sativa",))
    assert selected["parsed_accession"].tolist() == ["R1"]
    for kwargs in ({"match_filter": "bad"}, {"role_filter": "bad"}, {"species": ("absent",)}):
        with pytest.raises(AppError):
            filter_terminal_members(members=members, **kwargs)
    with pytest.raises(AppError, match="missing columns"):
        terminal_member_display(members=pd.DataFrame())


def test_species_audit_distinguishes_missing_sequence_from_non_representation(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Selected but unrepresented plants and human comparisons have separate states."""
    table = terminal_species_summary(
        members=_members(connection=terminal_connection),
        plant_species=(*PLANTS, "Glycine_max"),
        species_taxonomy=load_taxonomy_authority().species_taxonomy,
    ).set_index(keys="species")
    assert table.loc["Glycine_max", "match_status"] == "NOT_REPRESENTED"
    assert table.loc["Glycine_max", "published_member_count"] == 0
    assert pd.isna(table.loc["Glycine_max", "member_match_fraction"])
    assert table.loc["Triticum_aestivum", "match_status"] == "UNAVAILABLE"
    assert table.loc["Triticum_aestivum", "published_member_count"] == 1
    assert pd.isna(table.loc["Triticum_aestivum", "member_match_fraction"])
    assert table.loc["Solanum_lycopersicum", "match_status"] == "NO_MATCH"
    assert table.loc["Solanum_lycopersicum", "member_match_fraction"] == 0
    assert table.loc["Homo_sapiens", "taxonomic_role"] == "HUMAN_COMPARISON"
    assert table.loc["Homo_sapiens", "matching_member_count"] == 0
    assert table.loc["Arabidopsis_thaliana", "match_status"] == "ALL_MATCH"
    assert table.loc["Arabidopsis_thaliana", "ncbi_taxon_id"] == 3702


def test_species_summary_handles_mixed_paralogues_and_unresolved_comparisons(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Some-match and unmapped evidence retain their exact source state."""
    members = _members(connection=terminal_connection)
    non_match = members.iloc[[0]].copy()
    non_match["terminal_match"] = False
    unknown = members.iloc[[1]].copy()
    unknown["species"] = "Unresolved_species"
    joined = pd.concat(objs=[members, non_match, unknown], ignore_index=True)
    audit = terminal_species_summary(
        members=joined, plant_species=PLANTS,
        species_taxonomy=load_taxonomy_authority().species_taxonomy,
    ).set_index(keys="species")
    assert audit.loc["Arabidopsis_thaliana", "match_status"] == "SOME_MATCH"
    assert pd.isna(audit.loc["Unresolved_species", "accepted_species_name"])
    annotated = annotate_terminal_members(
        connection=terminal_connection, members=joined,
        species_taxonomy=load_taxonomy_authority().species_taxonomy,
        group_type="hierarchical_orthogroup",
    )
    assert annotated.iloc[-1]["taxonomy_mapping_status"] == "UNRESOLVED"


def test_screen_settings_record_unlimited_counts_and_exact_taxonomy_filters(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """TSV-ready settings retain the exact denominator and active filter IDs."""
    summary = _summary(connection=terminal_connection)
    provenance = terminal_screen_provenance(summary=summary, settings={
        "selected_plant_species": PLANTS, "required_exact_taxon_ids": [3702],
        "candidate_bounded": True,
    }).set_index(keys="setting")
    assert provenance.loc["source_group_count", "value"] == "2"
    assert provenance.loc["qualifying_group_count", "value"] == "1"
    assert provenance.loc["selected_plant_species", "value"] == ";".join(PLANTS)
    assert provenance.loc["required_exact_taxon_ids", "value"] == "3702"
    with pytest.raises(AppError, match="audit counts"):
        terminal_screen_provenance(summary=pd.DataFrame(), settings={})


def test_annotation_and_view_contracts_fail_closed(
    annotated_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Duplicate summaries and multi-group member rows cannot receive ambiguous joins."""
    summary = _summary(connection=annotated_connection)
    with pytest.raises(AppError, match="unique"):
        enrich_terminal_group_summary(
            connection=annotated_connection, summary=pd.concat(objs=[summary, summary]),
            group_type="hierarchical_orthogroup",
        )
    with pytest.raises(AppError, match="Unsupported"):
        enrich_terminal_group_summary(
            connection=annotated_connection, summary=summary, group_type="bad",
        )
    with pytest.raises(AppError, match="missing columns"):
        terminal_summary_display(summary=pd.DataFrame())
    members = _members(connection=annotated_connection)
    members.loc[0, "group_id"] = "different_group"
    with pytest.raises(AppError, match="one supported"):
        annotate_terminal_members(
            connection=annotated_connection, members=members,
            species_taxonomy=load_taxonomy_authority().species_taxonomy,
            group_type="hierarchical_orthogroup",
        )
    with pytest.raises(AppError, match="one selected group"):
        terminal_species_summary(
            members=members, plant_species=PLANTS,
            species_taxonomy=load_taxonomy_authority().species_taxonomy,
        )


def test_optional_schema_variations_are_nullable(
    terminal_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Minimal or malformed optional annotation schemas do not alter conservation evidence."""
    terminal_connection.execute("CREATE TABLE candidate_evidence(unrelated_column VARCHAR)")
    terminal_connection.execute("CREATE TABLE domain_summary(cluster_id VARCHAR)")
    summary = enrich_terminal_group_summary(
        connection=terminal_connection, summary=_summary(connection=terminal_connection),
        group_type="hierarchical_orthogroup",
    )
    assert summary["linked_seed_identifiers"].isna().all()
    assert summary["linked_cluster_e3_families"].isna().all()
    members = annotate_terminal_members(
        connection=terminal_connection, members=_members(connection=terminal_connection),
        species_taxonomy=load_taxonomy_authority().species_taxonomy,
        group_type="hierarchical_orthogroup",
    )
    assert members["domain_support_status"].isna().all()


def test_annotation_query_failures_have_context(
    annotated_connection: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Available but unreadable annotations cause controlled, logged application errors."""
    summary = _summary(connection=annotated_connection)
    members = _members(connection=annotated_connection)

    class FailingConnection:
        """Return schema information but fail scientific annotation queries."""

        def execute(self, query: str, parameters: object = None) -> object:
            """Delegate schema inspection and reject annotation data reads."""
            if query.startswith("SELECT"):
                raise RuntimeError("query failed")
            return annotated_connection.execute(query, parameters or [])

    connection = FailingConnection()
    with pytest.raises(AppError, match="ranking context"):
        enrich_terminal_group_summary(
            connection=connection, summary=summary, group_type="hierarchical_orthogroup",
        )
    with pytest.raises(AppError, match="domain annotations"):
        annotate_terminal_members(
            connection=connection, members=members,
            species_taxonomy=load_taxonomy_authority().species_taxonomy,
            group_type="hierarchical_orthogroup",
        )
    with pytest.raises(AppError, match="optional C-terminal annotations"):
        review._collect_cluster_annotations(
            connection=connection, relation="candidate_evidence", key_column="representative_id",
            fields={"seed_categories": "categories"}, clusters=("c1",),
        )


def test_member_annotations_bound_results_and_support_unlinked_full_authority(
    annotated_connection: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full authority without E3 cluster links keeps domain evidence unavailable."""
    members = _members(connection=annotated_connection)
    taxonomy = load_taxonomy_authority().species_taxonomy
    unlinked = members.copy()
    unlinked["source_cluster_ids"] = pd.NA
    annotations = annotate_terminal_members(
        connection=annotated_connection, members=unlinked, species_taxonomy=taxonomy,
        group_type="hierarchical_orthogroup",
    )
    assert annotations["domain_annotation_source"].isna().all()
    assert annotations["ncbi_taxon_id"].notna().sum() == 6
    monkeypatch.setattr(review, "MAXIMUM_RESULT_ROWS", 1)
    with pytest.raises(AppError, match="bounded result limit"):
        annotate_terminal_members(
            connection=annotated_connection, members=members, species_taxonomy=taxonomy,
            group_type="hierarchical_orthogroup",
        )
