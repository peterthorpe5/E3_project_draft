"""Tests for focused structural-reference and pair-evidence help."""

from __future__ import annotations

import pytest

from e3app.errors import AppError
from e3app.structural_help import (
    PAIR_EVIDENCE_DEFINITIONS,
    annotate_pair_evidence_html,
    human_extension_rank_help_markdown,
    pair_evidence_help_markdown,
    pocket_choice_help_markdown,
    reference_selection_help_markdown,
    structural_column_help,
)


def test_pair_evidence_help_defines_every_metric_and_threshold() -> None:
    """The readable help covers the exact viewer table and decision rules."""
    markdown = pair_evidence_help_markdown()
    assert set(PAIR_EVIDENCE_DEFINITIONS) == {
        "Minimum TM-score",
        "RMSD (Å)",
        "Pocket centroid distance (Å)",
        "Symmetric pocket overlap",
        "Local structural-residue match",
        "Local chemical-group conservation",
        "Same pocket position supported",
        "Locally conserved pocket supported",
    }
    assert all(label in markdown for label in PAIR_EVIDENCE_DEFINITIONS)
    assert "2M/(N-reference + N-mobile)" in markdown
    assert "hydrophobic (A, V, L, I, M, F, W, Y)" in markdown
    assert "do not demonstrate shared ligand binding" in markdown


def test_reference_help_explains_medicago_and_parent_preservation() -> None:
    """Reference help rejects species priority and records human-extension reuse."""
    parent = reference_selection_help_markdown(
        reference_accession="MTR_1",
        reference_species="Medicago_truncatula",
        preserved_from_parent=False,
    )
    extension = reference_selection_help_markdown(
        reference_accession="MTR_1",
        reference_species="Medicago_truncatula",
        preserved_from_parent=True,
    )
    for expected in (
        "Medicago truncatula",
        "not chosen because its species has biological priority",
        "pocket-predictor agreement",
        "closest to human",
    ):
        assert expected in parent
    assert "human extension inherited this plant reference unchanged" not in parent
    assert "human extension inherited this plant reference unchanged" in extension


@pytest.mark.parametrize(
    ("accession", "species", "missing_label"),
    (("", "Medicago_truncatula", "reference_accession"), ("P1", "", "reference_species")),
)
def test_reference_help_rejects_missing_identity(
    accession: str,
    species: str,
    missing_label: str,
) -> None:
    """Reference explanations cannot silently omit the selected identity."""
    with pytest.raises(AppError, match=missing_label):
        reference_selection_help_markdown(
            reference_accession=accession,
            reference_species=species,
            preserved_from_parent=True,
        )


def test_rank_and_pocket_help_preserve_scientific_boundaries() -> None:
    """Focused controls distinguish eligibility, sensitivity and validation."""
    rank_help = human_extension_rank_help_markdown(qualifying_group_count=22)
    pocket_help = pocket_choice_help_markdown()
    assert "22 qualifying groups" in rank_help
    assert "exact human accession" in rank_help
    assert "missing rank is not a drop-down error" in rank_help
    assert "rank-one pocket" in pocket_help
    assert "does not replace the rank-one result" in pocket_help
    assert "not experimentally confirmed" in pocket_help
    with pytest.raises(AppError, match="cannot be negative"):
        human_extension_rank_help_markdown(qualifying_group_count=-1)


def test_structural_table_help_is_targeted_to_recognised_columns() -> None:
    """Only genuinely ambiguous structural evidence fields receive header help."""
    assert "lower of the TM-scores" in str(
        structural_column_help(column_name="minimum_tm_score")
    )
    assert "fixed structural reference" in str(
        structural_column_help(column_name="reference_species")
    )
    assert structural_column_help(column_name="primary_group_id") is None


def test_pair_viewer_receives_accessible_idempotent_metric_tooltips() -> None:
    """Every recognised row gains keyboard-accessible help without changing values."""
    rows = "".join(
        f"<tr><th>{label}</th><td>VALUE_{index}</td></tr>"
        for index, label in enumerate(PAIR_EVIDENCE_DEFINITIONS)
    )
    document = f"<html><head></head><body><table>{rows}</table></body></html>"
    annotated = annotate_pair_evidence_html(document=document)
    assert 'id="e3-pair-evidence-help-style"' in annotated
    assert annotated.count('tabindex="0"') == len(PAIR_EVIDENCE_DEFINITIONS)
    assert annotated.count('role="tooltip"') == len(PAIR_EVIDENCE_DEFINITIONS)
    assert all(f"VALUE_{index}" in annotated for index in range(len(PAIR_EVIDENCE_DEFINITIONS)))
    assert annotate_pair_evidence_html(document=annotated) == annotated


def test_pair_viewer_annotation_handles_legacy_and_invalid_documents() -> None:
    """Unknown legacy viewers remain exact while invalid inputs fail explicitly."""
    legacy = "<html><body><p>No pair evidence table</p></body></html>"
    assert annotate_pair_evidence_html(document=legacy) == legacy
    without_head = "<table><tr><th>Minimum TM-score</th><td>0.8</td></tr></table>"
    annotated = annotate_pair_evidence_html(document=without_head)
    assert annotated.startswith('<style id="e3-pair-evidence-help-style">')
    prelabelled = '<html><style id="e3-pair-evidence-help-style"></style></html>'
    assert annotate_pair_evidence_html(document=prelabelled) == prelabelled
    with pytest.raises(AppError, match="must be text"):
        annotate_pair_evidence_html(document=None)  # type: ignore[arg-type]
    with pytest.raises(AppError, match="is empty"):
        annotate_pair_evidence_html(document="")
