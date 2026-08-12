"""Unit tests for candidate and expression visualisation preparation."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from e3app.errors import AppError
from e3app.visualisations import (
    build_candidate_landscape_figure,
    build_expression_heatmap_figure,
    build_final_gate_druggability_boxplot,
    build_species_tissue_profile_figure,
    build_structural_alignment_figure,
    build_volcano_figure,
    candidate_colour_columns,
    candidate_display_labels,
    candidate_identifier_column,
    candidate_identifiers_from_row,
    candidate_landscape_columns,
    candidate_metric_columns,
    candidate_rank_column,
    prepare_candidate_landscape,
    prepare_expression_heatmap_cells,
    prepare_final_gate_druggability_distribution,
    prepare_species_tissue_profile,
    prepare_species_tissue_summary,
    prepare_structural_alignment_frame,
    prepare_volcano_frame,
    selected_candidate_from_event,
    structural_alignment_plot_columns,
)


@pytest.fixture
def candidate_frame() -> pd.DataFrame:
    """Return two representative evolutionary candidate rows."""
    return pd.DataFrame(
        {
            "final_rank": [1, 2],
            "primary_group_id": ["N0.HOG1", "N0.HOG2"],
            "cluster_id": ["cluster_1", "cluster_2"],
            "candidate_accessions": ["Q1;Q2", "Q3"],
            "final_score": [0.9, 0.7],
            "expression_species_fraction": [1.0, 0.8],
            "target_species_fraction": [1.0, 0.9],
            "grant_aligned_final_pass": [True, False],
            "expression_supported_species": ["A;B", "A"],
            "expression_unavailable_species": ["", "B"],
        }
    )


def test_candidate_column_selection_and_preparation(
    candidate_frame: pd.DataFrame,
) -> None:
    """Candidate field choices are ordered, safe and numerically normalised."""
    available = list(candidate_frame.columns)
    assert candidate_identifier_column(available=available) == "primary_group_id"
    assert candidate_rank_column(available=available) == "final_rank"
    assert candidate_metric_columns(available=available) == [
        "final_score",
        "target_species_fraction",
        "expression_species_fraction",
    ]
    assert candidate_colour_columns(available=available)[0] == (
        "grant_aligned_final_pass"
    )
    selected = candidate_landscape_columns(available=available)
    assert {"primary_group_id", "final_score"}.issubset(selected)
    prepared = prepare_candidate_landscape(
        frame=candidate_frame,
        identifier_column="primary_group_id",
        metric_columns=("final_score", "expression_species_fraction"),
    )
    assert prepared["_candidate_key"].tolist() == ["N0.HOG1", "N0.HOG2"]
    labels = candidate_display_labels(frame=prepared, rank_column="final_rank")
    assert labels["N0.HOG1"] == "Rank 1 — N0.HOG1"
    identifiers = candidate_identifiers_from_row(row=prepared.iloc[0])
    assert identifiers == {
        "primary_group_id": "N0.HOG1",
        "cluster_id": "cluster_1",
    }
    with pytest.raises(AppError, match="stable identifier"):
        candidate_landscape_columns(available=("final_score", "prestructure_score"))
    with pytest.raises(AppError, match="at least two"):
        candidate_landscape_columns(
            available=("primary_group_id", "final_score")
        )

    evolutionary_available = ["final_evolutionary_rank", *available]
    assert candidate_rank_column(available=evolutionary_available) == (
        "final_evolutionary_rank"
    )


def test_candidate_landscape_figure_and_selection(
    candidate_frame: pd.DataFrame,
) -> None:
    """Plotly points retain a stable candidate key for linked selection."""
    prepared = prepare_candidate_landscape(
        frame=candidate_frame,
        identifier_column="primary_group_id",
        metric_columns=(
            "final_score",
            "expression_species_fraction",
            "target_species_fraction",
        ),
    )
    figure = build_candidate_landscape_figure(
        frame=prepared,
        x_column="expression_species_fraction",
        y_column="final_score",
        colour_column="grant_aligned_final_pass",
        size_column="target_species_fraction",
    )
    assert isinstance(figure, go.Figure)
    selected = selected_candidate_from_event(
        event={"selection": {"points": [{"customdata": ["N0.HOG2"]}]}},
        frame=prepared,
    )
    assert selected == "N0.HOG2"
    fallback = selected_candidate_from_event(
        event={"selection": {"points": [{"point_index": 0}]}},
        frame=prepared,
    )
    assert fallback == "N0.HOG1"
    assert selected_candidate_from_event(event=None, frame=prepared) is None
    with pytest.raises(AppError, match="both selected axes"):
        build_candidate_landscape_figure(
            frame=prepared.assign(final_score=pd.NA),
            x_column="expression_species_fraction",
            y_column="final_score",
            colour_column=None,
            size_column=None,
        )


def test_expression_heatmap_preparation_and_figure() -> None:
    """Heatmaps retain absent cells and expose source medians and counts."""
    cells = pd.DataFrame(
        {
            "candidate_id": ["N0.HOG1", "N0.HOG1", "N0.HOG2"],
            "species": ["Zea_mays", "Zea_mays", "Zea_mays"],
            "context_label": ["leaf", "root", "leaf"],
            "expression_unit": ["TPM", "TPM", "TPM"],
            "median_expression": [7.0, 0.0, 3.0],
            "context_row_count": [3, 2, 4],
            "mapped_member_count": [1, 1, 2],
            "positive_context_fraction": [1.0, 0.0, 0.75],
        }
    )
    prepared = prepare_expression_heatmap_cells(
        cells=cells,
        log_transform=True,
    )
    assert prepared["plot_value"].tolist() == [3.0, 0.0, 2.0]
    assert prepared.iloc[0]["display_context"] == "Zea mays — leaf"
    figure = build_expression_heatmap_figure(cells=cells, log_transform=True)
    assert isinstance(figure, go.Figure)
    assert figure.data[0].z[1][1] is None
    with pytest.raises(AppError, match="heatmap columns"):
        prepare_expression_heatmap_cells(
            cells=pd.DataFrame({"candidate_id": ["N0.HOG1"]}),
            log_transform=False,
        )


def test_species_tissue_profile_preparation_and_figure() -> None:
    """Tissue profiles facet species and retain ranges and evidence counts."""
    rows = pd.DataFrame(
        {
            "species_column": ["Zea_mays", "Zea_mays", "Arabidopsis_thaliana"],
            "organism_part": ["leaf", "leaf", "root"],
            "expression_context": ["leaf", "leaf", "root"],
            "expression_value": [3.0, 7.0, 1.0],
            "member_accession": ["P1", "P2", "P3"],
            "expression_positive": [True, True, True],
        }
    )
    profile = prepare_species_tissue_profile(rows=rows, log_transform=True)
    maize = profile[profile["species"].eq("Zea_mays")].iloc[0]
    assert maize["median_expression"] == 5.0
    assert maize["mapped_member_count"] == 2
    figure = build_species_tissue_profile_figure(
        profile=profile,
        expression_unit="TPM",
        log_transform=True,
    )
    assert isinstance(figure, go.Figure)
    complete = prepare_species_tissue_summary(
        summary=profile.drop(
            columns=[
                "plot_value",
                "plot_minimum",
                "plot_maximum",
                "error_minus",
                "error_plus",
            ]
        ),
        log_transform=False,
    )
    assert complete["median_expression"].tolist() == [1.0, 5.0]
    transformed = prepare_species_tissue_summary(
        summary=complete.drop(
            columns=[
                "plot_value",
                "plot_minimum",
                "plot_maximum",
                "error_minus",
                "error_plus",
            ]
        ),
        log_transform=True,
    )
    assert transformed["plot_value"].tolist() == [1.0, pytest.approx(2.5849625)]
    with pytest.raises(AppError, match="summary columns"):
        prepare_species_tissue_summary(
            summary=pd.DataFrame({"species": ["Zea_mays"]}),
            log_transform=True,
        )
    with pytest.raises(AppError, match="No tissue-annotated"):
        build_species_tissue_profile_figure(
            profile=pd.DataFrame(),
            expression_unit="TPM",
            log_transform=True,
        )
    with pytest.raises(AppError, match="profile columns"):
        prepare_species_tissue_profile(
            rows=pd.DataFrame({"expression_value": [1.0]}),
            log_transform=False,
        )


def test_volcano_preparation_and_figure() -> None:
    """Volcano classification uses real effects and bounded significance values."""
    rows = pd.DataFrame(
        {
            "label": ["UP", "DOWN", "NONE", "INVALID"],
            "effect_size": [2.0, -2.0, 0.1, 1.0],
            "significance_value": [0.001, 0.01, 0.5, 0.0],
        }
    )
    prepared = prepare_volcano_frame(
        rows=rows,
        effect_threshold=1.0,
        significance_threshold=0.05,
    )
    assert prepared["direction"].tolist() == [
        "Higher",
        "Lower",
        "Not significant",
    ]
    figure = build_volcano_figure(
        rows=rows,
        effect_threshold=1.0,
        significance_threshold=0.05,
        significance_label="adjusted P value",
    )
    assert isinstance(figure, go.Figure)
    with pytest.raises(AppError, match="non-negative"):
        prepare_volcano_frame(
            rows=rows,
            effect_threshold=-1.0,
            significance_threshold=0.05,
        )
    with pytest.raises(AppError, match="within"):
        prepare_volcano_frame(
            rows=rows,
            effect_threshold=1.0,
            significance_threshold=0.0,
        )
    with pytest.raises(AppError, match="Volcano columns"):
        prepare_volcano_frame(
            rows=pd.DataFrame({"label": ["GENE"]}),
            effect_threshold=1.0,
            significance_threshold=0.05,
        )


def test_structural_alignment_evidence_map() -> None:
    """3D alignment plots accept summary fields and retain exact identifiers."""
    frame = pd.DataFrame(
        {
            "cluster_id": ["cluster_1", "cluster_2"],
            "primary_group_id": ["N0.HOG1", "N0.HOG2"],
            "alignment_status": ["SUPPORTED", "NOT_SUPPORTED"],
            "mean_minimum_tm_score": [0.9, 0.4],
            "mean_pocket_overlap_fraction": [0.8, 0.3],
            "median_centroid_distance_angstrom": [1.2, 12.0],
        }
    )
    columns = structural_alignment_plot_columns(available=list(frame.columns))
    assert "mean_minimum_tm_score" in columns
    assert "mean_pocket_overlap_fraction" in columns
    prepared = prepare_structural_alignment_frame(frame=frame)
    assert prepared["_alignment_identifier"].tolist() == [
        "N0.HOG1",
        "N0.HOG2",
    ]
    figure = build_structural_alignment_figure(frame=frame)
    assert isinstance(figure, go.Figure)
    assert len(figure.layout.shapes) == 2
    assert structural_alignment_plot_columns(available=["minimum_tm_score"]) == []
    with pytest.raises(AppError, match="paired TM-score"):
        prepare_structural_alignment_frame(
            frame=pd.DataFrame({"minimum_tm_score": [0.8]})
        )


def test_final_gate_druggability_boxplot_preparation_and_threshold_line() -> None:
    """Member distributions retain final rank and show the selected gate."""
    eligible = pd.DataFrame(
        {
            "final_evolutionary_rank": [2, 1, 3],
            "primary_group_id": ["N0.HOG2", "N0.HOG1", "N0.HOG3"],
            "lead_cluster_id": ["cluster_2", "cluster_1", "cluster_3"],
        }
    )
    scores = pd.DataFrame(
        {
            "cluster_id": ["cluster_1", "cluster_1", "cluster_2", "ignored"],
            "member_accession": ["P1", "P2", "P3", "P4"],
            "species": ["A", "B", "A", "C"],
            "pocket_number": [1, 1, 2, 1],
            "druggability_score": [0.7, 0.5, 0.325, 0.9],
        }
    )
    prepared, truncated = prepare_final_gate_druggability_distribution(
        scores=scores,
        eligible_groups=eligible,
        max_groups=2,
    )
    assert truncated
    assert prepared["cluster_id"].tolist() == [
        "cluster_1",
        "cluster_1",
        "cluster_2",
    ]
    assert prepared["group_label"].drop_duplicates().tolist() == [
        "N0.HOG1 · cluster_1",
        "N0.HOG2 · cluster_2",
    ]
    figure = build_final_gate_druggability_boxplot(
        frame=prepared,
        threshold=0.5,
    )
    assert isinstance(figure, go.Figure)
    assert figure.data[0].type == "box"
    assert len(figure.layout.shapes) == 1
    assert figure.layout.shapes[0].x0 == 0.5
    with pytest.raises(AppError, match="number from 0 to 1"):
        build_final_gate_druggability_boxplot(frame=prepared, threshold=1.1)


def test_final_gate_druggability_plot_validation_and_fallback_labels() -> None:
    """Sparse compatibility rows receive safe labels and invalid inputs fail."""
    sparse_scores = pd.DataFrame(
        {
            "cluster_id": ["cluster_1", "cluster_other"],
            "member_accession": [None, "P2"],
            "druggability_score": [0.4, 0.9],
        }
    )
    sparse_groups = pd.DataFrame({"cluster_id": ["cluster_1"]})
    prepared, truncated = prepare_final_gate_druggability_distribution(
        scores=sparse_scores,
        eligible_groups=sparse_groups,
    )
    assert not truncated
    assert prepared["group_label"].tolist() == ["cluster_1"]
    assert prepared["member_accession"].tolist() == ["Unknown member"]
    assert prepared["species"].tolist() == ["Unknown"]
    figure = build_final_gate_druggability_boxplot(
        frame=prepared,
        threshold=0.4,
    )
    assert figure.data[0].type == "box"
    assert "pocket_number" not in figure.data[0].hovertemplate

    empty, _ = prepare_final_gate_druggability_distribution(
        scores=sparse_scores,
        eligible_groups=pd.DataFrame({"cluster_id": ["absent"]}),
    )
    assert empty.empty
    with pytest.raises(AppError, match="pandas data frames"):
        prepare_final_gate_druggability_distribution(  # type: ignore[arg-type]
            scores=[],
            eligible_groups=sparse_groups,
        )
    with pytest.raises(AppError, match="between 1 and 100"):
        prepare_final_gate_druggability_distribution(
            scores=sparse_scores,
            eligible_groups=sparse_groups,
            max_groups=0,
        )
    with pytest.raises(AppError, match="rows are missing"):
        prepare_final_gate_druggability_distribution(
            scores=pd.DataFrame({"cluster_id": ["cluster_1"]}),
            eligible_groups=sparse_groups,
        )
    with pytest.raises(AppError, match="lead cluster"):
        prepare_final_gate_druggability_distribution(
            scores=sparse_scores,
            eligible_groups=pd.DataFrame({"primary_group_id": ["G1"]}),
        )
    with pytest.raises(AppError, match="number from 0 to 1"):
        build_final_gate_druggability_boxplot(
            frame=prepared,
            threshold=True,  # type: ignore[arg-type]
        )
    with pytest.raises(AppError, match="required plot fields"):
        build_final_gate_druggability_boxplot(
            frame=pd.DataFrame({"group_label": ["G1"]}),
            threshold=0.5,
        )
    with pytest.raises(AppError, match="No member-level"):
        build_final_gate_druggability_boxplot(
            frame=prepared.iloc[0:0],
            threshold=0.5,
        )
