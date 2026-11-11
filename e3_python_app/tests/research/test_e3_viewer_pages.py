"""Exercise the new E3 pages and portable inputs without starting a worker."""

import json
from pathlib import Path

import duckdb
from streamlit.testing.v1 import AppTest

from e3app.navigation import CANDIDATE_STAGE, DEEPCLUST_STAGE
from e3app.research.jobs import list_jobs
from test_pocket_review import make_pocket_review


def test_main_e3_pages_and_both_workbench_entries(resource_db, tmp_path, monkeypatch) -> None:
    """Open named viewer pages and keep the old search out of the primary workflow."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "CREATE TABLE domain_hits AS SELECT 'Q5ZC88' AS member_accession, "
            "'N0.HOG0000390' AS primary_group_id, 'Oryza_sativa' AS species_column, "
            "744 AS protein_length, 1 AS location_start, 744 AS location_end, "
            "'PF_TEST' AS entry_accession, 'Example domain' AS entry_name"
        )
    workspace = tmp_path / "worker"
    profile = tmp_path / "research.toml"
    profile.write_text(f"workspace={json.dumps(str(workspace))}\n", encoding="utf-8")
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    path = Path(__file__).parents[2] / "src/e3app/streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    stage = "🧬 DeepClust research"
    app.radio(key="e3_navigation_stage").set_value(stage).run()
    page_key = f"e3_navigation_page_{stage}"
    assert app.radio(key=page_key).value == "DeepClust results & FASTA"
    assert not any("Queue Top-N" in item.label for item in app.button)
    app.radio(key=page_key).set_value("JBrowse MSA").run()
    assert app.radio(key="alignment_view_source").value == "Try an example"
    document = app.get("iframe")[0].proto.srcdoc
    assert '"height": 274' in document
    assert '"alignment_length": 56' in document
    assert any(item.label == "Download standalone JBrowse MSA viewer"
               for item in app.get("download_button"))
    app.radio(key=page_key).set_value("Protein feature browser").run()
    assert not any(item.label == "Workbench page" for item in app.radio)
    assert not app.get("iframe")
    app.text_input(key="recorded_feature_search_term").set_value("Q5ZC88")
    next(button for button in app.button if button.label == "Find recorded proteins").click().run()
    assert app.selectbox(key="recorded_feature_context").value[0] == "Q5ZC88"
    assert "Example domain" in app.get("iframe")[0].proto.srcdoc
    assert any(item.label == "Download Nightingale viewer (HTML)"
               for item in app.get("download_button"))
    app.radio(key=page_key).set_value("ESMFold & models").run()
    assert app.radio(key="esmfold_view_route").value == "Open an existing PDB"
    app.radio(key=page_key).set_value("DeepClust workbench").run()
    assert "DeepClust results & FASTA" in app.radio(key="research_section").options
    assert "Top-200 cluster campaign" not in app.radio(key="research_section").options
    app.checkbox(key="legacy_deepclust_enabled").check().run()
    assert "Top-200 cluster campaign" in app.radio(key="legacy_deepclust_route").options
    stage = "🟣 3 · E3 orthology context"
    app.radio(key="e3_navigation_stage").set_value(stage).run()
    app.radio(key=f"e3_navigation_page_{stage}").set_value("Protein research workbench").run()
    assert "DeepClust results & FASTA" in app.radio(key="research_section").options
    assert not app.exception and not app.error
    assert list_jobs(workspace=workspace) == []


def test_candidate_viewer_handoffs_keep_the_exact_selection(
    resource_db, tmp_path, monkeypatch,
) -> None:
    """Open the selected sequence, then show the selected HOG's missing-alignment fallback."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "CREATE TABLE domain_hits AS SELECT 'Q9SA03' AS member_accession, "
            "'N0.HOG0001' AS primary_group_id, 'Arabidopsis_thaliana' AS species_column, "
            "8 AS protein_length, 1 AS location_start, 4 AS location_end, "
            "'PF_TEST' AS entry_accession, 'Example domain' AS entry_name"
        )
    workspace = tmp_path / "worker"
    profile = tmp_path / "research.toml"
    profile.write_text(f"workspace={json.dumps(str(workspace))}\n", encoding="utf-8")
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_POCKET_REVIEW_DIR", str(make_pocket_review(tmp_path)))
    path = Path(__file__).parents[2] / "src/e3app/streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    app.radio(key="e3_navigation_stage").set_value(CANDIDATE_STAGE).run()
    page_key = f"e3_navigation_page_{CANDIDATE_STAGE}"
    assert {"Protein feature browser", "JBrowse MSA", "ESMFold & models"}.issubset(
        app.radio(key=page_key).options,
    )
    app.radio(key=page_key).set_value("Visual explorer").run()
    app.button(key="visual_candidate_protein_features").click().run()
    assert app.radio(key=page_key).value == "Protein feature browser"
    assert app.text_input(key="recorded_feature_search_term").value == "N0.HOG0001"
    assert app.selectbox(key="recorded_feature_context").value[0] == "Q9SA03"
    app.button(key="feature_to_models").click().run()
    assert app.radio(key=page_key).value == "ESMFold & models"
    assert app.radio(key="fold_route").value == "Selected E3 protein"
    assert any("Q9SA03 · N0.HOG0001" in line.value for line in app.caption)
    assert any(button.label == "Download selected protein FASTA"
               for button in app.get("download_button"))
    assert next(button for button in app.button
                if button.label == "Queue ESMFold prediction").proto.disabled
    app.radio(key="fold_route").set_value("Upload FASTA").run()
    uploader = app.get("file_uploader")[0].proto
    if hasattr(uploader, "max_upload_size_mb"):
        assert uploader.max_upload_size_mb == 20
    app.radio(key=page_key).set_value("Protein feature browser").run()
    app.button(key="feature_to_msa").click().run()
    assert app.radio(key=page_key).value == "JBrowse MSA"
    assert app.radio(key="alignment_view_source").value == "Published HOG alignment"
    assert any("N0.HOG0001" in info.value for info in app.info)
    app.text_input(key="published_alignment_input").set_value("N0.HOG1")
    find = next(button for button in app.button if button.label == "Find published alignment")
    find.click().run()
    assert any(button.label == "Download published aligned FASTA"
               for button in app.get("download_button"))
    assert "AC-DE" in app.get("iframe")[0].proto.srcdoc
    app.text_input(key="published_alignment_input").set_value("N0.HOG0001")
    find = next(button for button in app.button if button.label == "Find published alignment")
    find.click().run()
    prepare = next(button for button in app.button if button.label == "Prepare HOG member FASTA")
    prepare.click().run()
    assert app.radio(key="e3_navigation_stage").value == DEEPCLUST_STAGE
    assert app.radio(key="deepclust_exchange_mode").value == "Prepare query FASTA"
    assert any("2 of 2 HOG members" in caption.value for caption in app.caption)
    assert not app.exception and not app.error
    assert list_jobs(workspace=workspace) == []


def test_prepare_alignment_request_never_queues_a_job(tmp_path, monkeypatch) -> None:
    """A portable job retains the input and exposes its download without a local worker."""
    workspace = tmp_path / "worker"
    profile = tmp_path / "research.toml"
    profile.write_text(f"workspace={json.dumps(str(workspace))}\n", encoding="utf-8")
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    app = AppTest.from_string(
        "from e3app.research.ui import render_research_workbench\n"
        "render_research_workbench(initial_section='Family analysis', external_search=True)\n",
        default_timeout=20,
    ).run()
    app.radio(key="research_analysis_task").set_value("Alignment and tree").run()
    app.radio(key="analyse_route").set_value("Paste FASTA").run()
    app.text_area(key="analyse_pasted_fasta").set_value(">a\nACD\n>b\nACE\n").run()
    next(item for item in app.button if item.label == "Prepare files for another machine"
         ).click().run()
    assert not app.exception and not app.error
    assert any(item.label == "Download job files (ZIP)" for item in app.get("download_button"))
    assert list_jobs(workspace=workspace) == []
