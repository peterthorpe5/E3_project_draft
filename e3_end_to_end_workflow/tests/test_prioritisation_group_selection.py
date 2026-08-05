"""Regression tests for distinct evolutionary-group structural selection."""

from __future__ import annotations

import pytest

from e3workflow.errors import StageError
from e3workflow.prioritisation import (
    apply_evolutionary_group_selection,
    build_evolutionary_group_records,
    rank_records,
)


def _record(
    *, cluster_id: str, group_id: str, score: float, stringent: bool = True
) -> dict[str, object]:
    """Return one minimal pre-structure record for selection tests."""
    return {
        "cluster_id": cluster_id,
        "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
        "primary_group_id": group_id,
        "prestructure_score": score,
        "evidence_completeness_fraction": 1.0,
        "grant_aligned_stringent_pass": stringent,
        "computational_structure_selected": False,
    }


def test_group_limit_is_applied_to_distinct_evolutionary_groups() -> None:
    """Repeated DeepClust contributors must not consume extra group slots."""
    ranked = rank_records(
        records=[
            _record(cluster_id="DC1", group_id="HOG1", score=0.99),
            _record(cluster_id="DC2", group_id="HOG1", score=0.98),
            _record(cluster_id="DC3", group_id="HOG2", score=0.97),
            _record(cluster_id="DC4", group_id="HOG3", score=0.96),
        ]
    )

    selected_count = apply_evolutionary_group_selection(
        records=ranked,
        structure_group_limit=2,
    )

    assert selected_count == 2
    assert {
        str(row["cluster_id"])
        for row in ranked
        if bool(row["computational_structure_selected"])
    } == {"DC1", "DC2", "DC3"}
    groups, _ = build_evolutionary_group_records(ranked)
    assert [row["primary_group_id"] for row in groups] == ["HOG1", "HOG2", "HOG3"]


def test_unmapped_cluster_is_never_selected() -> None:
    """A cluster without an evolutionary-group authority must remain excluded."""
    record = _record(cluster_id="DC1", group_id="", score=1.0)
    ranked = rank_records(records=[record])

    assert apply_evolutionary_group_selection(
        records=ranked,
        structure_group_limit=10,
    ) == 0
    assert ranked[0]["computational_structure_selected"] is False


def test_group_selection_rejects_non_positive_limit() -> None:
    """Invalid group limits must fail before mutating selection state."""
    records = [_record(cluster_id="DC1", group_id="HOG1", score=1.0)]

    with pytest.raises(StageError, match="positive integer"):
        apply_evolutionary_group_selection(records=records, structure_group_limit=0)
