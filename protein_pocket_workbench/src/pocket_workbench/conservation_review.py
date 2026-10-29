"""Readable conservation and alignment evidence derived from existing saved fits."""

from __future__ import annotations

import logging
from dataclasses import asdict
from statistics import mean, median

from .core import ComparisonSettings
from .presentation import finite_number, pocket_rank
from .viewers import json_for_html, viewer_asset

LOGGER = logging.getLogger(__name__)
LEGACY_DEFAULTS = asdict(ComparisonSettings())
DECISIONS = {
    "supported": "Meets recorded rule",
    "not_supported": "Does not meet recorded rule",
    "not_assessed": "Not assessed",
}


def review_thresholds(*, result: dict) -> tuple[dict, list[str]]:
    """Read saved thresholds and explicitly identify established legacy defaults.

    Args:
        result: Existing comparison JSON, never modified.

    Returns:
        Numeric thresholds and names supplied by legacy workbench defaults.
        Invalid explicitly recorded values remain None rather than being repaired.
    """
    defaults = LEGACY_DEFAULTS
    settings = result.get("settings", {})
    settings = settings if isinstance(settings, dict) else {}
    thresholds, inherited = {}, []
    for key in (
        "radius",
        "max_centroid",
        "min_overlap",
        "min_tm",
        "min_residue_match",
        "min_chemical",
        "min_plddt",
    ):
        raw = settings.get(key) if key in settings else defaults[key]
        if key not in settings:
            inherited.append(key)
        value = finite_number(value=raw)
        maximum = 100 if key == "min_plddt" else 1
        valid = value is not None and (
            value > 0 if key in {"radius", "max_centroid"} else 0 <= value <= maximum
        )
        thresholds[key] = value if valid else None
        if not valid:
            LOGGER.warning("Saved comparison has an invalid %s threshold", key)
    return thresholds, inherited


def fit_quality(*, result: dict) -> dict:
    """Summarise fit quality without treating a short-fragment RMSD as global support.

    Args:
        result: Saved comparison result.

    Returns:
        Original engine/scope, numerical quality evidence and a labelled TM rule.
    """
    thresholds, inherited = review_thresholds(result=result)
    values = {
        key: finite_number(value=result.get(key))
        for key in (
            "rmsd",
            "aligned_atoms",
            "tm_reference",
            "tm_mobile",
            "reference_coverage",
            "mobile_coverage",
            "reference_fit_residues",
            "mobile_fit_residues",
        )
    }
    for key, value in values.items():
        valid = value is None or (
            0 <= value <= 1
            if key in {
                "tm_reference",
                "tm_mobile",
                "reference_coverage",
                "mobile_coverage",
            }
            else value >= 0 and (key == "rmsd" or value.is_integer())
        )
        if not valid:
            LOGGER.warning("Invalid saved fit-quality metric: %s", key)
            values[key] = None
    minimum = (
        min(values["tm_reference"], values["tm_mobile"])
        if values["tm_reference"] is not None and values["tm_mobile"] is not None
        else None
    )
    fold = (
        minimum >= thresholds["min_tm"]
        if minimum is not None and thresholds["min_tm"] is not None
        else None
    )
    return dict(
        values,
        minimum_tm=minimum,
        fold_supported=fold,
        engine=result.get("engine", "unreported"),
        scope=result.get("scope", "unreported"),
        thresholds=thresholds,
        legacy_thresholds=inherited,
    )


