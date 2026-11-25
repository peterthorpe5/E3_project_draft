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
from e3app.whatres import WhatResTarget
from e3app.whatres_residue_ui import RESIDUE_ACTION
from e3app.whatres_ui import FULL_MODEL_BUTTON, _score_identity
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
BATCH_PANEL = "HOG geometry (WhatRes)"
BATCH_CONTROL = "Calculate WhatRes scores for prepared HOG models"
BATCH_EXPORT = "Download HOG WhatRes scores (TSV)"


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


def linked_payload(*, app: AppTest) -> dict:
    """Read the evidence actually delivered to the linked Nightingale iframe."""
    iframe = app.get("iframe")[0].proto.srcdoc
    body = iframe.split('<script id="protein-data" type="application/json">', 1)[1]
    return json.loads(body.split("</script>", 1)[0])


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
    assert any(button.label == EXPORT for button in panel.get("download_button"))


def model_bundle(*, content: bytes, accession: str, hog_id: str):
    """Package one valid mmCIF under the normal retrieval audit and ZIP contract."""
    bundle = make_model_bundle(accessions=(accession,), hog_id=hog_id)
    output = BytesIO()
    with ZipFile(output, mode="w") as archive:
        archive.writestr(f"e3_{hog_id}_model_0.cif", content)
    record = replace(
        bundle.records[0], model_bytes=len(content), model_sha256=sha256(content).hexdigest(),
    )
    return replace(bundle, payload=output.getvalue(), records=(record,))


def test_score_identity_distinguishes_a_coordinate_file_from_a_review_trace(
    *, tmp_path: Path,
) -> None:
    """Only original hashes or available coordinate bytes identify a reusable score."""
    assert _score_identity(
        target=WhatResTarget(label="model", content=PDB, filename="9hki.pdb"),
        directory=tmp_path,
    ) == (tmp_path, sha256(PDB).hexdigest(), "9hki")
    assert _score_identity(
        target=WhatResTarget(label="review", model_sha256="a" * 64), directory=tmp_path,
    ) == (tmp_path, "a" * 64, "e3_model")
    assert _score_identity(
        target=WhatResTarget(label="public", alphafold_accession="Q6NKN8"), directory=tmp_path,
    ) == (tmp_path, "", "e3_model")


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
    panel = geometry_panel(app=app)
    assert panel.proto.expanded
    assert panel.get("popover")
    assert any("WhatRes setup needed" in item.value for item in panel.markdown)
    assert any("e3_python_app/README.md#optional-local-setup" in item.value
               for item in panel.markdown)
    assert any("doi.org/10.64898/2026.11.06.764824" in item.value for item in panel.markdown)
    assert any("side-chain atoms" in item.value and "Cα positions" in item.value
               for item in panel.markdown)
    assert panel.button[0].disabled
    monkeypatch.setenv("E3_WHATRES_DIR", str(tmp_path / "absent"))
    app.run()
    assert "WhatRes checkout" in geometry_panel(app=app).warning[0].value
    monkeypatch.setenv("E3_WHATRES_DIR", str(local_whatres))
    app.run()
    assert any("no saved checksum" in item.value for item in geometry_panel(app=app).caption)


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
    site = {"chain": "A", "resi": 1, "resn": "ALA", "x": 2, "y": 2, "z": 3,
            "pockets": [{"pocket_number": 4, "selection_rank": 1}]}
    member = {"accession": "P1", "species": "Arabidopsis_thaliana"}
    group = {"group_key": {"primary_group_id": "N0.HOG1"},
             "proteins": [{**member, "atoms": [site]}],
             "alignment": {"records": [{**member, "sequence": "AG", "pocket_annotations": [{
                 "fasta_position": 1, "fasta_residue": "A", "structure_label_chain": "A",
                 "structure_label_seq_id": 1, "pocket_number": 4, "selection_rank": 1,
             }]}]}}
    page = next((root / "groups").glob("*.html"))
    data = '<script id="reviewData" type="application/json">' + json.dumps(group) + "</script>"
    page.write_text(page.read_text().replace("</html>", data + "</html>"), encoding="utf-8")
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
    assert "differs from the original review model" in geometry_panel(app=app).warning[0].value
    assert geometry_panel(app=app).button[0].disabled
    assert not geometry_panel(app=app).dataframe
    uploads["structure"] = uploaded_file(content=PDB, name="native.pdb")
    app.run()
    calculate(app=app)
    assert_result(app=app, label="P1 · Arabidopsis thaliana")
    next(item for item in geometry_panel(app=app).button if item.label == RESIDUE_ACTION
         ).click().run()
    assert linked_payload(app=app)["pockets"][0]["geometry"]["median_residue_score"] == 30.25

    _navigate(app, stage=STRUCTURE, page="3D alignment")
    assert_result(app=app, label="Reference · P1 · Arabidopsis thaliana")
    assert linked_payload(app=app)["pockets"][0]["geometry"]["flagged_positions"] == "1"
    panel = geometry_panel(app=app)
    assert panel.selectbox[0].options == [
        "Reference · P1 · Arabidopsis thaliana", "Mobile · P2 · Zea mays",
    ]
    assert CONTROL not in [button.label for button in panel.button]
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


