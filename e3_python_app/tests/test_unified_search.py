"""Tests for batch-capable multi-field application search."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from e3app.errors import AppError
from e3app.unified_search import (
    collect_unified_search,
    parse_search_terms,
    searchable_columns,
    summarise_unified_search,
)


@pytest.fixture
def search_connection() -> duckdb.DuckDBPyConnection:
    """Create several searchable relations with identifiers and names."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE ranked(primary_group_id VARCHAR, candidate_accessions VARCHAR, "
        "seed_protein_names VARCHAR, final_rank INTEGER)"
    )
    connection.execute(
        "INSERT INTO ranked VALUES "
        "('N0.HOG0001', 'Q9SA03;P38398', 'F-box protein 27', 1), "
        "('N0.HOG0002', 'OTHER1', 'RING finger protein', 2)"
    )
    connection.execute(
        "CREATE TABLE aliases(primary_group_id VARCHAR, member_accession VARCHAR, "
        "identifier_type VARCHAR, identifier_value VARCHAR)"
    )
    connection.execute(
        "INSERT INTO aliases VALUES "
        "('N0.HOG0001', 'Q9SA03', 'gene_name', 'FB27'), "
        "('N0.HOG0002', 'OTHER1', 'gene_name', 'RING1')"
    )
    connection.execute("CREATE TABLE unsearchable(score DOUBLE)")
    try:
        yield connection
    finally:
        connection.close()


def test_parse_search_terms_supports_pasted_lists() -> None:
    """Newline, comma, semicolon and tab lists preserve multi-word names."""
    assert parse_search_terms(
        value="Q9SA03\nN0.HOG0001, F-box protein 27;FB27\tQ9SA03"
    ) == ("Q9SA03", "N0.HOG0001", "F-box protein 27", "FB27")
    assert parse_search_terms(value="") == ()
    with pytest.raises(AppError, match="at most 200"):
        parse_search_terms(value="x" * 201)
    with pytest.raises(AppError, match="at most 2"):
        parse_search_terms(value="a,b,c", maximum_terms=2)


def test_smart_search_matches_hog_seed_accession_and_name(
    search_connection: duckdb.DuckDBPyConnection,
) -> None:
    """One pasted query list searches exact identifiers and descriptive names."""
    matches = collect_unified_search(
        connection=search_connection,
        search_terms=("N0.HOG0001", "Q9SA03", "F-box protein", "FB27"),
        mode="smart",
    )
    assert set(matches["_search_term"]) == {
        "N0.HOG0001",
        "Q9SA03",
        "F-box protein",
        "FB27",
    }
    assert set(matches["_relation"]) == {"aliases", "ranked"}
    q9 = matches[matches["_search_term"] == "Q9SA03"]
    assert set(zip(q9["_relation"], q9["_matched_columns"], strict=True)) == {
        ("aliases", "member_accession"),
        ("ranked", "candidate_accessions"),
    }
    name = matches[matches["_search_term"] == "F-box protein"]
    assert name.iloc[0]["_matched_columns"] == "seed_protein_names"
    summary = summarise_unified_search(matches=matches)
    assert int(summary["matched_rows"].sum()) == len(matches)


def test_search_modes_and_bounds_are_explicit(
    search_connection: duckdb.DuckDBPyConnection,
) -> None:
    """Exact mode avoids partial IDs and invalid requests fail clearly."""
    exact = collect_unified_search(
        connection=search_connection,
        search_terms=("N0.HOG",),
        mode="exact",
    )
    assert exact.empty
    contains = collect_unified_search(
        connection=search_connection,
        search_terms=("N0.HOG",),
        mode="contains",
    )
    assert len(contains) == 4
    with pytest.raises(AppError, match="Enter at least one"):
        collect_unified_search(connection=search_connection, search_terms=())
    with pytest.raises(AppError, match="Unsupported"):
        collect_unified_search(
            connection=search_connection,
            search_terms=("x",),
            mode="bad",  # type: ignore[arg-type]
        )
    with pytest.raises(AppError, match="between 1 and 10000"):
        collect_unified_search(
            connection=search_connection,
            search_terms=("x",),
            maximum_rows_per_relation=0,
        )
    with pytest.raises(AppError, match="missing columns"):
        summarise_unified_search(matches=pd.DataFrame({"x": [1]}))


def test_search_column_classification_is_schema_tolerant() -> None:
    """Searchable fields are discovered without hard-coding whole schemas."""
    exact, text = searchable_columns(
        columns=("primary_group_id", "gene_name", "score", "custom_seed_id")
    )
    assert exact == ["primary_group_id", "custom_seed_id"]
    assert text == ["gene_name"]
