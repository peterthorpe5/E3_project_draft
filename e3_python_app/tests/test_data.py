"""Unit and integration tests for bounded DuckDB services."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from e3app.data import (
    infer_capability,
    list_relations,
    open_read_only,
    preview_relation,
    quote_identifier,
    relation_columns,
    relation_count,
    resource_overview,
    search_accession,
)
from e3app.errors import AppError


def test_identifier_and_capability_classification() -> None:
    """Only simple SQL identifiers pass and navigation categories are stable."""

    assert quote_identifier("safe_name") == '"safe_name"'
    with pytest.raises(AppError, match="Unsafe"):
        quote_identifier("bad; DROP TABLE x")
    assert infer_capability("hogs", []) == "orthology"
    assert infer_capability("scores", ["fpocket_score"]) == "ligandability"
    assert infer_capability("atlas", ["tpm"]) == "expression"
    assert infer_capability("source_manifest", []) == "provenance"
    assert infer_capability("clusters", []) == "candidate"
    assert infer_capability("proteins", ["sequence"]) == "resource"


def test_relation_queries(resource_db: Path) -> None:
    """Relation discovery, schema, count and previews use bounded queries."""

    with open_read_only(resource_db) as connection:
        relations = list_relations(connection)
        assert "candidates" in relations
        assert relation_columns(connection, "candidates") == ["accession", "organism", "score"]
        assert relation_count(connection, "candidates") == 2
        assert len(preview_relation(connection, "candidates", 1)) == 1
        overview = resource_overview(connection, ["candidates", "orthogroup_membership"])
        assert overview["row_count"].sum() == 3
        assert len(resource_overview(connection)) == len(relations)
    for limit in (0, 100_001):
        with open_read_only(resource_db) as connection:
            with pytest.raises(AppError, match="preview limit"):
                preview_relation(connection, "candidates", limit)
    with pytest.raises(AppError, match="does not exist"):
        with open_read_only(resource_db.parent / "missing.duckdb"):
            pass
    corrupt = resource_db.parent / "corrupt.duckdb"
    corrupt.write_text("not a database", encoding="utf-8")
    with pytest.raises(AppError, match="Could not open"):
        with open_read_only(corrupt):
            pass


def test_accession_search(resource_db: Path) -> None:
    """Accession search spans recognised columns and binds query values."""

    with open_read_only(resource_db) as connection:
        matches = search_accession(connection, "q9sa03")
        assert set(matches["_relation"]) >= {
            "candidates",
            "candidate_view",
            "orthogroup_membership",
            "pocket_scores",
        }
        assert search_accession(connection, "NOT_REAL").empty
        with pytest.raises(AppError):
            search_accession(connection, "")
        with pytest.raises(AppError):
            search_accession(connection, "X" * 201)
        with pytest.raises(AppError):
            search_accession(connection, "Q9SA03", 0)
        with pytest.raises(AppError):
            search_accession(connection, "Q9SA03", 10_001)


def test_relation_name_filtering(tmp_path: Path) -> None:
    """Unexpected quoted relation names are omitted from the UI allowlist."""

    path = tmp_path / "odd.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute('CREATE TABLE "odd-name"(value INTEGER)')
    with open_read_only(path) as connection:
        assert list_relations(connection) == []
        assert resource_overview(connection).empty


def test_case_insensitive_accession_column(tmp_path: Path) -> None:
    """Legacy capitalisation such as Entry remains searchable."""

    path = tmp_path / "capitalised.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute('CREATE TABLE legacy("Entry" VARCHAR)')
        connection.execute("INSERT INTO legacy VALUES ('Q9SA03')")
    with open_read_only(path) as connection:
        assert search_accession(connection, "Q9SA03")["Entry"].tolist() == ["Q9SA03"]
