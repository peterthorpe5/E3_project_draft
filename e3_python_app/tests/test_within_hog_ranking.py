"""Tests for the focused within-HOG member-ranking presentation helpers."""

from __future__ import annotations

import pandas as pd
import pytest

from e3app.errors import AppError
from e3app.within_hog_ranking import (
    summarise_within_hog_members,
    within_hog_choice_labels,
)


def test_within_hog_choice_labels_include_available_context() -> None:
    """Selector labels expose both HOG ranks and member counts when present."""
    hogs = pd.DataFrame(
        {
            "hog_id": ["N0.HOG2", "N0.HOG1"],
            "hog_prestructure_rank": [2, 1],
            "hog_poststructure_rank": [pd.NA, 3],
            "hog_member_count": [8, 12],
        }
    )
    labels = within_hog_choice_labels(hogs=hogs)
    assert list(labels) == ["N0.HOG2", "N0.HOG1"]
    assert labels["N0.HOG2"] == "N0.HOG2 · pre-structure rank 2 · members 8"
    assert labels["N0.HOG1"] == (
        "N0.HOG1 · pre-structure rank 1 · post-structure rank 3 · members 12"
    )


def test_within_hog_summary_preserves_assessment_states() -> None:
    """Counts and the first review member use the existing independent rank."""
    members = pd.DataFrame(
        {
            "hog_id": ["N0.HOG1", "N0.HOG1", "N0.HOG1"],
            "member_raw_identifier": ["raw_b", "raw_a", "raw_c"],
            "member_parsed_accession": ["B", "A", ""],
            "member_parsed_entry": ["", "ENTRY_A", "ENTRY_C"],
            "member_structural_readiness_rank": [2, 1, 3],
            "member_structural_readiness_status": [
                "STRUCTURAL_POCKET_EVIDENCE",
                "STRUCTURAL_POCKET_EVIDENCE",
                "NO_JOINED_STRUCTURAL_POCKET_EVIDENCE",
            ],
            "member_structure_assessed": [True, "true", False],
        }
    )
    summary = summarise_within_hog_members(members=members)
    assert summary.hog_id == "N0.HOG1"
    assert summary.member_count == 3
    assert summary.structurally_assessed_count == 2
    assert summary.unassessed_count == 1
    assert summary.first_member == "A"
    assert summary.first_member_status == "STRUCTURAL_POCKET_EVIDENCE"


def test_within_hog_helpers_fail_closed_on_malformed_frames() -> None:
    """Blank choices, mixed HOGs and absent rank evidence are rejected."""
    with pytest.raises(AppError, match="hog_id"):
        within_hog_choice_labels(hogs=pd.DataFrame({"other": [1]}))
    with pytest.raises(AppError, match="blank"):
        within_hog_choice_labels(hogs=pd.DataFrame({"hog_id": [""]}))
    with pytest.raises(AppError, match="duplicate"):
        within_hog_choice_labels(
            hogs=pd.DataFrame({"hog_id": ["N0.HOG1", "N0.HOG1"]})
        )
    empty = pd.DataFrame(
        columns=(
            "hog_id",
            "member_raw_identifier",
            "member_structural_readiness_rank",
            "member_structural_readiness_status",
            "member_structure_assessed",
        )
    )
    assert summarise_within_hog_members(members=empty).member_count == 0
    mixed = pd.DataFrame(
        {
            "hog_id": ["N0.HOG1", "N0.HOG2"],
            "member_raw_identifier": ["one", "two"],
            "member_structural_readiness_rank": [1, 1],
            "member_structural_readiness_status": ["A", "B"],
            "member_structure_assessed": [True, False],
        }
    )
    with pytest.raises(AppError, match="exactly one HOG"):
        summarise_within_hog_members(members=mixed)
    missing_rank = mixed.iloc[[0]].copy()
    missing_rank["member_structural_readiness_rank"] = pd.NA
    with pytest.raises(AppError, match="no usable readiness rank"):
        summarise_within_hog_members(members=missing_rank)
    with pytest.raises(AppError, match="missing columns"):
        summarise_within_hog_members(members=pd.DataFrame({"hog_id": []}))
