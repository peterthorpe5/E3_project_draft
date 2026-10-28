"""Evidence and group navigation must open the selected fit without project writes."""

import hashlib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from pocket_workbench import ui
from pocket_workbench.comparison import compare_batch
from pocket_workbench.core import ComparisonSettings


@pytest.mark.parametrize(
    ("page", "selection", "button_key"),
    [
        ("Structural evidence", "Saved fit to open in 3D", "evidence_open_fit"),
        ("HOG / model groups", "Group fit to inspect", "group_open_fit"),
    ],
)
def test_saved_fit_navigation_preserves_source_evidence(
    project, monkeypatch, tmp_path, page, selection, button_key
):
    """Inspect the chosen saved pair while keeping all project files identical."""
    compare_batch(
        root=project,
        pairs=[("synthetic_reference", "synthetic_variant")],
        settings=ComparisonSettings(engine="sequence_kabsch", top_pockets=2),
    )
    before = {
        p.relative_to(project): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in project.rglob("*")
        if p.is_file()
    }
    monkeypatch.setenv("POCKET_WORKBENCH_RESOURCE", str(project))
    monkeypatch.setenv("POCKET_WORKBENCH_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.delenv("POCKET_WORKBENCH_ALLOW_JOBS", raising=False)
    app = AppTest.from_file(str(Path(ui.__file__)), default_timeout=20).run()
    app.sidebar.radio[0].set_value(page).run()
    if page == "Structural evidence":
        assert any("No fits in this scope" in element.value for element in app.info)
    picker = next(element for element in app.selectbox if element.label == selection)
    picker.set_value(1).run()
    app.button(key=button_key).click().run()
    assert not app.exception and not app.error
    assert app.sidebar.radio[0].value == "Compare structures"
    assert app.session_state["comparison_reference"] == "synthetic_reference"
    assert app.session_state["comparison_mobile"] == "synthetic_variant"
    assert app.get("iframe")
    after = {
        p.relative_to(project): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in project.rglob("*")
        if p.is_file()
    }
    assert before == after