def pocket_review(*, result: dict, match: dict | None) -> dict:
    """Separate pocket position, lining conservation and the supporting fit evidence.

    Args:
        result: Saved comparison with its original thresholds and quality metrics.
        match: One actual saved pocket pair, or None if the pair was not tested.

    Returns:
        Explicit decisions, threshold checks, raw metrics and matched-CA distance
        summaries. No score, rank, coordinate, transform or saved flag is changed.
    """
    fit = fit_quality(result=result)
    thresholds = fit["thresholds"]
    match = match or {}
    numbers = {
        key: finite_number(value=match.get(key))
        for key in (
            "centroid_distance",
            "symmetric_overlap",
            "reference_fraction",
            "mobile_fraction",
            "mutual_match_fraction",
            "sequence_jaccard",
            "residue_identity_fraction",
            "chemical_group_conservation",
            "reference_mapping_fraction",
            "mobile_mapping_fraction",
        )
    }
    for key, value in numbers.items():
        if value is not None and not (
            value >= 0 if key == "centroid_distance" else 0 <= value <= 1
        ):
            LOGGER.warning("Invalid saved pocket metric: %s", key)
            numbers[key] = None
    position = match.get("position_supported")
    fold = match.get("fold_supported")
    position = position if type(position) is bool else None
    fold = fold if type(fold) is bool else None
    lining_available = all(
        value is not None
        for value in (
            numbers["mutual_match_fraction"],
            numbers["chemical_group_conservation"],
            thresholds["min_residue_match"],
            thresholds["min_chemical"],
        )
    )
    conserved = (
        bool(
            position
            and fold
            and numbers["mutual_match_fraction"] >= thresholds["min_residue_match"]
            and numbers["chemical_group_conservation"] >= thresholds["min_chemical"]
        )
        if position is not None and fold is not None and lining_available
        else None
    )
    checks = []
    mapping = match.get("complete_mapping")
    mapping = mapping if type(mapping) is bool else None
    checks.append(
        {
            "criterion": "Complete lining-residue mapping",
            "value": mapping,
            "rule": "Required",
            "threshold": True,
            "passes": mapping,
        }
    )
    for title, value, operator, threshold in (
        (
            "Pocket centroid distance (Å)",
            numbers["centroid_distance"],
            "≤",
            thresholds["max_centroid"],
        ),
        (
            "Symmetric CA overlap",
            numbers["symmetric_overlap"],
            "≥",
            thresholds["min_overlap"],
        ),
        ("Minimum TM-score", fit["minimum_tm"], "≥", thresholds["min_tm"]),
        (
            "Mutual-nearest lining match fraction",
            numbers["mutual_match_fraction"],
            "≥",
            thresholds["min_residue_match"],
        ),
        (
            "Chemical-group match fraction",
            numbers["chemical_group_conservation"],
            "≥",
            thresholds["min_chemical"],
        ),
    ):
        passes = (
            (value <= threshold if operator == "≤" else value >= threshold)
            if value is not None and threshold is not None
            else None
        )
        checks.append(
            {
                "criterion": title,
                "value": value,
                "rule": operator,
                "threshold": threshold,
                "passes": passes,
            }
        )
    consistent = []
    position_checks = [r["passes"] for r in checks[:3]]
    if position is not None and all(v is not None for v in position_checks):
        if position != all(position_checks):
            consistent.append(
                "The saved position flag differs from its displayed metric/threshold"
                " checks."
            )
    if (
        fold is not None
        and fit["fold_supported"] is not None
        and fold != fit["fold_supported"]
    ):
        consistent.append(
            "The saved fold flag differs from the displayed TM-score check."
        )
    correspondences = match.get("residue_correspondences")
    rows = correspondences if isinstance(correspondences, list) else []
    distances = [
        value
        for r in rows
        if isinstance(r, dict)
        and (value := finite_number(value=r.get("ca_distance"))) is not None
        and value >= 0
    ]
    distance_status = (
        "available"
        if distances
        else (
            "recorded_empty"
            if isinstance(correspondences, list) and not rows
            else "no_valid_distances" if rows else "not_supplied"
        )
    )
    return {
        "fit": fit,
        "metrics": numbers,
        "checks": checks,
        "position_supported": position,
        "fold_supported": fold,
        "conservation_supported": conserved,
        "complete_mapping": mapping,
        "distance_status": distance_status,
        "matched_pairs": len(rows) if isinstance(correspondences, list) else None,
        "valid_distance_pairs": (
            len(distances) if isinstance(correspondences, list) else None
        ),
        "omitted_distances": (
            len(rows) - len(distances) if isinstance(correspondences, list) else None
        ),
        "mean_ca_distance": mean(distances) if distances else None,
        "median_ca_distance": median(distances) if distances else None,
        "maximum_ca_distance": max(distances) if distances else None,
        "consistency_notes": consistent,
    }


def pocket_pair_rows(*, result: dict, pockets: list[dict]) -> list[dict]:
    """Create rank-preserving comparison rows for the selected saved structural fit.

    Args:
        result: Existing complete comparison.
        pockets: Project pocket metadata used only as an explicit rank lookup.

    Returns:
        One row per saved pair, original rank-one pair first. Missing rank stays None.
    """
    ranks = {
        (p["sample_id"], p["pocket_id"]): pocket_rank(pocket=p)
        for p in pockets
        if p.get("method") == "fpocket"
    }
    rows = []
    for match in result.get("pocket_matches", []):
        review = pocket_review(result=result, match=match)
        rank_a = ranks.get((result["reference"], match["reference_pocket"]))
        rank_b = ranks.get((result["mobile"], match["mobile_pocket"]))
        rank_a = rank_a or pocket_rank(pocket={"rank": match.get("reference_rank")})
        rank_b = rank_b or pocket_rank(pocket={"rank": match.get("mobile_rank")})
        rows.append(
            {
                "reference_pocket": match["reference_pocket"],
                "mobile_pocket": match["mobile_pocket"],
                "reference_rank": rank_a,
                "mobile_rank": rank_b,
                "original_rank_one_pair": rank_a == rank_b == 1,
                "position_supported": review["position_supported"],
                "fold_supported": review["fold_supported"],
                "conservation_supported": review["conservation_supported"],
                **review["metrics"],
                "mean_ca_distance": review["mean_ca_distance"],
                "median_ca_distance": review["median_ca_distance"],
                "maximum_ca_distance": review["maximum_ca_distance"],
                "matched_pairs": review["matched_pairs"],
                "complete_mapping": review["complete_mapping"],
            }
        )
    return sorted(
        rows,
        key=lambda r: (
            not r["original_rank_one_pair"],
            -(r["symmetric_overlap"] if r["symmetric_overlap"] is not None else -1),
            (
                r["centroid_distance"]
                if r["centroid_distance"] is not None
                else float("inf")
            ),
        ),
    )


def conservation_document(*, result: dict, pockets: list[dict]) -> str:
    """Build a small offline evidence page linked to the matching saved 3D viewer.

    Args:
        result: Saved fit and all its recorded pocket-pair evidence.
        pockets: Native pocket metadata for exact ranks.

    Returns:
        Standalone evidence HTML. The neighbouring viewer.html supplies the 3D view.
    """
    rows = pocket_pair_rows(result=result, pockets=pockets)
    matches = {
        (m["reference_pocket"], m["mobile_pocket"]): m
        for m in result.get("pocket_matches", [])
    }
    payload = {
        "comparison_id": result["comparison_id"],
        "reference": result["reference"],
        "mobile": result["mobile"],
        "fit": fit_quality(result=result),
        "pairs": [
            {
                "row": row,
                "review": pocket_review(
                    result=result,
                    match=matches[(row["reference_pocket"], row["mobile_pocket"])],
                ),
                "residues": (
                    matches[(row["reference_pocket"], row["mobile_pocket"])].get(
                        "residue_correspondences", []
                    )
                ),
            }
            for row in rows
        ],
    }
    return viewer_asset(name="conservation_review.html").replace(
        "@@DATA@@", json_for_html(value=payload)
    )
