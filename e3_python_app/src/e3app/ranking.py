"""Transparent ranking formulas and a non-authoritative weight explorer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from numbers import Real

import pandas as pd

DEFAULT_RANKING_WEIGHTS: dict[str, dict[str, float]] = {
    "prestructure": {
        "discovery": 0.10,
        "orthology": 0.35,
        "domain": 0.20,
        "expression": 0.35,
    },
    "ligandability": {
        "minimum_druggability": 0.25,
        "pocket_plddt": 0.25,
        "member_mapping": 0.25,
        "predictor_agreement": 0.25,
    },
    "structural": {
        "ligandability": 0.55,
        "pocket_conservation": 0.45,
    },
    "final": {
        "prestructure": 0.60,
        "structural": 0.40,
    },
}

RANKING_WEIGHT_LABELS: dict[str, dict[str, str]] = {
    "prestructure": {
        "discovery": "Discovery score",
        "orthology": "Orthology score",
        "domain": "Domain score",
        "expression": "Expression score",
    },
    "ligandability": {
        "minimum_druggability": "Minimum member druggability",
        "pocket_plddt": "Mean pocket pLDDT fraction",
        "member_mapping": "All-member mapping pass",
        "predictor_agreement": "Pocket-predictor agreement",
    },
    "structural": {
        "ligandability": "Ligandability score",
        "pocket_conservation": "Pocket-conservation score",
    },
    "final": {
        "prestructure": "Pre-structure score",
        "structural": "Structural score",
    },
}

RANKING_METHODOLOGY_MARKDOWN = r"""
### How the recorded computational ranking was calculated

The authoritative list is a **deterministic evidence-prioritisation**, not a
probability that a protein is an E3 ligase or that a PROTAC will work. Hard
grant-aligned gates are retained separately from the continuous scores: a large
score cannot repair a failed mandatory gate.

1. **Discovery score.** For the lead DeepClust cluster,
   $D=(f_{reviewed}+f_{ubiquitin\ GO}+(1-f_{exclusion}))/3$. The three terms are
   the reviewed-seed fraction, ubiquitin-related GO-positive seed fraction and
   the complement of the exclusion-flag fraction.
2. **Orthology score.** $O=f_{target}(0.8+0.2f_{mandatory})$. Broad target-species
   representation supplies most of the score, while representation of all six
   mandatory crop species provides the remaining adjustment.
3. **Domain and expression scores.** $A$ is the fraction of domain-assessed
   species with a catalogued E3-associated domain, and $E$ is the fraction of
   uniquely mapped expression-assessed species with broad expression support.
   An unavailable assessed denominator was assigned the neutral scoring value
   0.5, while availability and gate status remained explicit elsewhere.
4. **Pre-structure score.** $P=0.10D+0.35O+0.20A+0.35E$.
5. **Ligandability score.** $L=(d_{min}+p_{pLDDT}+m_{map}+p_{agree})/4$, where
   $d_{min}$ is the minimum selected-pocket druggability across assessed
   members, $p_{pLDDT}$ is mean pocket-confidence support, $m_{map}$ is 1 only
   when every assessed member passes mapping, and $p_{agree}$ is the fraction
   supported by both pocket-prediction signals.
6. **Pocket-conservation score.** The stored score was
   $C=0.30f_{component}+0.25o_{region}+0.20c_{chemical}+0.15d_{min}+0.10p_{pLDDT}$.
   These are conserved-component coverage, mean aligned pocket-region overlap,
   biochemical-class conservation, minimum druggability and mean pocket pLDDT
   support. It summarises sequence-region evidence; it is not experimental
   binding or proof of an equivalent 3D cavity.
7. **Structural score.** The production base score was
   $S_{base}=0.55L+0.45C$. A separately configured 3D refinement would be
   $S=(1-w_{3D})S_{base}+w_{3D}T$ for assessed groups, where
   $T=0.40TM_{min}+0.40o_{3D}+0.20(1-\min(d_{centroid}/d_{max},1))$.
   In the recorded production profile, $w_{3D}=0$: 3D agreement was an explicit
   eligibility/support gate and was **not silently reweighted** into the score.
8. **Final score.** $F=0.60P+0.40S$.
9. **Ordering and tie-breaks.** Cluster rows were ordered first by the recorded
   base-gate pass tier, then descending $F$, descending evidence completeness
   and finally stable cluster identifier. DeepClust rows belonging to the same
   primary OrthoFinder group were consolidated; the best deterministic lead
   cluster represented that evolutionary group. Final evolutionary rank then
   followed the lead cluster's recorded final rank, with pre-structure group
   rank and stable group key as deterministic tie-breaks.

