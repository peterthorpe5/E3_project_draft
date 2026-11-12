"""Exercise the E3 viewer pages, portable inputs and app-host alignment."""

import json
from pathlib import Path
import time

import duckdb
from streamlit.testing.v1 import AppTest

from e3app.navigation import CANDIDATE_STAGE, DEEPCLUST_STAGE
from e3app.research.jobs import artifact_path, get_job, job_directory, list_jobs
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
    assert app.radio(key="alignment_view_source").value == "Align a HOG"
    app.radio(key="alignment_view_source").set_value("Try an example").run()
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
                if button.label == "Start ESMFold prediction").proto.disabled
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


def test_align_published_hog_directly(resource_db, tmp_path, monkeypatch) -> None:
    """Load exact released members, select a reference and queue the frozen FASTA."""
    workspace = tmp_path / "worker"
    profile = tmp_path / "research.toml"
    profile.write_text(f"workspace={json.dumps(str(workspace))}\n", encoding="utf-8")
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "INSERT INTO hierarchical_membership VALUES "
            "('N0.HOG0001', 'Zea_mays', 'NO_SEQUENCE')"
        )
    path = Path(__file__).parents[2] / "src/e3app/streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    app.radio(key="e3_navigation_stage").set_value(DEEPCLUST_STAGE).run()
    page = app.radio(key=f"e3_navigation_page_{DEEPCLUST_STAGE}")
    page.set_value("DeepClust workbench").run()
    app.radio(key="research_section").set_value("Family analysis").run()
    app.radio(key="research_analysis_task").set_value("Alignment and tree").run()
    app.radio(key="analyse_route").set_value("Published HOG members").run()
    assert list_jobs(workspace=workspace) == []
    app.text_input(key="analyse_hog_input").set_value("n0.hog0001")
    next(button for button in app.button if button.label == "Load HOG members").click().run()
    assert any("2 of 3 members have usable sequences" in line.value for line in app.caption)
    downloads = [button.label for button in app.get("download_button")]
    assert "Download HOG protein FASTA" in downloads
    mode = app.radio(key="analyse_hog_mode_N0.HOG0001")
    mode.set_value("Choose members").run()
    members = app.multiselect(key="analyse_hog_choice_N0.HOG0001")
    member_table = app.session_state["analyse_hog_members"][1]
    members.select(member_table.loc[member_table["identifier"].eq("Q9SA03"), "member_key"].item())
    members.run()
    assert any("1 protein selected" in line.value for line in app.caption)
    app.radio(key="analyse_hog_mode_N0.HOG0001").set_value("All available members").run()
    reference = next(item for item in app.selectbox if item.label == "Reference protein")
    assert len(reference.options) == 3
    reference.select(next(option for option in reference.options if option.startswith("Q9SA03|")))
    prepare = next(
        button for button in app.button if button.label == "Prepare files for another machine"
    )
    prepare.click().run()
    assert "Download job files (ZIP)" in [button.label for button in app.get("download_button")]
    assert list_jobs(workspace=workspace) == []
    queue = next(button for button in app.button if button.label == "Queue alignment and tree")
    queue.click().run()
    jobs = list_jobs(workspace=workspace)
    assert len(jobs) == 1 and jobs[0]["operation"] == "align"
    directory = job_directory(workspace=workspace, job_id=jobs[0]["job_id"])
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    assert request["parameters"]["e3_hog_id"] == "N0.HOG0001"
    assert request["parameters"]["reference_id"].startswith("Q9SA03|")
    fasta = (directory / "input.fasta").read_text(encoding="utf-8")
    assert fasta.count(">") == 2 and "MSTNPKPN" in fasta and "MAAAN" in fasta
    assert "NO_SEQUENCE" not in fasta
    app.text_input(key="analyse_hog_input").set_value("N0.HOG9999999")
    next(button for button in app.button if button.label == "Load HOG members").click().run()
    assert "Download job files (ZIP)" not in [button.label for button in app.get("download_button")]
    assert not app.exception and not app.error
    app.radio(key=f"e3_navigation_page_{DEEPCLUST_STAGE}").set_value("JBrowse MSA").run()
    app.radio(key="alignment_view_source").set_value("Published HOG alignment").run()
    app.text_input(key="published_alignment_input").set_value("N0.HOG0001")
    find = next(button for button in app.button if button.label == "Find published alignment")
    find.click().run()
    next(button for button in app.button if button.label == "Align this HOG").click().run()
    assert app.radio(key="alignment_view_source").value == "Align a HOG"
    assert app.selectbox(key="msa_hog_selector").value == "N0.HOG0001"
    assert len(list_jobs(workspace=workspace)) == 1

    app.radio(key="msa_hog_mode_N0.HOG0001").set_value("Choose members").run()
    member_table = app.session_state["msa_hog_members"][1]
    chosen = member_table.loc[member_table["identifier"].eq("Q9SA03"), "member_key"].item()
    app.multiselect(key="msa_hog_choice_N0.HOG0001").select(chosen).run()
    app.button(key="selected_hog_members_annotate").click().run()
    assert app.radio(key="research_section").value == "Annotations"
    assert app.radio(key="annotate_route").value == "Prepared FASTA"
    label, prepared = app.session_state["research_prepared_fasta"]
    assert "N0.HOG0001" in label
    assert prepared.startswith(">Q9SA03|") and prepared.count(">") == 1
    assert prepared.splitlines()[1] == "MSTNPKPN"
    assert len(list_jobs(workspace=workspace)) == 1
    assert not app.exception and not app.error


