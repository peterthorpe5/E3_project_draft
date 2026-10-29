"""Conservation displays preserve thresholds, absent evidence and original ranks."""

import copy
import json

import pytest
from streamlit.testing.v1 import AppTest

from pocket_workbench import ui
from pocket_workbench.conservation_review import (
    conservation_document,
    fit_quality,
    pocket_pair_rows,
    pocket_review,
    review_thresholds,
)
from pocket_workbench.core import load_project


@pytest.fixture
def saved_pair(project):
    """Load a computed synthetic fit and its saved original rank-one pair."""
    data = load_project(root=project)
    result = json.loads((project / data["comparisons"][0]["result_path"]).read_text())
    match = next(
        m
        for m in result["pocket_matches"]
        if m["reference_pocket"] == m["mobile_pocket"] == 1
    )
    return data, result, match


def test_fit_quality_preserves_zeroes_missing_scores_and_input_denominators(saved_pair):
    """RMSD and coverage retain their distinct meanings; missing TM is not zero."""
    _, result, _ = saved_pair
    result.update(
        rmsd=0,
        reference_coverage=0.27,
        mobile_coverage=0.5,
        reference_fit_residues=120,
        mobile_fit_residues=65,
    )
    quality = fit_quality(result=result)
    assert quality["rmsd"] == 0
    assert quality["minimum_tm"] is None and quality["fold_supported"] is None
    assert quality["reference_coverage"] == 0.27
    assert quality["reference_fit_residues"] == 120
    result.update(tm_reference=0.208, tm_mobile=0.3)
    assert fit_quality(result=result)["fold_supported"] is False
    result.update(tm_reference=0)
    assert fit_quality(result=result)["minimum_tm"] == 0
    result.update(rmsd=-1, reference_coverage=1.5, aligned_atoms=1.5)
    quality = fit_quality(result=result)
    assert (
        quality["rmsd"]
        is quality["reference_coverage"]
        is quality["aligned_atoms"]
        is None
    )


def test_thresholds_distinguish_legacy_defaults_from_invalid_recorded_values(
    saved_pair,
):
    """Legacy compatibility is explicit; invalid saved thresholds are not repaired."""
    _, result, _ = saved_pair
    thresholds, inherited = review_thresholds(result=result)
    assert thresholds["max_centroid"] == 8 and not inherited
    result["settings"] = {"min_overlap": None, "radius": -1, "min_tm": True}
    thresholds, inherited = review_thresholds(result=result)
    assert (
        thresholds["min_overlap"]
        is thresholds["radius"]
        is thresholds["min_tm"]
        is None
    )
    assert "min_chemical" in inherited and "min_overlap" not in inherited
    result["settings"] = "bad legacy metadata"
    assert review_thresholds(result=result)[0]["min_chemical"] == 0.6


def test_geometric_agreement_does_not_invent_fold_or_conservation_support(saved_pair):
    """The Kabsch fixture has excellent positional evidence but no TM-score."""
    _, result, match = saved_pair
    before = copy.deepcopy((result, match))
    review = pocket_review(result=result, match=match)
    assert review["position_supported"] is True
    assert review["fold_supported"] is None and review["conservation_supported"] is None
    assert review["matched_pairs"] == 8
    assert 0 <= review["mean_ca_distance"] < 0.001
    assert review["maximum_ca_distance"] >= review["median_ca_distance"]
    assert (result, match) == before


@pytest.mark.parametrize(
    ("position", "fold", "fraction", "chemical", "expected"),
    [
        (True, True, 0.8, 0.9, True),
        (False, True, 0.8, 0.9, False),
        (True, False, 0.8, 0.9, False),
        (True, True, 0.49, 0.9, False),
        (True, True, 0.8, 0.59, False),
        (True, None, 0.8, 0.9, None),
        (True, True, None, 0.9, None),
        (True, True, 0.8, None, None),
    ],
)
def test_conservation_requires_all_recorded_evidence_and_thresholds(
    saved_pair, position, fold, fraction, chemical, expected
):
    """Position, fold, matched lining and chemical agreement remain distinct."""
    _, result, match = saved_pair
    match.update(
        position_supported=position,
        fold_supported=fold,
        mutual_match_fraction=fraction,
        chemical_group_conservation=chemical,
    )
    assert (
        pocket_review(result=result, match=match)["conservation_supported"] is expected
    )


