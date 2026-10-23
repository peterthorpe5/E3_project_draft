"""Optional live server/browser integration across the main scientific pages."""

import http.client
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("POCKET_WORKBENCH_BROWSER_TESTS") != "1",
    reason="Requires the optional installed Playwright Chromium browser",
)


def test_live_browser_navigation_and_glossary(project, tmp_path):
    """The actual app serves tables, 3D/sequence views and searchable definitions."""
    from playwright.sync_api import sync_playwright

    from pocket_workbench import ui

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = dict(
        os.environ,
        POCKET_WORKBENCH_RESOURCE=str(project),
        POCKET_WORKBENCH_WORKSPACE=str(tmp_path / "workspace"),
    )
    with (tmp_path / "server.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(Path(ui.__file__)),
                "--server.address",
                "127.0.0.1",
                "--server.port",
                str(port),
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            ready = False
            for _ in range(100):
                try:
                    client = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    client.request("GET", "/_stcore/health")
                    ready = client.getresponse().status == 200
                    client.close()
                    if ready:
                        break
                except OSError:
                    time.sleep(0.1)
            assert ready, "Streamlit did not start"
            with sync_playwright() as api:
                browser = api.chromium.launch(
                    args=[
                        "--no-sandbox",
                        "--enable-unsafe-swiftshader",
                        "--use-angle=swiftshader",
                    ]
                )
                page = browser.new_page(viewport={"width": 1500, "height": 1000})
                page.set_default_timeout(20000)
                page.goto(f"http://127.0.0.1:{port}")
                sidebar = page.get_by_test_id("stSidebar")
                for label, button in [
                    ("Models & pockets", "Download displayed TSV"),
                    ("Compare structures", "Download offline 3D page"),
                    ("Alignment & trees", "Download offline alignment page"),
                ]:
                    sidebar.get_by_text(label, exact=True).click()
                    page.get_by_role("button", name=button, exact=True).first.wait_for()
                    if label == "Models & pockets":
                        page.frame_locator("iframe").first.locator("#status").wait_for()
                        assert (
                            page.frame_locator("iframe").first.locator("canvas").count()
                        )
                    if label == "Alignment & trees":
                        page.frame_locator("iframe").first.locator(
                            "#overview svg"
                        ).first.wait_for()
                sidebar.get_by_text("HOG / model groups", exact=True).click()
                page.get_by_role(
                    "button", name="Prepare model ZIP for Inspector", exact=True
                ).click()
                page.get_by_role(
                    "button",
                    name="Download model ZIP for manual Inspector upload",
                    exact=True,
                ).wait_for()
                sidebar.get_by_text("Structural evidence", exact=True).click()
                page.get_by_text(
                    "Structural evidence and top-k review", exact=True
                ).wait_for()
                sidebar.get_by_text("Methods & glossary", exact=True).click()
                page.get_by_role("tab", name="Searchable glossary").click()
                search = page.get_by_role(
                    "textbox", name="Search this table", exact=True
                )
                search.fill("pLDDT")
                search.press("Enter")
                page.get_by_role(
                    "button", name="Download displayed TSV", exact=True
                ).wait_for()
                assert not page.get_by_test_id("stException").count()
                browser.close()
        finally:
            os.killpg(server.pid, signal.SIGTERM)
            server.wait(timeout=5)
