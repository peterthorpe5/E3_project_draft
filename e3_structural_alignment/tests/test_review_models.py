"""Tests for visual-review immutable settings and inputs."""

from pathlib import Path

import pytest

from e3structalign.errors import InputValidationError
from e3structalign.review_models import ReviewInputs, ReviewSettings


def test_review_settings_validate_bounds() -> None:
    """Review settings reject unsafe or nonsensical sizes."""
    ReviewSettings(review_limit=50, member_pocket_top_k=5).validate()
    for settings in (
        ReviewSettings(review_limit=0),
        ReviewSettings(review_limit=501),
        ReviewSettings(member_pocket_top_k=0),
        ReviewSettings(member_pocket_top_k=21),
    ):
        with pytest.raises(InputValidationError):
            settings.validate()


def test_review_inputs_expose_only_checksum_bound_files(tmp_path: Path) -> None:
    """Directory authorities are excluded from the file checksum inventory."""
    source = tmp_path / "source.tsv"
    source.write_text("field\nvalue\n", encoding="utf-8")
    inputs = ReviewInputs(
        run_root=tmp_path,
        shortlist=source,
        selected_pockets=source,
        ranked_pockets=source,
        ranked_pocket_sequence_coordinates=source,
        asset_manifest=source,
        alignments_root=tmp_path,
        structural_summary=source,
        sensitivity_group_summary=source,
        sensitivity_member_summary=source,
        structural_alignments=source,
        structural_pocket_comparisons=source,
        structural_interactive_root=tmp_path,
    )
    assert len(inputs.file_inputs()) == 10
    assert "alignments_root" not in inputs.file_inputs()
    assert "structural_interactive_root" not in inputs.file_inputs()

    supplementary = ReviewInputs(
        **{
            **inputs.__dict__,
            "supplementary_group_sequences": source,
        }
    )
    assert supplementary.file_inputs()["supplementary_group_sequences"] == source
