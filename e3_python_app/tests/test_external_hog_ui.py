"""Full-app HOG hand-off, model preparation and stale-download regressions."""

from __future__ import annotations

from pathlib import Path
import shutil

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from e3app.errors import AppError
from e3app.external_hog import collect_external_hog_members, collect_external_hogs
from test_external_hog import make_model_bundle
from test_streamlit_app import _navigate


def _external_app(*, resource_db: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """Open the integrated external tools page with the smallest screen-preview cap."""
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(resource_db))
    monkeypatch.setenv("E3_MAX_TABLE_ROWS", "1")
    path = Path(__file__).resolve().parents[1] / "src/e3app/streamlit_app.py"
    app = AppTest.from_file(str(path), default_timeout=20).run()
    return _navigate(app, stage="🔵 1 · Information", page="External links")


def _prepare_models(*, app: AppTest) -> AppTest:
    """Click the explicit model-preparation action in the external tools page."""
    next(button for button in app.button
         if button.label == "Prepare models for external tools").click().run()
    assert not app.exception
    return app


def test_selected_hog_model_preparation_and_individual_model_download(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preparing a HOG uses all its members and offers audited Inspector/Protein Imager files."""
    calls = []

    def prepare(*, hog_id: str, accessions: list[str], species_by_accession: dict[str, str]):
        calls.append((hog_id, tuple(accessions), species_by_accession))
        return make_model_bundle(hog_id=hog_id, accessions=tuple(accessions))

    monkeypatch.setattr("e3app.alphafold_hog_bundle.build_alphafold_hog_bundle", prepare)
    app = _external_app(resource_db=resource_db, monkeypatch=monkeypatch)
    assert not app.exception
    assert not calls
    _prepare_models(app=app)
    assert calls[0][0:2] == ("N0.HOG0001", ("Q9SA03", "P38398"))
    assert calls[0][2]["P38398"] == "Homo_sapiens"
    downloads = {button.label: button.proto for button in app.get("download_button")}
    assert "Download ZIP for manual Inspector upload" in downloads
    assert "Download selected model for Protein Imager (mmCIF)" in downloads
    selector = next(item for item in app.selectbox
                    if item.label == "Prepared model for Protein Imager")
    selector.set_value("P38398").run()
    assert not app.exception
    assert len(calls) == 1
    assert app.session_state["external_links_alphafold_bundle"]["bundle"].included_count == 2
    assert any(item.label == "Open Protein Imager for the downloaded model"
               for item in app.get("link_button"))


def test_member_selection_invalidates_a_prepared_bundle(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ZIP prepared for two members is hidden when the model selection changes."""
    monkeypatch.setattr(
        "e3app.alphafold_hog_bundle.build_alphafold_hog_bundle",
        lambda **kwargs: make_model_bundle(accessions=tuple(kwargs["accessions"])),
    )
    app = _external_app(resource_db=resource_db, monkeypatch=monkeypatch)
    _prepare_models(app=app)
    selector = next(item for item in app.multiselect
                    if item.label == "HOG members to include in the model ZIP")
    selector.set_value(["Q9SA03"]).run()
    assert not app.exception
    assert not any(button.label == "Download ZIP for manual Inspector upload"
                   for button in app.get("download_button"))
    assert not any(item.label == "Prepared model for Protein Imager" for item in app.selectbox)
    next(item for item in app.multiselect
         if item.label == "HOG members to include in the model ZIP").set_value(
        ["Q9SA03", "P38398"]
    ).run()
    assert not any(button.label == "Download ZIP for manual Inspector upload"
                   for button in app.get("download_button"))


def test_hog_change_drops_prepared_models_and_populates_single_member_links(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switching to a one-member HOG cannot expose the previous group's prepared files."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "INSERT INTO hierarchical_membership VALUES ('N0.HOG0002', 'Other_species', 'P12345')"
        )
    monkeypatch.setattr(
        "e3app.alphafold_hog_bundle.build_alphafold_hog_bundle",
        lambda **kwargs: make_model_bundle(accessions=tuple(kwargs["accessions"])),
    )
    app = _external_app(resource_db=resource_db, monkeypatch=monkeypatch)
    _prepare_models(app=app)
    next(item for item in app.selectbox if item.label == "HOG for external tools").set_value(
        "N0.HOG0002"
    ).run()
    assert not app.exception
    assert not any(button.label == "Download ZIP for manual Inspector upload"
                   for button in app.get("download_button"))
    links = {item.label: item.proto.url for item in app.get("link_button")}
    assert links["Open first protein in Mol*"].endswith("?afdb=P12345")
    assert "Open selected pair in EMERALD" not in links
    assert any("one member" in item.value for item in app.info)


def test_source_change_cannot_reuse_same_hog_preparation(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The same HOG/accessions under another source require new preparation."""
    monkeypatch.setattr(
        "e3app.alphafold_hog_bundle.build_alphafold_hog_bundle",
        lambda **kwargs: make_model_bundle(accessions=tuple(kwargs["accessions"])),
    )
    app = _external_app(resource_db=resource_db, monkeypatch=monkeypatch)
    _prepare_models(app=app)
    other = tmp_path / "another_release.duckdb"
    shutil.copy2(src=resource_db, dst=other)
    monkeypatch.setenv("E3_RESOURCE_DUCKDB", str(other))
    app.run()
    assert not app.exception
    assert not any(button.label == "Download ZIP for manual Inspector upload"
                   for button in app.get("download_button"))


def test_pair_changes_update_populated_urls_and_local_ids_use_fasta(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pair roles follow the choice; local identifiers are never guessed as UniProt."""
    app = _external_app(resource_db=resource_db, monkeypatch=monkeypatch)
    members = app.session_state["external_links_context"]["members"]
    first = members.loc[members["identifier"].eq("P38398"), "member_key"].iloc[0]
    next(item for item in app.selectbox
         if item.label == "First protein for external tools").set_value(
        first
    ).run()
    assert not app.exception
    links = {item.label: item.proto.url for item in app.get("link_button")}
    assert "seqA=P38398&seqB=Q9SA03" in links["Open selected pair in EMERALD"]
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "UPDATE hierarchical_membership SET raw_identifier = 'local_gene' "
            "WHERE species = 'Arabidopsis_thaliana'"
        )
        connection.execute(
            "UPDATE candidate_group_member_sequences SET raw_identifier = 'local_gene' "
            "WHERE species = 'Arabidopsis_thaliana'"
        )
    app.run()
    assert not app.exception
    links = {item.label: item.proto.url for item in app.get("link_button")}
    assert "Open first protein in Mol*" not in links
    assert "Open selected pair in EMERALD" not in links
    assert any(item.label == "Download selected HOG pair FASTA"
               for item in app.get("download_button"))


def test_preparation_failure_and_unavailable_members_do_not_offer_a_stale_zip(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed explicit retrieval never falls back to a previously prepared bundle."""
    monkeypatch.setattr(
        "e3app.alphafold_hog_bundle.build_alphafold_hog_bundle",
        lambda **kwargs: make_model_bundle(accessions=tuple(kwargs["accessions"])),
    )
    app = _external_app(resource_db=resource_db, monkeypatch=monkeypatch)
    _prepare_models(app=app)

    def fail(**kwargs):
        raise AppError("Test service unavailable")

    monkeypatch.setattr("e3app.alphafold_hog_bundle.build_alphafold_hog_bundle", fail)
    _prepare_models(app=app)
    assert any("service unavailable" in item.value for item in app.error)
    assert not any(item.label == "Download ZIP for manual Inspector upload"
                   for item in app.get("download_button"))


def test_missing_membership_retains_manual_tool_entry_points(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A release without root membership offers clear availability guidance and manual links."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute("DROP TABLE hierarchical_membership")
    app = _external_app(resource_db=resource_db, monkeypatch=monkeypatch)
    assert not app.exception
    assert not any(item.label == "HOG for external tools" for item in app.selectbox)
    assert any("root-level membership" in item.value for item in app.info)
    assert any(item.label == "Open Protein Imager" for item in app.get("link_button"))


def test_hog_context_queries_are_cached_across_pair_reruns(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing pair widgets does not rescan HOG metadata or selected-member authorities."""
    calls = {"hogs": 0, "members": 0}

    def hogs(*, connection: object):
        calls["hogs"] += 1
        return collect_external_hogs(connection=connection)

    def members(*, connection: object, hog_id: str):
        calls["members"] += 1
        return collect_external_hog_members(connection=connection, hog_id=hog_id)

    monkeypatch.setattr("e3app.external_hog.collect_external_hogs", hogs)
    monkeypatch.setattr("e3app.external_hog.collect_external_hog_members", members)
    app = _external_app(resource_db=resource_db, monkeypatch=monkeypatch)
    keys = app.session_state["external_links_context"]["members"]["member_key"].tolist()
    next(item for item in app.selectbox
         if item.label == "First protein for external tools").set_value(keys[1]).run()
    assert not app.exception
    assert calls == {"hogs": 1, "members": 1}


@pytest.mark.parametrize("mode", ("empty", "local"))
def test_empty_or_local_only_hogs_do_not_offer_unprepared_model_downloads(
    *, resource_db: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """Missing member/model capability stays explicit while manual entry points remain usable."""
    with duckdb.connect(str(resource_db)) as connection:
        if mode == "empty":
            connection.execute("DELETE FROM hierarchical_membership")
        else:
            connection.execute("UPDATE hierarchical_membership SET raw_identifier = 'local_gene'")
    app = _external_app(resource_db=resource_db, monkeypatch=monkeypatch)
    assert not app.exception
    assert not any(item.label == "Download ZIP for manual Inspector upload"
                   for item in app.get("download_button"))
    if mode == "empty":
        assert any("No root HOG" in item.value for item in app.info)
    else:
        assert any("No canonical UniProt" in item.value for item in app.warning)
