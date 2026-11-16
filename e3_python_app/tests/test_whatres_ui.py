"""Exercise WhatRes through the app's model selection, execution and download routes."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from e3app.research import expansion_ui
from e3app.research.common import atomic_json, file_sha256
from e3app.research.jobs import claim_job, finish_job, job_directory, submit_job
from e3app.research.providers import pdb_evidence
from test_external_hog import make_model_bundle
from test_pocket_review import make_pocket_review
from test_streamlit_app import _navigate
from test_whatres import PDB, local_whatres, make_mmcif

APP_SCRIPT = Path(__file__).resolve().parents[1] / "src/e3app/streamlit_app.py"
CANDIDATES = "🟢 2 · Candidate discovery"
STRUCTURE = "🟡 5 · Structural comparison"
PANEL = "Model geometry (WhatRes)"
CONTROL = "Calculate WhatRes scores"
EXPORT = "Download WhatRes scores (TSV)"


def uploaded_file(*, content: bytes, name: str) -> SimpleNamespace:
    """Supply an upload-like object to the Streamlit test runner."""
    return SimpleNamespace(name=name, size=len(content), getvalue=lambda: content)


@pytest.fixture
def configured_app(
    *, resource_db: Path, local_whatres: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> dict[str, Path]:
    """Set up the installed E3 app and isolate its test models, release and workspace."""
    workspace = tmp_path / "research"
    profile = tmp_path / "research.toml"
    profile.write_text(f"workspace={json.dumps(str(workspace))}\n", encoding="utf-8")
    monkeypatch.setenv("E3_WHATRES_DIR", str(local_whatres))
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_RESEARCH_CONFIG", str(profile))
    monkeypatch.delenv("E3_POCKET_REVIEW_DIR", raising=False)
    monkeypatch.delenv("E3_HUMAN_PLANT_REVIEW_DIR", raising=False)
    return {"workspace": workspace, "whatres": local_whatres}


def geometry_panel(*, app: AppTest):
    """Find the optional WhatRes panel on the current page."""
    assert not app.exception and not app.error
    return next(panel for panel in app.expander if panel.label == PANEL)


def calculate(*, app: AppTest) -> None:
    """Click the actual Streamlit button and wait for the local scoring call."""
    button = next(item for item in geometry_panel(app=app).button if item.label == CONTROL)
    button.click().run()


def assert_result(*, app: AppTest, label: str) -> None:
    """Check the rendered model-level values and the independent TSV action."""
    panel = geometry_panel(app=app)
    assert panel.dataframe[0].value.iloc[-1].to_dict() == {
        "Model": label, "Realism (0–100)": 42.5, "Apparent resolution (Å)": 2.35,
        "WhatRes note": "",
    }
    assert panel.get("download_button")[0].label == EXPORT


def test_render_whatres_shows_optional_setup_errors_and_unavailable_originals(
    *, local_whatres: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maintain a working viewer when WhatRes or the exact native model is unavailable."""
    monkeypatch.delenv("E3_WHATRES_DIR", raising=False)
    script = (
        "from e3app.whatres_ui import render_whatres\n"
        "render_whatres(models=(), key='test', recorded=True)\n"
    )
    app = AppTest.from_string(script).run()
    assert "Set E3_WHATRES_DIR" in geometry_panel(app=app).caption[0].value
    monkeypatch.setenv("E3_WHATRES_DIR", str(tmp_path / "absent"))
    app.run()
    assert "WhatRes checkout" in geometry_panel(app=app).warning[0].value
    monkeypatch.setenv("E3_WHATRES_DIR", str(local_whatres))
    app.run()
    assert "no unambiguous original-model checksum" in geometry_panel(app=app).caption[0].value


