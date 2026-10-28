"""Pocket data preparation, download and stale-source protection in the real UI."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from e3app.protein_imager import prepare_protein_imager_data
from test_protein_imager_pockets import make_pocket_report, original_cif
from test_protein_imager_ui import _app, _click_prepare
from test_streamlit_app import _navigate


def _with_pockets(
    *, resource_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> tuple[AppTest, Path]:
    """Open a configured app with real pocket exports and a deterministic missing-model provider."""
    root = make_pocket_report(parent=tmp_path, group_id="N0.HOG0001")
    monkeypatch.setenv("E3_POCKET_REVIEW_DIR", str(root))
    monkeypatch.setenv("E3_HUMAN_PLANT_REVIEW_DIR", str(root))

    def prepare(**kwargs):
        """Run the production pocket exporter without contacting AlphaFold Database."""
        return prepare_protein_imager_data(**kwargs, reader=lambda *args: b"[]")

    monkeypatch.setattr("e3app.protein_imager.prepare_protein_imager_data", prepare)
    return _app(resource_db=resource_db, monkeypatch=monkeypatch), root


@pytest.mark.parametrize("stage,page", (
    ("🔵 1 · Information", "External links"),
    ("🟠 4 · Structural prioritisation", "External links"),
    ("🟠 4 · Structural prioritisation", "Ligandability"),
    ("🟡 5 · Structural comparison", "3D structures & pockets"),
    ("🟡 5 · Structural comparison", "Human & plant 3D alignment"),
))
def test_all_entry_points_prepare_recorded_pockets(
    *, resource_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str, page: str,
) -> None:
    """Every previously bare link carries its exact selected evidence into downloadable files."""
    app, _ = _with_pockets(resource_db=resource_db, tmp_path=tmp_path, monkeypatch=monkeypatch)
    _navigate(app, stage=stage, page=page)
    if page == "Ligandability":
        next(item for item in app.text_input
             if item.label == "UniProt accession for Protein Imager").set_value("Q9SA03").run()
    assert not app.exception
    _click_prepare(app=app)
    labels = {button.label for button in app.get("download_button")}
    assert "Download Protein Imager upload files (ZIP)" in labels
    assert "Download selected pocket inspection file (mmCIF)" in labels
    assert any("CA_only files contain" in item.value for item in app.warning)
    assert any("supplementary TSV" in item.value for item in app.caption)
    selector = next(item for item in app.selectbox
                    if item.label == "Pocket inspection file to download")
    assert selector.options == [
        "Q9SA03_CA_only_protein.cif", "Q9SA03_CA_only_rank1_pocket7.cif",
        "Q9SA03_CA_only_rank2_pocket2.cif",
    ]
    selector.set_value("Q9SA03_CA_only_rank1_pocket7.cif").run()
    assert not app.exception


def test_report_change_invalidates_prepared_pocket_files(
    *, resource_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An edited report cannot leave pocket files from its previous contents available."""
    app, root = _with_pockets(
        resource_db=resource_db, tmp_path=tmp_path, monkeypatch=monkeypatch,
    )
    _navigate(app, stage="🟠 4 · Structural prioritisation", page="External links")
    _click_prepare(app=app)
    page = next((root / "groups").iterdir())
    page.write_text(page.read_text().replace('"druggability_score": 0.75',
                                             '"druggability_score": 0.65'))
    app.run()
    assert not app.exception
    assert not any(item.label == "Download selected pocket inspection file (mmCIF)"
                   for item in app.get("download_button"))
    _click_prepare(app=app)
    page.write_text(page.read_text().replace('"primary_group_id": "N0.HOG0001"',
                                             '"primary_group_id": "N0.HOG0002"'))
    app.run()
    assert not app.exception
    assert any("Invalid recorded" in item.value for item in app.warning)
    assert next(item for item in app.button if item.label == "Prepare Protein Imager data").disabled
    assert not any(item.label == "Download selected pocket inspection file (mmCIF)"
                   for item in app.get("download_button"))


def test_original_model_upload_enables_atoms_and_replacement_clears_downloads(
    *, resource_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supply original bytes to the real exporter and bind them to prepared state."""
    uploads = [SimpleNamespace(getvalue=original_cif)]
    monkeypatch.setattr("streamlit.file_uploader", lambda *args, **kwargs: uploads)
    app, _ = _with_pockets(resource_db=resource_db, tmp_path=tmp_path, monkeypatch=monkeypatch)
    _navigate(app, stage="🟠 4 · Structural prioritisation", page="External links")
    _click_prepare(app=app)
    prepared = app.session_state["external_pi_prepared_data"]["prepared"]
    assert prepared.pocket_audit[0]["representation"] == "original_model_checksum_verified"
    assert not any("CA_only files contain" in item.value for item in app.warning)
    uploads[0] = SimpleNamespace(getvalue=lambda: original_cif() + b"# changed\n")
    app.run()
    assert not app.exception
    assert not any(item.label == "Download selected pocket inspection file (mmCIF)"
                   for item in app.get("download_button"))
