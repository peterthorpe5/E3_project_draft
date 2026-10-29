"""External links, context navigation and stale-download behaviour in Streamlit."""

import hashlib
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from pocket_workbench import external_ui, ui
from pocket_workbench.core import WorkbenchError, load_project


@pytest.fixture
def external_app(project, monkeypatch, tmp_path):
    """Open the real external-tools route with an isolated native resource."""
    monkeypatch.setenv("POCKET_WORKBENCH_RESOURCE", str(project))
    monkeypatch.setenv("POCKET_WORKBENCH_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.delenv("POCKET_WORKBENCH_ALLOW_JOBS", raising=False)
    app = AppTest.from_file(str(Path(ui.__file__)), default_timeout=20).run()
    app.sidebar.radio[0].set_value("External links").run()
    assert not app.exception and not app.error
    return app


def test_external_route_prepares_exact_local_files_and_clears_changed_model_set(
    external_app,
):
    """A changed ZIP selection cannot expose a previous request's prepared download."""
    app = external_app
    assert "Download selected pair FASTA" in {
        b.proto.label for b in app.get("download_button")
    }
    next(
        b for b in app.button if b.label == "Prepare models for external tools"
    ).click().run()
    assert not app.exception and not app.error
    prepared = app.session_state["external_prepared"]
    with zipfile.ZipFile(io.BytesIO(prepared["payload"])) as archive:
        assert (
            json.loads(archive.read("handoff.json"))["coordinate_frame"]
            == "original_prepared_models"
        )
    assert "Download prepared external-tool ZIP" in {
        b.proto.label for b in app.get("download_button")
    }
    app.multiselect(key="external_model_set").set_value(["synthetic_variant"]).run()
    assert "external_prepared" not in app.session_state
    assert "Download prepared external-tool ZIP" not in {
        b.proto.label for b in app.get("download_button")
    }
    assert not app.exception and not app.error


def test_exploratory_pair_does_not_silently_change_independent_zip_selection(
    external_app,
):
    """Sequence-pair changes leave the independent model-ZIP selection unchanged."""
    app = external_app
    original = list(app.session_state["external_model_set"])
    app.selectbox(key="external_second").set_value("model:synthetic_variant").run()
    assert app.session_state["external_second"] == "model:synthetic_variant"
    assert app.session_state["external_model_set"] == original
    next(b for b in app.button if b.label == "Use current model pair").click().run()
    assert app.session_state["external_model_set"] == [
        "synthetic_reference",
        "synthetic_variant",
    ]
    assert not app.exception and not app.error


def test_external_preparation_failure_removes_previous_success(
    external_app, monkeypatch
):
    """A failed repeat cannot leave the previous success presented as a fresh result."""
    app = external_app
    next(
        b for b in app.button if b.label == "Prepare models for external tools"
    ).click().run()
    assert "external_prepared" in app.session_state
    monkeypatch.setattr(
        external_ui,
        "prepare_external_bundle",
        Mock(side_effect=WorkbenchError("Synthetic preparation failure")),
    )
    next(
        b for b in app.button if b.label == "Prepare models for external tools"
    ).click().run()
    assert not app.exception
    assert any("Synthetic preparation failure" in e.value for e in app.error)
    assert "external_prepared" not in app.session_state


def test_explicit_uniprot_metadata_populates_the_selected_role_links(
    project, external_app
):
    """Public buttons use the accession binding without rewriting the model ID."""
    path = project / "project.json"
    data = json.loads(path.read_text())
    for model in data["models"]:
        model["source_accession"] = {
            "synthetic_reference": "P38398",
            "synthetic_mobile": "P51587",
        }.get(model["sample_id"], "")
    path.write_text(json.dumps(data))
    app = external_app.run()
    links = {b.proto.label: b.proto.url for b in app.get("link_button")}
    assert (
        links["Open first in Mol* (database model)"]
        == "https://molstar.org/viewer/?afdb=P38398"
    )
    assert (
        links["Open second in AlphaFold Database"]
        == "https://alphafold.ebi.ac.uk/entry/P51587"
    )
    assert "seqA=P38398&seqB=P51587" in links["Open selected pair in EMERALD"]
    assert app.session_state["external_first"] == "model:synthetic_reference"
    assert not app.exception and not app.error


@pytest.mark.parametrize(
    "origin",
    [
        "Models & pockets",
        "Compare structures",
        "HOG / model groups",
        "Alignment & trees",
    ],
)
def test_context_links_preserve_current_selection_and_never_write_native_evidence(
    project, external_app, origin
):
    """Context hand-offs retain their model/pair/group and optional saved transform."""
    before = {
        p.relative_to(project): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in project.rglob("*")
        if p.is_file()
    }
    app = external_app
    app.sidebar.radio[0].set_value(origin).run()
    keys = {
        "Models & pockets": "model_external_tools",
        "Compare structures": "comparison_external_tools",
        "HOG / model groups": "group_external_tools",
        "Alignment & trees": "sequence_external_tools",
    }
    app.button(key=keys[origin]).click().run()
    assert app.sidebar.radio[0].value == "External links"
    if origin == "Models & pockets":
        assert app.session_state["external_first"] == "model:synthetic_reference"
        assert app.session_state["external_second"] is None
    if origin == "Compare structures":
        assert app.session_state["external_first"] == "model:synthetic_reference"
        assert app.session_state["external_second"] == "model:synthetic_mobile"
        assert (
            app.session_state["external_fit"]
            == load_project(root=project)["comparisons"][0]["comparison_id"]
        )
        next(
            b for b in app.button if b.label == "Prepare models for external tools"
        ).click().run()
        with zipfile.ZipFile(
            io.BytesIO(app.session_state["external_prepared"]["payload"])
        ) as archive:
            assert (
                json.loads(archive.read("handoff.json"))["coordinate_frame"]
                == "saved_alignment"
            )
    if origin == "HOG / model groups":
        assert app.session_state["external_group"] == "synthetic"
    assert not app.exception and not app.error
    assert before == {
        p.relative_to(project): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in project.rglob("*")
        if p.is_file()
    }