def test_group_then_pair_ui_checks_original_files_and_reuses_the_exact_score(
    *, configured_app: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Score an exact native group file, then compare the reference and mobile models."""
    root = make_pocket_review(parent=tmp_path)
    path = root / "tables/protein_model_inventory.tsv"
    inventory = pd.read_csv(path, sep="\t")
    alternate = PDB.replace(b"   6.000", b"   6.100")
    inventory["model_sha256"] = sha256(PDB).hexdigest()
    mobile = inventory.assign(
        candidate_accession="P2", species_column="Zea_mays", is_reference=False,
        model_sha256=sha256(alternate).hexdigest(),
    )
    pd.concat([inventory, mobile]).to_csv(path, sep="\t", index=False)
    monkeypatch.setenv("E3_POCKET_REVIEW_DIR", str(root))
    uploads = {}
    original = st.file_uploader

    def upload(*args, **kwargs):
        """Return a controlled browser upload for WhatRes and use normal widgets elsewhere."""
        if kwargs.get("label") == "Original full-atom structure":
            return uploads.get("structure")
        return original(*args, **kwargs)

    monkeypatch.setattr(st, "file_uploader", upload)
    downloads = Mock(wraps=st.download_button)
    monkeypatch.setattr(st, "download_button", downloads)
    app = AppTest.from_file(str(APP_SCRIPT), default_timeout=30).run()
    _navigate(app, stage=STRUCTURE, page="3D structures & pockets")
    assert geometry_panel(app=app).button[0].disabled
    uploads["structure"] = SimpleNamespace(size=20_000_001)
    app.run()
    assert "exceeds 20 MB" in geometry_panel(app=app).warning[0].value
    assert geometry_panel(app=app).button[0].disabled
    uploads["structure"] = uploaded_file(content=alternate, name="wrong.pdb")
    app.run()
    calculate(app=app)
    assert "differs from the original review model" in geometry_panel(app=app).warning[0].value
    assert not geometry_panel(app=app).dataframe
    uploads["structure"] = uploaded_file(content=PDB, name="native.pdb")
    app.run()
    calculate(app=app)
    assert_result(app=app, label="P1 · Arabidopsis thaliana")

    _navigate(app, stage=STRUCTURE, page="3D alignment")
    assert_result(app=app, label="Reference · P1 · Arabidopsis thaliana")
    panel = geometry_panel(app=app)
    assert panel.selectbox[0].options == [
        "Reference · P1 · Arabidopsis thaliana", "Mobile · P2 · Zea mays",
    ]
    assert not panel.button
    uploads["structure"] = uploaded_file(content=alternate, name="native_mobile.pdb")
    panel.selectbox[0].set_value(1).run()
    calculate(app=app)
    assert_result(app=app, label="Mobile · P2 · Zea mays")
    assert len(geometry_panel(app=app).dataframe[0].value) == 2
    last = next(call for call in reversed(downloads.call_args_list)
                if call.kwargs.get("label") == EXPORT)
    table = pd.read_csv(StringIO(last.kwargs["data"]), sep="\t")
    assert table["model_sha256"].tolist() == [
        sha256(PDB).hexdigest(), sha256(alternate).hexdigest(),
    ]
    assert table["scored_pdb_sha256"].tolist() == table["model_sha256"].tolist()
    assert table["whatres_version"].tolist() == ["1.0.0", "1.0.0"]


@pytest.mark.parametrize("recorded", [True, False])
def test_linked_features_score_the_specific_review_or_current_alphafold_model(
    *, recorded: bool, configured_app: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the linked Nightingale view attached to the exact model in both source routes."""
    model = make_mmcif()
    if recorded:
        residues = pdb_evidence(pdb=PDB.decode(), expected_sequence="AG")
        evidence = expansion_ui.monomer_view_payload(residues=pd.DataFrame(residues))
        evidence.update(
            model_source="Test review", model_sha256=sha256(PDB).hexdigest(), pockets=[],
        )
        monkeypatch.setattr(st, "file_uploader", Mock(
            return_value=uploaded_file(content=PDB, name="native.pdb"),
        ))
    else:
        evidence = None
    monkeypatch.setattr(expansion_ui, "released_member_sequence", Mock(return_value="AG"))
    monkeypatch.setattr(expansion_ui, "linked_review_evidence", Mock(return_value=evidence))
    fetch = Mock(return_value=(model, "https://alphafold.ebi.ac.uk/files/test.cif"))
    monkeypatch.setattr(expansion_ui, "render_alphafold_retrieval", fetch)
    workspace = str(configured_app["workspace"])
    app = AppTest.from_string(
        "from pathlib import Path\n"
        "import pandas as pd\n"
        "from e3app.config import AppConfig\n"
        "from e3app.research.common import ResearchConfig\n"
        "from e3app.research.expansion_ui import render_linked_features\n"
        "render_linked_features(\n"
        f"    config=ResearchConfig(workspace=Path({workspace!r})), app_config=AppConfig(),\n"
        "    connection=None, choice=('P1', 'HOG1', 'Plant_species', 'P1'),\n"
        "    domains=pd.DataFrame(),\n"
        ")\n",
    ).run()
    assert app.get("iframe") and fetch.called is not recorded
    calculate(app=app)
    assert_result(app=app, label="P1 · Plant species")
    score = next(iter(app.session_state["whatres_session_scores"].values()))
    assert score.input_format == ("PDB" if recorded else "mmCIF")
    assert score.model_sha256 == sha256(PDB if recorded else model).hexdigest()


def test_uploaded_pdb_scores_without_fasta_and_does_not_reuse_changed_coordinates(
    *, configured_app: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the normal ESMFold model upload route and a changed coordinate file."""
    monkeypatch.setattr("e3app.whatres_ui.MAX_SESSION_SCORES", 1)
    uploads = {"viewer_model_pdb": uploaded_file(content=PDB, name="uploaded.pdb")}
    monkeypatch.setattr(st, "file_uploader", Mock(side_effect=lambda **kwargs: uploads.get(
        kwargs.get("key"),
    )))
    app = AppTest.from_file(str(APP_SCRIPT), default_timeout=30).run()
    _navigate(app, stage=CANDIDATES, page="ESMFold & models")
    calculate(app=app)
    assert_result(app=app, label="uploaded.pdb")
    uploads["viewer_model_fasta"] = uploaded_file(content=b">ag\nAG\n", name="model.fasta")
    app.run()
    assert app.get("iframe")
    assert_result(app=app, label="ag")
    uploads["viewer_model_pdb"] = uploaded_file(content=PDB + b"\n", name="uploaded.pdb")
    app.run()
    assert not geometry_panel(app=app).dataframe
    calculate(app=app)
    assert_result(app=app, label="ag")
    cache = app.session_state["whatres_session_scores"]
    assert [score.model_sha256 for score in cache.values()] == [sha256(PDB + b"\n").hexdigest()]


def test_completed_esmfold_model_scores_the_saved_manifest_artifact(
    *, configured_app: dict[str, Path],
) -> None:
    """Reach model geometry from a checksummed, completed ESMFold job."""
    workspace = configured_app["workspace"]
    job = submit_job(workspace=workspace, operation="predict", parameters={})
    claim_job(workspace=workspace, job_id=job)
    directory = job_directory(workspace=workspace, job_id=job)
    (directory / "model.pdb").write_bytes(PDB)
    pd.DataFrame(pdb_evidence(pdb=PDB.decode(), expected_sequence="AG")).to_csv(
        directory / "residues.tsv", sep="\t", index=False,
    )
    pd.DataFrame([{
        "sequence_id": "saved_prediction", "status": "PREDICTED", "pdb_artifact": "model.pdb",
        "residue_artifact": "residues.tsv", "sequence_sha256": sha256(b"AG").hexdigest(),
    }]).to_csv(directory / "predictions.tsv", sep="\t", index=False)
    atomic_json(path=directory / "manifest.json", value={
        "job_id": job, "operation": "predict", "artifacts": {
            name: {"path": name, "sha256": file_sha256(path=directory / name)}
            for name in ("predictions.tsv", "model.pdb", "residues.tsv")
        },
    })
    finish_job(workspace=workspace, job_id=job)
    app = AppTest.from_file(str(APP_SCRIPT), default_timeout=30).run()
    _navigate(app, stage=CANDIDATES, page="ESMFold & models")
    app.radio(key="esmfold_view_route").set_value("Predict with ESMFold").run()
    calculate(app=app)
    assert_result(app=app, label="saved_prediction")
    score = next(iter(app.session_state["whatres_session_scores"].values()))
    assert score.model_sha256 == sha256(PDB).hexdigest()


def test_prepared_hog_model_scores_the_downloadable_alpha_fold_coordinates(
    *, configured_app: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reuse the exact mmCIF from the prepared model picker for geometry scoring."""
    model = make_mmcif()
    bundle = make_model_bundle(accessions=("Q9SA03",), hog_id="N0.HOG0001")
    output = BytesIO()
    with ZipFile(output, mode="w") as archive:
        archive.writestr("e3_N0.HOG0001_model_0.cif", model)
    record = replace(
        bundle.records[0], model_bytes=len(model), model_sha256=sha256(model).hexdigest(),
    )
    prepare = Mock(return_value=replace(bundle, payload=output.getvalue(), records=(record,)))
    monkeypatch.setattr("e3app.alphafold_hog_bundle.build_alphafold_hog_bundle", prepare)
    app = AppTest.from_file(str(APP_SCRIPT), default_timeout=30).run()
    _navigate(app, stage=STRUCTURE, page="HOG model comparison")
    prepare_button = next(item for item in app.button
                          if item.label == "Prepare Inspector ZIP for selected members")
    prepare_button.click().run()
    assert prepare.call_args.kwargs["hog_id"] == "N0.HOG0001"
    member = next(item for item in app.selectbox if item.label == "Prepared AlphaFold model")
    assert member.value == "Q9SA03"
    calculate(app=app)
    assert_result(app=app, label="Q9SA03 · AlphaFold Database")
    score = next(iter(app.session_state["whatres_session_scores"].values()))
    assert score.model_sha256 == sha256(model).hexdigest()