@pytest.mark.parametrize(
    "source", ["matching", "different", "no checksum", "sequence mismatch", "trace mismatch"],
)
def test_linked_trace_offers_full_model_retrieval_and_labels_its_scores(
    *, source: str, configured_app: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrieve a full model from a portable trace and verify both types of scores."""
    atoms = PDB.replace(b" GLY ", b" VAL ") if source == "sequence mismatch" else PDB
    model = make_mmcif(pdb=atoms)
    model_digest = sha256(model).hexdigest()
    digest = {"different": "b" * 64, "no checksum": ""}.get(source, model_digest)
    residues = pdb_evidence(pdb=PDB.decode(), expected_sequence="AG")
    evidence = expansion_ui.monomer_view_payload(residues=pd.DataFrame(residues))
    pocket = {"number": 4, "rank": 1, "positions": [1], "color": "#c24e00"}
    evidence.update(model_source="Portable test review", model_sha256=digest, pockets=[pocket])
    for point in evidence["model"]:
        point["plddt"] = None
    if source == "trace mismatch":
        evidence["model"][0]["x"] += 1
    monkeypatch.setattr(expansion_ui, "released_member_sequence", Mock(return_value="AG"))
    monkeypatch.setattr(expansion_ui, "linked_review_evidence", Mock(return_value=evidence))
    retrieve = Mock(return_value=model_bundle(content=model, accession="Q6NKN8", hog_id="HOG1"))
    monkeypatch.setattr("e3app.research.retrieval_ui.build_alphafold_hog_bundle", retrieve)
    if source == "no checksum":
        monkeypatch.delenv("E3_WHATRES_DIR")
    workspace = str(configured_app["workspace"])
    app = AppTest.from_string(
        "import pandas as pd\n"
        "from pathlib import Path\n"
        "from e3app.config import AppConfig\n"
        "from e3app.research.common import ResearchConfig\n"
        "from e3app.research.expansion_ui import render_linked_features\n"
        "render_linked_features(\n"
        f"    config=ResearchConfig(workspace=Path({workspace!r})), app_config=AppConfig(),\n"
        "    connection=None, choice=('Q6NKN8', 'HOG1', 'Arabidopsis_thaliana', 'Q6NKN8'),\n"
        "    domains=pd.DataFrame(),\n"
        ")\n",
    ).run()
    assert app.get("iframe") and not retrieve.called
    original = linked_payload(app=app)
    assert original["pockets"] == [pocket]
    assert [point["plddt"] for point in original["model"]] == [None, None]
    panel = geometry_panel(app=app)
    assert next(button for button in panel.button if button.label == CONTROL).disabled
    next(button for button in panel.button if button.label == FULL_MODEL_BUTTON).click().run()
    retrieve.assert_called_once_with(hog_id="HOG1", accessions=["Q6NKN8"], include_pae=False)
    panel = geometry_panel(app=app)
    assert any(item.label == "Download AlphaFold model (mmCIF)"
               for item in panel.get("download_button"))
    assert any("match the original review" in item.value for item in panel.caption) == (
        digest == model_digest
    )
    displayed = linked_payload(app=app)
    if source == "sequence mismatch":
        assert displayed == original
        assert any("could not be used for pLDDT" in item.value for item in app.info)
    else:
        assert [point["plddt"] for point in displayed["model"]] == [80, 60]
        if source == "matching":
            assert displayed["pockets"] == [pocket]
            assert displayed["confidence_source"] == "Checksum-matched AlphaFold Database"
            assert displayed["model_source"] == "Portable test review"
        else:
            assert displayed["pockets"] == []
            assert displayed["confidence_source"] == "AlphaFold Database"
            assert displayed["model_sha256"] == model_digest
            if source == "trace mismatch":
                assert any("mapped to the review trace" in item.value for item in app.info)
            next(item for item in app.radio if item.label == "3D trace").set_value(
                "Reviewed model and pockets",
            ).run()
            assert linked_payload(app=app) == original
            next(item for item in app.radio if item.label == "3D trace").set_value(
                "Retrieved AlphaFold Database model",
            ).run()
            assert linked_payload(app=app) == displayed
    if source == "different":
        assert any("different SHA-256" in item.value for item in panel.info)
    if source == "no checksum":
        assert next(button for button in panel.button if button.label == CONTROL).disabled
        monkeypatch.setenv("E3_WHATRES_DIR", str(configured_app["whatres"]))
        app.run()
    calculate(app=app)
    label = "Q6NKN8 · Arabidopsis thaliana"
    if digest != model_digest:
        label += " · current AlphaFold Database"
    assert_result(app=app, label=label)
    score = next(iter(app.session_state["whatres_session_scores"].values()))
    assert score.model_sha256 == model_digest
    if source == "different":
        panel = geometry_panel(app=app)
        panel.radio(key="linked_protein_whatres_source").set_value("Original review file").run()
        assert not geometry_panel(app=app).dataframe
        assert any(digest in item.value for item in geometry_panel(app=app).caption)


def test_uploaded_pdb_scores_without_fasta_and_does_not_reuse_changed_coordinates(
    *, configured_app: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the normal ESMFold model upload route and a changed coordinate file."""
    monkeypatch.setattr("e3app.whatres_ui.MAX_SESSION_SCORES", 1)
    uploads = {}
    monkeypatch.setattr(st, "file_uploader", Mock(side_effect=lambda **kwargs: uploads.get(
        kwargs.get("key"),
    )))
    app = AppTest.from_file(str(APP_SCRIPT), default_timeout=30).run()
    _navigate(app, stage=CANDIDATES, page="ESMFold & models")
    panel = geometry_panel(app=app)
    assert any("Upload a full-atom PDB above" in item.value for item in panel.caption)
    assert panel.button[0].disabled
    uploads["viewer_model_pdb"] = uploaded_file(content=PDB, name="uploaded.pdb")
    app.run()
    calculate(app=app)
    assert_result(app=app, label="uploaded.pdb")
    next(item for item in geometry_panel(app=app).button if item.label == RESIDUE_ACTION
         ).click().run()
    assert linked_payload(app=app)["model"][0]["native_id"] == "A 1"
    uploads["viewer_model_fasta"] = uploaded_file(content=b">ag\nAG\n", name="model.fasta")
    app.run()
    assert len(app.get("iframe")) == 1
    assert linked_payload(app=app)["model"][0]["residue_score"] == 30.25
    assert linked_payload(app=app)["model"][0]["plddt"] == 80
    assert_result(app=app, label="uploaded.pdb")
    uploads["viewer_model_pdb"] = uploaded_file(content=PDB + b"\n", name="uploaded.pdb")
    app.run()
    assert not geometry_panel(app=app).dataframe
    calculate(app=app)
    assert_result(app=app, label="uploaded.pdb")
    cache = app.session_state["whatres_session_scores"]
    assert [score.model_sha256 for score in cache.values()] == [sha256(PDB + b"\n").hexdigest()]
    uploads["viewer_model_fasta"] = uploaded_file(content=b">wrong\nGG\n", name="wrong.fasta")
    app.run()
    assert_result(app=app, label="uploaded.pdb")
    assert any(
        "Could not open the linked sequence viewer" in warning.value for warning in app.warning
    )


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
    prepare = Mock(
        return_value=model_bundle(content=model, accession="Q9SA03", hog_id="N0.HOG0001"),
    )
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


@pytest.mark.parametrize("page", ["HOG model comparison", "External links"])
def test_prepared_hog_scores_and_downloads_the_whole_current_selection(
    *, page: str, configured_app: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Download the model ZIP and score its members through both actual app entry points."""
    monkeypatch.setenv("E3_MAX_TABLE_ROWS", "1")
    hog = "N0.HOG0001"
    model = make_mmcif()
    bundle = model_bundle(content=model, accession="Q9SA03", hog_id=hog)
    absent = replace(
        bundle.records[0], model_index=1, accession="P38398", species="Homo_sapiens",
        status="not_available", model_sha256="", model_bytes=0, model_url="",
        detail="No model available",
    )
    prepare = Mock(return_value=replace(bundle, records=(*bundle.records, absent)))
    monkeypatch.setattr("e3app.alphafold_hog_bundle.build_alphafold_hog_bundle", prepare)
    downloads = Mock(wraps=st.download_button)
    monkeypatch.setattr(st, "download_button", downloads)
    app = AppTest.from_file(str(APP_SCRIPT), default_timeout=30).run()
    stage = STRUCTURE if page == "HOG model comparison" else "🔵 1 · Information"
    _navigate(app, stage=stage, page=page)
    panel = next(item for item in app.expander if item.label == BATCH_PANEL)
    assert panel.get("popover")
    assert any("doi.org/10.64898/2026.11.06.764824" in item.value for item in panel.markdown)
    assert not panel.button
    button = ("Prepare Inspector ZIP for selected members" if page == "HOG model comparison"
              else "Prepare models for external tools")
    next(item for item in app.button if item.label == button).click().run()
    assert not app.exception and not app.error
    assert prepare.call_args.kwargs["hog_id"] == hog
    assert list(prepare.call_args.kwargs["accessions"]) == ["Q9SA03", "P38398"]
    zip_download = next(item for item in downloads.call_args_list
                        if item.args == ("Download ZIP for manual Inspector upload",))
    with ZipFile(BytesIO(zip_download.kwargs["data"])) as archive:
        assert archive.read(f"e3_{hog}_model_0.cif") == model

    panel = next(item for item in app.expander if item.label == BATCH_PANEL)
    next(item for item in panel.button if item.label == BATCH_CONTROL).click().run()
    assert not app.exception and not app.error
    prepare.assert_called_once()
    panel = next(item for item in app.expander if item.label == BATCH_PANEL)
    assert {item.label: item.value for item in panel.metric} == {
        "Models scored": "1 / 2", "Median realism": "42.50",
        "Median apparent resolution": "2.35 Å",
    }
    assert panel.dataframe[0].value["Accession"].tolist() == ["Q9SA03", "P38398"]
    assert any(item.label == BATCH_EXPORT for item in panel.get("download_button"))
    tsv = next(item.kwargs["data"] for item in downloads.call_args_list
               if item.kwargs.get("label") == BATCH_EXPORT)
    table = pd.read_csv(StringIO(tsv), sep="\t")
    assert table.loc[0, "model_sha256"] == sha256(model).hexdigest()
    assert table.loc[0, ["realism", "apparent_resolution"]].tolist() == [42.5, 2.35]
    assert table.loc[1, "retrieval_status"] == "not_available"
    assert table.loc[1, "scoring_status"] == "not_attempted"
    assert table.loc[1, ["realism", "apparent_resolution"]].isna().all()

    app.run()
    assert any(item.label == BATCH_EXPORT for item in app.get("download_button"))
    next(item for item in app.multiselect
         if item.label == "HOG members to include in the model ZIP").set_value(["Q9SA03"]).run()
    assert not any(item.label == BATCH_EXPORT for item in app.get("download_button"))
    assert not any(item.label == "Models scored" for item in app.metric)
