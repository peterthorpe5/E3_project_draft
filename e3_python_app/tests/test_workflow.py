"""Tests for the end-to-end workflow schematic."""

from __future__ import annotations

import pytest

from e3app.workflow import WORKFLOW_STAGES, _stage_card, workflow_schematic_html


def test_workflow_stages_cover_the_complete_release_path() -> None:
    """The schematic retains every mandatory stage and the optional chemistry branch."""
    assert tuple(WORKFLOW_STAGES) == (
        "inputs",
        "discovery",
        "orthofinder",
        "orthology",
        "domains",
        "expression",
        "shortlist",
        "ligandability",
        "alignment",
        "chemistry",
        "integration",
        "reporting",
    )
    assert WORKFLOW_STAGES["chemistry"]["optional"] is True
    assert all(
        stage["optional"] is False
        for key, stage in WORKFLOW_STAGES.items()
        if key != "chemistry"
    )


def test_stage_card_is_escaped_and_rejects_unknown_keys() -> None:
    """Configured content is safely rendered and invalid stage keys fail clearly."""
    html = _stage_card(key="ligandability")
    assert "Structures, pockets and pocket conservation" in html
    assert "<strong>Output:</strong>" in html
    with pytest.raises(KeyError, match="Unknown workflow stage"):
        _stage_card(key="missing")


def test_complete_schematic_explains_branches_and_interpretation_boundary() -> None:
    """The rendered map contains all stages, key methods and the final boundary."""
    html = workflow_schematic_html()
    for stage in WORKFLOW_STAGES.values():
        assert stage["title"] in html
    for text in (
        "tantan masking",
        "OrthoFinder 2.5.5",
        "median-TPM threshold of 0.5",
        "P2Rank",
        "US-align and TM-align",
        "hard gates separate from continuous scores",
        "structural, chemical and experimental validation",
    ):
        assert text in html
    assert 'role="figure"' in html
    assert html.count("workflow-stage-optional") == 2
