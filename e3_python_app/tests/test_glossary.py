"""Tests for plain-language scientific terminology and threshold help."""

from __future__ import annotations

import pytest

from e3app.glossary import (
    GLOSSARY_ENTRIES,
    SLIDER_HELP,
    glossary_rows,
    glossary_sections,
)


def test_glossary_covers_requested_terms_and_rules() -> None:
    """The app should define ambiguous terms and every manual threshold."""

    terms = {entry.term for entry in GLOSSARY_ENTRIES}
    required_terms = {
        "Seed",
        "Normalised seed",
        "Non-seed member",
        "Gate",
        "Gated / gated out",
        "Strict / stringent",
        "Minimum domain-supported assessed-species fraction",
        "Minimum expression-supported assessed-species fraction",
        "Tissue / organism part",
        "NOT_MAPPED",
    }
    assert required_terms.issubset(terms)
    assert set(SLIDER_HELP) == {
        "target_species_fraction",
        "mandatory_species_fraction",
        "domain_species_fraction",
        "expression_species_fraction",
        "structural_species_fraction",
        "minimum_druggability_score",
    }


def test_glossary_preserves_exact_completed_thresholds() -> None:
    """Recorded rules must retain values used by the completed run."""

    recorded = "\n".join(entry.recorded_rule for entry in GLOSSARY_ENTRIES)
    for expected in ("0.90", "1.00", "0.80", "0.75", "0.50", "8 Å", "4 Å"):
        assert expected in recorded
    assert "Greater than 0.0 TPM/FPKM" in recorded


def test_glossary_rows_validate_the_section() -> None:
    """Glossary export should be ordered and reject unknown sections."""

    sections = glossary_sections()
    assert sections[0] == "Groups and identifiers"
    assert glossary_rows(sections[0])[0]["Term"] == "Seed"
    with pytest.raises(ValueError, match="Unknown glossary section"):
        glossary_rows("missing")
