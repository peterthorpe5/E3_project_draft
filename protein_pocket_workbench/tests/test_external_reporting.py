"""Portable external-tool pages preserve sequences, model links and local inputs."""

import json

import pytest

from pocket_workbench.core import WorkbenchError, load_project
from pocket_workbench.external_reporting import (
    export_external_review,
    external_review_document,
)
from pocket_workbench.reporting import export_review


def test_offline_external_document_escapes_identifiers_and_preserves_missing_sequences(
    project,
):
    """External page data remains inert and missing sequences stay explicitly absent."""
    data = load_project(root=project)
    data["title"] = "</script><script>window.bad=1</script>"
    data["models"][0]["sequence"] = ""
    document = external_review_document(
        data=data, model_files={}, residue_files={}, group_files=[], fits=[]
    )
    assert data["title"] not in document
    assert (
        "window.bad=1" in document
    )  # In escaped inert JSON, not an executable script.
    payload = json.loads(
        document.split('<script id="external-data" type="application/json">')[1].split(
            "</script>"
        )[0]
    )
    assert payload["records"][0]["model_input"]["sequence"] is None
    assert payload["records"][0]["representative_fasta"]["sequence"]
    assert not any("prepared_model" in r for r in payload["records"])
    assert '<script src="http' not in document


def test_external_export_refuses_resource_overlap_and_existing_outputs(
    project, tmp_path
):
    """An export cannot overwrite a native resource or earlier review directory."""
    data = load_project(root=project)
    for target in [project / "external", tmp_path]:
        with pytest.raises(WorkbenchError):
            export_external_review(
                root=project, data=data, output=target, group_files=[], fits=[]
            )


def test_portable_review_contains_external_hub_exact_model_files_and_annotated_zip(
    project, tmp_path
):
    """The finished HTML review supports external tools without Python or HPC access."""
    out = export_review(root=project, output=tmp_path / "review")
    assert "external/index.html" in (out / "index.html").read_text()
    page = (out / "external/index.html").read_text()
    payload = json.loads(
        page.split('<script id="external-data" type="application/json">')[1].split(
            "</script>"
        )[0]
    )
    for record in payload["records"]:
        if record["model_href"]:
            path = out / "external" / record["model_href"]
            assert path.is_file()
        if record["residue_href"]:
            assert (out / "external" / record["residue_href"]).is_file()
    for group in payload["groups"]:
        assert (out / "external" / group["href"]).is_file()
    for fit in payload["fits"]:
        for key in ("reference_href", "mobile_href", "result_href"):
            assert (out / "external" / fit[key]).is_file()
    assert (out / "external/public_links.tsv").read_text().startswith("record_id\t")
    import zipfile

    with zipfile.ZipFile(next((out / "model_groups").glob("*.zip"))) as archive:
        assert {"pocket_residues.tsv", "model_inputs.fasta", "handoff.json"} <= set(
            archive.namelist()
        )
    assert not any(p.suffix == ".csv" for p in (out / "external").rglob("*"))
