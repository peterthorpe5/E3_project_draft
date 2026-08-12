"""Tests for transparent score formulas and exploratory reweighting."""

from __future__ import annotations

import pandas as pd
import pytest

from e3app.ranking import (
    DEFAULT_RANKING_WEIGHTS,
    normalise_ranking_weights,
    recompute_exploratory_ranking,
    select_ranking_relation,
)


def _ranking_frame() -> pd.DataFrame:
    """Return two complete group rows with deliberately different evidence."""
    return pd.DataFrame(
        {
            "final_evolutionary_rank": [1, 2],
            "evolutionary_group_key": ["HOG:A", "HOG:B"],
            "primary_group_id": ["A", "B"],
            "lead_cluster_id": ["cluster_a", "cluster_b"],
            "lead_discovery_score": [1.0, 0.0],
            "lead_orthology_score": [1.0, 0.8],
            "lead_domain_score": [0.2, 1.0],
            "lead_expression_score": [0.2, 1.0],
            "minimum_druggability_score": [0.4, 0.8],
            "mean_pocket_plddt_fraction": [0.8, 0.8],
            "all_assessed_members_pass_mapping": [True, True],
            "predictor_agreement_fraction": [1.0, 1.0],
            "pocket_conservation_score": [0.8, 0.7],
            "three_dimensional_pocket_score": [0.2, 0.9],
            "three_dimensional_alignment_status": [
                "CONSERVED_3D_POCKET_SUPPORTED",
                "CONSERVED_3D_POCKET_SUPPORTED",
            ],
            "evidence_completeness_fraction": [1.0, 1.0],
            "grant_aligned_base_pass": [True, True],
            "grant_aligned_final_pass": [True, True],
            "prestructure_score": [0.56, 0.83],
            "ligandability_score": [0.8, 0.9],
            "structural_score": [0.8, 0.81],
            "final_score": [0.656, 0.822],
        }
    )


def test_ranking_relation_selection_is_authoritative() -> None:
    """The evolutionary-group relation wins over compatibility tables."""
    assert select_ranking_relation(
        relation_names=(
            "candidate_master_results",
            "final_evolutionary_candidate_prioritisation",
        )
    ) == "final_evolutionary_candidate_prioritisation"
    assert select_ranking_relation(relation_names=("unrelated",)) is None


def test_weight_normalisation_is_explicit_and_defensive() -> None:
    """Slider values are normalised but invalid groups cannot be evaluated."""
    assert normalise_ranking_weights(
        weights={"a": 2 / 3, "b": 1 / 3}, expected=("a", "b")
    ) == pytest.approx({"a": 2 / 3, "b": 1 / 3})
    with pytest.raises(ValueError, match="expected components"):
        normalise_ranking_weights(weights={"a": 1}, expected=("a", "b"))
    with pytest.raises(ValueError, match="positive"):
        normalise_ranking_weights(weights={"a": 0, "b": 0}, expected=("a", "b"))


def test_recorded_weights_reproduce_layer_formulas_and_allow_reordering() -> None:
    """Defaults reproduce stored formulas and changed weights alter rank only."""
    source = _ranking_frame()
    result = recompute_exploratory_ranking(
        frame=source,
        prestructure_weights=DEFAULT_RANKING_WEIGHTS["prestructure"],
        ligandability_weights=DEFAULT_RANKING_WEIGHTS["ligandability"],
        structural_weights=DEFAULT_RANKING_WEIGHTS["structural"],
        final_weights=DEFAULT_RANKING_WEIGHTS["final"],
    )
    assert result["evolutionary_group_key"].tolist() == ["HOG:B", "HOG:A"]
    assert result["exploratory_ligandability_score"].tolist() == pytest.approx(
        [0.9, 0.8]
    )
    pd.testing.assert_frame_equal(source, _ranking_frame())

    discovery_only = recompute_exploratory_ranking(
        frame=source,
        prestructure_weights={
            "discovery": 1.0,
            "orthology": 0.0,
            "domain": 0.0,
            "expression": 0.0,
        },
        ligandability_weights=DEFAULT_RANKING_WEIGHTS["ligandability"],
        structural_weights=DEFAULT_RANKING_WEIGHTS["structural"],
        final_weights={"prestructure": 1.0, "structural": 0.0},
    )
    assert discovery_only["evolutionary_group_key"].tolist() == ["HOG:A", "HOG:B"]


def test_gate_tier_and_three_dimensional_refinement_are_optional() -> None:
    """Gate-tier preservation and 3D weighting remain explicit sensitivity choices."""
    source = _ranking_frame()
    source.loc[0, "grant_aligned_base_pass"] = False
    gated = recompute_exploratory_ranking(
        frame=source,
        prestructure_weights=DEFAULT_RANKING_WEIGHTS["prestructure"],
        ligandability_weights=DEFAULT_RANKING_WEIGHTS["ligandability"],
        structural_weights=DEFAULT_RANKING_WEIGHTS["structural"],
        final_weights=DEFAULT_RANKING_WEIGHTS["final"],
        three_dimensional_weight=1.0,
        preserve_gate_tier=True,
    )
    assert gated.iloc[0]["evolutionary_group_key"] == "HOG:B"
    assert gated.iloc[0]["exploratory_structural_score"] == pytest.approx(0.9)
    source.loc[0, "three_dimensional_alignment_status"] = pd.NA
    unavailable = recompute_exploratory_ranking(
        frame=source,
        prestructure_weights=DEFAULT_RANKING_WEIGHTS["prestructure"],
        ligandability_weights=DEFAULT_RANKING_WEIGHTS["ligandability"],
        structural_weights=DEFAULT_RANKING_WEIGHTS["structural"],
        final_weights=DEFAULT_RANKING_WEIGHTS["final"],
        three_dimensional_weight=1.0,
        preserve_gate_tier=False,
    )
    unavailable_a = unavailable.loc[
        unavailable["evolutionary_group_key"] == "HOG:A"
    ].iloc[0]
    assert unavailable_a["exploratory_structural_score"] == pytest.approx(0.8)
    with pytest.raises(ValueError, match="between 0 and 1"):
        recompute_exploratory_ranking(
            frame=source,
            prestructure_weights=DEFAULT_RANKING_WEIGHTS["prestructure"],
            ligandability_weights=DEFAULT_RANKING_WEIGHTS["ligandability"],
            structural_weights=DEFAULT_RANKING_WEIGHTS["structural"],
            final_weights=DEFAULT_RANKING_WEIGHTS["final"],
            three_dimensional_weight=2.0,
        )
