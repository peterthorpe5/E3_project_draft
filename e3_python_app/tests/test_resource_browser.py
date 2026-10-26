"""End-to-end navigation, complete-download and selected-group dossier workflows."""

from __future__ import annotations

import csv
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import duckdb
from openpyxl import load_workbook
import pytest
from streamlit.testing.v1 import AppTest

from e3app.errors import AppError
from e3app.resource_browser import source_identity


def _open_page(
    *,
    resource_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    page: str,
) -> AppTest:
    """Open a full-application page through the new top-level navigation."""
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_MAX_TABLE_ROWS", "5")
    path = Path(__file__).resolve().parents[1] / "src/e3app/streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    app.radio(key="e3_navigation_stage").set_value("🔎 Search & results").run()
    app.radio(key="e3_navigation_page_🔎 Search & results").set_value(page).run()
    assert not app.exception
    return app


def _submit_search(*, app: AppTest, text: str) -> AppTest:
    """Submit the search form through the actual Streamlit widgets."""
    next(area for area in app.text_area if area.label == "Search term(s)").set_value(text)
    next(
        button for button in app.button if button.label == "Search the complete loaded resource"
    ).click()
    return app.run()


def test_all_results_complete_download_ignores_display_rows_and_fields(
    resource_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A five-row, one-field preview still exports all 1,502 rows and source fields."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "INSERT INTO candidate_master_results(final_rank, primary_group_id) "
            "SELECT i, 'N0.HOG' || lpad(CAST(i AS VARCHAR), 7, '0') "
            "FROM range(2, 1502) t(i)"
        )
        connection.execute(
            "INSERT INTO candidate_master_results(final_rank, primary_group_id) "
            "VALUES (1600, 'N0.HOG0004891')"
        )
    app = _open_page(resource_db=resource_db, monkeypatch=monkeypatch, page="All results")
    app.selectbox(key="all_results_relation").set_value("candidate_master_results").run()
    app.multiselect(key="all_results_columns_candidate_master_results").set_value(
        ["primary_group_id"]
    ).run()
    assert not app.exception
    preview = next(
        table.value for table in app.dataframe if "primary_group_id" in table.value.columns
    )
    assert len(preview) == 5
    assert len(preview.columns) == 1
    app.button(key="all_results_complete_prepare").click().run()
    assert not app.exception
    payload = app.session_state["all_results_complete_prepared"][1]
    with ZipFile(BytesIO(payload)) as archive:
        manifest = list(
            csv.DictReader(StringIO(archive.read("manifest.tsv").decode()), delimiter="\t")
        )
        assert manifest[0]["exported_rows"] == "1502"
        rows = list(
            csv.DictReader(StringIO(archive.read(manifest[0]["file"]).decode()), delimiter="\t")
        )
        assert any(row["primary_group_id"] == "N0.HOG0004891" for row in rows)
        assert "final_rank" in rows[0]
        assert len(rows[0]) == 16
    app.number_input(key="all_results_rows").set_value(1).run()
    assert app.session_state["all_results_complete_prepared"][1] == payload
    app.multiselect(key="all_results_columns_candidate_master_results").set_value([]).run()
    assert any("complete download remains available" in item.value for item in app.info)
    assert any(
        button.key == "all_results_complete_download" for button in app.get("download_button")
    )
    app.text_area(key="all_results_filter").set_value("  N0.HOG0004891  ").run()
    assert not app.exception
    assert "all_results_complete_prepared" not in app.session_state
    assert any(
        metric.label == "Complete matching rows" and metric.value == "1" for metric in app.metric
    )
    app.button(key="all_results_columns_candidate_master_results_all").click().run()
    filtered = next(
        table.value for table in app.dataframe if "primary_group_id" in table.value.columns
    )
    assert filtered.iloc[0]["primary_group_id"] == "N0.HOG0004891"
    assert int(filtered.iloc[0]["final_rank"]) == 1600
    app.button(key="all_results_columns_candidate_master_results_first").click().run()
    app.radio(key="all_results_complete_format").set_value("excel").run()
    app.button(key="all_results_complete_prepare").click().run()
    workbook = load_workbook(BytesIO(app.session_state["all_results_complete_prepared"][1]))
    assert workbook["Manifest"]["C2"].value == 1


