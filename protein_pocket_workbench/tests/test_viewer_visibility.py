"""Real-browser regressions for pocket visibility, rank identity and sequence rows."""

import copy
import csv
import json
import os

import pytest

from pocket_workbench.annotations import (
    pocket_alignment_data,
    pocket_alignment_document,
)
from pocket_workbench.core import load_project
from pocket_workbench.viewers import model_viewer_records, structure_document

pytestmark = pytest.mark.skipif(
    os.getenv("POCKET_WORKBENCH_BROWSER_TESTS") != "1",
    reason="Requires the optional installed Playwright Chromium browser",
)


@pytest.fixture
def page():
    """Keep viewer tests offline and fail on JavaScript or HTTP dependencies."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as api:
        browser = api.chromium.launch(
            args=[
                "--no-sandbox",
                "--enable-unsafe-swiftshader",
                "--use-angle=swiftshader",
            ]
        )
        page = browser.new_page(viewport={"width": 1450, "height": 1100})
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda r: requests.append(r.url) if r.url.startswith("http") else None,
        )
        page.route("http**://**", lambda route: route.abort())
        yield page
        browser.close()
        assert not errors, errors
        assert not requests, requests


def open_structure(*, project, page, metadata=None, pair=False):
    """Open the same document builder used by the app, with saved demo coordinates.

    Args:
        project: Temporary native resource.
        page: Chromium page with networking blocked.
        metadata: Optional replacement reference pocket metadata.
        pair: Whether to include the saved transformed mobile model.

    Returns:
        Loaded native data and the reference model record.
    """
    data = load_project(root=project)
    result = json.loads((project / data["comparisons"][0]["result_path"]).read_text())
    models = {m["sample_id"]: m for m in data["models"]}
    reference, mobile = models[result["reference"]], models[result["mobile"]]
    path = project / "visibility_test.html"
    path.write_text(
        structure_document(
            reference_pdb=(project / reference["prepared_model"]).read_text(),
            reference_label=reference["sample_id"],
            reference_metadata=metadata
            or model_viewer_records(
                root=project, model=reference, pockets=data["pockets"]
            ),
            mobile_pdb=(project / result["mobile_aligned"]).read_text() if pair else "",
            mobile_label=mobile["sample_id"] if pair else "",
            mobile_metadata=(
                model_viewer_records(
                    root=project, model=mobile, pockets=data["pockets"]
                )
                if pair
                else None
            ),
            match=(
                next(
                    m
                    for m in result["pocket_matches"]
                    if m["reference_pocket"] == m["mobile_pocket"] == 1
                )
                if pair
                else None
            ),
        )
    )
    page.goto(path.as_uri())
    page.wait_for_function("Boolean(window.pocketDisplayState)")
    return data, reference


def test_pocket_default_is_local_and_context_filters_keep_lining_visible(project, page):
    """The chosen lining remains the focus when background context is filtered."""
    open_structure(project=project, page=page)
    state = page.evaluate("window.pocketDisplayState[0]")
    assert state["pockets"] == [1] and state["ranks"] == [1]
    assert state["lining"] == 8
    assert 8 <= state["visible"] < 32
    page.get_by_text("Pocket appearance", exact=True).click()
    assert page.get_by_label("Pocket lining surface", exact=True).is_checked()
    assert "not a calculated empty cavity volume" in page.locator("body").inner_text()
    page.get_by_text("Pocket appearance", exact=True).click()
    page.get_by_role("button", name="Show whole models", exact=True).click()
    assert page.evaluate("window.pocketDisplayState[0].visible") == 32
    page.get_by_role("button", name="Focus pockets", exact=True).click()
    page.locator("#model-controls summary").first.click()
    page.get_by_label(
        "synthetic_reference minimum displayed pLDDT", exact=True
    ).evaluate("e=>{e.value='100';e.dispatchEvent(new Event('input',{bubbles:true}));}")
    filtered = page.evaluate("window.pocketDisplayState[0]")
    assert filtered["visible"] == 0
    assert filtered["pockets"] == [1] and filtered["lining"] == 8


def test_filtered_pockets_retain_original_ranks_instead_of_being_promoted(
    project, page
):
    """Top one means original rank one, even when rank three is the first available."""
    data = load_project(root=project)
    model = next(m for m in data["models"] if m["sample_id"] == "synthetic_reference")
    metadata = model_viewer_records(root=project, model=model, pockets=data["pockets"])
    metadata["pockets"][0]["review_rank"] = 3
    metadata["pockets"][1]["review_rank"] = 8
    open_structure(project=project, page=page, metadata=metadata)
    assert page.evaluate("window.pocketDisplayState[0].ranks") == [3]
    selection = page.get_by_label("synthetic_reference pocket selection", exact=True)
    selection.select_option("top1")
    assert page.evaluate("window.pocketDisplayState[0].pockets") == []
    selection.select_option("top3")
    assert page.evaluate("window.pocketDisplayState[0].ranks") == [3]


def test_unknown_rank_is_not_inferred_from_pocket_identifier(project, page):
    """Legacy records with no rank remain explicitly unreported in 3D."""
    data = load_project(root=project)
    model = next(m for m in data["models"] if m["sample_id"] == "synthetic_reference")
    metadata = model_viewer_records(root=project, model=model, pockets=data["pockets"])
    metadata["pockets"] = [
        {k: v for k, v in metadata["pockets"][0].items() if k != "review_rank"}
    ]
    open_structure(project=project, page=page, metadata=metadata)
    assert page.evaluate("window.pocketDisplayState[0].ranks") == [None]
    assert "Rank unreported" in page.locator("#selection-summary").inner_text()


def test_pair_uses_transformed_geometry_and_distinct_model_colours(project, page):
    """An aligned mobile's local context follows its displayed, transformed atoms."""
    open_structure(project=project, page=page, pair=True)
    states = page.evaluate("window.pocketDisplayState")
    assert states[0]["colours"] != states[1]["colours"]
    assert states[0]["visible"] == states[1]["visible"] > 0
    assert states[0]["context"] == states[1]["context"]
    page.get_by_label("synthetic_mobile pocket selection", exact=True).select_option(
        "p:2"
    )
    assert (
        "differs from the saved pair" in page.locator("#display-warning").inner_text()
    )
    assert page.evaluate("window.pocketDisplayState[1].ranks") == [2]


