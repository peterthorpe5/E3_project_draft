"""Pure preparation and Plotly builders for E3 evidence visualisations."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)

CANDIDATE_METRIC_LABELS: Mapping[str, str] = {
    "final_score": "Final integrated score",
    "prestructure_score": "Pre-structure score",
    "best_prestructure_score": "Best pre-structure score",
    "mean_prestructure_score": "Mean pre-structure score",
    "structural_score": "Structural score",
    "ligandability_score": "Ligandability score",
    "pocket_conservation_score": "Pocket conservation score",
    "three_dimensional_pocket_score": "3D pocket score",
    "target_species_fraction": "Target-species fraction",
    "mandatory_species_fraction": "Mandatory-species fraction",
    "domain_species_fraction": "Domain-supported assessed-species fraction",
    "domain_annotation_coverage_fraction": "Domain evidence coverage",
    "expression_species_fraction": "Expression-supported assessed-species fraction",
    "expression_evidence_coverage_fraction": "Expression evidence coverage",
    "structural_species_fraction": "Structurally assessed species fraction",
    "evidence_completeness_fraction": "Evidence completeness",
    "minimum_druggability_score": "Minimum member druggability",
    "mean_druggability_score": "Mean member druggability",
    "mean_pocket_plddt_fraction": "Mean pocket pLDDT fraction",
    "predictor_agreement_fraction": "Pocket-predictor agreement",
    "mean_pairwise_region_overlap": "Mean pocket-region overlap",
    "mean_chemical_group_conservation": "Chemical-group conservation",
    "mean_minimum_tm_score": "Mean minimum TM-score",
    "mean_pocket_overlap_fraction": "Mean 3D pocket overlap",
    "mean_structural_residue_match_fraction": "Structural residue-match fraction",
    "mean_structural_residue_identity_fraction": "Structural residue identity",
    "mean_structural_chemical_group_conservation": (
        "Structural chemical-group conservation"
    ),
    "median_centroid_distance_angstrom": "Median pocket-centroid distance (Å)",
}

CANDIDATE_IDENTIFIER_PREFERENCE = (
    "evolutionary_group_key",
    "primary_group_id",
    "cluster_id",
    "lead_cluster_id",
)

CANDIDATE_RANK_PREFERENCE = (
    "final_evolutionary_rank",
    "final_rank",
    "prestructure_evolutionary_group_rank",
    "evolutionary_group_rank",
    "computational_rank",
    "lead_computational_rank",
)

CANDIDATE_STATUS_COLUMNS = (
    "recommendation_status",
    "grant_aligned_prediction_status",
    "grant_aligned_final_pass",
    "grant_aligned_base_pass",
    "grant_aligned_prestructure_pass",
    "lead_grant_aligned_stringent_pass",
    "conservation_status",
    "three_dimensional_alignment_status",
)

CANDIDATE_DETAIL_COLUMNS = (
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "cluster_id",
    "lead_cluster_id",
    "candidate_accessions",
    "lead_candidate_accessions",
    "target_species_present",
    "target_species_missing",
    "domain_supported_species",
    "domain_annotated_negative_species",
    "domain_unavailable_species",
    "expression_supported_species",
    "expression_assessed_negative_species",
    "expression_unavailable_species",
    "lead_expression_supported_species",
    "lead_expression_assessed_negative_species",
    "lead_expression_unavailable_species",
    "inclusion_reasons",
    "exclusion_reasons",
    "missing_evidence",
    "structural_exclusion_reasons",
)

EXPRESSION_CONTEXT_LABELS: Mapping[str, str] = {
    "organism_part": "Tissue / organism part",
    "developmental_stage": "Developmental stage",
    "condition": "Condition",
    "expression_context": "Expression context",
    "experiment_accession": "Experiment accession",
    "sample_or_condition": "Atlas sample / condition group",
}

STRUCTURAL_ALIGNMENT_COLUMN_ALIASES: Mapping[str, tuple[str, ...]] = {
    "tm_score": ("mean_minimum_tm_score", "minimum_tm_score"),
    "pocket_overlap": (
        "mean_pocket_overlap_fraction",
        "pocket_overlap_fraction",
    ),
    "centroid_distance": (
        "median_centroid_distance_angstrom",
        "centroid_distance_angstrom",
    ),
    "status": (
        "alignment_status",
        "three_dimensional_alignment_status",
        "position_alignment_status",
    ),
    "identifier": (
        "primary_group_id",
        "cluster_id",
        "mobile_accession",
        "reference_accession",
    ),
}


def candidate_identifier_column(*, available: Sequence[str]) -> str | None:
    """Choose the best stable candidate identifier from available columns.

    Args:
        available: Candidate relation columns.

    Returns:
        Preferred identifier column, or ``None``.
    """
    return next(
        (column for column in CANDIDATE_IDENTIFIER_PREFERENCE if column in available),
        None,
    )


def candidate_rank_column(*, available: Sequence[str]) -> str | None:
    """Choose the best rank column from available candidate fields.

    Args:
        available: Candidate relation columns.

    Returns:
        Preferred rank column, or ``None``.
    """
    return next(
        (column for column in CANDIDATE_RANK_PREFERENCE if column in available),
        None,
    )


def candidate_metric_columns(*, available: Sequence[str]) -> list[str]:
    """Return recognised numeric candidate metrics in scientific display order.

    Args:
        available: Candidate relation columns.

    Returns:
        Recognised metric columns.
    """
    return [column for column in CANDIDATE_METRIC_LABELS if column in available]


def candidate_colour_columns(*, available: Sequence[str]) -> list[str]:
    """Return status and metric fields suitable for candidate-point colour.

    Args:
        available: Candidate relation columns.

    Returns:
        Ordered colour-field choices.
    """
    statuses = [column for column in CANDIDATE_STATUS_COLUMNS if column in available]
    return [*statuses, *candidate_metric_columns(available=available)]


def candidate_landscape_columns(*, available: Sequence[str]) -> list[str]:
    """Return all fields required by the interactive candidate landscape.

    Args:
        available: Candidate relation columns.

    Returns:
        De-duplicated landscape fields.

    Raises:
        AppError: If no stable identifier or fewer than two metrics exist.
    """
    identifier = candidate_identifier_column(available=available)
    metrics = candidate_metric_columns(available=available)
    if identifier is None:
        raise AppError("The candidate relation has no recognised stable identifier")
    if len(metrics) < 2:
        raise AppError("The candidate relation needs at least two recognised numeric metrics")
    selected = [
        identifier,
        *CANDIDATE_RANK_PREFERENCE,
        *CANDIDATE_STATUS_COLUMNS,
        *CANDIDATE_DETAIL_COLUMNS,
        *metrics,
    ]
    return list(dict.fromkeys(column for column in selected if column in available))


def prepare_candidate_landscape(
    *,
    frame: pd.DataFrame,
    identifier_column: str,
    metric_columns: Sequence[str],
) -> pd.DataFrame:
    """Normalise a candidate frame for stable plotting and selection.

    Args:
        frame: Candidate rows collected from DuckDB.
        identifier_column: Stable identifier column.
        metric_columns: Numeric metric columns.

    Returns:
        Cleaned frame containing ``_candidate_key``.

    Raises:
        AppError: If required columns are absent or no candidates remain.
    """
    missing = sorted(
        {identifier_column, *metric_columns}.difference(frame.columns)
    )
    if missing:
        raise AppError("Candidate landscape columns are unavailable: " + ", ".join(missing))
    prepared = frame.copy()
    prepared["_candidate_key"] = prepared[identifier_column].astype("string").str.strip()
    prepared = prepared[
        prepared["_candidate_key"].notna() & prepared["_candidate_key"].ne("")
    ].copy()
    for column in metric_columns:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    prepared = prepared.drop_duplicates(subset="_candidate_key", keep="first")
    prepared = prepared.reset_index(drop=True)
    if prepared.empty:
        raise AppError("No candidate rows with a stable identifier are available")
    LOGGER.info("Prepared %d unique candidates for visualisation", len(prepared))
    return prepared


def candidate_identifiers_from_row(*, row: Mapping[str, object]) -> dict[str, object]:
    """Extract exact relation identifiers from one selected candidate row.

    Args:
        row: Selected candidate row.

    Returns:
        Non-empty candidate identifiers suitable for exact DuckDB filtering.
    """
    identifiers: dict[str, object] = {}
    for column in CANDIDATE_IDENTIFIER_PREFERENCE:
        value = row.get(column)
        if value is None or pd.isna(value) or not str(value).strip():
            continue
        identifiers[column] = value
    return identifiers


def candidate_display_labels(
    *,
    frame: pd.DataFrame,
    rank_column: str | None,
) -> dict[str, str]:
    """Build concise rank-aware labels for candidate selectors.

    Args:
        frame: Prepared candidate landscape frame.
        rank_column: Optional rank column.

    Returns:
        Mapping from candidate key to display label.
    """
    labels = {}
    for _, row in frame.iterrows():
        key = str(row["_candidate_key"])
        rank = row.get(rank_column) if rank_column is not None else None
        if rank is None or pd.isna(rank):
            labels[key] = key
        else:
            labels[key] = f"Rank {int(rank):,} — {key}"
    return labels


def build_candidate_landscape_figure(
    *,
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    colour_column: str | None,
    size_column: str | None,
) -> go.Figure:
    """Build an interactive multi-metric candidate scatter plot.

    Args:
        frame: Prepared candidate landscape frame.
        x_column: Numeric x-axis metric.
        y_column: Numeric y-axis metric.
        colour_column: Optional categorical or numeric colour field.
        size_column: Optional non-negative numeric size field.

    Returns:
        Plotly candidate-landscape figure.

    Raises:
        AppError: If selected columns are absent or contain no plottable rows.
    """
    selected = [x_column, y_column]
    selected.extend(
        column for column in (colour_column, size_column) if column is not None
    )
    missing = sorted(set(selected).difference(frame.columns))
    if missing:
        raise AppError("Candidate plot columns are unavailable: " + ", ".join(missing))
    plot_frame = frame.dropna(subset=[x_column, y_column]).copy()
    if size_column is not None:
        plot_frame[size_column] = pd.to_numeric(
            plot_frame[size_column], errors="coerce"
        ).clip(lower=0.0)
    if plot_frame.empty:
        raise AppError("No candidates have values for both selected axes")
    hover_columns = [
        column
        for column in (
            "primary_group_id",
            "cluster_id",
            "final_evolutionary_rank",
            "final_rank",
            "prestructure_evolutionary_group_rank",
            "evolutionary_group_rank",
            "recommendation_status",
            "grant_aligned_prediction_status",
            "candidate_accessions",
            "missing_evidence",
        )
        if column in plot_frame.columns
    ]
    custom_columns = [
        column
        for column in (
            "_candidate_key",
            "primary_group_id",
            "cluster_id",
            "lead_cluster_id",
        )
        if column in plot_frame.columns
    ]
    figure = px.scatter(
        plot_frame,
        x=x_column,
        y=y_column,
        color=colour_column,
        size=size_column,
        hover_name="_candidate_key",
        hover_data=hover_columns,
        custom_data=custom_columns,
        labels={
            column: CANDIDATE_METRIC_LABELS.get(column, column.replace("_", " ").title())
            for column in selected
        },
        render_mode="webgl",
    )
    figure.update_traces(
        marker={"line": {"width": 0.4, "color": "rgba(80,80,80,0.45)"}},
        selector={"mode": "markers"},
    )
    figure.update_layout(
        dragmode="select",
        legend_title_text=(
            colour_column.replace("_", " ").title() if colour_column else None
        ),
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
    )
    return figure


def selected_candidate_from_event(
    *,
    event: object,
    frame: pd.DataFrame,
) -> str | None:
    """Resolve the first candidate selected in a Streamlit Plotly event.

    Args:
        event: Streamlit selection-state object or mapping.
        frame: Prepared candidate frame in plot order.

    Returns:
        Candidate key, or ``None`` when no point is selected.
    """
    if event is None:
        return None
    selection = (
        event.get("selection", {})
        if isinstance(event, Mapping)
        else getattr(event, "selection", {})
    )
    points = (
        selection.get("points", [])
        if isinstance(selection, Mapping)
        else getattr(selection, "points", [])
    )
    if not points:
        return None
    point = points[0]
    custom = point.get("customdata") if isinstance(point, Mapping) else None
    if custom and str(custom[0]).strip():
        return str(custom[0]).strip()
    point_index = None
    if isinstance(point, Mapping):
        point_index = point.get("point_index", point.get("point_number"))
    if isinstance(point_index, int) and 0 <= point_index < len(frame):
        return str(frame.iloc[point_index]["_candidate_key"])
    return None


def prepare_expression_heatmap_cells(
    *,
    cells: pd.DataFrame,
    log_transform: bool,
) -> pd.DataFrame:
    """Prepare aggregated expression cells without conflating missing and zero.

    Args:
        cells: Output from the bounded expression heatmap query.
        log_transform: Whether to plot ``log2(1 + expression)``.

    Returns:
        Cleaned cells with display context and plot value.
    """
    required = {
        "candidate_id",
        "species",
        "context_label",
        "expression_unit",
        "median_expression",
        "context_row_count",
    }
    missing = sorted(required.difference(cells.columns))
    if missing:
        raise AppError("Expression heatmap columns are unavailable: " + ", ".join(missing))
    prepared = cells.copy()
    prepared["median_expression"] = pd.to_numeric(
        prepared["median_expression"], errors="coerce"
    )
    prepared = prepared.dropna(subset=["candidate_id", "median_expression"])
    prepared["species"] = prepared["species"].fillna("Unknown").astype(str)
    prepared["context_label"] = prepared["context_label"].fillna("Unknown").astype(str)
    prepared["display_context"] = (
        prepared["species"].str.replace("_", " ", regex=False)
        + " — "
        + prepared["context_label"]
    )
    if log_transform:
        prepared["plot_value"] = prepared["median_expression"].map(
            lambda value: math.log2(1.0 + max(0.0, float(value)))
        )
    else:
        prepared["plot_value"] = prepared["median_expression"]
    return prepared.reset_index(drop=True)


def build_expression_heatmap_figure(
    *,
    cells: pd.DataFrame,
    log_transform: bool,
) -> go.Figure:
    """Build a candidate-by-species/context expression heatmap.

    Args:
        cells: Aggregated expression cells.
        log_transform: Whether cells use ``log2(1 + expression)``.

    Returns:
        Interactive Plotly heatmap.

    Raises:
        AppError: If no expression cells are available.
    """
    prepared = prepare_expression_heatmap_cells(
        cells=cells,
        log_transform=log_transform,
    )
    if prepared.empty:
        raise AppError("No mapped expression contexts are available for the selection")
    row_order = list(dict.fromkeys(prepared["candidate_id"].astype(str)))
    column_order = list(dict.fromkeys(prepared["display_context"].astype(str)))
    value_lookup = {
        (str(row.candidate_id), str(row.display_context)): float(row.plot_value)
        for row in prepared.itertuples()
    }
    raw_lookup = {
        (str(row.candidate_id), str(row.display_context)): float(row.median_expression)
        for row in prepared.itertuples()
    }
    count_lookup = {
        (str(row.candidate_id), str(row.display_context)): int(row.context_row_count)
        for row in prepared.itertuples()
    }
    z_values = [
        [value_lookup.get((candidate, context)) for context in column_order]
        for candidate in row_order
    ]
    custom_values = [
        [
            [
                raw_lookup.get((candidate, context)),
                count_lookup.get((candidate, context), 0),
            ]
            for context in column_order
        ]
        for candidate in row_order
    ]
    unit = str(prepared["expression_unit"].iloc[0])
    colour_title = f"log2(1 + {unit})" if log_transform else unit
    figure = go.Figure(
        data=go.Heatmap(
            z=z_values,
            x=column_order,
            y=row_order,
            customdata=custom_values,
            colorscale="Viridis",
            colorbar={"title": colour_title},
            hovertemplate=(
                "Candidate: %{y}<br>Species / context: %{x}<br>"
                f"Median {unit}: %{{customdata[0]:.4g}}<br>"
                "Contributing rows: %{customdata[1]}<extra></extra>"
            ),
            hoverongaps=False,
        )
    )
    figure.update_layout(
        xaxis={"title": "Species and biological context", "tickangle": -45},
        yaxis={"title": "Candidate group", "autorange": "reversed"},
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
    )
    return figure


def prepare_species_tissue_profile(
    *,
    rows: pd.DataFrame,
    log_transform: bool,
) -> pd.DataFrame:
    """Aggregate all mapped tissues into one linked profile per species.

    Args:
        rows: Exact candidate Expression Atlas context rows.
        log_transform: Whether to plot ``log2(1 + expression)``.

    Returns:
        Species-by-tissue profile points with provenance counts and ranges.
    """
    required = {"species_column", "organism_part", "expression_value"}
    missing = sorted(required.difference(rows.columns))
    if missing:
        raise AppError("Species/tissue profile columns are unavailable: " + ", ".join(missing))
    prepared = rows.copy()
    prepared["expression_value"] = pd.to_numeric(
        prepared["expression_value"], errors="coerce"
    )
    prepared = prepared.dropna(subset=["expression_value"])
    prepared["species"] = (
        prepared["species_column"].fillna("Unknown").astype(str)
    )
    prepared["tissue"] = prepared["organism_part"].fillna("").astype(str).str.strip()
    if "expression_context" in prepared.columns:
        fallback = prepared["expression_context"].fillna("Unknown").astype(str)
        prepared.loc[prepared["tissue"].eq(""), "tissue"] = fallback
    prepared.loc[prepared["tissue"].eq(""), "tissue"] = "Unknown"
    grouped = (
        prepared.groupby(["species", "tissue"], dropna=False)["expression_value"]
        .agg(
            median_expression="median",
            minimum_expression="min",
            maximum_expression="max",
            context_row_count="size",
        )
        .reset_index()
    )
    if "member_accession" in prepared.columns:
        members = (
            prepared.groupby(["species", "tissue"], dropna=False)["member_accession"]
            .nunique()
            .rename("mapped_member_count")
            .reset_index()
        )
        grouped = grouped.merge(members, on=["species", "tissue"], how="left")
    else:
        grouped["mapped_member_count"] = 0
    if "expression_positive" in prepared.columns:
        positive = prepared.assign(
            _positive=prepared["expression_positive"].fillna(False).astype(bool)
        )
        fractions = (
            positive.groupby(["species", "tissue"], dropna=False)["_positive"]
            .mean()
            .rename("positive_context_fraction")
            .reset_index()
        )
        grouped = grouped.merge(fractions, on=["species", "tissue"], how="left")
    else:
        grouped["positive_context_fraction"] = pd.NA
    source_columns = {
        "plot_value": "median_expression",
        "plot_minimum": "minimum_expression",
        "plot_maximum": "maximum_expression",
    }
    for target, source in source_columns.items():
        if log_transform:
            grouped[target] = grouped[source].map(
                lambda value: math.log2(1.0 + max(0.0, float(value)))
            )
        else:
            grouped[target] = grouped[source].astype(float)
    grouped["error_minus"] = grouped["plot_value"] - grouped["plot_minimum"]
    grouped["error_plus"] = grouped["plot_maximum"] - grouped["plot_value"]
    return grouped.sort_values(["species", "tissue"]).reset_index(drop=True)


def prepare_species_tissue_summary(
    *,
    summary: pd.DataFrame,
    log_transform: bool,
) -> pd.DataFrame:
    """Prepare complete database-aggregated species/tissue profile cells.

    Args:
        summary: Complete post-aggregation species/tissue rows from DuckDB.
        log_transform: Whether to plot ``log2(1 + expression)``.

    Returns:
        Numerically normalised profile cells with plot values and error ranges.

    Raises:
        AppError: If required aggregate fields are absent.
    """
    required = {
        "species",
        "tissue",
        "median_expression",
        "minimum_expression",
        "maximum_expression",
        "context_row_count",
        "mapped_member_count",
        "positive_context_fraction",
    }
    missing = sorted(required.difference(summary.columns))
    if missing:
        raise AppError(
            "Species/tissue summary columns are unavailable: " + ", ".join(missing)
        )
    prepared = summary.copy()
    numeric_columns = (
        "median_expression",
        "minimum_expression",
        "maximum_expression",
        "context_row_count",
        "mapped_member_count",
        "positive_context_fraction",
    )
    for column in numeric_columns:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    prepared = prepared.dropna(subset=["median_expression"])
    prepared["species"] = prepared["species"].fillna("Unknown").astype(str)
    prepared["tissue"] = prepared["tissue"].fillna("Unknown").astype(str)
    source_columns = {
        "plot_value": "median_expression",
        "plot_minimum": "minimum_expression",
        "plot_maximum": "maximum_expression",
    }
    for target, source in source_columns.items():
        if log_transform:
            prepared[target] = prepared[source].map(
                lambda value: math.log2(1.0 + max(0.0, float(value)))
            )
        else:
            prepared[target] = prepared[source].astype(float)
    prepared["error_minus"] = prepared["plot_value"] - prepared["plot_minimum"]
    prepared["error_plus"] = prepared["plot_maximum"] - prepared["plot_value"]
    return prepared.sort_values(["species", "tissue"]).reset_index(drop=True)


def build_species_tissue_profile_figure(
    *,
    profile: pd.DataFrame,
    expression_unit: str,
    log_transform: bool,
) -> go.Figure:
    """Build faceted tissue-expression profiles for every mapped species.

    Args:
        profile: Output from :func:`prepare_species_tissue_profile`.
        expression_unit: Exact expression unit displayed.
        log_transform: Whether values use ``log2(1 + expression)``.

    Returns:
        Interactive Plotly faceted point profile.

    Raises:
        AppError: If the profile is empty.
    """
    if profile.empty:
        raise AppError("No tissue-annotated expression rows are available")
    y_label = (
        f"log2(1 + median {expression_unit})"
        if log_transform
        else f"Median {expression_unit}"
    )
    figure = px.scatter(
        profile,
        x="tissue",
        y="plot_value",
        facet_col="species",
        facet_col_wrap=3,
        error_y="error_plus",
        error_y_minus="error_minus",
        size="context_row_count",
        hover_name="tissue",
        hover_data={
            "median_expression": ":.4g",
            "minimum_expression": ":.4g",
            "maximum_expression": ":.4g",
            "context_row_count": True,
            "mapped_member_count": True,
            "positive_context_fraction": ":.3f",
            "plot_value": False,
            "error_plus": False,
            "error_minus": False,
        },
        labels={"tissue": "Tissue / organism part", "plot_value": y_label},
    )
    figure.update_traces(marker={"opacity": 0.78})
    figure.for_each_annotation(
        lambda annotation: annotation.update(
            text=annotation.text.replace("species=", "").replace("_", " ")
        )
    )
    figure.update_xaxes(tickangle=-45, matches=None)
    species_count = max(1, int(profile["species"].nunique()))
    figure_height = min(2000, max(600, math.ceil(species_count / 3) * 320))
    figure.update_layout(
        showlegend=False,
        height=figure_height,
        margin={"l": 20, "r": 20, "t": 35, "b": 20},
    )
    return figure


def prepare_volcano_frame(
    *,
    rows: pd.DataFrame,
    effect_threshold: float,
    significance_threshold: float,
) -> pd.DataFrame:
    """Classify statistically valid differential-expression rows.

    Args:
        rows: Standardised differential-expression rows.
        effect_threshold: Absolute log2-effect threshold.
        significance_threshold: Adjusted-P/FDR/Q-value threshold.

    Returns:
        Classified rows containing ``minus_log10_significance`` and ``direction``.

    Raises:
        AppError: If thresholds or required columns are invalid.
    """
    if effect_threshold < 0:
        raise AppError("The volcano effect threshold must be non-negative")
    if not 0 < significance_threshold <= 1:
        raise AppError("The volcano significance threshold must be within (0, 1]")
    required = {"label", "effect_size", "significance_value"}
    missing = sorted(required.difference(rows.columns))
    if missing:
        raise AppError("Volcano columns are unavailable: " + ", ".join(missing))
    prepared = rows.copy()
    prepared["effect_size"] = pd.to_numeric(prepared["effect_size"], errors="coerce")
    prepared["significance_value"] = pd.to_numeric(
        prepared["significance_value"], errors="coerce"
    )
    prepared = prepared[
        prepared["effect_size"].notna()
        & prepared["significance_value"].gt(0.0)
        & prepared["significance_value"].le(1.0)
    ].copy()
    prepared["minus_log10_significance"] = -prepared["significance_value"].map(
        math.log10
    )
    prepared["direction"] = "Not significant"
    significant = prepared["significance_value"].le(significance_threshold)
    prepared.loc[
        significant & prepared["effect_size"].ge(effect_threshold), "direction"
    ] = "Higher"
    prepared.loc[
        significant & prepared["effect_size"].le(-effect_threshold), "direction"
    ] = "Lower"
    return prepared.reset_index(drop=True)


def build_volcano_figure(
    *,
    rows: pd.DataFrame,
    effect_threshold: float,
    significance_threshold: float,
    significance_label: str,
) -> go.Figure:
    """Build a volcano plot from a real effect-size/significance relation.

    Args:
        rows: Standardised differential-expression rows.
        effect_threshold: Absolute log2-effect threshold.
        significance_threshold: Adjusted-P/FDR/Q-value threshold.
        significance_label: Source significance column name.

    Returns:
        Interactive Plotly volcano figure.
    """
    prepared = prepare_volcano_frame(
        rows=rows,
        effect_threshold=effect_threshold,
        significance_threshold=significance_threshold,
    )
    figure = px.scatter(
        prepared,
        x="effect_size",
        y="minus_log10_significance",
        color="direction",
        hover_name="label",
        category_orders={"direction": ["Higher", "Lower", "Not significant"]},
        labels={
            "effect_size": "log2 fold change",
            "minus_log10_significance": f"-log10({significance_label})",
        },
        render_mode="webgl",
    )
    figure.add_vline(x=effect_threshold, line_dash="dash")
    figure.add_vline(x=-effect_threshold, line_dash="dash")
    figure.add_hline(y=-math.log10(significance_threshold), line_dash="dash")
    figure.update_layout(margin={"l": 20, "r": 20, "t": 20, "b": 20})
    return figure


def structural_alignment_plot_columns(*, available: Sequence[str]) -> list[str]:
    """Return the source columns required for the 3D alignment evidence map.

    Args:
        available: Columns in one structural-alignment relation.

    Returns:
        Ordered available columns. An empty list means that the relation lacks
        either the TM-score or pocket-overlap axis.
    """
    selected: list[str] = []
    for role, aliases in STRUCTURAL_ALIGNMENT_COLUMN_ALIASES.items():
        match = next((column for column in aliases if column in available), None)
        if role in {"tm_score", "pocket_overlap"} and match is None:
            return []
        if match is not None and match not in selected:
            selected.append(match)
    for column in (
        "cluster_id",
        "primary_group_type",
        "primary_group_id",
        "reference_accession",
        "mobile_accession",
        "alignment_tool",
        "position_alignment_status",
        "alignment_status",
        "mean_structural_residue_match_fraction",
        "mean_structural_chemical_group_conservation",
    ):
        if column in available and column not in selected:
            selected.append(column)
    return selected


def prepare_structural_alignment_frame(*, frame: pd.DataFrame) -> pd.DataFrame:
    """Standardise summary or pairwise 3D-alignment evidence for plotting.

    Args:
        frame: Bounded structural-alignment source rows.

    Returns:
        Copy containing standardised private plot columns.

    Raises:
        AppError: If the two required metrics are absent or contain no usable
            paired values.
    """
    available = list(frame.columns)
    selected = structural_alignment_plot_columns(available=available)
    if not selected:
        raise AppError(
            "The selected 3D alignment relation lacks paired TM-score and "
            "pocket-overlap values"
        )

    def selected_alias(role: str) -> str | None:
        """Return the first available column for one standard plot role."""
        return next(
            (
                column
                for column in STRUCTURAL_ALIGNMENT_COLUMN_ALIASES[role]
                if column in available
            ),
            None,
        )

    prepared = frame.copy()
    tm_column = selected_alias("tm_score")
    overlap_column = selected_alias("pocket_overlap")
    if tm_column is None or overlap_column is None:
        raise AppError("The 3D alignment axes could not be resolved")
    prepared["_tm_score"] = pd.to_numeric(
        prepared[tm_column], errors="coerce"
    )
    prepared["_pocket_overlap"] = pd.to_numeric(
        prepared[overlap_column], errors="coerce"
    )
    centroid_column = selected_alias("centroid_distance")
    prepared["_centroid_distance"] = (
        pd.to_numeric(prepared[centroid_column], errors="coerce")
        if centroid_column is not None
        else pd.NA
    )
    status_column = selected_alias("status")
    prepared["_alignment_status"] = (
        prepared[status_column].fillna("UNCLASSIFIED").astype(str)
        if status_column is not None
        else "UNCLASSIFIED"
    )
    identifier_column = selected_alias("identifier")
    prepared["_alignment_identifier"] = (
        prepared[identifier_column].fillna("Unidentified row").astype(str)
        if identifier_column is not None
        else pd.Series(
            [f"Alignment row {index + 1}" for index in range(len(prepared))],
            index=prepared.index,
        )
    )
    prepared = prepared[
        prepared["_tm_score"].notna()
        & prepared["_pocket_overlap"].notna()
    ].copy()
    if prepared.empty:
        raise AppError("No paired 3D alignment values are available to plot")
    return prepared.reset_index(drop=True)


def build_structural_alignment_figure(*, frame: pd.DataFrame) -> go.Figure:
    """Build an interactive TM-score/pocket-overlap alignment evidence map.

    Args:
        frame: Bounded summary or pairwise alignment rows.

    Returns:
        Plotly scatter plot with recorded same-position threshold lines.
    """
    prepared = prepare_structural_alignment_frame(frame=frame)
    hover_data: dict[str, object] = {
        "_tm_score": ":.3f",
        "_pocket_overlap": ":.3f",
        "_centroid_distance": ":.3f",
        "_alignment_status": False,
        "_alignment_identifier": False,
    }
    for column in (
        "cluster_id",
        "primary_group_id",
        "reference_accession",
        "mobile_accession",
        "alignment_tool",
        "position_alignment_status",
    ):
        if column in prepared.columns:
            hover_data[column] = True
    figure = px.scatter(
        prepared,
        x="_tm_score",
        y="_pocket_overlap",
        color="_alignment_status",
        hover_name="_alignment_identifier",
        hover_data=hover_data,
        labels={
            "_tm_score": "Minimum TM-score",
            "_pocket_overlap": "3D pocket-overlap fraction",
            "_centroid_distance": "Pocket-centroid distance (Å)",
            "_alignment_status": "Alignment status",
        },
        render_mode="webgl",
    )
    figure.add_vline(x=0.5, line_dash="dash", annotation_text="TM = 0.50")
    figure.add_hline(
        y=0.5,
        line_dash="dash",
        annotation_text="Overlap = 0.50",
    )
    figure.update_xaxes(range=[0, 1])
    figure.update_yaxes(range=[0, 1])
    figure.update_layout(
        legend_title_text="Alignment status",
        margin={"l": 20, "r": 20, "t": 35, "b": 20},
    )
    return figure
