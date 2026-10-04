"""Headless end-to-end tests for the Streamlit presentation layer."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from e3app.taxonomy import load_taxonomy_authority
from test_pocket_review import make_pocket_review

STAGE_TAB_LABELS = [
    "🔵 1 · Information",
    "🟢 2 · Candidate discovery",
    "🟣 3 · E3 orthology context",
    "🟠 4 · Structural prioritisation",
    "🟡 5 · Structural comparison",
    "🔴 6 · Chemistry & outputs",
]


def _navigate(app: AppTest, *, stage: str, page: str) -> AppTest:
    """Select one lazily rendered application page in a headless test."""
    stage_control = next(
        radio for radio in app.radio if radio.label == "Analysis section"
    )
    stage_control.set_value(stage).run()
    page_control = next(radio for radio in app.radio if radio.label == "Page")
    page_control.set_value(page).run()
    return app


def test_streamlit_source_uses_current_width_and_widget_state_contracts() -> None:
    """Removed Streamlit APIs and duplicate selectbox defaults do not regress."""
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    source = path.read_text(encoding="utf-8")
    assert "use_container_width" not in source
    assert "maximum_allowed = min(config.max_rows, 1000)" in source
    assert "font-size: 1.02rem !important" in source
    assert "font-size: 0.96rem !important" in source
    assert "font-size: 1.48rem !important" in source
    assert "font-size: 1.22rem !important" in source
    assert "Load AlphaFold confidence for graph and trimming" in source
    assert "components.html(viewer_document, height=1480, scrolling=True)" in source
    compatibility_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "e3app"
        / "resources"
        / "terminal_trim_compat.js"
    )
    compatibility_source = compatibility_path.read_text(encoding="utf-8")
    assert "const height = 460;" in compatibility_source
    assert "retained-core mean pLDDT" in compatibility_source
    assert "do not recalculate the saved HOG or within-HOG rankings" in (
        compatibility_source
    )
    selector_start = source.index('selector_key = "recommendation_druggability_group"')
    selector_end = source.index("plot_rows, overview_truncated", selector_start)
    assert "index=" not in source[selector_start:selector_end]


def test_app_renders_and_searches(resource_db: Path, monkeypatch: object) -> None:
    """Lazy navigation renders one page and supports terminal and search work."""

    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_MAX_TABLE_ROWS", "100")
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert not app.exception
    assert app.title[0].value == "ARIA plant E3 discovery and ligandability resource"
    stage_control = next(
        radio for radio in app.radio if radio.label == "Analysis section"
    )
    assert stage_control.options == STAGE_TAB_LABELS
    assert stage_control.value == "🔵 1 · Information"
    page_control = next(radio for radio in app.radio if radio.label == "Page")
    assert page_control.value == "Overview"
    assert "Glossary" in page_control.options
    primary_help = [
        expander
        for expander in app.expander
        if expander.label == "❓ How to use this tab"
    ]
    assert len(primary_help) == 1
    assert not any(
        expander.label == "ⓘ Methods and thresholds"
        for expander in app.expander
    )

    _navigate(
        app,
        stage="🟣 3 · E3 orthology context",
        page="C-terminal conservation",
    )
    assert not app.exception
    terminal_input = next(
        item
        for item in app.text_input
        if item.label == "Exact C-terminal sequence"
    )
    terminal_slider = next(
        slider
        for slider in app.slider
        if slider.label == "Minimum matching plant members (%)"
    )
    assert terminal_input.value == "N"
    assert terminal_slider.value == 80
    plant_selector = next(
        selector
        for selector in app.multiselect
        if selector.label
        == "Plant species included in the conservation calculation"
    )
    assert "Arabidopsis_thaliana" in plant_selector.value
    assert "Oryza_sativa" in plant_selector.value
    assert any(
        metric.label == "Qualifying groups" and metric.value == "1"
        for metric in app.metric
    )
    group_selector = next(
        selector
        for selector in app.selectbox
        if selector.label == "Orthology group to inspect"
    )
    assert group_selector.value == "N0.HOG0001"
    assert any(
        metric.label == "Groups with an Arabidopsis match"
        and metric.value == "1"
        for metric in app.metric
    )
    assert any(
        button.label == "Download available selected-group sequences as FASTA"
        for button in app.get("download_button")
    )
    assert len(
        [
            expander
            for expander in app.expander
            if expander.label == "❓ How to use this tab"
        ]
    ) == 1
    assert len(
        [
            expander
            for expander in app.expander
            if expander.label == "ⓘ Methods and thresholds"
        ]
    ) == 1

    _navigate(
        app,
        stage="🔴 6 · Chemistry & outputs",
        page="Search",
    )
    assert not app.exception
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
    _navigate(
        app,
        stage="🟢 2 · Candidate discovery",
        page="Computational recommendations",
    )
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
    stage_control = next(
        radio for radio in app.radio if radio.label == "Analysis section"
    )
    assert stage_control.options == STAGE_TAB_LABELS
    page_control = next(radio for radio in app.radio if radio.label == "Page")
    assert page_control.value == "Overview"


def test_app_accepts_custom_reviewed_taxonomy(
    resource_db: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """A new release taxonomy bridge is exposed without inferred mappings."""
    mapping = tmp_path / "reviewed_taxonomy.tsv"
    mapping.write_text(
        "workflow_species_label\taccepted_species_name\tncbi_taxon_id\t"
        "lineage_taxon_ids\tlineage_names\tlineage_ranks\t"
        "mapping_status\trole\n"
        "Arabidopsis_thaliana\tArabidopsis thaliana\t3702\t1;2759;3702\t"
        "root;Eukaryota;Arabidopsis thaliana\t"
        "no rank;superkingdom;species\tREVIEWED\ttarget_plant\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_TAXONOMY_MAP", str(mapping))
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert not app.exception
    assert any(
        str(mapping.resolve()) in success.value for success in app.success
    )
    assert any(
        "Custom taxonomy mapping" in success.value for success in app.success
    )


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
    assert len(app.info) >= 1

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
    monkeypatch.setenv("E3_HUMAN_PLANT_REVIEW_DIR", str(review_dir))
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=10).run()
    assert not app.exception

    _navigate(
        app,
        stage="🟡 5 · Structural comparison",
        page="3D structures & pockets",
    )
    assert not app.exception
    group_selectors = [
        selector for selector in app.selectbox if selector.label == "Evolutionary group"
    ]
    assert len(group_selectors) == 1
    assert group_selectors[0].value == "groups/rank_001__hog__N0.HOG1.html"

    _navigate(
        app,
        stage="🟡 5 · Structural comparison",
        page="3D alignment",
    )
    assert not app.exception
    superposition_selectors = [
        selector
        for selector in app.selectbox
        if selector.label == "Evolutionary group for structural superposition"
    ]
    assert len(superposition_selectors) == 1
    pair_selectors = [
        selector
        for selector in app.selectbox
        if selector.label == "Reference and aligned protein pair"
    ]
    assert len(pair_selectors) == 1
    assert any("Reference: P1" in option for option in pair_selectors[0].options)
    expander_labels = [expander.label for expander in app.expander]
    assert "❓ Why was this structural reference selected?" in expander_labels
    assert "❓ Define the pair-evidence terms" in expander_labels
    assert "↗ EMERALD and Mol* follow-up" in expander_labels
    pair_downloads = [
        button
        for button in app.get("download_button")
        if button.label == "Download exact pair FASTA"
    ]
    assert len(pair_downloads) == 1

    _navigate(
        app,
        stage="🟡 5 · Structural comparison",
        page="Human & plant 3D alignment",
    )
    assert not app.exception
    human_group_selectors = [
        selector
        for selector in app.selectbox
        if selector.label == "Human-and-plant evolutionary group"
    ]
    assert len(human_group_selectors) == 1
    rank_checks = [
        number
        for number in app.number_input
        if number.label == "Original parent rank"
    ]
    assert len(rank_checks) == 1
    assert rank_checks[0].value == 7
    pair_selectors = [
        selector
        for selector in app.selectbox
        if selector.label == "Reference and aligned protein pair"
    ]
    assert len(pair_selectors) == 1
    assert any("Reference: P1" in option for option in pair_selectors[0].options)
    nested_labels = {tab.label for tab in app.tabs}
    assert "Pairwise 3D comparison" in nested_labels
    assert "Choose structures & pockets" in nested_labels
    assert "Pocket-aligned FASTA" in nested_labels
    expander_labels = [expander.label for expander in app.expander]
    assert expander_labels.count("❓ Why was this structural reference selected?") == 1
    assert expander_labels.count("❓ Define the pair-evidence terms") == 1
    assert "❓ Why are only some parent ranks listed?" in expander_labels
    assert "❓ What do the protein and pocket choices mean?" in expander_labels
    assert expander_labels.count("↗ EMERALD and Mol* follow-up") == 1
    pair_downloads = [
        button
        for button in app.get("download_button")
        if button.label == "Download exact pair FASTA"
    ]
    assert len(pair_downloads) == 1


def _terminal_app(*, resource_db: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """Open the conservation page against a representative read-only resource."""
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_MAX_TABLE_ROWS", "100")
    path = Path(__file__).resolve().parents[1] / "src" / "e3app" / "streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=15).run()
    return _navigate(app=app, stage="🟣 3 · E3 orthology context", page="C-terminal conservation")


def test_terminal_compact_table_species_audit_and_settings_downloads(
    resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complete user workflow exposes readable fractions and exact downloadable evidence."""
    app = _terminal_app(resource_db=resource_db, monkeypatch=monkeypatch)
    assert not app.exception
    compact = next(table.value for table in app.dataframe if "Group" in table.value.columns)
    assert compact.loc[0, "Plant proteins matching / assessed"] == "2/2 (100.0%)"
    assert compact.loc[0, "Arabidopsis matching IDs"] == "Q9SA03"
    assert compact.loc[0, "Human IDs"] == "P38398"
    assert compact.loc[0, "Group rank after structure"] == 1
    assert len(compact.columns) == 9
    species = next(
        table.value for table in app.dataframe if "Species result" in table.value.columns
    )
    assert len(species) == 13
    maize = species.loc[species["Source species"] == "Zea_mays"].iloc[0]
    assert maize["Species result"] == "No published member"
    settings = next(
        table.value for table in app.dataframe if "setting" in table.value.columns
    ).set_index(keys="setting")
    assert settings.loc["qualifying_group_count", "value"] == "1"
    assert settings.loc["candidate_bounded", "value"] == "True"
    assert settings.loc["minimum_plant_species_match_fraction", "value"] == "0.0"
    labels = {button.label for button in app.get("download_button")}
    assert "Download screen settings and counts as TSV" in labels
    assert "Download species evidence as Excel" in labels
    assert "Download member evidence as Excel" in labels
    assert any(
        expander.label == "❓ How to read the conservation tables" for expander in app.expander
    )


