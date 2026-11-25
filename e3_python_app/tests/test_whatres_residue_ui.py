"""Exercise native geometry from a full-model selection to linked pockets and TSV downloads."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import StringIO
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from e3app import whatres_residue_ui as ui
from e3app.errors import AppError
from e3app.research import expansion_ui
from e3app.research.linked_features import review_member_evidence
from e3app.research.providers import pdb_evidence
from e3app.whatres import WHATRES_PAPER, WhatResTarget
from e3app.whatres_residues import native_geometry_view, score_residue_geometry
from test_whatres import PDB, local_whatres, make_mmcif
from test_whatres_ui import FULL_MODEL_BUTTON, configured_app, geometry_panel, linked_payload
from test_whatres_ui import model_bundle


@pytest.fixture
def target(*, local_whatres: Path) -> WhatResTarget:
    """Provide the scored full model with complete coordinate provenance."""
    report = score_residue_geometry(directory=local_whatres, content=PDB, filename="model.pdb")
    return WhatResTarget(label="Model A", filename="model.pdb", content=PDB, residue_report=report)


def test_geometry_download_keeps_nulls_and_both_file_identities(
    *, target: WhatResTarget, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Export the full TSV, preserving missing values, exact identity and a safe filename."""
    download = Mock()
    monkeypatch.setattr(st, "download_button", download)
    ui.geometry_download(frame=pd.DataFrame([{"residue_score": None}]),
                         report=target.residue_report, target=target, key="native", kind="residue")
    args = download.call_args.kwargs
    row = pd.read_csv(StringIO(args["data"]), sep="\t", keep_default_na=False).iloc[0]
    assert row["residue_score"] == "" and row["model"] == "Model A"
    assert row["model_sha256"] == row["scored_pdb_sha256"] == sha256(PDB).hexdigest()
    assert row["whatres_version"] == "1.0.0" and args["file_name"].endswith("_residue_geometry.tsv")