The sliders below recompute scores only from values already present in the
completed resource. They create a sensitivity ranking and never modify the
authoritative ranks, gates, source files or pipeline outputs.
"""


def select_ranking_relation(*, relation_names: Sequence[str]) -> str | None:
    """Select the most authoritative relation usable for weight sensitivity."""
    preferred = (
        "final_evolutionary_candidate_prioritisation",
        "top_computational_review_shortlist",
        "top_50_computational_review_shortlist",
        "candidate_master_results",
        "final_candidate_prioritisation",
    )
    return next((name for name in preferred if name in relation_names), None)


def normalise_ranking_weights(
    *,
    weights: Mapping[str, Real],
    expected: Sequence[str],
) -> dict[str, float]:
    """Validate and normalise one non-negative weight group to sum to one."""
    if set(weights) != set(expected):
        raise ValueError("Ranking weights do not match the expected components.")
    converted: dict[str, float] = {}
    for name in expected:
        value = weights[name]
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("Ranking weights must be real numbers.")
        numeric = float(value)
        if numeric < 0 or numeric > 1:
            raise ValueError("Ranking weights must be between 0 and 1.")
        converted[name] = numeric
    total = sum(converted.values())
    if total <= 0:
        raise ValueError("At least one ranking weight in each group must be positive.")
    return {name: value / total for name, value in converted.items()}


def _numeric_series(
    *, frame: pd.DataFrame, candidates: Sequence[str]
) -> pd.Series:
    """Return the first available bounded numeric component series."""
    column = next((name for name in candidates if name in frame.columns), None)
    if column is None:
        raise ValueError(
            "Ranking sensitivity requires one of: " + ", ".join(candidates)
        )
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0).clip(0.0, 1.0)


def _logical_series(*, frame: pd.DataFrame, column: str) -> pd.Series:
    """Return a conservative Boolean interpretation of one stored field."""
    if column not in frame.columns:
        raise ValueError(f"Ranking sensitivity requires {column}.")
    values = frame[column]
    if pd.api.types.is_bool_dtype(values.dtype):
        return values.fillna(False).astype(bool)
    return values.astype("string").str.strip().str.lower().isin(
        {"true", "t", "1", "yes", "y", "pass"}
    )


def recompute_exploratory_ranking(
    *,
    frame: pd.DataFrame,
    prestructure_weights: Mapping[str, Real],
    ligandability_weights: Mapping[str, Real],
    structural_weights: Mapping[str, Real],
    final_weights: Mapping[str, Real],
    three_dimensional_weight: Real = 0.0,
    preserve_gate_tier: bool = True,
) -> pd.DataFrame:
    """Recompute a bounded, explicitly non-authoritative sensitivity ranking."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Ranking sensitivity requires a pandas DataFrame.")
    if frame.empty:
        return pd.DataFrame()
    if isinstance(three_dimensional_weight, bool) or not isinstance(
        three_dimensional_weight, Real
    ):
        raise TypeError("The 3D refinement weight must be a real number.")
    weight_3d = float(three_dimensional_weight)
    if weight_3d < 0 or weight_3d > 1:
        raise ValueError("The 3D refinement weight must be between 0 and 1.")

    pre = normalise_ranking_weights(
        weights=prestructure_weights,
        expected=tuple(DEFAULT_RANKING_WEIGHTS["prestructure"]),
    )
    ligand = normalise_ranking_weights(
        weights=ligandability_weights,
        expected=tuple(DEFAULT_RANKING_WEIGHTS["ligandability"]),
    )
    structural = normalise_ranking_weights(
        weights=structural_weights,
        expected=tuple(DEFAULT_RANKING_WEIGHTS["structural"]),
    )
    final = normalise_ranking_weights(
        weights=final_weights,
        expected=tuple(DEFAULT_RANKING_WEIGHTS["final"]),
    )

    discovery = _numeric_series(
        frame=frame, candidates=("lead_discovery_score", "discovery_score")
    )
    orthology = _numeric_series(
        frame=frame, candidates=("lead_orthology_score", "orthology_score")
    )
    domain = _numeric_series(
        frame=frame, candidates=("lead_domain_score", "domain_score")
    )
    expression = _numeric_series(
        frame=frame, candidates=("lead_expression_score", "expression_score")
    )
    exploratory_prestructure = (
        discovery * pre["discovery"]
        + orthology * pre["orthology"]
        + domain * pre["domain"]
        + expression * pre["expression"]
    )
    minimum_druggability = _numeric_series(
        frame=frame, candidates=("minimum_druggability_score",)
    )
    pocket_plddt = _numeric_series(
        frame=frame, candidates=("mean_pocket_plddt_fraction",)
    )
    member_mapping = _logical_series(
        frame=frame, column="all_assessed_members_pass_mapping"
    ).astype(float)
    predictor_agreement = _numeric_series(
        frame=frame, candidates=("predictor_agreement_fraction",)
    )
    exploratory_ligandability = (
        minimum_druggability * ligand["minimum_druggability"]
        + pocket_plddt * ligand["pocket_plddt"]
        + member_mapping * ligand["member_mapping"]
        + predictor_agreement * ligand["predictor_agreement"]
    )
    pocket_conservation = _numeric_series(
        frame=frame, candidates=("pocket_conservation_score",)
    )
    base_structural = (
        exploratory_ligandability * structural["ligandability"]
        + pocket_conservation * structural["pocket_conservation"]
    )
    three_dimensional = _numeric_series(
        frame=frame, candidates=("three_dimensional_pocket_score",)
    )
    if "three_dimensional_alignment_status" in frame.columns:
        alignment_status = frame["three_dimensional_alignment_status"].astype(
            "string"
        ).str.strip().str.upper()
        assessed = alignment_status.notna() & ~alignment_status.isin(
            {"", "NOT_ASSESSED", "NOT_STRUCTURALLY_ASSESSED"}
        )
    else:
        assessed = pd.Series(False, index=frame.index)
    exploratory_structural = base_structural.where(
        ~assessed,
        base_structural * (1.0 - weight_3d) + three_dimensional * weight_3d,
    )
    exploratory_final = (
        exploratory_prestructure * final["prestructure"]
        + exploratory_structural * final["structural"]
    )

    result = frame.copy()
    result["exploratory_prestructure_score"] = exploratory_prestructure
    result["exploratory_ligandability_score"] = exploratory_ligandability
    result["exploratory_structural_score"] = exploratory_structural
    result["exploratory_final_score"] = exploratory_final
    identity = next(
        (
            name
            for name in (
                "evolutionary_group_key",
                "primary_group_id",
                "lead_cluster_id",
                "cluster_id",
            )
            if name in result.columns
        ),
        None,
    )
    if identity is None:
        raise ValueError("Ranking sensitivity requires a stable group identifier.")
    completeness = (
        pd.to_numeric(result["evidence_completeness_fraction"], errors="coerce")
        .fillna(0.0)
        .clip(0.0, 1.0)
        if "evidence_completeness_fraction" in result.columns
        else pd.Series(0.0, index=result.index)
    )
    result["_e3_completeness"] = completeness
    sort_columns = ["exploratory_final_score", "_e3_completeness", identity]
    ascending = [False, False, True]
    if preserve_gate_tier and "grant_aligned_base_pass" in result.columns:
        result["_e3_gate_tier"] = _logical_series(
            frame=result, column="grant_aligned_base_pass"
        )
        sort_columns.insert(0, "_e3_gate_tier")
        ascending.insert(0, False)
    result = result.sort_values(
        sort_columns,
        ascending=ascending,
        kind="mergesort",
    ).reset_index(drop=True)
    result.insert(0, "exploratory_rank", range(1, len(result) + 1))
    recorded_rank_name = next(
        (
            name
            for name in ("final_evolutionary_rank", "final_rank", "computational_rank")
            if name in result.columns
        ),
        None,
    )
    if recorded_rank_name is not None:
        recorded_rank = pd.to_numeric(result[recorded_rank_name], errors="coerce")
        result.insert(
            1,
            "rank_change_positive_means_moved_up",
            (recorded_rank - result["exploratory_rank"]).astype("Int64"),
        )
    keep = [
        "exploratory_rank",
        "rank_change_positive_means_moved_up",
        recorded_rank_name,
        identity,
        "primary_group_type",
        "primary_group_id",
        "lead_cluster_id",
        "boss_review_status",
        "grant_aligned_prediction_status",
        "grant_aligned_base_pass",
        "grant_aligned_final_pass",
        "final_score",
        "exploratory_final_score",
        "prestructure_score",
        "exploratory_prestructure_score",
        "ligandability_score",
        "exploratory_ligandability_score",
        "structural_score",
        "exploratory_structural_score",
        "pocket_conservation_score",
        "three_dimensional_pocket_score",
        "evidence_completeness_fraction",
    ]
    keep = [name for name in keep if name is not None and name in result.columns]
    return result.loc[:, list(dict.fromkeys(keep))]
