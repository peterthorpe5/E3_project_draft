"""Behavioural tests for guided navigation, handoffs and submission prerequisites."""

from dataclasses import replace
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs

import pytest
from streamlit.testing.v1 import AppTest

from e3app.research import analysis, local_worker, providers, ui
from e3app.research.common import ResearchError, iter_fasta
from e3app.research.guidance import SECTIONS
from e3app.research.jobs import (
    INTERPROSCAN_CONTACT_FILE, artifact_path, get_job, job_directory, list_jobs, submit_job,
)
from e3app.research.runner import run_next_job


@pytest.fixture
def guided_profile(*, research_config, tmp_path, monkeypatch):
    """Configure tiny real Parquet sources without executing external tools.

    Args:
        research_config: Small official-schema data fixture.
        tmp_path: Private test directory.
        monkeypatch: Scoped environment changes.

    Returns:
        Profile path and its research configuration.
    """
    config = replace(research_config, mafft=sys.executable, fasttree=sys.executable)
    profile = tmp_path / "guided.toml"
    profile.write_text(
        "\n".join(
            f"{key}={json.dumps(str(getattr(config, key)))}"
            for key in ("workspace", "index", "sequences", "sequence_map", "mafft", "fasttree")
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    return profile, config


@pytest.fixture
def guided_app(*, guided_profile):
    """Create the actual standalone Streamlit application in a private workspace.

    Args:
        guided_profile: Isolated research profile.

    Returns:
        Rendered app testing session.
    """
    return AppTest.from_file(
        str(Path(ui.__file__).with_name("standalone.py")), default_timeout=20
    ).run()


def find_control(*, controls, label):
    """Find a widget by its visible label rather than its page position.

    Args:
        controls: Streamlit test widget collection.
        label: Exact visible label.

    Returns:
        Matching widget.
    """
    return next(item for item in controls if item.label == label)


def read_request(*, workspace: Path, job_id: str) -> dict:
    """Read the submitted scientific controls from the private fixture workspace.

    Args:
        workspace: Test workspace.
        job_id: Submitted job ID.

    Returns:
        Immutable request record, distinct from the sanitised status summary.
    """
    path = job_directory(workspace=workspace, job_id=job_id) / "request.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_start_and_all_generic_pages_explain_the_workflow(*, guided_app, guided_profile):
    """New sessions give a starting point; every page renders with native help."""
    app = guided_app
    assert not app.exception
    assert app.radio(key="research_section").value == "Start here"
    assert any("standalone protein session" in item.value for item in app.info)
    assert not any(item.label.startswith("Start from E3") for item in app.button)
    for section in SECTIONS:
        app.radio(key="research_section").set_value(section).run()
        assert not app.exception and not app.error
        for controls in (
            app.radio,
            app.text_area,
            app.text_input,
            app.selectbox,
            app.number_input,
            app.checkbox,
        ):
            assert all(item.proto.help for item in controls)
    assert list_jobs(workspace=guided_profile[1].workspace) == []
    assert any(
        item.label == "Download the workbench user guide" for item in app.get("download_button")
    )


def test_start_buttons_select_input_routes_without_submitting(*, guided_app, guided_profile):
    """A route button selects an appropriate form, without creating a job."""
    app = guided_app
    find_control(controls=app.button, label="I have a protein FASTA").click().run()
    assert app.radio(key="research_section").value == "Family analysis"
    assert app.radio(key="analyse_route").value == "Upload FASTA"
    assert app.radio(key="research_analysis_task").value == "Alignment and tree"
    app.radio(key="research_section").set_value("Start here").run()
    find_control(controls=app.button, label="I know a global DeepClust centroid").click().run()
    assert app.radio(key="research_discovery_mode").value == "Known global centroids"
    assert not any(item.label == "Rank global clusters" for item in app.button)
    app.radio(key="research_section").set_value("Start here").run()
    find_control(controls=app.button, label="I have protein sequence IDs").click().run()
    assert app.radio(key="research_discovery_mode").value == "Sequence identifiers"
    assert list_jobs(workspace=guided_profile[1].workspace) == []


def test_e3_session_recommends_one_group_and_keeps_generic_routes(*, guided_profile):
    """The full app defaults to its optional E3 adapter without querying on entry."""
    script = (
        "import duckdb\nfrom e3app.research.ui import render_research_workbench\n"
        "connection = duckdb.connect()\n"
        "render_research_workbench(connection=connection)\n"
    )
    app = AppTest.from_string(script, default_timeout=20).run()
    find_control(controls=app.button, label="Start from E3 groups (recommended)").click().run()
    assert not app.exception and not app.error
    assert app.radio(key="research_discovery_mode").value == "E3 ranked groups"
    assert find_control(controls=app.number_input, label="Top ranked E3 groups/clusters").value == 1
    assert "Sequence identifiers" in app.radio(key="research_discovery_mode").options
    assert any("Prepare the selected E3 inputs" in item.value for item in app.info)
    assert find_control(controls=app.button, label="Queue exact global cluster mapping").disabled
    assert list_jobs(workspace=guided_profile[1].workspace) == []


def test_mapping_selection_hands_exact_ids_to_retrieval(*, guided_app, guided_profile):
    """A completed exact mapping can populate a retrieval request with no retyping."""
    _, config = guided_profile
    mapping = submit_job(
        workspace=config.workspace, operation="resolve", parameters={"identifiers": ["P1"]}
    )
    run_next_job(config=config, job_id=mapping)
    app = guided_app
    app.radio(key="research_section").set_value("Discover").run()
    app.radio(key="research_discovery_mode").set_value("Sequence identifiers").run()
    find_control(
        controls=app.button, label="Use selected mapped clusters for retrieval"
    ).click().run()
    assert app.text_area(key="research_retrieve_ids").value == "GLOBAL_A"
    assert len(list_jobs(workspace=config.workspace)) == 1
    find_control(controls=app.button, label="Queue complete cluster retrieval").click().run()
    assert not app.exception and app.success
    queued = list_jobs(workspace=config.workspace)[0]
    assert queued["operation"] == "retrieve" and queued["status"] == "QUEUED"
    assert read_request(workspace=config.workspace, job_id=queued["job_id"])["parameters"] == {
        "cluster_ids": ["GLOBAL_A"]
    }
    find_control(controls=app.button, label="Track this job").click().run()
    assert app.radio(key="research_section").value == "Jobs"
    assert app.selectbox(key="research_job").value == queued["job_id"]


def test_ranking_selection_and_unconfigured_taxonomy(*, guided_app, guided_profile):
    """Taxonomy is optional and a ranking selection does not retrieve automatically."""
    app = guided_app
    app.radio(key="research_section").set_value("Discover").run()
    assert find_control(
        controls=app.text_input, label="Required species/taxon IDs (optional, e.g. 9606 3702)"
    ).disabled
    find_control(controls=app.button, label="Rank global clusters").click().run()
    assert not app.exception and not app.error
    find_control(
        controls=app.button, label="Use selected ranked clusters for retrieval"
    ).click().run()
    assert app.text_area(key="research_retrieve_ids").value == "GLOBAL_A"
    assert list_jobs(workspace=guided_profile[1].workspace) == []


def test_completed_retrieval_handoff_preserves_exact_fasta_source(*, guided_app, guided_profile):
    """The next-step button selects the retrieved family without another job."""
    _, config = guided_profile
    job = submit_job(
        workspace=config.workspace, operation="retrieve", parameters={"cluster_ids": ["GLOBAL_A"]}
    )
    run_next_job(config=config, job_id=job)
    app = guided_app
    app.radio(key="research_section").set_value("Jobs").run()
    assert any(
        item.label == "Technical details · parameters, provenance and logs" for item in app.expander
    )
    find_control(controls=app.button, label="Analyse this family").click().run()
    assert not app.exception
    assert app.radio(key="research_section").value == "Family analysis"
    source = app.selectbox(key="analyse_source").value
    assert source[0] == job and source[1].endswith(".fasta")
    assert len(list_jobs(workspace=config.workspace)) == 1


def test_remote_prediction_requires_explicit_submission_selection(*, guided_app, guided_profile):
    """External sequence submission must be chosen before a model request is queued."""
    _, config = guided_profile
    job = submit_job(
        workspace=config.workspace, operation="retrieve", parameters={"cluster_ids": ["GLOBAL_A"]}
    )
    run_next_job(config=config, job_id=job)
    app = guided_app
    app.radio(key="research_section").set_value("Models").run()
    app.radio(key="fold_execution").set_value("Research worker").run()
    assert find_control(controls=app.button, label="Queue ESMFold prediction").disabled
    app.checkbox(key="fold_consent_atlas").check().run()
    assert not find_control(controls=app.button, label="Queue ESMFold prediction").disabled
    find_control(
        controls=app.text_area,
        label="Exact sequence IDs to fold (blank selects input; maximum 100)",
    ).set_value("B")
    find_control(controls=app.button, label="Queue ESMFold prediction").click().run()
    request = read_request(
        workspace=config.workspace, job_id=list_jobs(workspace=config.workspace)[0]["job_id"]
    )
    assert request["parameters"]["remote_allowed"] is True
    assert request["parameters"]["sequence_ids"] == ["B"]
    assert get_job(workspace=config.workspace, job_id=request["job_id"])["status"] == "QUEUED"


def test_annotation_only_shows_controls_for_the_selected_route(*, guided_app):
    """An InterProScan request does not expose irrelevant eggNOG scope settings."""
    app = guided_app
    app.radio(key="research_section").set_value("Annotations").run()
    assert not any(item.label.startswith("eggNOG") for item in app.text_input)
    assert any("InterProScan is unavailable" in item.value for item in app.warning)
    app.selectbox(key="annotation_engine").set_value("eggnog").run()
    assert not app.exception
    assert (
        find_control(controls=app.text_input, label="eggNOG taxonomic scope").value == "Eukaryota"
    )
    assert find_control(controls=app.text_input, label="eggNOG target taxon ID").value == "2759"
    assert not any("Submit selected" in item.label for item in app.checkbox)
    app.selectbox(key="annotation_engine").set_value("interpro_remote").run()
    assert any("contact email" in item.value for item in app.warning)
    assert app.checkbox(key="annotation_remote_consent")
    assert find_control(controls=app.button, label="Start annotation").disabled


def test_interproscan_contact_reaches_only_the_consented_request(
    *, guided_app, guided_profile, monkeypatch,
):
    """Validate the page field and pass it privately to the worker's EBI request."""
    _, config = guided_profile
    app = guided_app
    app.radio(key="research_section").set_value("Annotations").run()
    app.radio(key="annotate_route").set_value("Paste FASTA").run()
    app.text_area(key="annotate_pasted_fasta").set_value(">plant_protein\nACDE\n").run()
    app.selectbox(key="annotation_engine").set_value("interpro_remote").run()
    app.radio(key="annotation_execution").set_value("Research worker").run()
    app.checkbox(key="annotation_remote_consent").check().run()
    app.text_input(key="interproscan_contact_email").set_value("invalid").run()
    assert find_control(controls=app.button, label="Queue annotation").disabled
    assert any("valid InterProScan contact email" in item.value for item in app.warning)
    app.checkbox(key="annotation_remote_consent").uncheck().run()
    address = "researcher+e3@example.org"
    app.text_input(key="interproscan_contact_email").set_value(f" {address} ").run()
    assert find_control(controls=app.button, label="Queue annotation").disabled
    assert list_jobs(workspace=config.workspace) == []
    app.checkbox(key="annotation_remote_consent").check().run()
    find_control(controls=app.button, label="Queue annotation").click().run()
    assert not app.exception
    (job,) = list_jobs(workspace=config.workspace)
    directory = job_directory(workspace=config.workspace, job_id=job["job_id"])
    contact = directory / INTERPROSCAN_CONTACT_FILE
    assert contact.stat().st_mode & 0o777 == 0o600
    assert address not in (directory / "request.json").read_text(encoding="utf-8")
    assert address not in json.dumps(job)
    http = Mock(side_effect=[b"iprscan5-fixture", b"FINISHED", b""])
    monkeypatch.setattr(providers, "http_request", http)

    def run_saved_job(*, config, job_id, label):
        """Exercise the saved job and mocked provider when the app starts its worker."""
        assert label == "external analysis"
        run_next_job(config=replace(config, email="profile@example.org"), job_id=job_id)

    monkeypatch.setattr(local_worker, "_start_local_job", run_saved_job)
    app.radio(key="research_section").set_value("Jobs").run()
    app.button(key=f"start_external_job_{job['job_id']}").click().run()
    assert not app.exception
    assert get_job(workspace=config.workspace, job_id=job["job_id"])["status"] == "COMPLETE"
    post = http.call_args_list[0].kwargs
    assert post["method"] == "POST"
    assert parse_qs(post["body"].decode())["email"] == [address]
    assert not contact.exists()
    for path in directory.glob("*.json"):
        assert address not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("section", ("Models", "Annotations"))
def test_external_form_defaults_to_starting_the_app_host_worker(
    *, guided_app, guided_profile, monkeypatch, section,
):
    """The hosted route starts the exact worker only after explicit submission consent."""
    _, config = guided_profile
    app = guided_app
    launch = Mock()
    monkeypatch.setattr(local_worker, "_start_local_job", launch)
    app.radio(key="research_section").set_value(section).run()
    if section == "Models":
        input_key, consent_key = "fold", "fold_consent_atlas"
        label, operation, engine = "Start ESMFold prediction", "predict", "atlas"
    else:
        app.selectbox(key="annotation_engine").set_value("interpro_remote").run()
        app.text_input(key="interproscan_contact_email").set_value("researcher@example.org").run()
        input_key, consent_key = "annotate", "annotation_remote_consent"
        label, operation, engine = "Start annotation", "annotate", "interpro_remote"
    execution_key = "fold_execution" if section == "Models" else "annotation_execution"
    assert app.radio(key=execution_key).value == "App host"
    app.radio(key=f"{input_key}_route").set_value("Paste FASTA").run()
    app.text_area(key=f"{input_key}_pasted_fasta").set_value(">plant_protein\nAC\n").run()
    assert find_control(controls=app.button, label=label).disabled
    assert not launch.called
    app.checkbox(key=consent_key).check().run()
    find_control(controls=app.button, label=label).click().run()
    assert not app.exception
    (job,) = list_jobs(workspace=config.workspace)
    assert job["operation"] == operation
    assert launch.call_args.kwargs["job_id"] == job["job_id"]
    assert launch.call_count == 1
    request = read_request(workspace=config.workspace, job_id=job["job_id"])
    assert request["parameters"]["engine"] == engine
    assert request["parameters"]["execution_target"] == "app_host"
    assert request["parameters"]["remote_allowed"] is True
    app.run()
    assert launch.call_count == 1


def test_alignment_summary_is_readable_and_aligned_fasta_is_not_an_input(
    *, guided_app, guided_profile, monkeypatch
):
    """Metrics replace raw first-view JSON and gapped FASTA is not offered for analysis."""
    _, config = guided_profile

    def fake_command(*, arguments, output, config, stdout=None):
        """Return deterministic alignment evidence without invoking a tool.

        Args:
            arguments: Recorded tool arguments.
            output: Job directory.
            config: Research configuration.
            stdout: Requested output file.
        """
        if "--version" in arguments:
            stdout.write_text("fixture version\n", encoding="utf-8")
        elif "--auto" in arguments:
            stdout.write_text(Path(arguments[-1]).read_text(encoding="utf-8"), encoding="utf-8")
        else:
            names = [key for key, _ in iter_fasta(path=Path(arguments[-1]), aligned=True)]
            stdout.write_text(
                "(" + ",".join(f"{name}:0.1" for name in names) + ");\n", encoding="utf-8"
            )

    monkeypatch.setattr(analysis, "run_command", fake_command)
    alignment = submit_job(
        workspace=config.workspace,
        operation="align",
        parameters={},
        fasta=">a\nACD\n>b\nACE\n>c\nACF\n",
    )
    run_next_job(config=config, job_id=alignment)
    assert get_job(workspace=config.workspace, job_id=alignment)["status"] == "COMPLETE"
    app = guided_app
    app.radio(key="research_section").set_value("Jobs").run()
    find_control(controls=app.button, label="Open result in Alignments and trees").click().run()
    assert not app.exception and not app.error
    assert app.selectbox(key="research_alignment_job").value == alignment
    assert {item.label for item in app.metric} == {
        "Aligned proteins",
        "Aligned positions",
        "Mean gap fraction",
    }
    assert any(item.label == "Technical alignment summary (JSON)" for item in app.expander)
    assert all(item.proto.help for item in app.metric)
    app.radio(key="completed_alignment_view").set_value("Statistics").run()
    assert not app.exception
    positions, members = app.dataframe
    position_config = json.loads(positions.proto.columns)
    member_config = json.loads(members.proto.columns)
    assert all(position_config[column]["help"] for column in positions.value.columns)
    assert all(member_config[column]["help"] for column in members.value.columns)
    assert "single residue" in position_config["consensus_fraction_of_known"]["help"]
    assert "number of comparable positions" in (
        member_config["blosum62_sum_over_comparable_positions"]["help"]
    )
    assert len(app.get("plotly_chart")) == 1
    manifest_path = job_directory(workspace=config.workspace, job_id=alignment) / "manifest.json"
    legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del legacy_manifest["artifacts"]["auspice.json"]
    manifest_path.write_text(json.dumps(legacy_manifest), encoding="utf-8")
    app.radio(key="completed_alignment_view").set_value("Auspice tree").run()
    assert not app.exception and len(app.get("plotly_chart")) == 1
    assert "Download Auspice dataset" in {button.label for button in app.get("download_button")}
    app.radio(key="research_section").set_value("Family analysis").run()
    source = app.selectbox(key="analyse_source")
    assert all("alignment.fasta" not in label for label in source.options)


def test_completed_alignment_can_infer_missing_tree_on_app_host(
    *, guided_app, guided_profile, tmp_path, monkeypatch,
):
    """Launch the exact tree-only worker, then show its tree in Auspice and JBrowse."""
    profile, config = guided_profile
    fasttree = tmp_path / "FastTree"
    fasttree.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        '[[ "$1" == "-wag" && "$2" == "-gamma" && -f "$3" ]]\n'
        "printf '%s\\n' '((plant_A:0.1,plant_B:0.2)0.8:0.05,plant_C:0.3);'\n",
        encoding="utf-8",
    )
    fasttree.chmod(0o700)
    config = replace(config, fasttree=str(fasttree))
    profile.write_text(
        profile.read_text(encoding="utf-8").replace(
            f"fasttree={json.dumps(sys.executable)}", f"fasttree={json.dumps(str(fasttree))}"
        ),
        encoding="utf-8",
    )

    def mafft(*, arguments, output, config, stdout):
        """Write a fixed gapped alignment and reject any tree command in the parent job."""
        if "--version" in arguments:
            stdout.write_text("MAFFT test\n", encoding="utf-8")
        else:
            assert "--auto" in arguments
            stdout.write_text(">plant_A\nACDE\n>plant_B\nAC-E\n>plant_C\nACFE\n", encoding="utf-8")

    monkeypatch.setattr(analysis, "run_command", mafft)
    alignment = submit_job(
        workspace=config.workspace, operation="align", parameters={"infer_tree": False},
        fasta=">plant_A\nACDE\n>plant_B\nACE\n>plant_C\nACFE\n",
    )
    run_next_job(config=config, job_id=alignment)
    source = artifact_path(workspace=config.workspace, job_id=alignment, artifact="alignment.fasta")
    saved_alignment = source.read_bytes()
    app = guided_app
    app.radio(key="research_section").set_value("Alignments and trees").run()
    app.radio(key="completed_alignment_view").set_value("Auspice tree").run()
    assert any("no saved protein tree" in item.value for item in app.info)
    app.button(key=f"infer_tree_{alignment}").click().run()
    (job,) = list_jobs(workspace=config.workspace, operation="tree", source_job=alignment)
    tree_id = job["job_id"]
    deadline = time.monotonic() + 20
    while job["status"] in {"QUEUED", "RUNNING"} and time.monotonic() < deadline:
        time.sleep(0.1)
        job = get_job(workspace=config.workspace, job_id=tree_id)
    assert job["status"] == "COMPLETE", job
    assert source.read_bytes() == saved_alignment
    assert len(list_jobs(workspace=config.workspace, operation="align")) == 1
    app.run()
    assert not app.exception and not app.error
    assert not app.get("iframe") and len(app.get("plotly_chart")) == 1
    assert {"Download Newick tree", "Download Auspice dataset"} <= {
        button.label for button in app.get("download_button")
    }
    app.radio(key="completed_alignment_view").set_value("JBrowse MSA").run()
    assert "plant_A:0.1,plant_B:0.2" in app.get("iframe")[0].proto.srcdoc


def test_subclustering_routes_and_saved_job_launch(*, guided_app, guided_profile, monkeypatch):
    """Dispatch the selected host route and keep old queued job IDs intact."""
    profile, config = guided_profile
    with profile.open(mode="a", encoding="utf-8") as handle:
        handle.write(
            f"diamond={json.dumps(sys.executable)}\n"
            'remote_host="denbi-fixture"\nremote_config="/vm/research.toml"\n'
        )
    launch = Mock()
    monkeypatch.setattr(local_worker, "_start_local_job", launch)
    app = guided_app
    app.radio(key="research_section").set_value("Family analysis").run()
    app.radio(key="analyse_route").set_value("Paste FASTA").run()
    app.text_area(key="analyse_pasted_fasta").set_value(">a\nACDE\n>b\nACDF\n").run()
    assert app.radio(key="subcluster_execution").value == "App host"
    find_control(controls=app.button, label="Run subclustering here").click().run()
    local_id = launch.call_args.kwargs["job_id"]
    local = read_request(workspace=config.workspace, job_id=local_id)
    assert local["parameters"]["subcluster_transport"] == "local"
    assert local["parameters"]["execution_target"] == "app_host"
    app.radio(key="subcluster_execution").set_value("External VM (SSH)").run()
    find_control(controls=app.button, label="Run subclustering on external VM").click().run()
    vm_id = launch.call_args.kwargs["job_id"]
    vm = read_request(workspace=config.workspace, job_id=vm_id)
    assert vm["parameters"]["subcluster_transport"] == "ssh"
    assert vm["parameters"]["execution_target"] == "app_host"
    app.radio(key="subcluster_execution").set_value("Research worker").run()
    find_control(controls=app.button, label="Queue stricter subclustering").click().run()
    assert launch.call_count == 2
    jobs = list_jobs(workspace=config.workspace)
    assert len(jobs) == 3
    saved_id = jobs[0]["job_id"]
    request = read_request(workspace=config.workspace, job_id=saved_id)
    app.radio(key="research_section").set_value("Jobs").run()
    app.button(key=f"start_subcluster_{saved_id}").click().run()
    assert launch.call_count == 3 and launch.call_args.kwargs["job_id"] == saved_id
    assert read_request(workspace=config.workspace, job_id=saved_id) == request
    assert list_jobs(workspace=config.workspace) == jobs
    assert not app.exception and not app.error


def test_subcluster_handoff_uses_audited_source_and_exact_selection(
    *, guided_app, guided_profile, monkeypatch
):
    """Selecting a result carries the owning FASTA and subcluster into a new alignment."""
    from e3app.research import runner

    _, config = guided_profile

    def fake_subcluster(*, config, source, output, parameters):
        """Publish a deterministic audited family without invoking DIAMOND.

        Args:
            config: Workspace profile.
            source: Complete input FASTA.
            output: Owned result directory.
            parameters: Selected clustering thresholds.

        Returns:
            Fixture sequence, summary and audited membership artifacts.
        """
        (output / "sequences.fasta").write_text(source.read_text(), encoding="utf-8")
        (output / "subclusters.tsv").write_text(
            "subcluster_id\trepresentative_id\tmember_count\nsub_A\ta\t2\nsub_B\tc\t1\n",
            encoding="utf-8",
        )
        (output / "membership.tsv").write_text(
            "subcluster_id\tsequence_id\taudited_representative_id\talignment_status\tpident\t"
            "representative_coverage\tmember_coverage\tevalue\tbitscore\n"
            "sub_A\ta\ta\tCENTROID_SELF\t\t\t\t\t\n"
            "sub_A\tb\ta\tEXACT_THRESHOLDS_PASS\t85\t100\t100\t1e-12\t100\n"
            "sub_B\tc\tc\tCENTROID_SELF\t\t\t\t\t\n",
            encoding="utf-8",
        )
        return {
            name: output / name for name in ("sequences.fasta", "subclusters.tsv", "membership.tsv")
        }

    monkeypatch.setattr(runner, "subcluster", fake_subcluster)
    job = submit_job(
        workspace=config.workspace,
        operation="subcluster",
        parameters={},
        fasta=">a\nACD\n>b\nACE\n>c\nACF\n",
    )
    run_next_job(config=config, job_id=job)
    app = guided_app
    app.radio(key="research_section").set_value("Family analysis").run()
    assert app.selectbox(key=f"subcluster_network_group_{job}").value == ""
    app.radio(key="research_section").set_value("Jobs").run()
    assert "Download displayed network (GraphML)" in {
        button.label for button in app.get("download_button")
    }
    app.selectbox(key=f"subcluster_network_group_{job}").set_value("sub_A").run()
    find_control(controls=app.button, label="Set up alignment for this subcluster").click().run()
    assert app.selectbox(key=f"align_subcluster_{job}").value == "sub_A"
    find_control(controls=app.button, label="Queue alignment and tree").click().run()
    assert not app.exception and not app.error
    queued = read_request(
        workspace=config.workspace, job_id=list_jobs(workspace=config.workspace)[0]["job_id"]
    )
    assert queued["operation"] == "align"
    assert queued["parameters"]["subcluster_id"] == "sub_A"
    assert queued["parameters"]["source_job"] == job
    assert queued["parameters"]["source_artifact"] == "sequences.fasta"


def test_uploaded_fasta_can_queue_an_alignment_without_deepclust(
    *, guided_app, guided_profile, monkeypatch
):
    """The generic FASTA entry point does not depend on global database membership."""
    from unittest.mock import Mock

    uploaded = SimpleNamespace(size=18, getvalue=Mock(return_value=b">a\nACD\n>b\nACE\n"))
    monkeypatch.setattr(ui.st, "file_uploader", Mock(return_value=uploaded))
    app = guided_app
    find_control(controls=app.button, label="I have a protein FASTA").click().run()
    find_control(controls=app.button, label="Queue alignment and tree").click().run()
    assert not app.exception and app.success
    config = guided_profile[1]
    queued = read_request(
        workspace=config.workspace, job_id=list_jobs(workspace=config.workspace)[0]["job_id"]
    )
    assert queued["operation"] == "align" and queued["parameters"]["subcluster_id"] == ""
    assert "source_job" not in queued["parameters"]


@pytest.mark.parametrize(
    "changes",
    [
        {"section": "unknown"},
        {"section": "Jobs", "source_job": "one"},
        {"section": "Discover", "discovery_mode": "unknown"},
        {"section": "Family analysis", "analysis_task": "unknown"},
        {"section": "Family analysis", "input_route": "unknown"},
    ],
)
def test_navigation_rejects_invalid_destinations_without_mutation(*, monkeypatch, changes):
    """A malformed callback cannot partially change the current page selection."""
    state = {}
    monkeypatch.setattr(ui.st, "session_state", state)
    with pytest.raises(ResearchError):
        ui.navigate_research(**changes)
    assert state == {}
