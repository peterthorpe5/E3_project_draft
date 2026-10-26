"""Full-resource filters and exports must never inherit the screen row limit."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from e3app.enriched_hogs import ENRICHED_HOG_OVERVIEW
from e3app.errors import AppError
from e3app.result_queries import (
    ResourceQuery,
    build_result_query,
    build_search_queries,
    preview_query,
    query_count,
    search_predicate,
    summarise_search_queries,
    validated_terms,
)


def test_all_rows_and_fields_survive_a_small_preview(resource_db: Path) -> None:
    """Filtering is applied before LIMIT and rank values remain resource-wide."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "INSERT INTO candidate_master_results(final_rank, primary_group_id, "
            "prestructure_evolutionary_group_rank) "
            "SELECT i, 'N0.HOG' || lpad(CAST(i AS VARCHAR), 7, '0'), i + 7 "
            "FROM range(2, 1502) t(i)"
        )
        query = build_result_query(connection=connection, result="candidate_master_results")
        assert query_count(connection=connection, query=query) == 1501
        assert len(preview_query(connection=connection, query=query, maximum_rows=10)) == 10
        filtered = build_result_query(
            connection=connection,
            result=ENRICHED_HOG_OVERVIEW,
            columns=("hog_id", "hog_prestructure_rank", "hog_poststructure_rank"),
            terms=("  n0.hog0001499  ",),
            mode="exact",
        )
        frame = preview_query(connection=connection, query=filtered, maximum_rows=1)
        assert frame.iloc[0]["hog_id"] == "N0.HOG0001499"
        assert int(frame.iloc[0]["hog_poststructure_rank"]) == 1499
        assert int(frame.iloc[0]["hog_prestructure_rank"]) == 1506


def test_complete_search_counts_all_matches_and_preserves_provenance(resource_db: Path) -> None:
    """Full counts and matching terms are independent of a one-row preview."""
    with duckdb.connect(str(resource_db), read_only=True) as connection:
        queries = build_search_queries(connection=connection, terms=("Q9SA03", "missing"))
        summary = summarise_search_queries(connection=connection, queries=queries)
        assert set(summary["search_term"]) == {"Q9SA03"}
        candidate = next(query for query in queries if query.name == "candidate_master_results")
        frame = preview_query(connection=connection, query=candidate, maximum_rows=1)
        assert frame.loc[0, "_relation"] == "candidate_master_results"
        assert frame.loc[0, "_search_term"] == "Q9SA03"
        assert "candidate_accessions" in frame.loc[0, "_matched_columns"]
        assert "final_rank" in frame.columns
        assert summarise_search_queries(connection=connection, queries=()).empty


def test_literal_filters_token_headers_and_hidden_fields() -> None:
    """Quotes, percent signs and pipe/list identifiers are never SQL patterns."""
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE source(raw_identifier VARCHAR, description VARCHAR, rank INT)"
        )
        connection.execute(
            "INSERT INTO source VALUES (?, ?, 7), (?, ?, 12)",
            ["sp|Q9SA03|FB27_ARATH", "Pete's 100% protein", "X; Y ;Z", "other"],
        )
        for terms, mode in (
            (("Q9SA03",), "exact"),
            (("Pete's 100%",), "contains"),
            (("Y",), "exact"),
        ):
            query = build_result_query(
                connection=connection,
                result="source",
                columns=("rank",),
                terms=terms,
                mode=mode,
            )
            assert query_count(connection=connection, query=query) == 1
        attack = build_result_query(
            connection=connection,
            result="source",
            terms=("' OR TRUE --",),
            mode="contains",
        )
        assert query_count(connection=connection, query=attack) == 0
        assert search_predicate(columns=("score",), terms=("x",), mode="exact") == ("FALSE", ())


@pytest.mark.parametrize(
    "terms", [("x" * 201,), (None,), "x", ("x\x00",), tuple(str(i) for i in range(51))]
)
def test_invalid_explicit_terms_are_rejected(terms: object) -> None:
    """Malformed input cannot bypass the bound-query contract."""
    with pytest.raises(AppError):
        validated_terms(terms=terms)


def test_wide_bulk_filter_uses_bound_arrays_without_expression_depth_failure() -> None:
    """Fifty terms across a wide schema remain a bounded-size predicate tree."""
    with duckdb.connect(":memory:") as connection:
        projection = ", ".join(f"'P49' AS protein_accession_{index}" for index in range(30))
        connection.execute(f"CREATE TABLE wide AS SELECT {projection}")
        query = build_result_query(
            connection=connection,
            result="wide",
            terms=tuple(f"P{i}" for i in range(50)),
        )
        assert len(query.parameters) == 30
        assert query_count(connection=connection, query=query) == 1


def test_validated_terms_keep_first_spelling_and_order() -> None:
    """Case-insensitive duplicate removal preserves the user's first term."""
    assert validated_terms(terms=(" A ", "B", "a", " ")) == ("A", "B")


def test_invalid_queries_and_preview_bounds_fail_explicitly(resource_db: Path) -> None:
    """No failed source can produce an apparently complete, partial result."""
    with duckdb.connect(str(resource_db), read_only=True) as connection:
        for result, columns in (
            ("missing", None),
            ("candidates", ()),
            ("candidates", ("unknown",)),
        ):
            with pytest.raises(AppError):
                build_result_query(connection=connection, result=result, columns=columns)
        with pytest.raises(AppError, match="Enter at least"):
            build_search_queries(connection=connection, terms=())
        with pytest.raises(AppError, match="Unsupported"):
            build_search_queries(connection=connection, terms=("x",), mode="invalid")
        query = build_result_query(connection=connection, result="candidates")
        for maximum in (0, True, 1.5, 100001):
            with pytest.raises(AppError, match="Preview rows"):
                preview_query(connection=connection, query=query, maximum_rows=maximum)
        invalid = ResourceQuery(name="missing", sql="SELECT * FROM missing")
        with pytest.raises(AppError, match="Could not count"):
            query_count(connection=connection, query=invalid)
        with pytest.raises(AppError, match="Could not preview"):
            preview_query(connection=connection, query=invalid, maximum_rows=2)
        with pytest.raises(AppError, match="could not read"):
            summarise_search_queries(connection=connection, queries=(invalid,))