def test_compact_alignment_keeps_regions_distinct_and_downloads_displayed_ids(
    project, page
):
    """Condensing replicates must not merge different input ranges or evidence."""
    data = load_project(root=project)
    payload = pocket_alignment_data(
        root=project,
        data=data,
        aligned_records={k: "-" + v for k, v in data["sequences"].items()},
    )
    original = payload["rows"][0]
    duplicate = dict(original, sample_id="extra_replicate", display_label="Replicate")
    payload["rows"].append(duplicate)
    for region in (1, 2):
        payload["rows"].append(
            dict(
                original,
                sample_id=f"region_{region}",
                scope_key=f"region_{region}",
                display_label=f"Region {region}",
            )
        )
    original_annotations = copy.deepcopy(
        [a for a in payload["annotations"] if a["sample_id"] == original["sample_id"]]
    )
    payload["annotations"].extend(
        dict(a, sample_id="extra_replicate") for a in original_annotations
    )
    path = project / "compact_alignment_test.html"
    path.write_text(pocket_alignment_document(payload=payload))
    page.goto(path.as_uri())
    page.wait_for_function("Boolean(window.pocketAlignmentReady)")
    assert page.locator("#overview svg").count() == 5
    assert "Rank 1" in page.locator("#legend").inner_text()
    assert "Rank 3" not in page.locator("#legend").inner_text()
    page.get_by_label("Alignment row selection", exact=True).select_option("all")
    assert page.locator("#overview svg").count() == 6
    page.locator("#search").fill("extra_replicate")
    assert page.locator("#overview svg").count() == 1
    assert page.locator("#status").inner_text().startswith("1 of 6")
    page.get_by_label("Maximum review rank", exact=True).select_option("1")
    page.locator("#overview circle").first.click()
    detail = page.locator("#selection").inner_text()
    assert "FASTA position 2" in detail and "alignment column 3" in detail
    with page.expect_download() as pending:
        page.get_by_role(
            "button", name="Download displayed annotation TSV", exact=True
        ).click()
    with pending.value.path().open() as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows and {r["sample_id"] for r in rows} == {"extra_replicate"}
    assert {r["review_rank"] for r in rows} == {"1"}


def test_fasta_only_residue_selection_identifies_just_the_clicked_record(project, page):
    """FASTA-only rows have distinct selection identity despite absent model IDs."""
    payload = dict(
        rows=[
            dict(
                sample_id="",
                sequence_id=name,
                aligned="-ACD",
                mapping_status="no_model",
            )
            for name in ("FASTA_A", "FASTA_B")
        ],
        annotations=[],
        alignment_length=4,
        top_k=5,
        has_preparation_screen=False,
    )
    path = project / "fasta_only_alignment.html"
    path.write_text(pocket_alignment_document(payload=payload))
    page.goto(path.as_uri())
    page.wait_for_function("Boolean(window.pocketAlignmentReady)")
    page.locator("#alignment .aline").nth(1).locator(".aa").nth(2).click()
    assert "FASTA_A" in page.locator("#selection").inner_text()
    assert "FASTA position 2" in page.locator("#selection").inner_text()
    assert page.locator(".aa.selected").count() == 1
