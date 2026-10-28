"""Prepare/download/upload workflows at every Protein Imager entry point."""

from __future__ import annotations

from pathlib import Path
import shutil

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from e3app.errors import AppError
from test_pocket_review import make_pocket_review
from test_protein_imager import make_imager_data
from test_streamlit_app import _navigate


def _app(*, resource_db: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """Open the real application with a deliberately tiny result preview."""
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_MAX_TABLE_ROWS", "1")
    path = Path(__file__).resolve().parents[1] / "src/e3app/streamlit_app.py"
    return AppTest.from_file(str(path), default_timeout=20).run()


def _click_prepare(*, app: AppTest) -> None:
    """Prepare only the Protein Imager data for the currently displayed selection."""
    next(button for button in app.button
         if button.label == "Prepare Protein Imager data").click().run()
    assert not app.exception


def _assert_downloads(*, app: AppTest) -> None:
    """Check that both the bulk ZIP and a directly uploadable structure are offered."""
    labels = {button.label for button in app.get("download_button")}
    assert "Download Protein Imager upload files (ZIP)" in labels
    assert "Download selected structure for Protein Imager (mmCIF)" in labels
    assert any(button.label == "Open Protein Imager" for button in app.get("link_button"))
    assert any("Extract the ZIP" in item.value for item in app.caption)


@pytest.mark.parametrize("stage", ("🔵 1 · Information", "🟠 4 · Structural prioritisation"))
def test_external_links_prepares_selected_hog_upload_files(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    """Both shared page routes expose a dedicated preparation action and actual model files."""
    requests = []

    def prepare(**kwargs):
        """Capture the explicit selection and return real, locally prepared upload bytes."""
        requests.append((kwargs["group_id"], tuple(kwargs["accessions"])))
        return make_imager_data(
            group_id=kwargs["group_id"], accessions=tuple(kwargs["accessions"]),
        )[0]

    monkeypatch.setattr("e3app.protein_imager.prepare_protein_imager_data", prepare)
    app = _app(resource_db=resource_db, monkeypatch=monkeypatch)
    _navigate(app, stage=stage, page="External links")
    assert not app.exception
    assert not requests
    _click_prepare(app=app)
    assert requests == [("N0.HOG0001", ("Q9SA03", "P38398"))]
    _assert_downloads(app=app)
    prepared = app.session_state["external_pi_prepared_data"]["prepared"]
    assert prepared.files[0].data.startswith(b"data_Q9SA03\n")
    next(item for item in app.selectbox if item.label == "Structure file to download").set_value(
        "P38398"
    ).run()
    assert not app.exception
    assert len(requests) == 1


def test_ligandability_prepares_an_individual_protein_or_hog(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The formerly bare link now supplies files for the explicit accession or selected HOG."""
    requests = []

    def prepare(**kwargs):
        """Prepare offline coordinate files while recording the requested data scope."""
        requests.append((kwargs["group_id"], tuple(kwargs["accessions"])))
        return make_imager_data(
            group_id=kwargs["group_id"], accessions=tuple(kwargs["accessions"]),
        )[0]

    monkeypatch.setattr("e3app.protein_imager.prepare_protein_imager_data", prepare)
    app = _app(resource_db=resource_db, monkeypatch=monkeypatch)
    _navigate(app, stage="🟠 4 · Structural prioritisation", page="Ligandability")
    assert not app.exception
    assert not requests
    button = next(item for item in app.button if item.label == "Prepare Protein Imager data")
    assert button.disabled
    next(item for item in app.text_input
         if item.label == "UniProt accession for Protein Imager").set_value("q9sa03").run()
    _click_prepare(app=app)
    assert requests == [("Q9SA03", ("Q9SA03",))]
    _assert_downloads(app=app)
    next(item for item in app.radio
         if item.label == "Prepare Protein Imager data for").set_value("HOG members").run()
    assert not app.exception
    assert not any(item.label == "Download Protein Imager upload files (ZIP)"
                   for item in app.get("download_button"))
    _click_prepare(app=app)
    assert requests[-1] == ("N0.HOG0001", ("Q9SA03", "P38398"))
    _assert_downloads(app=app)


@pytest.mark.parametrize("page", ("3D structures & pockets", "Human & plant 3D alignment"))
def test_selected_review_prepares_current_group_without_reselecting_the_hog(
    *, resource_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, page: str,
) -> None:
    """Plant and human/plant review links automatically bind to the displayed group."""
    review = make_pocket_review(tmp_path)
    for path in review.rglob("*.tsv"):
        path.write_text(path.read_text().replace("P1", "Q9SA03").replace("P2", "P38398"))
    for path in list(review.rglob("*P1*")):
        if path.is_file():
            path.rename(path.with_name(path.name.replace("P1", "Q9SA03").replace("P2", "P38398")))
    monkeypatch.setenv("E3_POCKET_REVIEW_DIR", str(review))
    monkeypatch.setenv("E3_HUMAN_PLANT_REVIEW_DIR", str(review))
    requests = []

    def prepare(**kwargs):
        """Supply full model fixtures for exactly the currently selected report group."""
        requests.append((kwargs["group_id"], tuple(kwargs["accessions"])))
        return make_imager_data(
            group_id=kwargs["group_id"], accessions=tuple(kwargs["accessions"]),
        )[0]

    monkeypatch.setattr("e3app.protein_imager.prepare_protein_imager_data", prepare)
    app = _app(resource_db=resource_db, monkeypatch=monkeypatch)
    _navigate(app, stage="🟡 5 · Structural comparison", page=page)
    assert not app.exception
    assert not requests
    assert not any(item.label == "HOG for Protein Imager" for item in app.selectbox)
    _click_prepare(app=app)
    assert requests == [("N0.HOG1", ("Q9SA03", "P38398"))]
    _assert_downloads(app=app)


def test_selection_changes_and_failed_retry_remove_previous_ready_files(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A preparation from another member set or a failed retry cannot remain downloadable."""
    monkeypatch.setattr(
        "e3app.protein_imager.prepare_protein_imager_data",
        lambda **kwargs: make_imager_data(
            group_id=kwargs["group_id"], accessions=tuple(kwargs["accessions"]),
        )[0],
    )
    app = _app(resource_db=resource_db, monkeypatch=monkeypatch)
    _navigate(app, stage="🔵 1 · Information", page="External links")
    _click_prepare(app=app)
    next(item for item in app.multiselect
         if item.label == "Proteins to prepare for Protein Imager").set_value(["Q9SA03"]).run()
    assert not app.exception
    assert not any(item.label == "Download Protein Imager upload files (ZIP)"
                   for item in app.get("download_button"))
    _click_prepare(app=app)

    def fail(**kwargs):
        """Simulate an unavailable provider after an earlier successful preparation."""
        raise AppError("Test provider unavailable")

    monkeypatch.setattr("e3app.protein_imager.prepare_protein_imager_data", fail)
    _click_prepare(app=app)
    assert any("preparation failed" in item.value for item in app.error)
    assert not any(item.label == "Download selected structure for Protein Imager (mmCIF)"
                   for item in app.get("download_button"))


def test_unavailable_models_offer_an_audit_instead_of_upload_files(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty preparation cannot be presented as a model upload package."""
    monkeypatch.setattr(
        "e3app.protein_imager.prepare_protein_imager_data",
        lambda **kwargs: make_imager_data(
            group_id=kwargs["group_id"], accessions=tuple(kwargs["accessions"]),
            missing=tuple(kwargs["accessions"]),
        )[0],
    )
    app = _app(resource_db=resource_db, monkeypatch=monkeypatch)
    _navigate(app, stage="🔵 1 · Information", page="External links")
    _click_prepare(app=app)
    assert any("No requested model" in item.value for item in app.warning)
    assert any(item.label == "Download Protein Imager retrieval audit (ZIP)"
               for item in app.get("download_button"))
    assert not any(item.label == "Download Protein Imager upload files (ZIP)"
                   for item in app.get("download_button"))


def test_hog_change_and_invalid_single_accession_do_not_reuse_prepared_data(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing the selected HOG or entering an unsupported accession removes old downloads."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "INSERT INTO hierarchical_membership VALUES ('N0.HOG0002', 'Other_species', 'P12345')"
        )
    monkeypatch.setattr(
        "e3app.protein_imager.prepare_protein_imager_data",
        lambda **kwargs: make_imager_data(
            group_id=kwargs["group_id"], accessions=tuple(kwargs["accessions"]),
        )[0],
    )
    app = _app(resource_db=resource_db, monkeypatch=monkeypatch)
    _navigate(app, stage="🟠 4 · Structural prioritisation", page="Ligandability")
    next(item for item in app.radio
         if item.label == "Prepare Protein Imager data for").set_value("HOG members").run()
    _click_prepare(app=app)
    next(item for item in app.selectbox if item.label == "HOG for Protein Imager").set_value(
        "N0.HOG0002"
    ).run()
    assert not app.exception
    assert not any(item.label == "Download Protein Imager upload files (ZIP)"
                   for item in app.get("download_button"))
    next(item for item in app.radio
         if item.label == "Prepare Protein Imager data for").set_value("One protein").run()
    next(item for item in app.text_input
         if item.label == "UniProt accession for Protein Imager").set_value("local_gene").run()
    assert not app.exception
    assert next(item for item in app.button if item.label == "Prepare Protein Imager data").disabled


def test_partial_preparation_and_source_change_are_explicit(
    *, resource_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only available proteins are offered, and another release cannot reuse those files."""
    monkeypatch.setattr(
        "e3app.protein_imager.prepare_protein_imager_data",
        lambda **kwargs: make_imager_data(
            group_id=kwargs["group_id"], accessions=tuple(kwargs["accessions"]),
            missing=("P38398",),
        )[0],
    )
    app = _app(resource_db=resource_db, monkeypatch=monkeypatch)
    _navigate(app, stage="🔵 1 · Information", page="External links")
    _click_prepare(app=app)
    assert any("Unavailable models: P38398" in item.value for item in app.warning)
    selector = next(item for item in app.selectbox if item.label == "Structure file to download")
    assert selector.options == ["Q9SA03"]
    other = tmp_path / "another_release.duckdb"
    shutil.copy2(src=resource_db, dst=other)
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(other))
    app.run()
    assert not app.exception
    assert not any(item.label == "Download Protein Imager upload files (ZIP)"
                   for item in app.get("download_button"))


def test_empty_hog_catalogue_leaves_individual_protein_preparation_available(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty HOG catalogue gives a clear next step without creating a model request."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute("DELETE FROM hierarchical_membership")
    app = _app(resource_db=resource_db, monkeypatch=monkeypatch)
    _navigate(app, stage="🟠 4 · Structural prioritisation", page="Ligandability")
    next(item for item in app.radio
         if item.label == "Prepare Protein Imager data for").set_value("HOG members").run()
    assert not app.exception
    assert any("No HOG with member records" in item.value for item in app.info)
    assert next(item for item in app.button if item.label == "Prepare Protein Imager data").disabled
