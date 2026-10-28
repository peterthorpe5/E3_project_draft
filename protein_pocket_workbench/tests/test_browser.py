"""Optional real-browser checks for the bundled scientific viewer libraries."""

import json
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("POCKET_WORKBENCH_BROWSER_TESTS") != "1",
    reason="Set POCKET_WORKBENCH_BROWSER_TESTS=1 after installing Playwright Chromium",
)


@pytest.mark.parametrize(
    "kind", ["structure", "alignment", "jbrowse", "pocket_alignment"]
)
def test_viewer_initialises_offline_in_chromium(project, kind):
    """Real third-party viewers initialise without any HTTP dependency."""
    from playwright.sync_api import sync_playwright

    from pocket_workbench.core import load_project

    data = load_project(root=project)
    if kind == "structure":
        result = json.loads(
            (project / data["comparisons"][0]["result_path"]).read_text()
        )
        path = project / result["viewer_path"]
    elif kind == "pocket_alignment":
        from pocket_workbench.annotations import (
            pocket_alignment_data,
            pocket_alignment_document,
        )
        from pocket_workbench.importing import read_fasta

        path = project / "annotation_browser_test.html"
        path.write_text(
            pocket_alignment_document(
                payload=pocket_alignment_data(
                    root=project,
                    data=data,
                    aligned_records=read_fasta(
                        path=project / data["sequence_analyses"][0]["alignment_path"],
                        aligned=True,
                    ),
                )
            )
        )
    else:
        directory = (project / data["sequence_analyses"][0]["alignment_path"]).parent
        path = directory / (
            "alignment_tree.html" if kind == "jbrowse" else "alignment_viewer.html"
        )
    with sync_playwright() as api:
        browser = api.chromium.launch(
            args=[
                "--no-sandbox",
                "--enable-unsafe-swiftshader",
                "--use-angle=swiftshader",
            ]
        )
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                requests.append(request.url) if request.url.startswith("http") else None
            ),
        )
        page.route("http**://**", lambda route: route.abort())
        page.goto(path.as_uri())
        if kind == "structure":
            page.wait_for_function("Boolean(window.pocketViewer)", timeout=20000)
            assert page.locator("canvas").count() >= 1
            page.get_by_label("Mobile", exact=True).uncheck()
            page.get_by_label("Mobile", exact=True).check()
            page.get_by_role("button", name="Focus pockets").click()
            page.get_by_label("Colour by pLDDT").check()
            assert (
                page.locator("#status").inner_text().startswith("synthetic_reference")
            )
        elif kind == "pocket_alignment":
            page.wait_for_function("Boolean(window.pocketAlignmentReady)")
            assert page.locator("#overview svg").count() == 3
            assert page.locator("#alignment .mark").count() > 0
            page.locator("#overview circle").first.click()
            assert "FASTA position" in page.locator("#selection").inner_text()
            page.get_by_label("Maximum review rank", exact=True).select_option("1")
            assert "mapped annotations" in page.locator("#status").inner_text()
        elif kind == "jbrowse":
            page.wait_for_function("Boolean(window.proteinMSA)", timeout=20000)
            assert page.locator("canvas,svg").count() > 0
        else:
            page.wait_for_function(
                "document.getElementById('viewer').childElementCount > 0", timeout=20000
            )
            assert "could not" not in page.locator("#status").inner_text()
        assert not errors, errors
        assert not requests, requests
        browser.close()
