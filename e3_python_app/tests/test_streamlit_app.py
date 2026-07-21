"""Headless end-to-end tests for the Streamlit presentation layer."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_app_renders_and_searches(resource_db: Path, monkeypatch: object) -> None:
    """The app renders all tabs and accepts a representative accession."""

    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_MAX_TABLE_ROWS", "100")
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert not app.exception
    assert app.title[0].value == "ARIA plant E3 discovery resource"
    assert len(app.tabs) == 4
    app.text_input[0].set_value("Q9SA03").run()
    assert not app.exception


def test_app_reports_missing_database(monkeypatch: object, tmp_path: Path) -> None:
    """Invalid configuration is shown in-app without a database write."""

    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(tmp_path / "missing.duckdb"))
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert app.error
    assert "does not exist" in app.error[0].value


def test_app_handles_empty_and_corrupt_databases(monkeypatch: object, tmp_path: Path) -> None:
    """Empty resources render guidance and corrupt resources show a controlled error."""

    import duckdb

    empty = tmp_path / "empty.duckdb"
    with duckdb.connect(str(empty)):
        pass
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(empty))
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert not app.exception
    assert len(app.info) >= 3

    corrupt = tmp_path / "corrupt.duckdb"
    corrupt.write_text("not duckdb", encoding="utf-8")
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(corrupt))
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert app.error
    assert "Could not open" in app.error[0].value
