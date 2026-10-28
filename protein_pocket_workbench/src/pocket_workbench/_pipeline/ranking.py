"""Transparent per-model cavity ranking without a synthetic combined score."""

from __future__ import annotations


def rank_cavities(*, pockets: list[dict], matches: list[dict]) -> list[dict]:
    """Rank fpocket cavities by their P2Rank rescore or a labelled fallback.

    Args:
        pockets: Parsed and annotated pockets for one model.
        matches: Independent P2Rank versus fpocket residue overlaps.

    Returns:
        fpocket cavities with one-based review_rank and explicit ranking_basis.
        Confidence is displayed alongside scores, never multiplied into them.
    """
    cavities = [dict(pocket) for pocket in pockets if pocket["method"] == "fpocket"]
    rescored = {
        pocket["fpocket_pocket_id"]: pocket
        for pocket in pockets
        if pocket["method"] == "p2rank_rescore"
    }
    complete = bool(cavities) and set(rescored) == {p["pocket_id"] for p in cavities}
    for pocket in cavities:
        rescore = rescored.get(pocket["pocket_id"], {})
        overlaps = [
            row for row in matches if row["fpocket_pocket_id"] == pocket["pocket_id"]
        ]
        best = max(overlaps, key=lambda row: row["jaccard"], default={})
        pocket.update(
            {
                "ranking_basis": "p2rank_rescore"
                if complete
                else "fpocket_druggability",
                "p2rank_rescore_rank": rescore.get("rank"),
                "p2rank_rescore_score": rescore.get("score"),
                "p2rank_rescore_probability": rescore.get("probability"),
                "independent_p2rank_match": best.get("p2rank_pocket_id"),
                "match_jaccard": best.get("jaccard"),
            }
        )
    if complete:
        cavities.sort(key=lambda row: row["p2rank_rescore_rank"])
    else:
        cavities.sort(key=lambda row: (-row["druggability_score"], row["pocket_id"]))
    for rank, pocket in enumerate(cavities, start=1):
        pocket["review_rank"] = rank
    return cavities
