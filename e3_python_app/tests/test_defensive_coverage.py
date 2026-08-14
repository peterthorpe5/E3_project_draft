"""Focused tests for defensive application branches in the release gate."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from e3app import exports
from e3app.data import (
    collect_candidate_evidence,
    collect_candidate_landscape,
    collect_differential_expression,
    collect_expression_heatmap,
    collect_expression_profile_rows,
    distinct_text_values,
    filter_expression_context,
    open_read_only,
)
from e3app.errors import AppError
from e3app.ranking import (
    DEFAULT_RANKING_WEIGHTS,
    _logical_series,
    _numeric_series,
    normalise_ranking_weights,
    recompute_exploratory_ranking,
)
from e3app.unified_search import (
    collect_unified_search,
    parse_search_terms,
    summarise_unified_search,
)


def test_data_collectors_reject_unsafe_empty_and_incompatible_requests(
    resource_db: Path,
) -> None:
    """Every bounded DuckDB collector fails explicitly for invalid requests."""
    with open_read_only(path=resource_db) as connection:
        with pytest.raises(AppError, match="at least one candidate landscape"):
            collect_candidate_landscape(
                connection=connection,
                relation="candidate_master_results",
                selected_columns=(),
            )
        with pytest.raises(AppError, match="distinct values"):
            distinct_text_values(
                connection=connection,
                relation="candidates",
                column="accession",
                maximum_values=0,
            )
        with pytest.raises(AppError, match="one expression column"):
            filter_expression_context(
                connection=connection,
                relation="candidate_expression_context_summary",
                selected_columns=(),
            )
        with pytest.raises(AppError, match="candidate evidence rows"):
            collect_candidate_evidence(
                connection=connection,
                relation="candidate_expression_context_summary",
                identifiers={"primary_group_id": "N0.HOG0001"},
                maximum_rows=0,
            )
        with pytest.raises(AppError, match="heatmap cells"):
            collect_expression_heatmap(
                connection=connection,
                relation="candidate_expression_context_summary",
                candidate_column="primary_group_id",
                candidate_ids=("N0.HOG0001",),
                context_column="organism_part",
                expression_unit="TPM",
                maximum_cells=0,
            )
        with pytest.raises(AppError, match="fields are unavailable"):
            collect_expression_heatmap(
                connection=connection,
                relation="candidate_expression_context_summary",
                candidate_column="missing_candidate",
                candidate_ids=("N0.HOG0001",),
                context_column="organism_part",
                expression_unit="TPM",
            )
        with pytest.raises(AppError, match="Select one expression unit"):
            collect_expression_heatmap(
                connection=connection,
                relation="candidate_expression_context_summary",
                candidate_column="primary_group_id",
                candidate_ids=("N0.HOG0001",),
                context_column="organism_part",
                expression_unit=" ",
            )
        with pytest.raises(AppError, match="Select one expression unit"):
            collect_expression_profile_rows(
                connection=connection,
                relation="candidate_expression_context_summary",
                candidate_column="primary_group_id",
                candidate_id="N0.HOG0001",
                expression_unit=" ",
            )
        with pytest.raises(AppError, match="profile rows"):
            collect_expression_profile_rows(
                connection=connection,
                relation="candidate_expression_context_summary",
                candidate_column="primary_group_id",
                candidate_id="N0.HOG0001",
                expression_unit="TPM",
                maximum_rows=0,
            )
        with pytest.raises(AppError, match="fields are unavailable"):
            collect_expression_profile_rows(
                connection=connection,
                relation="candidate_expression_context_summary",
                candidate_column="missing_candidate",
                candidate_id="N0.HOG0001",
                expression_unit="TPM",
            )
        with pytest.raises(AppError, match="differential-expression rows"):
            collect_differential_expression(
                connection=connection,
                capability={
                    "relation": "candidates",
                    "effect_column": "score",
                    "significance_column": "score",
                    "label_column": "accession",
                },
                maximum_rows=0,
            )
        with pytest.raises(AppError, match="columns are unavailable"):
            collect_differential_expression(
                connection=connection,
                capability={
                    "relation": "candidates",
                    "effect_column": "score",
                    "significance_column": "missing_significance",
                    "label_column": "accession",
                },
            )


def test_fasta_and_display_exports_reject_malformed_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Table, FASTA and PDF exporters cover every documented validation path."""
    with pytest.raises(ValueError, match="non-empty names"):
        exports.dataframe_display_formats(frame=pd.DataFrame(columns=[""]))
    with pytest.raises(TypeError, match="pandas DataFrame"):
        exports.dataframe_to_fasta_bytes(
            frame=[],  # type: ignore[arg-type]
            identifier_column="id",
            sequence_column="sequence",
        )
    for invalid_width in (True, 0):
        with pytest.raises(ValueError, match="positive integer"):
            exports.dataframe_to_fasta_bytes(
                frame=pd.DataFrame(data={"id": ["x"], "sequence": ["AA"]}),
                identifier_column="id",
                sequence_column="sequence",
                line_width=invalid_width,
            )
    with pytest.raises(ValueError, match="non-empty names"):
        exports.dataframe_to_fasta_bytes(
            frame=pd.DataFrame(data={"": ["x"], "sequence": ["AA"]}),
            identifier_column="",
            sequence_column="sequence",
        )
    with pytest.raises(ValueError, match="missing columns"):
        exports.dataframe_to_fasta_bytes(
            frame=pd.DataFrame(data={"id": ["x"]}),
            identifier_column="id",
            sequence_column="sequence",
        )
    with pytest.raises(ValueError, match="has no identifier"):
        exports.dataframe_to_fasta_bytes(
            frame=pd.DataFrame(data={"id": [pd.NA], "sequence": ["AA"]}),
            identifier_column="id",
            sequence_column="sequence",
        )
    with pytest.raises(ValueError, match="has no sequence"):
        exports.dataframe_to_fasta_bytes(
            frame=pd.DataFrame(data={"id": ["x"], "sequence": [""]}),
            identifier_column="id",
            sequence_column="sequence",
        )
    with pytest.raises(ValueError, match="at least one sequence"):
        exports.dataframe_to_fasta_bytes(
            frame=pd.DataFrame(columns=["id", "sequence"]),
            identifier_column="id",
            sequence_column="sequence",
        )
    payload = exports.dataframe_to_fasta_bytes(
        frame=pd.DataFrame(
            data={"id": ["x"], "sequence": ["AA"], "description": [""]}
        ),
        identifier_column="id",
        sequence_column="sequence",
        description_columns=("description",),
    )
    assert payload == b">x\nAA\n"

    import plotly.io as plotly_io

    def fail_renderer(*args: object, **kwargs: object) -> bytes:
        """Simulate an unavailable or incompatible Kaleido renderer."""
        raise ValueError("renderer unavailable")

    monkeypatch.setattr(plotly_io, "to_image", fail_renderer)
    with pytest.raises(RuntimeError, match="requires the packaged Kaleido"):
        exports.plotly_figure_to_pdf_bytes(figure={"data": []})


