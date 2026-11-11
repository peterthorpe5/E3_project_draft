"""Exercise the new E3 pages and portable inputs without starting a worker."""

import json
from pathlib import Path

import duckdb
from streamlit.testing.v1 import AppTest

from e3app.research.jobs import list_jobs


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
    app.radio(key="alignment_view_source").set_value("Try an example").run()
    assert any(item.label == "Download standalone JBrowse MSA viewer"
               for item in app.get("download_button"))
    app.radio(key=page_key).set_value("Protein feature browser").run()
    assert not any(item.label == "Workbench page" for item in app.radio)
    assert any("Q5ZC88" in option for option in app.selectbox[0].options)
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
