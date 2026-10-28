"""Display summaries must retain the identity and limits of saved evidence."""

import copy
import json
import math

import numpy as np
import pytest

from pocket_workbench.core import WorkbenchError, load_project
from pocket_workbench.evidence import comparison_audit
from pocket_workbench.presentation import (
    analysis_label,
    dataset_summary,
    evidence_figure,
    finite_number,
    model_labels,
    pocket_rank,
    ranked_pockets,
    similarity_figure,
)


@pytest.mark.parametrize(
    "value", [None, True, False, np.bool_(True), "", "bad", float("nan"), float("inf")]
)
def test_missing_numbers_are_never_zero(value):
    """Unassessed scores must not appear as numerical evidence in a plot."""
    assert finite_number(value=value) is None
    assert finite_number(value=0) == 0


def test_short_labels_keep_models_regions_and_collisions_distinct():
    """Short display names retain replicate/range identity and full lookup keys."""
    names = [
        "fold_np_848668_19102026_model_0",
        "fold_np_848668_20102026_model_0",
        "fold_np_848668_19102026_model_1__a123b456_r002",
    ]
    labels = model_labels(identifiers=names)
    assert set(labels) == set(names)
    assert len(set(labels.values())) == 3
    assert labels[names[0]] == "np_848668 · model 0"
    assert "region 2" in labels[names[2]]
    assert model_labels(identifiers=list(reversed(names))) == labels


def test_analysis_labels_explain_scope_without_fabricating_ranges():
    """Full-model, region and sequence selections have different interpretations."""
    settings = {"fit_scope": "global", "min_plddt": 70}
    assert "Independent confidence" in analysis_label(
        engine="usalign", settings=settings
    )
    assert "Retained region" in analysis_label(
        engine="usalign", settings=json.dumps(settings), scope="cleaned_region"
    )
    label = analysis_label(engine="tmalign", settings={"start": None, "end": None})
    assert "None" not in label
    assert "Sequence-paired" in label
    assert "Reference range 10–50" in analysis_label(
        engine="tmalign", settings={"start": 10, "end": 50}
    )
    assert "Sequence-paired" in analysis_label(engine="usalign", settings="broken")


def test_pocket_sort_uses_original_rank_and_leaves_unknowns_unknown():
    """Filtering and sorting cannot promote a cavity ID into an assigned rank."""
    pockets = [
        {"sample_id": "A", "pocket_id": 1, "review_rank": 9},
        {"sample_id": "A", "pocket_id": 12, "review_rank": 3},
        {"sample_id": "A", "pocket_id": 2},
    ]
    original = copy.deepcopy(pockets)
    assert [p["pocket_id"] for p in ranked_pockets(pockets=pockets)] == [12, 1, 2]
    assert pockets == original
    assert pocket_rank(pocket=pockets[2]) is None
    assert pocket_rank(pocket={"review_rank": -1, "rank": 4}) == 4
    assert pocket_rank(pocket={"review_rank": 1.5, "pocket_id": 1}) is None
    assert pocket_rank(pocket={"review_rank": True}) is None


def test_dataset_summary_counts_fasta_only_and_available_confidence(project):
    """Missing confidence does not lower a median or conceal FASTA-only records."""
    data = load_project(root=project)
    data["sequences"]["FASTA_only"] = "ACDE"
    data["models"][0]["mean_plddt"] = None
    data["models"][1]["mean_plddt"] = 30
    data["models"][2]["mean_plddt"] = 90
    summary = dataset_summary(data=data)
    assert summary["models"] == 3
    assert summary["fasta_only_sequences"] == 1
    assert summary["models_with_confidence"] == 2
    assert summary["median_model_plddt"] == 60
    assert summary["models_mean_below_50"] == 1


def test_similarity_matrix_retains_direction_missing_values_and_hover_ids():
    """A directional fit is never mirrored into a cell that was not measured."""
    names = ["fold_np_848668_19102026_model_0", "fold_np_848668_19102026_model_1"]
    fit = dict(
        reference=names[0],
        mobile=names[1],
        status="complete",
        rmsd=2.3,
        tm_reference=0,
        tm_mobile=0.4,
    )
    figure = similarity_figure(fits=[fit], metric="Minimum TM-score")
    assert figure.data[0].z[0][1] == 0
    assert math.isnan(figure.data[0].z[1][0])
    assert math.isnan(figure.data[0].z[0][0])
    assert list(figure.data[0].customdata[0][1]) == names
    assert "model 0" in figure.data[0].x[0]
    assert figure.layout.height >= 500
    fit["tm_reference"] = None
    assert math.isnan(
        similarity_figure(fits=[fit], metric="Minimum TM-score").data[0].z[0][1]
    )
    with pytest.raises(WorkbenchError):
        similarity_figure(fits=[fit], metric="Invented score")


def test_evidence_plot_uses_the_metric_and_decision_for_the_selected_pair():
    """An alternative's overlap must not be coloured with the rank-one decision."""
    row = dict(
        reference="A",
        mobile="B",
        scope="full_model",
        minimum_tm=0.6,
        rank_one_overlap=0.2,
        rank_one_position="not_supported",
        best_tested_overlap=0.9,
        best_tested_position_supported=True,
        settings=json.dumps({"min_tm": 0.55, "min_overlap": 0.65}),
    )
    strict, omitted = evidence_figure(rows=[row], view="rank_one")
    assert omitted == 0
    assert list(strict.data[0].y) == [0.2]
    assert strict.data[0].name == "Position rule not met"
    alternative, _ = evidence_figure(rows=[row], view="alternatives")
    assert list(alternative.data[0].y) == [0.9]
    assert alternative.data[0].name == "Position rule met"
    assert strict.layout.shapes[0].x0 == 0.55
    assert strict.layout.shapes[1].y0 == 0.65
    row.update(minimum_tm=None, settings="broken")
    empty, omitted = evidence_figure(rows=[row], view="rank_one")
    assert omitted == 1
    assert not empty.layout.shapes
    with pytest.raises(WorkbenchError):
        evidence_figure(rows=[row], view="invented")


def test_audit_exposes_strict_and_alternative_values_without_changing_ranks(project):
    """New plot fields derive from distinct saved pairs, preserving rank one."""
    data = load_project(root=project)
    path = project / data["comparisons"][0]["result_path"]
    saved = json.loads(path.read_text())
    strict = next(
        m
        for m in saved["pocket_matches"]
        if m["reference_pocket"] == m["mobile_pocket"] == 1
    )
    other = next(
        m
        for m in saved["pocket_matches"]
        if m["reference_pocket"] == 1 and m["mobile_pocket"] == 2
    )
    strict.update(symmetric_overlap=0.2, position_supported=False)
    other.update(symmetric_overlap=0.9, position_supported=True)
    path.write_text(json.dumps(saved))
    ranks = copy.deepcopy(data["pockets"])
    row = comparison_audit(root=project, data=data, top_k=2)[0]
    assert row["rank_one_overlap"] == 0.2
    assert row["rank_one_position"] == "not_supported"
    assert row["best_tested_overlap"] == 0.9
    assert row["best_tested_member_rank"] == 2
    assert row["best_tested_position_supported"] is True
    assert data["pockets"] == ranks
