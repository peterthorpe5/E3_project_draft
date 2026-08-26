"""Tests for recorded-method and threshold annotations."""

from __future__ import annotations

import pytest

from e3app.errors import AppError
from e3app.method_annotations import (
    METHOD_ANNOTATIONS,
    TM_SCORE_REFERENCE_URL,
    method_annotation,
    method_annotation_markdown,
)


def test_scientific_tabs_have_substantive_method_annotations() -> None:
    """Every selected scientific tab has sections and an interpretation boundary."""
    expected = {
        "Workflow schematic",
        "Computational recommendations",
        "Threshold explorer",
        "Independent structural-review shortlist",
        "Orthology",
        "Domains",
        "Expression",
        "Ligandability",
        "Pocket conservation",
        "3D structures & pockets",
        "Pocket-aligned sequences",
        "3D alignment",
        "Human & plant 3D alignment",
        "Computational chemistry",
        "Provenance and QC",
    }
    assert set(METHOD_ANNOTATIONS) == expected
    for tab_name in expected:
        annotation = method_annotation(tab_name=tab_name)
        assert len(annotation.introduction) >= 80
        assert annotation.sections
        assert all(section.heading and section.bullets for section in annotation.sections)
        assert len(annotation.interpretation_boundary) >= 60


def test_structural_annotation_records_thresholds_and_reference() -> None:
    """The 3D help records the production gates and requested TM-score source."""
    markdown = method_annotation_markdown(tab_name="3D alignment")
    assert "TM-score at least 0.50" in markdown
    assert "centroid distance at most 8 Angstrom" in markdown
    assert "Residue proximity was assessed within 4 Angstrom" in markdown
    assert "chemical-group conservation at least 0.60" in markdown
    assert "group support at least 0.75" in markdown
    assert "not a threshold invented for this project" in markdown
    assert TM_SCORE_REFERENCE_URL in markdown
    assert "Xu and Zhang (2010)" in markdown


def test_alphafold_annotation_distinguishes_retrieval_qc_and_scope() -> None:
    """AlphaFold help remains explicit about provenance, QC, PAE and human models."""
    markdown = method_annotation_markdown(tab_name="3D structures & pockets")
    assert "Canonical monomer mmCIF models were retrieved" in markdown
    assert "No human model was selected" in markdown
    assert "0.50 of residues at pLDDT at least 70" in markdown
    assert "not a standalone downstream exclusion gate" in markdown
    assert "PAE was downloaded where available but was not a formal production gate" in markdown
    assert "several Arabidopsis thaliana accessions" in markdown
    assert "structural_representative_selection_audit" in markdown
    assert "not a claim that the selected paralogue is biologically superior" in markdown


def test_human_extension_annotation_explains_member_and_reference_selection() -> None:
    """Human inclusion and the preserved plant reference are not conflated."""
    markdown = method_annotation_markdown(tab_name="Human & plant 3D alignment")
    assert "did not choose one favoured human paralogue" in markdown
    assert "Exact sequence-only members remain" in markdown
    assert "inherited unchanged" in markdown
    assert "never chose a new reference" in markdown
    assert "pocket mapping fraction" in markdown


def test_mapping_annotation_distinguishes_integrated_and_component_qc() -> None:
    """Mapping help does not conflate the final fraction flag with stricter QC."""
    markdown = method_annotation_markdown(tab_name="Ligandability")
    assert "integrated pocket-mapping pass used mapping fraction at least 0.95" in markdown
    assert "stricter mapping_qc_pass" in markdown
    assert "zero ambiguous mappings" in markdown
    assert "0.70 of all predicted pocket residues" in markdown
    assert "could not inflate this conservative fraction" in markdown


def test_optional_thresholds_are_not_mislabelled_as_production_gates() -> None:
    """The threshold-explorer box marks its score controls as optional and disabled."""
    markdown = method_annotation_markdown(tab_name="Threshold explorer")
    assert "Optional post-hoc controls" in markdown
    assert "disabled until selected" in markdown
    assert "must not be reported as additional production gates" in markdown


def test_unknown_method_annotation_fails_explicitly() -> None:
    """An unmaintained tab cannot silently receive generic method text."""
    with pytest.raises(AppError, match="No method and threshold annotation"):
        method_annotation(tab_name="Unknown")
