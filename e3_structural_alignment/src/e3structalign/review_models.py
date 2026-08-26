"""Immutable models for ranked pocket-review report generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from e3structalign.errors import InputValidationError


@dataclass(frozen=True)
class ReviewSettings:
    """User-controlled settings for one review-report build.

    Attributes:
        review_limit: Maximum number of authoritative ranked groups to report.
        member_pocket_top_k: Maximum retained pocket rank to display per protein.
    """

    review_limit: int = 50
    member_pocket_top_k: int = 5

    def validate(self) -> None:
        """Validate bounded positive report settings."""
        if not 1 <= self.review_limit <= 500:
            raise InputValidationError("review_limit must be between 1 and 500")
        if not 1 <= self.member_pocket_top_k <= 20:
            raise InputValidationError(
                "member_pocket_top_k must be between 1 and 20"
            )


@dataclass(frozen=True)
class ReviewInputOverrides:
    """Optional explicit replacements for automatically discovered run inputs."""

    shortlist: Path | None = None
    selected_pockets: Path | None = None
    ranked_pockets: Path | None = None
    ranked_pocket_sequence_coordinates: Path | None = None
    asset_manifest: Path | None = None
    alignments_root: Path | None = None
    structural_summary: Path | None = None
    sensitivity_group_summary: Path | None = None
    sensitivity_member_summary: Path | None = None
    structural_alignments: Path | None = None
    structural_pocket_comparisons: Path | None = None
    structural_interactive_root: Path | None = None
    supplementary_group_sequences: Path | None = None


@dataclass(frozen=True)
class ReviewInputs:
    """Resolved, validated authorities used to build the review report."""

    run_root: Path
    shortlist: Path
    selected_pockets: Path
    ranked_pockets: Path
    ranked_pocket_sequence_coordinates: Path
    asset_manifest: Path
    alignments_root: Path
    structural_summary: Path
    sensitivity_group_summary: Path
    sensitivity_member_summary: Path
    structural_alignments: Path
    structural_pocket_comparisons: Path
    structural_interactive_root: Path
    supplementary_group_sequences: Path | None = None

    def file_inputs(self) -> dict[str, Path]:
        """Return every checksum-bound input file keyed by stable role."""
        inputs = {
            "shortlist": self.shortlist,
            "selected_pockets": self.selected_pockets,
            "ranked_pockets": self.ranked_pockets,
            "ranked_pocket_sequence_coordinates": (
                self.ranked_pocket_sequence_coordinates
            ),
            "asset_manifest": self.asset_manifest,
            "structural_summary": self.structural_summary,
            "sensitivity_group_summary": self.sensitivity_group_summary,
            "sensitivity_member_summary": self.sensitivity_member_summary,
            "structural_alignments": self.structural_alignments,
            "structural_pocket_comparisons": (
                self.structural_pocket_comparisons
            ),
        }
        if self.supplementary_group_sequences is not None:
            inputs["supplementary_group_sequences"] = (
                self.supplementary_group_sequences
            )
        return inputs
