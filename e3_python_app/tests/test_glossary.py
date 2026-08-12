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
    assert len(GLOSSARY_ENTRIES) >= 360
    for expected in (
        "Tantan masking",
        "P2Rank",
        "fpocket-rescore",
        "rescore_2024",
        "PAE",
        "FMOPhore",
        "FrAncestor",
        "final_evolutionary_rank",
        "boss_review_status",
    ):
        assert expected in terms


def test_glossary_preserves_exact_completed_thresholds() -> None:
    """Recorded rules must retain values used by the completed run."""

    recorded = "\n".join(entry.recorded_rule for entry in GLOSSARY_ENTRIES)
    for expected in ("0.90", "1.00", "0.80", "0.75", "0.50", "8 Å", "4 Å"):
        assert expected in recorded
    assert "Median TPM at least 0.5" in recorded
    assert "Greater than 0.0 TPM/FPKM" not in recorded

    definitions = "\n".join(entry.definition for entry in GLOSSARY_ENTRIES)
    assert "five-number summary" in definitions
    assert "not a list of biological replicates" in definitions


def test_glossary_rows_validate_the_section() -> None:
    """Glossary export should be ordered and reject unknown sections."""

    sections = glossary_sections()
    assert sections[0] == "Groups and identifiers"
    assert glossary_rows(sections[0])[0]["Term"] == "Seed"
    field_rows = glossary_rows("1. Ranks and review statuses")
    final_rank = next(
        row for row in field_rows if row["Term"] == "final_evolutionary_rank"
    )
    assert final_rank["Type / unit"] == "Integer; blank if ineligible"
    assert final_rank["Source"] == "Final candidate field dictionary v1.0"
    assert "experimental validation rank" in final_rank["Interpretation / caution"]
    with pytest.raises(ValueError, match="Unknown glossary section"):
        glossary_rows("missing")


def test_glossary_resource_validation_rejects_bad_arguments() -> None:
    """Resource loading fails clearly before displaying malformed content."""
    from e3app import glossary

    with pytest.raises(ValueError, match="filename"):
        glossary._load_resource_entries(file_name="", source="source")
    with pytest.raises(ValueError, match="source label"):
        glossary._load_resource_entries(
            file_name="project_term_glossary.tsv",
            source="",
        )
