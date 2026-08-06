"""Headless end-to-end tests for the Streamlit presentation layer."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from test_pocket_review import make_pocket_review


def test_app_renders_and_searches(resource_db: Path, monkeypatch: object) -> None:
    """The app renders all tabs and accepts a representative accession."""

    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_MAX_TABLE_ROWS", "100")
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert not app.exception
    assert app.title[0].value == "ARIA plant E3 discovery and ligandability resource"
    assert len(app.tabs) == 21
    assert app.tabs[1].label == "Glossary"
    assert app.tabs[2].label == "Computational recommendations"
    assert app.tabs[3].label == "Threshold explorer"
    assert app.tabs[4].label == "Visual explorer"
    assert app.tabs[15].label == "3D structures & pockets"
    assert app.tabs[16].label == "Pocket-aligned sequences"
    tab_labels = [tab.label for tab in app.tabs]
    assert "Candidate landscape" in tab_labels
    assert "Expression heatmap" in tab_labels
    assert "Species & tissue expression" in tab_labels
    assert "Volcano eligibility" in tab_labels
    assert len(app.multiselect) >= 8
    assert any("Columns to display" in item.label for item in app.multiselect)
    metric_labels = [metric.label for metric in app.metric]
    assert "Evolutionary groups assessed" in metric_labels
    assert "Milestone 1 pre-structure passes" in metric_labels
    app.text_input[0].set_value("Q9SA03").run()
    assert not app.exception
    app.radio[0].set_value("structural").run()
    assert not app.exception
    assert any(
        slider.label == "Minimum member druggability score"
        for slider in app.slider
    )


def test_app_reports_missing_database(monkeypatch: object, tmp_path: Path) -> None:
    """Invalid configuration is shown in-app without a database write."""

    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(tmp_path / "missing.duckdb"))
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert app.error
    assert "does not exist" in app.error[0].value


def test_app_accepts_master_parquet(master_parquet: Path, monkeypatch: object) -> None:
    """The one-Parquet mode renders the same grant-facing application."""
    monkeypatch.delenv("E3_RESOURCE_DUCKDB", raising=False)
    monkeypatch.setenv("E3_RESOURCE_PARQUET", str(master_parquet))
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert not app.exception
    assert len(app.tabs) == 21


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
    assert len(app.info) >= 4

    corrupt = tmp_path / "corrupt.duckdb"
    corrupt.write_text("not duckdb", encoding="utf-8")
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(corrupt))
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert app.error
    assert "Could not open" in app.error[0].value


def test_app_renders_portable_structure_and_alignment_tabs(
    resource_db: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """A valid pocket-review bundle activates both visual review tabs."""
    review_dir = make_pocket_review(tmp_path)
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_POCKET_REVIEW_DIR", str(review_dir))
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert not app.exception
    group_selectors = [
        selector for selector in app.selectbox if selector.label == "Evolutionary group"
    ]
    assert len(group_selectors) == 2
    assert all(
        selector.value == "groups/rank_001__hog__N0.HOG1.html"
        for selector in group_selectors
    )