def test_native_chain_fallback_and_no_report_preserve_selected_view(
    *, target: WhatResTarget, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed for mismatched models and handle multiple and unplottable native chains."""
    rendered, info, caption = Mock(), Mock(), Mock()
    monkeypatch.setattr(expansion_ui, "show_features", rendered)
    monkeypatch.setattr(st, "info", info)
    monkeypatch.setattr(st, "caption", caption)
    monkeypatch.setattr(st, "selectbox", Mock(return_value="B"))
    evidence = {"model_sha256": "b" * 64, "model": [], "pockets": []}
    assert ui.show_geometry_view(target=replace(target, residue_report=None), key="x",
                                 evidence=evidence, inline=True) is evidence
    report = target.residue_report
    multiple = replace(report, rows=(*report.rows, dict(report.rows[0], chain="B", x=None)))
    assert ui.show_geometry_view(target=replace(target, residue_report=multiple), key="test",
                                 evidence=evidence, inline=True) is evidence
    assert "different checksums" in info.call_args.args[0]
    assert "no Cα positions" in caption.call_args.args[0] and not rendered.called
    ui.show_geometry_view(target=target, key="test")
    assert rendered.call_args.kwargs["payload"]["model"][0]["native_id"] == "A 1"


def test_review_member_geometry_requires_unique_native_member_and_alignment() -> None:
    """Use native group membership and the exact aligned sequence for portable review pages."""
    atom = {"chain": "A", "resi": 1, "resn": "ALA", "x": 2, "y": 2, "z": 3}
    member = {"accession": "P1", "species": "Plant", "atoms": [atom], "model_sha256": "a" * 64}
    record = {"accession": "P1", "species": "Plant", "sequence": "-A"}
    group = {"proteins": [member], "alignment": {"records": [record]}}
    args = dict(group=group, accession="P1", species="Plant", source="original")
    evidence = review_member_evidence(**args)
    assert evidence["sequence"] == "A" and evidence["model_source"] == "original"
    assert review_member_evidence(**args, expected_sequence="G") is None
    group["proteins"].append(member)
    assert review_member_evidence(**args) is None


@pytest.mark.parametrize("different", [False, True])
def test_linked_app_retrieval_to_residue_measurements_pocket_view_and_exports(
    *, different: bool, configured_app: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Click the actual retrieval and local assessment controls, read the iframe and both TSVs."""
    cif = make_mmcif()
    digest = sha256(cif).hexdigest()
    review = expansion_ui.monomer_view_payload(
        residues=pd.DataFrame(pdb_evidence(pdb=PDB.decode(), expected_sequence="AG")),
    )
    review.update(model_source="Plant review", model_sha256="d" * 64 if different else digest,
                  pockets=[{"rank": 1, "number": 4, "color": "#c24e00", "positions": [1, 2]}])
    monkeypatch.setattr(expansion_ui, "released_member_sequence", Mock(return_value="AG"))
    monkeypatch.setattr(expansion_ui, "linked_review_evidence", Mock(return_value=review))
    fetch = Mock(return_value=model_bundle(content=cif, accession="Q6NKN8", hog_id="HOG1"))
    monkeypatch.setattr("e3app.research.retrieval_ui.build_alphafold_hog_bundle", fetch)
    downloads = Mock(wraps=st.download_button)
    monkeypatch.setattr(st, "download_button", downloads)
    app = AppTest.from_string(
        "import pandas as pd\nfrom pathlib import Path\n"
        "from e3app.config import AppConfig\nfrom e3app.research.common import ResearchConfig\n"
        "from e3app.research.expansion_ui import render_linked_features\n"
        f"render_linked_features(config=ResearchConfig(workspace=Path("
        f"{str(configured_app['workspace'])!r})), app_config=AppConfig(), connection=None, "
        "choice=('Q6NKN8','HOG1','Plant','Q6NKN8'), domains=pd.DataFrame())"
    ).run()
    panel = geometry_panel(app=app)
    assert next(item for item in panel.button if item.label == ui.RESIDUE_ACTION).disabled
    next(item for item in panel.button if item.label == FULL_MODEL_BUTTON).click().run()
    next(item for item in geometry_panel(app=app).button if item.label == ui.RESIDUE_ACTION
         ).click().run()
    panel = geometry_panel(app=app)
    payload = linked_payload(app=app)
    assert payload["geometry_limit"] == pytest.approx(29.35)
    assert [point["residue_score"] for point in payload["model"]] == [30.25, 12.25]
    assert any(WHATRES_PAPER in item.value for item in app.markdown)
    assert len(app.session_state["whatres_residue_reports"]) == 1
    exported = {call.kwargs["label"]: call.kwargs["data"] for call in downloads.call_args_list
                if call.kwargs.get("label", "").endswith("geometry (TSV)")}
    residue = pd.read_csv(StringIO(exported["Download residue geometry (TSV)"]), sep="\t")
    assert residue["model_sha256"].tolist() == [digest, digest]
    assert residue["n_outliers"].tolist() == [2, 0]
    if different:
        assert not payload["pockets"] and "Download pocket geometry (TSV)" not in exported
        next(item for item in app.radio if item.label == "3D trace").set_value(
            "Reviewed model and pockets",
        ).run()
        assert not app.exception
        assert "geometry_limit" not in app.get("iframe")[-1].proto.srcdoc.split(
            '<script id="protein-data" type="application/json">', 1)[1].split("</script>", 1)[0]
        assert any("different checksums" in item.value for item in app.info)
    else:
        pocket = pd.read_csv(StringIO(exported["Download pocket geometry (TSV)"]), sep="\t")
        assert pocket.iloc[0][["assessed_residues", "flagged_residues", "outlier_count",
                               "median_residue_score", "peak_position"]].tolist() == [
                                   2, 1, 2, 21.25, 1]
        assert pocket.iloc[0]["mapped_positions"] == "1 2"
        assert payload["pockets"][0]["geometry"]["flagged_positions"] == "1"
        next(item for item in panel.checkbox if item.label.startswith("Show only")).check().run()
        assert len(geometry_panel(app=app).dataframe[0].value) == 1
        assert len(app.session_state["whatres_residue_reports"]) == 1


def test_controls_show_errors_and_can_retry_without_reusing_other_models(
    *, target: WhatResTarget, local_whatres: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry a failed local assessment, bound its cache and exercise a missing review."""
    runner = Mock(side_effect=[AppError("test feature failure"), target.residue_report])
    monkeypatch.setattr(ui, "score_residue_geometry", runner)
    monkeypatch.setattr(ui, "read_group_evidence", Mock(side_effect=AppError("incomplete review")))
    app = AppTest.from_string(
        "from e3app.whatres import WhatResTarget\n"
        "from e3app.whatres_residue_ui import render_residue_controls\nfrom pathlib import Path\n"
        "import streamlit as st\n"
        "st.session_state.setdefault('whatres_residue_reports', dict.fromkeys('abc'))\n"
        f"render_residue_controls(target=WhatResTarget(label='fixture', content={PDB!r},"
        f"filename='test.pdb', model_sha256='{target.residue_report.model_sha256}',"
        "group_id='H', species='plant', review_accession='P1'),"
        f"directory=Path({str(local_whatres)!r}), key='test', review_dir=Path('fixture'))",
    ).run()
    app.button[0].click().run()
    assert "test feature failure" in app.warning[0].value
    app.button[0].click().run()
    assert not app.exception and app.get("iframe")
    assert any("mapped pocket residues" in item.value for item in app.caption)
    assert len(app.session_state["whatres_residue_reports"]) == 3
    app.run()
    assert runner.call_count == 2


def test_pocket_panel_native_review_and_empty_tracks(
    *, target: WhatResTarget, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep native review output available with or without mapped pocket evidence."""
    render, caption = Mock(), Mock()
    monkeypatch.setattr(st, "caption", caption)
    monkeypatch.setattr(expansion_ui, "show_features", render)
    review = native_geometry_view(report=target.residue_report, chain="A")
    ui.show_pocket_geometry(evidence=review, report=target.residue_report, target=target, key="x")
    assert "mapped pocket residues" in caption.call_args.args[0]
    assert ui.show_geometry_view(target=target, key="x", evidence=review) == review
    assert render.call_args.kwargs["payload"]["model"][1]["residue_score"] == 12.25