def test_terminal_member_filters_preserve_full_screen_and_missing_sequences(
    resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filtering non-matches or unavailable rows changes only the member preview."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "UPDATE candidate_group_member_sequences SET protein_sequence = 'MAAAQ' "
            "WHERE species = 'Homo_sapiens'"
        )
        connection.execute(
            "INSERT INTO candidate_group_member_sequences(record_type, group_id, species, "
            "raw_identifier, protein_sequence) VALUES "
            "('HIERARCHICAL_ORTHOGROUP', 'N0.HOG0001', 'Triticum_aestivum', 'wheat_missing', NULL)"
        )
    app = _terminal_app(resource_db=resource_db, monkeypatch=monkeypatch)
    assert not app.exception
    app.selectbox(key="terminal_member_match_filter").set_value("non_match").run()
    assert not app.exception
    preview = next(table.value for table in app.dataframe if "Match state" in table.value.columns)
    assert preview["Accession"].tolist() == ["P38398"]
    assert preview["Match state"].tolist() == ["Assessed non-match"]
    assert any(metric.label == "Qualifying groups" and metric.value == "1" for metric in app.metric)
    app.selectbox(key="terminal_member_match_filter").set_value("unavailable").run()
    assert not app.exception
    preview = next(table.value for table in app.dataframe if "Match state" in table.value.columns)
    assert preview["Source protein ID"].tolist() == ["wheat_missing"]
    assert preview["Match state"].tolist() == ["Sequence unavailable"]
    app.selectbox(key="terminal_member_role_filter").set_value("human").run()
    assert not app.exception
    assert any("No members meet" in info.value for info in app.info)
    assert any(
        button.label == "Download filtered member preview as TSV"
        for button in app.get("download_button")
    )
    complete = next(
        table.value for table in app.dataframe if "protein_description" in table.value.columns
    )
    assert len(complete) == 4
    with duckdb.connect(str(resource_db), read_only=True) as connection:
        count = connection.execute(
            "SELECT count(*) FROM candidate_group_member_sequences"
        ).fetchone()[0]
        assert count == 6


