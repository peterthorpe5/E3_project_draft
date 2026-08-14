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
    assert len(app.tabs) == 28
    assert "Glossary" in [tab.label for tab in app.tabs]
    assert "3D alignment" in [tab.label for tab in app.tabs]
    glossary_selectors = [
        selector for selector in app.selectbox if selector.label == "Glossary section"
    ]
    assert len(glossary_selectors) == 1
    assert glossary_selectors[0].options[0] == "All sections"
    tab_labels = [tab.label for tab in app.tabs]
    assert "Candidate landscape" in tab_labels
    assert "Glossary" in tab_labels
    assert "Workflow schematic" in tab_labels
    assert "Computational recommendations" in tab_labels
    assert "Threshold explorer" in tab_labels
    assert "Visual explorer" in tab_labels
    assert "Expression heatmap" in tab_labels
    assert "Species & tissue expression" in tab_labels
    assert "Volcano eligibility" in tab_labels
    assert "Computational chemistry" in tab_labels
    assert "3D structures & pockets" in tab_labels
    assert "Pocket-aligned sequences" in tab_labels
    assert "Human HOGs" in tab_labels
    assert "Plant & human HOGs" in tab_labels
    assert "Seed & HOG explorer" in tab_labels
    assert "Search" in tab_labels
    assert "3D alignment" in tab_labels
    assert any(
        "Stages 00–01" in markdown.value
        for markdown in app.markdown
    )
    assert len(app.multiselect) >= 8
    assert any("Columns to display" in item.label for item in app.multiselect)
    metric_labels = [metric.label for metric in app.metric]
    assert "Evolutionary groups assessed" in metric_labels
    assert "Milestone 1 pre-structure passes" in metric_labels
    assert "E3-seeded neighbourhoods" in metric_labels
    orthology_tab = next(tab for tab in app.tabs if tab.label == "Orthology")
    orthology_checkbox_labels = [
        checkbox.label for checkbox in orthology_tab.checkbox
    ]
    assert "Log-transform group-size axis" in orthology_checkbox_labels
    assert "Log-transform group-count axis" in orthology_checkbox_labels
    assert "Log-transform 1KP-species axis" in orthology_checkbox_labels
    seed_tab = next(tab for tab in app.tabs if tab.label == "Seed & HOG explorer")
    group_level_radios = [orthology_tab.radio[0], seed_tab.radio[0]]
    for group_level_radio in group_level_radios:
        assert group_level_radio.label == "OrthoFinder grouping level"
        assert (
            "Root-level phylogenetic HOGs (N0.HOG…; recommended)"
            in group_level_radio.options
        )
        assert (
            "Original MCL orthogroups (OG…; broader legacy view)"
            in group_level_radio.options
        )
    search_area = next(
        area for area in app.text_area if area.label == "Search term(s)"
    )
    search_button = next(
        button
        for button in app.button
        if button.label == "Search the complete loaded resource"
    )
    search_area.set_value("Q9SA03")
    search_button.click()
    app.run()
    assert not app.exception
    assert any(
        metric.label == "Entered terms matched" and metric.value == "1 / 1"
        for metric in app.metric
    )
    assert any(
        slider.label == "Minimum member druggability score"
        for slider in app.slider
    )
    metric_labels = [metric.label for metric in app.metric]
    assert "Pre-structure passes" in metric_labels
    assert "Structurally informed passes" in metric_labels
    assert any(
        "### Pre-structure candidate list" in markdown.value
        for markdown in app.markdown
    )
    assert any(
        "### Structurally informed candidate list" in markdown.value
        for markdown in app.markdown
    )
    focused_sliders = [
        slider
        for slider in app.slider
        if slider.label
        == "Minimum member druggability required for every assessed member"
    ]
    assert len(focused_sliders) == 1
    assert focused_sliders[0].value == 0.50
    assert any(
        "recorded production threshold is 0.50" in caption.value
        for caption in app.caption
    )


def test_app_reports_missing_database(monkeypatch: object, tmp_path: Path) -> None:
    """Invalid configuration is shown in-app without a database write."""

    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(tmp_path / "missing.duckdb"))
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert app.error
    assert "does not exist" in app.error[0].value


def test_final_druggability_slider_recalculates_the_focused_pass_list(
    recommendation_threshold_db: Path,
    monkeypatch: object,
) -> None:
    """Changing only the final threshold updates counts without app errors."""
    monkeypatch.setenv(
        "E3_RESOURCE_DUCKDB",
        str(recommendation_threshold_db),
    )
    monkeypatch.setenv("E3_MAX_TABLE_ROWS", "100")
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert not app.exception
    focused = next(
        slider
        for slider in app.slider
        if slider.label
        == "Minimum member druggability required for every assessed member"
    )
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Recorded passes at 0.50"] == "1"
    assert metrics["Sensitivity passes at 0.50"] == "1"
    group_selectors = [
        selector
        for selector in app.selectbox
        if selector.label == "Evolutionary group to display"
    ]
    assert len(group_selectors) == 1
    assert group_selectors[0].value == "cluster_1"
    assert "All groups reaching the last gate" in group_selectors[0].options

    focused.set_value(0.30).run()
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Recorded passes at 0.50"] == "1"
    assert metrics["Sensitivity passes at 0.30"] == "2"
    assert metrics["Groups changing pass status"] == "1"
    group_selector = next(
        selector
        for selector in app.selectbox
        if selector.label == "Evolutionary group to display"
    )
    group_selector.set_value("cluster_2").run()
    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Minimum member score"] == "0.325"
    assert metrics["Status at 0.30"] == "PASS"
    assert any(
        "N0.HOG0002" in markdown.value and "cluster_2" in markdown.value
        for markdown in app.markdown
    )
    assert any(
        "Each point is one assessed member's retained selected-pocket score"
        in caption.value
        for caption in app.caption
    )


def test_app_accepts_master_parquet(master_parquet: Path, monkeypatch: object) -> None:
    """The one-Parquet mode renders the same grant-facing application."""
    monkeypatch.delenv("E3_RESOURCE_DUCKDB", raising=False)
    monkeypatch.setenv("E3_RESOURCE_PARQUET", str(master_parquet))
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert not app.exception
    assert len(app.tabs) == 26
    assert "Glossary" in [tab.label for tab in app.tabs]
    assert "Workflow schematic" in [tab.label for tab in app.tabs]
    assert "3D alignment" in [tab.label for tab in app.tabs]


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