def test_ranking_sensitivity_validates_types_fields_and_fallbacks() -> None:
    """Exploratory ranking covers type, range and optional-column branches."""
    with pytest.raises(TypeError, match="real numbers"):
        normalise_ranking_weights(
            weights={"a": True, "b": 0.5},
            expected=("a", "b"),
        )
    with pytest.raises(ValueError, match="between 0 and 1"):
        normalise_ranking_weights(
            weights={"a": 1.1, "b": 0.5},
            expected=("a", "b"),
        )
    with pytest.raises(ValueError, match="requires one of"):
        _numeric_series(
            frame=pd.DataFrame(data={"other": [1]}),
            candidates=("score",),
        )
    with pytest.raises(ValueError, match="requires pass"):
        _logical_series(
            frame=pd.DataFrame(data={"other": [1]}),
            column="pass",
        )
    parsed = _logical_series(
        frame=pd.DataFrame(data={"pass": ["yes", "no", "PASS"]}),
        column="pass",
    )
    assert parsed.tolist() == [True, False, True]
    with pytest.raises(TypeError, match="pandas DataFrame"):
        recompute_exploratory_ranking(
            frame=[],  # type: ignore[arg-type]
            prestructure_weights=DEFAULT_RANKING_WEIGHTS["prestructure"],
            ligandability_weights=DEFAULT_RANKING_WEIGHTS["ligandability"],
            structural_weights=DEFAULT_RANKING_WEIGHTS["structural"],
            final_weights=DEFAULT_RANKING_WEIGHTS["final"],
        )
    empty = recompute_exploratory_ranking(
        frame=pd.DataFrame(),
        prestructure_weights=DEFAULT_RANKING_WEIGHTS["prestructure"],
        ligandability_weights=DEFAULT_RANKING_WEIGHTS["ligandability"],
        structural_weights=DEFAULT_RANKING_WEIGHTS["structural"],
        final_weights=DEFAULT_RANKING_WEIGHTS["final"],
    )
    assert empty.empty
    with pytest.raises(TypeError, match="3D refinement weight"):
        recompute_exploratory_ranking(
            frame=pd.DataFrame(data={"unused": [1]}),
            prestructure_weights=DEFAULT_RANKING_WEIGHTS["prestructure"],
            ligandability_weights=DEFAULT_RANKING_WEIGHTS["ligandability"],
            structural_weights=DEFAULT_RANKING_WEIGHTS["structural"],
            final_weights=DEFAULT_RANKING_WEIGHTS["final"],
            three_dimensional_weight=True,
        )

    source = pd.DataFrame(
        data={
            "evolutionary_group_key": ["HOG:A"],
            "lead_discovery_score": [1.0],
            "lead_orthology_score": [1.0],
            "lead_domain_score": [1.0],
            "lead_expression_score": [1.0],
            "minimum_druggability_score": [0.5],
            "mean_pocket_plddt_fraction": [0.8],
            "all_assessed_members_pass_mapping": [True],
            "predictor_agreement_fraction": [1.0],
            "pocket_conservation_score": [0.7],
            "three_dimensional_pocket_score": [0.9],
        }
    )
    fallback = recompute_exploratory_ranking(
        frame=source,
        prestructure_weights=DEFAULT_RANKING_WEIGHTS["prestructure"],
        ligandability_weights=DEFAULT_RANKING_WEIGHTS["ligandability"],
        structural_weights=DEFAULT_RANKING_WEIGHTS["structural"],
        final_weights=DEFAULT_RANKING_WEIGHTS["final"],
        preserve_gate_tier=False,
    )
    assert fallback["evolutionary_group_key"].tolist() == ["HOG:A"]
    assert "rank_change_positive_means_moved_up" not in fallback.columns
    with pytest.raises(ValueError, match="stable group identifier"):
        recompute_exploratory_ranking(
            frame=source.drop(columns="evolutionary_group_key"),
            prestructure_weights=DEFAULT_RANKING_WEIGHTS["prestructure"],
            ligandability_weights=DEFAULT_RANKING_WEIGHTS["ligandability"],
            structural_weights=DEFAULT_RANKING_WEIGHTS["structural"],
            final_weights=DEFAULT_RANKING_WEIGHTS["final"],
            preserve_gate_tier=False,
        )


def test_unified_search_validates_remaining_limits_and_empty_summary(
    resource_db: Path,
) -> None:
    """Search parsing and collection reject unsafe limits and empty summaries."""
    with pytest.raises(AppError, match="maximum_terms"):
        parse_search_terms(value="x", maximum_terms=0)
    with pytest.raises(AppError, match="must be text"):
        parse_search_terms(value=1)  # type: ignore[arg-type]
    with open_read_only(path=resource_db) as connection:
        with pytest.raises(AppError, match="at most 50"):
            collect_unified_search(
                connection=connection,
                search_terms=tuple(f"term_{index}" for index in range(51)),
            )
        with pytest.raises(AppError, match="maximum_total_rows"):
            collect_unified_search(
                connection=connection,
                search_terms=("Q9SA03",),
                maximum_total_rows=0,
            )
    empty = summarise_unified_search(
        matches=pd.DataFrame(
            columns=("_search_order", "_search_term", "_relation")
        )
    )
    assert empty.empty
    assert empty.columns.tolist() == [
        "search_order",
        "search_term",
        "relation",
        "matched_rows",
    ]
