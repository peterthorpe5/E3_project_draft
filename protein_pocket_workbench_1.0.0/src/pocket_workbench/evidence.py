"""Rank-preserving structural evidence summaries for generic protein projects."""

from __future__ import annotations

import json
from pathlib import Path

from .core import inside


def comparison_audit(*, root: Path, data: dict, top_k: int = 5) -> list[dict]:
    """Keep rank-one conclusions separate from alternative-pocket sensitivity.

    Args:
        root: Project directory.
        data: Imported evidence and completed comparison index.
        top_k: Largest original rank admitted to the sensitivity view.

    Returns:
        One explicit scope/engine/conclusion record per saved comparison.
    """
    ranks = {
        (p["sample_id"], int(p["pocket_id"])): p.get("review_rank")
        for p in data["pockets"]
        if p["method"] == "fpocket"
    }
    rows = []
    for comparison in data["comparisons"]:
        result = json.loads(
            inside(root=root, relative=comparison["result_path"]).read_text()
        )
        matches = result.get("pocket_matches", [])
        selected = []
        strict = None
        for match in matches:
            a = ranks.get((result["reference"], match["reference_pocket"]))
            b = ranks.get((result["mobile"], match["mobile_pocket"]))
            if a == b == 1:
                strict = match
            if a == 1 and b and b <= top_k:
                selected.append(match)
        supported = [m for m in selected if m["position_supported"]]
        best = max(selected, key=lambda m: m.get("symmetric_overlap", 0), default=None)
        minimum_tm = (
            min(result["tm_reference"], result["tm_mobile"])
            if result.get("tm_reference") is not None
            and result.get("tm_mobile") is not None
            else None
        )
        rows.append(
            {
                "comparison_id": result["comparison_id"],
                "reference": result["reference"],
                "mobile": result["mobile"],
                "engine": result["engine"],
                "scope": result.get("scope", "unreported"),
                "settings": json.dumps(result.get("settings", {}), sort_keys=True),
                "status": result["status"],
                "error": result.get("error"),
                "rank_one_position": (
                    "supported"
                    if strict and strict["position_supported"]
                    else "not_supported" if strict else "not_assessed"
                ),
                "rank_one_position_and_fold": (
                    bool(strict["position_supported"] and strict["fold_supported"])
                    if strict and strict.get("fold_supported") is not None
                    else None
                ),
                "rank_one_conserved": (
                    bool(
                        strict["position_supported"]
                        and strict["fold_supported"]
                        and strict["mutual_match_fraction"]
                        >= result.get("settings", {}).get("min_residue_match", 0.5)
                        and strict["chemical_group_conservation"]
                        >= result.get("settings", {}).get("min_chemical", 0.6)
                    )
                    if strict
                    and strict.get("fold_supported") is not None
                    and strict.get("chemical_group_conservation") is not None
                    else None
                ),
                "top_k": top_k,
                "top_k_tested_pairs": len(selected),
                "top_k_supported_pairs": len(supported),
                "top_k_fold_supported_member_pockets": sorted(
                    {
                        m["mobile_pocket"]
                        for m in supported
                        if m.get("fold_supported") is True
                    }
                ),
                "top_k_position": (
                    "supported"
                    if supported
                    else "no_supported_tested_pair" if selected else "not_assessed"
                ),
                "alternative_pocket_support": (
                    True
                    if supported and strict and not strict["position_supported"]
                    else False if strict else None
                ),
                "rmsd": result.get("rmsd"),
                "minimum_tm": minimum_tm,
                "best_tested_overlap": best["symmetric_overlap"] if best else None,
                "reference_coverage": result.get("reference_coverage"),
                "mobile_coverage": result.get("mobile_coverage"),
            }
        )
    return rows


def aligner_agreement(*, rows: list[dict]) -> list[dict]:
    """Require USalign and TMalign to support the same ranked member pocket.

    Args:
        rows: Single-aligner audit records with complete settings and fit scope.

    Returns:
        Paired-aligner decisions; incomplete tool evidence remains unassessed.
    """
    groups = {}
    for row in rows:
        if row["engine"] not in {"usalign", "tmalign"}:
            continue
        settings = json.loads(row["settings"])
        settings.pop("engine", None)
        key = (row["reference"], row["mobile"], json.dumps(settings, sort_keys=True))
        groups.setdefault(key, {})[row["engine"]] = row
    records = []
    for (reference, mobile, settings), tools in groups.items():
        complete = set(tools) == {"usalign", "tmalign"}
        strict = [r["rank_one_position_and_fold"] for r in tools.values()]
        conserved = [r["rank_one_conserved"] for r in tools.values()]
        assessed = complete and all(v is not None for v in strict)
        same_pockets = (
            sorted(
                set.intersection(
                    *[
                        set(r["top_k_fold_supported_member_pockets"])
                        for r in tools.values()
                    ]
                )
            )
            if complete
            else []
        )
        records.append(
            {
                "reference": reference,
                "mobile": mobile,
                "settings": settings,
                "available_aligners": ";".join(sorted(tools)),
                "rank_one_both_aligners": all(strict) if assessed else None,
                "rank_one_conserved_both_aligners": (
                    all(conserved)
                    if complete and all(v is not None for v in conserved)
                    else None
                ),
                "top_k_same_member_pockets": ";".join(map(str, same_pockets)),
                "top_k_both_aligners": (
                    bool(same_pockets)
                    if complete and all(r["top_k_tested_pairs"] for r in tools.values())
                    else None
                ),
            }
        )
    return records