@pytest.mark.parametrize(
    ("control", "taxon_id", "expected"),
    [("excluded_exact_taxon_ids", 9606, "0"),
     ("only_clade_taxon_ids", 33090, "0"),
     ("include_clade_taxon_ids", 4479, "1"),
     ("required_exact_taxon_ids", 3702, "1")],
)
def test_terminal_taxonomy_controls_change_groups_on_form_submission(
    resource_db: Path, monkeypatch: pytest.MonkeyPatch,
    control: str, taxon_id: int, expected: str,
) -> None:
    """Reviewed clade/exact predicates filter full membership without mutating denominators."""
    app = _terminal_app(resource_db=resource_db, monkeypatch=monkeypatch)
    app.multiselect(key=f"terminal_{control}").set_value([taxon_id])
    next(
        button for button in app.button if button.label == "Apply C-terminal conservation screen"
    ).click()
    app.run()
    assert not app.exception
    assert any(
        metric.label == "Qualifying groups" and metric.value == expected for metric in app.metric
    )
    if expected == "0":
        assert any("No published group meets" in info.value for info in app.info)
    else:
        compact = next(table.value for table in app.dataframe if "Group" in table.value.columns)
        assert compact.loc[0, "Plant proteins matching / assessed"] == "2/2 (100.0%)"
    settings = next(
        table.value for table in app.dataframe if "setting" in table.value.columns
    ).set_index(keys="setting")
    assert settings.loc[control, "value"] == str(taxon_id)