def test_missing_and_empty_residue_distance_records_are_different(saved_pair):
    """Unavailable old-schema distances cannot appear as zero matched pairs."""
    _, result, match = saved_pair
    del match["residue_correspondences"]
    missing = pocket_review(result=result, match=match)
    assert missing["distance_status"] == "not_supplied"
    assert missing["matched_pairs"] is None and missing["mean_ca_distance"] is None
    match["residue_correspondences"] = []
    empty = pocket_review(result=result, match=match)
    assert empty["distance_status"] == "recorded_empty" and empty["matched_pairs"] == 0
    match["residue_correspondences"] = [
        {"ca_distance": None},
        {"ca_distance": -1},
        {"ca_distance": float("nan")},
        {"ca_distance": 1.5},
    ]
    review = pocket_review(result=result, match=match)
    assert review["matched_pairs"] == 4 and review["valid_distance_pairs"] == 1
    assert review["omitted_distances"] == 3 and review["mean_ca_distance"] == 1.5
    assert pocket_review(result=result, match=None)["position_supported"] is None


def test_threshold_check_inconsistency_is_visible_without_rewriting_saved_flags(
    saved_pair,
):
    """Inconsistent saved flags must not silently replace displayed evidence."""
    _, result, match = saved_pair
    match.update(centroid_distance=20, position_supported=True)
    review = pocket_review(result=result, match=match)
    assert review["position_supported"] is True
    assert review["checks"][1]["passes"] is False
    assert review["consistency_notes"]
    match["centroid_distance"] = -1
    assert (
        pocket_review(result=result, match=match)["metrics"]["centroid_distance"]
        is None
    )


def test_pair_rows_preserve_original_rank_one_and_unknown_ranks(saved_pair):
    """The best overlap alternative never displaces the primary rank-one pair."""
    data, result, match = saved_pair
    match["symmetric_overlap"] = 0.2
    other = next(
        m
        for m in result["pocket_matches"]
        if m["reference_pocket"] == 1 and m["mobile_pocket"] == 2
    )
    other["symmetric_overlap"] = 0.95
    rows = pocket_pair_rows(result=result, pockets=data["pockets"])
    assert rows[0]["original_rank_one_pair"] is True
    assert rows[0]["symmetric_overlap"] == 0.2
    assert (
        next(r for r in rows if r["reference_pocket"] == 1 and r["mobile_pocket"] == 2)[
            "mobile_rank"
        ]
        == 2
    )
    result["pocket_matches"] = [dict(match, reference_rank=None, mobile_rank=None)]
    row = pocket_pair_rows(result=result, pockets=[])[0]
    assert row["reference_rank"] is row["mobile_rank"] is None
    assert row["original_rank_one_pair"] is False


def test_conservation_html_is_inert_and_handles_no_tested_pairs(saved_pair):
    """The portable page contains inert JSON without third-party script fetches."""
    data, result, _ = saved_pair
    result["reference"] = "</script><script>bad()</script>"
    document = conservation_document(result=result, pockets=data["pockets"])
    assert result["reference"] not in document
    assert '<script src="http' not in document
    payload = json.loads(
        document.split('<script id="conservation-data" type="application/json">')[
            1
        ].split("</script>")[0]
    )
    assert payload["reference"] == result["reference"]
    result["pocket_matches"] = []
    assert '"pairs": []' in conservation_document(result=result, pockets=[])


def test_conservation_page_and_exact_alternative_pair_jump(
    project, monkeypatch, tmp_path
):
    """The selected alternative opens the same pocket pair in the saved 3D fit."""
    monkeypatch.setenv("POCKET_WORKBENCH_RESOURCE", str(project))
    monkeypatch.setenv("POCKET_WORKBENCH_WORKSPACE", str(tmp_path / "workspace"))
    app = AppTest.from_file(ui.__file__, default_timeout=20).run()
    app.sidebar.radio[0].set_value("Pocket conservation").run()
    assert not app.exception and not app.error
    assert app.session_state["conservation_pair"] == (1, 1)
    assert any("Not assessed" in e.value for e in app.info)
    app.selectbox(key="conservation_pair").set_value((1, 2)).run()
    assert any("alternative pocket pair" in e.value for e in app.info)
    next(
        b for b in app.button if b.label == "Open this pocket pair in 3D"
    ).click().run()
    assert not app.exception and not app.error
    assert app.sidebar.radio[0].value == "Compare structures"
    selection = app.selectbox(key="comparison_pocket_pair")
    assert "compared rank 2" in selection.format_func(selection.value)
    app.button(key="comparison_conservation").click().run()
    assert app.sidebar.radio[0].value == "Pocket conservation"
    assert app.session_state["conservation_pair"] == (1, 2)