def test_jbrowse_aligns_a_selected_hog_on_the_app_host(resource_db, tmp_path, monkeypatch):
    """Start at the HOG selector and open the resulting alignment from a one-shot worker."""
    mafft = tmp_path / "mafft"
    mafft.write_text(
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n'
        'if [[ "$1" == "--version" ]]; then printf "%s\\n" "MAFFT test fixture"; exit 0; fi\n'
        "awk '/^>/ { print; next } { while (length($0) < 8) $0 = $0 \"-\"; print }' "
        '"${@: -1}"\n',
        encoding="utf-8",
    )
    mafft.chmod(0o700)
    workspace = tmp_path / "worker"
    profile = tmp_path / "research.toml"
    profile.write_text(
        f"workspace={json.dumps(str(workspace))}\nmafft={json.dumps(str(mafft))}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    path = Path(__file__).parents[2] / "src/e3app/streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=30).run()
    app.radio(key="e3_navigation_stage").set_value(CANDIDATE_STAGE).run()
    app.radio(key=f"e3_navigation_page_{CANDIDATE_STAGE}").set_value("JBrowse MSA").run()
    assert app.selectbox(key="msa_hog_selector").value is None
    assert not app.get("iframe")
    app.selectbox(key="msa_hog_selector").set_value("N0.HOG0001").run()
    assert any(item.label == "Download HOG protein FASTA" for item in app.get("download_button"))
    app.button(key="msa_prepare_job").click().run()
    assert any(item.label == "Download job files (ZIP)" for item in app.get("download_button"))
    assert list_jobs(workspace=workspace) == []
    app.button(key="msa_align_here").click().run()
    jobs = list_jobs(workspace=workspace)
    assert len(jobs) == 1
    job_id = jobs[0]["job_id"]
    deadline = time.monotonic() + 20
    job = get_job(workspace=workspace, job_id=job_id)
    while job["status"] in {"QUEUED", "RUNNING"} and time.monotonic() < deadline:
        time.sleep(0.1)
        job = get_job(workspace=workspace, job_id=job_id)
    directory = job_directory(workspace=workspace, job_id=job_id)
    assert job["status"] == "COMPLETE", (job, (directory / "local_worker.log").read_text())
    alignment = artifact_path(workspace=workspace, job_id=job_id, artifact="alignment.fasta")
    assert "MAAAN---" in alignment.read_text(encoding="utf-8")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["parameters"]["e3_hog_id"] == "N0.HOG0001"
    assert manifest["parameters"]["execution_target"] == "app_host"
    app.run()
    open_alignment = next(button for button in app.button
                          if button.label == "Open completed alignment")
    open_alignment.click().run()
    assert app.radio(key="alignment_view_source").value == "Completed alignment job"
    assert app.selectbox(key="research_alignment_job").value == job_id
    assert "MAAAN---" in app.get("iframe")[0].proto.srcdoc

    next(button for button in app.button if button.label == "Calculate heatmap").click().run()
    assert "MAAAN---" in app.get("iframe")[0].proto.srcdoc
    assert len(app.get("plotly_chart")) == 1
    selection, comparison = app.session_state["alignment_heatmap_result"]
    assert selection[0] == job_id
    assert comparison.similarity.iat[0, 1] == 0.2
    assert comparison.denominators.iat[0, 1] == 5
    assert {"Download identity matrix (TSV)", "Download comparable residue counts (TSV)"} <= {
        button.label for button in app.get("download_button")
    }
    first_protein = selection[1][0]
    proteins_key = f"identity_heatmap_proteins_{job_id}"
    app.multiselect(key=proteins_key).set_value([first_protein])
    next(button for button in app.button if button.label == "Calculate heatmap").click().run()
    updated_selection, updated = app.session_state["alignment_heatmap_result"]
    assert updated_selection == (job_id, (first_protein,))
    assert updated.similarity.shape == (1, 1)
    app.toggle(key="show_alignment_heatmap").set_value(False).run()
    assert app.get("iframe") and not app.get("plotly_chart")
    app.toggle(key="show_alignment_heatmap").set_value(True).run()
    assert app.multiselect(key=proteins_key).value == [first_protein]
    assert len(app.get("plotly_chart")) == 1

    for action, section, input_key in (
        ("subcluster", "Family analysis", "analyse"),
        ("annotate", "Annotations", "annotate"),
        ("model", "Models", "fold"),
    ):
        app.button(key=f"alignment_members_{job_id}_{action}").click().run()
        assert app.radio(key="research_section").value == section
        assert app.radio(key=f"{input_key}_route").value == "Completed job"
        assert app.selectbox(key=f"{input_key}_source").value == (job_id, "sequences.fasta")
        if action == "subcluster":
            assert app.radio(key="research_analysis_task").value == "Stricter subclusters"
        if action == "model":
            assert app.radio(key="esmfold_view_route").value == "Predict with ESMFold"
        assert not app.exception and not app.error
        app.radio(key="research_section").set_value("Alignments and trees").run()

    assert len(list_jobs(workspace=workspace)) == 1
    assert not app.exception and not app.error
