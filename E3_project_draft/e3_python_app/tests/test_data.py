"""Unit and integration tests for bounded DuckDB services."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from e3app.config import AppConfig
from e3app.data import (
    _safe_relation_name,
    default_columns,
    discover_run_parquets,
    grant_overview,
    infer_capability,
    list_relations,
    open_read_only,
    open_resource,
    preview_relation,
    preview_selected_columns,
    quote_identifier,
    relation_columns,
    relation_count,
    relations_for_section,
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
    assert infer_capability("structural_alignment_summary", []) == "structural_alignment"
    assert infer_capability("pocket_conservation_summary", []) == "pocket_conservation"
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
        assert list(
            preview_selected_columns(
                connection,
                "candidates",
                ["accession", "score"],
                1,
            ).columns
        ) == ["accession", "score"]
        overview = resource_overview(connection, ["candidates", "orthogroup_membership"])
        assert overview["row_count"].sum() == 3
        assert len(resource_overview(connection)) == len(relations)
    for limit in (0, 100_001):
        with open_read_only(resource_db) as connection:
            with pytest.raises(AppError, match="preview limit"):
                preview_relation(connection, "candidates", limit)
    with open_read_only(resource_db) as connection:
        with pytest.raises(AppError, match="at least one"):
            preview_selected_columns(connection, "candidates", [], 1)
        with pytest.raises(AppError, match="Unknown columns"):
            preview_selected_columns(connection, "candidates", ["missing"], 1)
        with pytest.raises(AppError, match="preview limit"):
            preview_selected_columns(connection, "candidates", ["accession"], 0)
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
            "candidate_master_results",
            "orthogroup_membership",
            "pocket_scores",
        }
        assert search_accession(connection, "NOT_REAL").empty
        delimited = search_accession(connection, "Q00002")
        assert "candidate_master_results" in set(delimited["_relation"])
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


def test_flexible_parquet_sources(
    master_parquet: Path,
    run_results_dir: Path,
) -> None:
    """Single-master and current-run modes expose the same canonical relation."""
    master_config = AppConfig(resource_parquet=master_parquet)
    with open_resource(master_config) as connection:
        assert "candidate_master_results" in list_relations(connection)
        assert relation_count(connection, "candidate_master_results") == 1
        assert grant_overview(connection) == {
            "candidate_count": 1,
            "prestructure_pass_count": 1,
            "final_pass_count": 1,
            "structural_assessed_count": 1,
        }
    discovered = discover_run_parquets(run_results_dir)
    assert list(discovered) == ["candidate_master_results"]
    with open_resource(AppConfig(resource_run_dir=run_results_dir)) as connection:
        assert "candidate_master_results" in list_relations(connection)
        assert "resource_relation_catalog" in list_relations(connection)


def test_run_discovery_defensive_branches(
    master_parquet: Path,
    tmp_path: Path,
) -> None:
    """Run discovery excludes stale paths and resolves duplicate/unknown names."""
    missing = tmp_path / "missing"
    with pytest.raises(AppError, match="does not exist"):
        discover_run_parquets(missing)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AppError, match="no usable"):
        discover_run_parquets(empty)

    run = tmp_path / "run"
    first = run / "09_ligandability" / "tables" / "selected_pockets.parquet"
    duplicate = run / "copy" / "tables" / "selected_pockets.parquet"
    unknown = run / "other" / "tables" / "odd result.parquet"
    hidden = run / ".cache" / "ignored.parquet"
    stale = run / "superseded" / "stale.parquet"
    for path in (first, duplicate, unknown, hidden, stale):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(master_parquet.read_bytes())
    discovered = discover_run_parquets(run)
    assert "selected_pockets" in discovered
    assert "other_tables_odd_result" in discovered
    assert not any("ignored" in name or "stale" in name for name in discovered)
    assert _safe_relation_name(run / "123.parquet", run) == "result_123"


def test_open_resource_failure_branches(tmp_path: Path) -> None:
    """Unconfigured and corrupt Parquet sources fail with controlled errors."""
    with pytest.raises(AppError, match="No resource"):
        with open_resource(AppConfig()):
            pass
    corrupt = tmp_path / "corrupt.parquet"
    corrupt.write_text("not parquet", encoding="utf-8")
    with pytest.raises(AppError, match="Could not open resource"):
        with open_resource(AppConfig(resource_parquet=corrupt)):
            pass


def test_sections_and_column_defaults(resource_db: Path) -> None:
    """Grant sections select only available relations and sensible default columns."""
    with open_read_only(resource_db) as connection:
        assert relations_for_section(connection, "candidates")[0] == (
            "candidate_master_results"
        )
        assert relations_for_section(connection, "orthology")
        assert relations_for_section(connection, "domains")[0] == "domain_summary"
        assert "resource_metadata" in relations_for_section(connection, "provenance")
        columns = relation_columns(connection, "candidate_master_results")
        selected = default_columns("candidates", columns)
        assert {"cluster_id", "final_score"}.issubset(selected)
        with pytest.raises(AppError, match="Unknown result section"):
            relations_for_section(connection, "missing")


def test_grant_overview_fallbacks(tmp_path: Path) -> None:
    """Overview reports zeros when no candidate or gate columns are present."""
    path = tmp_path / "minimal.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE TABLE unrelated(value INTEGER)")
    with open_read_only(path) as connection:
        assert grant_overview(connection)["candidate_count"] == 0
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE TABLE candidate_evidence(representative_id VARCHAR)")
        connection.execute("INSERT INTO candidate_evidence VALUES ('cluster_1')")
    with open_read_only(path) as connection:
        assert grant_overview(connection) == {
            "candidate_count": 1,
            "prestructure_pass_count": 0,
            "final_pass_count": 0,
            "structural_assessed_count": 0,
        }