def test_terminal_custom_taxonomy_keeps_arabidopsis_and_human_roles(
    resource_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Custom source aliases preserve the reviewed experimental and comparison roles."""
    taxonomy = load_taxonomy_authority().species_taxonomy.copy()
    for source, alias in (("Arabidopsis_thaliana", "arath_input"), ("Homo_sapiens", "human_input")):
        taxonomy.loc[taxonomy["source_species_name"] == source, "source_species_name"] = alias
        with duckdb.connect(str(resource_db)) as connection:
            connection.execute(
                "UPDATE candidate_group_member_sequences SET species = ? WHERE species = ?",
                [alias, source],
            )
    path = tmp_path / "reviewed_taxonomy.tsv"
    taxonomy.to_csv(path_or_buf=path, sep="\t", index=False)
    monkeypatch.setenv("E3_TAXONOMY_MAP", str(path))
    app = _terminal_app(resource_db=resource_db, monkeypatch=monkeypatch)
    assert not app.exception
    assert app.checkbox(key="terminal_require_arabidopsis").value
    compact = next(table.value for table in app.dataframe if "Group" in table.value.columns)
    assert compact.loc[0, "Arabidopsis matching IDs"] == "Q9SA03"
    assert compact.loc[0, "Human IDs"] == "P38398"
    app.selectbox(key="terminal_member_role_filter").set_value("human").run()
    preview = next(table.value for table in app.dataframe if "Match state" in table.value.columns)
    assert preview["Source species"].tolist() == ["human_input"]
    assert preview["Accepted species"].tolist() == ["Homo sapiens"]


def test_terminal_deselecting_arabidopsis_disables_the_match_requirement(
    resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A form state from an earlier run cannot enforce Arabidopsis after it is deselected."""
    app = _terminal_app(resource_db=resource_db, monkeypatch=monkeypatch)
    app.multiselect(key="terminal_plant_species").set_value(["Oryza_sativa"])
    app.number_input(key="terminal_minimum_members").set_value(1)
    app.number_input(key="terminal_minimum_species").set_value(1)
    next(
        button for button in app.button if button.label == "Apply C-terminal conservation screen"
    ).click()
    app.run()
    assert not app.exception
    settings = next(
        table.value for table in app.dataframe if "setting" in table.value.columns
    ).set_index(keys="setting")
    assert settings.loc["require_arabidopsis_match", "value"] == "False"
    assert app.checkbox(key="terminal_require_arabidopsis").disabled
    assert any(metric.label == "Qualifying groups" and metric.value == "1" for metric in app.metric)


def test_terminal_row_selection_opens_group_and_preserves_manual_selection(
    resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dataframe row event and the group picker drive the same inspected group."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "INSERT INTO candidate_group_member_sequences(record_type, group_id, species, "
            "raw_identifier, protein_sequence) VALUES "
            "('HIERARCHICAL_ORTHOGROUP', 'N0.HOG0002', 'Arabidopsis_thaliana', 'arab2', 'MN'), "
            "('HIERARCHICAL_ORTHOGROUP', 'N0.HOG0002', 'Oryza_sativa', 'rice2', 'MN')"
        )
    original_dataframe = st.dataframe

    def selected_row(*args: object, **kwargs: object) -> object:
        """Deliver a row-selection event while retaining the actual rendered table."""
        original_result = original_dataframe(*args, **kwargs)
        if str(kwargs.get("key", "")).startswith("terminal_group_table_"):
            return SimpleNamespace(selection=SimpleNamespace(rows=[1]))
        return original_result

    monkeypatch.setattr(st, "dataframe", selected_row)
    app = _terminal_app(resource_db=resource_db, monkeypatch=monkeypatch)
    assert not app.exception
    selector = app.selectbox(key="terminal_selected_group")
    assert selector.value == "N0.HOG0002"
    selector.set_value("N0.HOG0001").run()
    assert not app.exception
    assert app.selectbox(key="terminal_selected_group").value == "N0.HOG0001"
