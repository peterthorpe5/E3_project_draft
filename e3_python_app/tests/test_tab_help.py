"""Tests for complete top-level application help."""

from __future__ import annotations

import pytest

from e3app.errors import AppError
from e3app.tab_help import TOP_LEVEL_TAB_HELP, tab_help_entry, tab_help_text


def test_every_top_level_tab_has_substantive_help() -> None:
    """The maintained help catalogue covers every current primary tab."""
    expected = {
        "Overview",
        "Workflow schematic",
        "Glossary",
        "Computational recommendations",
        "Threshold explorer",
        "Independent structural-review shortlist",
        "Visual explorer",
        "Candidates",
        "Orthology",
        "Human HOGs",
        "Plant & human HOGs",
        "Seed & HOG explorer",
        "E3 seed catalogue",
        "Domains",
        "Expression",
        "Ligandability",
        "Pocket conservation",
        "3D structures & pockets",
        "Pocket-aligned sequences",
        "3D alignment",
        "Human & plant 3D alignment",
        "Computational chemistry",
        "Search",
        "All results",
        "Provenance and QC",
    }
    assert set(TOP_LEVEL_TAB_HELP) == expected
    for name in expected:
        entry = tab_help_entry(tab_name=name)
        assert len(entry.instruction) >= 80
        assert len(entry.yields) >= 80
        text = tab_help_text(tab_name=name)
        assert "**What this tab yields:**" in text
        assert entry.instruction in text
        assert entry.yields in text


def test_unknown_tab_help_fails_explicitly() -> None:
    """A new unregistered tab cannot silently receive generic guidance."""
    with pytest.raises(AppError, match="No contextual help"):
        tab_help_text(tab_name="Unknown")
