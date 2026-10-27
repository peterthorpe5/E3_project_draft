"""Direct group lookup, scoped membership and safeguards against eager full scans."""

from pathlib import Path

import duckdb
import pytest

from e3app.errors import AppError
from e3app.group_lookup import (
    exact_group_terms,
    find_exact_groups,
    group_match_queries,
    quick_group_profile,
)
from e3app.result_queries import preview_query, resource_schema


def test_group_detection_preserves_matching_semantics() -> None:
    """Only complete group-ID lists use the automatic group lookup."""
    assert exact_group_terms(terms=(" n0.hog0004891 ", "og0006"), mode="smart") == (
        "N0.HOG0004891",
        "OG0006",
    )
    assert exact_group_terms(terms=("N0.HOG0004891",), mode="contains") == ()
    assert exact_group_terms(terms=("N0.HOG0004891", "P1"), mode="smart") == ()
    assert exact_group_terms(terms=(), mode="exact") == ()
    with pytest.raises(AppError, match="Unsupported"):
        exact_group_terms(terms=("HOG3",), mode="invalid")


def test_lookup_confirms_existing_groups_and_skips_descriptions(resource_db: Path) -> None:
    """A HOG written in a description cannot become a recorded group match."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute("CREATE TABLE notes(description VARCHAR)")
        connection.execute("INSERT INTO notes VALUES ('N0.HOG9999')")
        schema = resource_schema(connection=connection)
        assert find_exact_groups(
            connection=connection,
            terms=("N0.HOG0001", "N0.HOG9999", "OG0001686"),
            schema=schema,
        ) == ("N0.HOG0001", "OG0001686")
        assert find_exact_groups(connection=connection, terms=()) == ()
        profile = quick_group_profile(connection=connection, group_id="N0.HOG0001", maximum_rows=1)
        assert profile["member_count"] == 2
        assert profile["species_count"] == 2
        assert len(profile["members"]) == 1
        assert "protein_sequence" not in profile["members"].columns
        assert set(profile["ranks"]["recorded_rank"]) == {"1"}
        og = quick_group_profile(connection=connection, group_id="OG0001686")
        assert og["membership_source"] == "orthogroup_membership"


def test_generic_and_typed_keys_and_missing_membership() -> None:
    """Generic schemas and typed evolutionary keys retain exact group semantics."""
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE custom(evolutionary_group_key VARCHAR, description VARCHAR)"
        )
        connection.execute("INSERT INTO custom VALUES ('HOG:N0.HOG0008', 'an annotation')")
        connection.execute("INSERT INTO custom VALUES ('family-alpha', 'another annotation')")
        assert find_exact_groups(connection=connection, terms=("N0.HOG0008", "family-alpha")) == (
            "N0.HOG0008",
            "FAMILY-ALPHA",
        )
        queries = group_match_queries(connection=connection, terms=("N0.HOG0008",))
        frame = preview_query(connection=connection, query=queries[0], maximum_rows=10)
        assert len(frame) == 1
        assert frame.iloc[0]["description"] == "an annotation"
        assert frame.iloc[0]["_matched_columns"] == "evolutionary_group_key"
        profile = quick_group_profile(connection=connection, group_id="N0.HOG0008")
        assert profile["member_count"] is None
        assert profile["ranks"].empty
        assert profile["members"].empty
        with pytest.raises(AppError, match="at least one"):
            group_match_queries(connection=connection, terms=())
        for value in ("", " "):
            with pytest.raises(AppError, match="Choose a group"):
                quick_group_profile(connection=connection, group_id=value)
        for maximum in (0, True, 1.5, 100001):
            with pytest.raises(AppError, match="Preview rows"):
                quick_group_profile(
                    connection=connection, group_id="family-alpha", maximum_rows=maximum
                )


def test_profile_falls_back_to_sequence_membership_without_fetching_sequences() -> None:
    """Missing hierarchy and species fields do not force a full enriched join."""
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE hierarchical_membership(group_id VARCHAR)")
        connection.execute(
            "CREATE TABLE candidate_group_member_sequences("
            "group_id VARCHAR, parsed_accession VARCHAR, protein_sequence VARCHAR)"
        )
        connection.execute(
            "INSERT INTO candidate_group_member_sequences VALUES ('N0.HOG1', 'P1', 'MAAA')"
        )
        profile = quick_group_profile(connection=connection, group_id="N0.HOG1")
        assert profile["member_count"] == 1
        assert profile["species_count"] is None
        assert profile["membership_source"] == "candidate_group_member_sequences"
        assert "protein_sequence" not in profile["members"].columns


def test_failed_lookup_is_reported_instead_of_silently_ignored() -> None:
    """A failed source cannot become a false no-match result."""
    with duckdb.connect(":memory:") as connection:
        with pytest.raises(AppError, match="could not read"):
            find_exact_groups(
                connection=connection, terms=("N0.HOG1",), schema={"missing": ("group_id",)}
            )