def test_protein_search_shows_original_ranks_and_complete_linked_dossier(
    resource_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Searching a non-seed member finds HOG ranks and cluster-linked domain evidence."""
    app = _open_page(resource_db=resource_db, monkeypatch=monkeypatch, page="Protein & HOG search")
    app = _submit_search(app=app, text="P38398")
    assert not app.exception
    assert app.selectbox(key="search_dossier_group").value == "N0.HOG0001"
    assert any(
        metric.label == "Rank before structural analysis" and metric.value == "1"
        for metric in app.metric
    )
    assert any(
        metric.label == "Rank after structural analysis" and metric.value == "1"
        for metric in app.metric
    )
    app.button(key="group_dossier_complete_prepare").click().run()
    assert not app.exception
    with ZipFile(BytesIO(app.session_state["group_dossier_complete_prepared"][1])) as archive:
        manifest = list(
            csv.DictReader(StringIO(archive.read("manifest.tsv").decode()), delimiter="\t")
        )
        assert (
            next(row for row in manifest if row["source"] == "domain_summary")["exported_rows"]
            == "1"
        )
        assert (
            next(row for row in manifest if row["source"] == "candidate_evidence")["exported_rows"]
            == "1"
        )
        assert (
            next(row for row in manifest if row["source"] == "hierarchical_membership")[
                "exported_rows"
            ]
            == "2"
        )
    app.selectbox(key="dossier_source").set_value("candidate_evidence").run()
    assert not app.exception
    evidence = next(
        table.value for table in app.dataframe if "raw_member_count" in table.value.columns
    )
    assert int(evidence.iloc[0]["raw_member_count"]) == 12
    app.button(key="search_direct_complete_prepare").click().run()
    assert not app.exception
    assert app.session_state["search_direct_complete_prepared"][1].startswith(b"PK")
    # Unsaved form edits do not relabel an already-applied search/export.
    next(area for area in app.text_area if area.label == "Search term(s)").set_value("Q9SA03")
    app.number_input(key="search_preview_rows").set_value(1).run()
    assert any("Applied search: P38398" in item.value for item in app.caption)
    app = _submit_search(app=app, text="not-a-real-protein")
    assert any("No identifier or name match" in item.value for item in app.warning)
    app = _submit_search(app=app, text="")
    assert any("Enter at least one" in item.value for item in app.warning)
    assert not app.exception


def test_thin_release_keeps_direct_matches_without_inventing_group_ranks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accession-only data keeps complete exports and explains absent group linkage."""
    path = tmp_path / "thin.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE TABLE proteins(accession VARCHAR, description VARCHAR)")
        connection.execute("INSERT INTO proteins VALUES ('P1', 'an ungrouped protein')")
    app = _open_page(resource_db=path, monkeypatch=monkeypatch, page="Protein & HOG search")
    app = _submit_search(app=app, text="P1")
    assert not app.exception
    assert any("no recorded group link" in item.value for item in app.info)
    app.button(key="search_direct_complete_prepare").click().run()
    assert app.session_state["search_direct_complete_prepared"][1].startswith(b"PK")
    app.button(key="search_columns_proteins_all").click().run()
    app.button(key="search_columns_proteins_first").click().run()
    app.multiselect(key="search_columns_proteins").set_value([]).run()
    assert not app.exception
    # A changed source invalidates the old search and prepared export controls.
    with duckdb.connect(str(path)) as connection:
        connection.execute("INSERT INTO proteins VALUES ('P2', 'new release content')")
    app.run()
    assert "complete_resource_search" not in app.session_state
    assert not any(
        button.key == "search_direct_complete_download" for button in app.get("download_button")
    )


def test_complete_export_failure_is_actionable_and_removes_old_payload(
    resource_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed complete export never leaves a stale or partial download visible."""
    app = _open_page(resource_db=resource_db, monkeypatch=monkeypatch, page="All results")

    def fail_export(**kwargs: object) -> bytes:
        """Simulate a controlled read/write failure in the real export action."""
        raise AppError("Cannot read this source")

    monkeypatch.setattr("e3app.resource_browser.complete_tsv_archive", fail_export)
    app.button(key="all_results_complete_prepare").click().run()
    assert any("Cannot read this source" in error.value for error in app.error)
    assert "all_results_complete_prepared" not in app.session_state
    assert not app.exception
    app.text_area(key="all_results_filter").set_value("x" * 201).run()
    assert any("at most 200" in error.value for error in app.error)


def test_source_identity_tracks_nested_parquets(tmp_path: Path) -> None:
    """Replacing a source Parquet invalidates exports even if its parent path is unchanged."""
    nested = tmp_path / "results"
    nested.mkdir()
    path = nested / "members.parquet"
    path.write_bytes(b"first")
    config = SimpleNamespace(source_path=tmp_path)
    before = source_identity(config=config)
    path.write_bytes(b"changed source")
    assert source_identity(config=config) != before
