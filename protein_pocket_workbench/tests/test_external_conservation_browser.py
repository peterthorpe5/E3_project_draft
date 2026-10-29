"""Offline external-file hand-offs and exact pocket-evidence-to-3D navigation."""

import json
import os
from urllib.parse import parse_qs, urlparse

import pytest

from pocket_workbench.conservation_review import conservation_document
from pocket_workbench.core import load_project
from pocket_workbench.external_reporting import external_review_document
from pocket_workbench.viewers import model_viewer_records, structure_document

pytestmark = pytest.mark.skipif(
    os.getenv("POCKET_WORKBENCH_BROWSER_TESTS") != "1",
    reason="Requires optional installed Playwright Chromium",
)


@pytest.fixture
def page():
    """Block all remote dependencies and collect frontend errors."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as api:
        browser = api.chromium.launch(
            args=[
                "--no-sandbox",
                "--enable-unsafe-swiftshader",
                "--use-angle=swiftshader",
            ]
        )
        page = browser.new_page(viewport={"width": 1500, "height": 1200})
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                requests.append(request.url) if request.url.startswith("http") else None
            ),
        )
        page.route("http**://**", lambda route: route.abort())
        yield page
        browser.close()
        assert not errors, errors
        assert not requests, requests


def test_offline_external_page_prefills_valid_ids_and_downloads_selected_exact_fasta(
    project, page
):
    """The portable hub changes links and sequence downloads with its current roles."""
    data = load_project(root=project)
    for model in data["models"]:
        model["source_accession"] = {
            "synthetic_reference": "P38398",
            "synthetic_mobile": "P51587",
        }.get(model["sample_id"], "")
    path = project / "external_links_test.html"
    path.write_text(
        external_review_document(
            data=data, model_files={}, residue_files={}, group_files=[], fits=[]
        )
    )
    page.goto(path.as_uri())
    page.wait_for_function("Boolean(window.externalLinksReady)")
    link = page.get_by_role(
        "link", name="Open selected pair in EMERALD", exact=True
    ).get_attribute("href")
    assert parse_qs(urlparse(link).query)["seqA"] == ["P38398"]
    assert (
        page.get_by_role(
            "link", name="Open in Mol* (database model)", exact=True
        ).first.get_attribute("href")
        == "https://molstar.org/viewer/?afdb=P38398"
    )
    with page.expect_download() as pending:
        page.get_by_role("button", name="Download selected FASTA", exact=True).click()
    content = pending.value.path().read_text()
    assert content.count(">") == 2 and content.startswith(
        ">first|model:synthetic_reference"
    )
    page.get_by_label("Second protein or model", exact=True).select_option(
        "model:synthetic_variant"
    )
    assert not page.get_by_role(
        "link", name="Open selected pair in EMERALD", exact=True
    ).count()
    assert page.get_by_role(
        "link", name="Open EMERALD for FASTA upload", exact=True
    ).count()
    with page.expect_download() as pending:
        page.get_by_role("button", name="Download selected FASTA", exact=True).click()
    assert "second|model:synthetic_variant" in pending.value.path().read_text()


def test_offline_conservation_opens_the_exact_alternative_pocket_pair(project, page):
    """Evidence, residue downloads and 3D retain the same selected saved pair."""
    data = load_project(root=project)
    result = json.loads((project / data["comparisons"][0]["result_path"]).read_text())
    (project / "conservation_test.html").write_text(
        conservation_document(result=result, pockets=data["pockets"])
    )
    models = {m["sample_id"]: m for m in data["models"]}
    reference, mobile = models[result["reference"]], models[result["mobile"]]
    strict = next(
        m
        for m in result["pocket_matches"]
        if m["reference_pocket"] == m["mobile_pocket"] == 1
    )
    (project / "viewer.html").write_text(
        structure_document(
            reference_pdb=(project / reference["prepared_model"]).read_text(),
            mobile_pdb=(project / result["mobile_aligned"]).read_text(),
            reference_label=result["reference"],
            mobile_label=result["mobile"],
            reference_metadata=model_viewer_records(
                root=project, model=reference, pockets=data["pockets"]
            ),
            mobile_metadata=model_viewer_records(
                root=project, model=mobile, pockets=data["pockets"]
            ),
            match=strict,
        )
    )
    page.goto((project / "conservation_test.html").as_uri())
    page.wait_for_function("Boolean(window.conservationReviewReady)")
    assert "Not assessed" in page.locator("#decisions").inner_text()
    assert "original rank-one pair" in page.locator("#pair-note").inner_text()
    assert page.locator("#distance-chart circle").count() == 8
    with page.expect_download() as pending:
        page.get_by_role(
            "button", name="Download all saved matched residue pairs TSV", exact=True
        ).click()
    assert len(pending.value.path().read_text().splitlines()) == 9
    payload = json.loads(page.locator("#conservation-data").text_content())
    alternative = next(
        i
        for i, p in enumerate(payload["pairs"])
        if p["row"]["reference_pocket"] == 1 and p["row"]["mobile_pocket"] == 2
    )
    page.locator("#pair").select_option(str(alternative))
    assert "alternative pair" in page.locator("#pair-note").inner_text()
    page.get_by_role("link", name="Open this pocket pair in 3D", exact=True).click()
    page.wait_for_function("Boolean(window.pocketDisplayState)")
    states = page.evaluate("window.pocketDisplayState")
    assert states[0]["pockets"] == [1] and states[1]["pockets"] == [2]
    page.goto(
        (project / "viewer.html").as_uri() + "?reference-pocket=1&mobile-pocket=999999"
    )
    page.wait_for_function("Boolean(window.pocketDisplayState)")
    assert page.evaluate("window.pocketDisplayState[1].pockets") == [1]
