"""Grant-focused Streamlit presentation over DuckDB and portable review data."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Sequence

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from e3app.config import AppConfig, config_from_environment, validate_config
from e3app.data import (
    SECTION_SPECS,
    candidate_evidence_relations,
    collect_candidate_evidence,
    collect_candidate_landscape,
    collect_differential_expression,
    collect_expression_heatmap,
    collect_expression_profile_rows,
    collect_expression_tissue_summary,
    default_columns,
    differential_expression_relations,
    distinct_text_values,
    filter_expression_context,
    grant_overview,
    list_relations,
    open_resource,
    preview_selected_columns,
    relation_count,
    relation_columns,
    relations_for_section,
    resource_overview,
    search_accession,
    select_candidate_landscape_relation,
)
from e3app.errors import AppError
from e3app.exports import (
    dataframe_display_formats,
    dataframe_display_widths,
    render_table_downloads,
)
from e3app.glossary import SLIDER_HELP, glossary_rows, glossary_sections
from e3app.pocket_review import (
    PocketReviewBundle,
    group_choice_labels,
    prepare_pocket_review,
    read_group_html,
    read_review_html,
    selected_group_members,
    selected_group_row,
)
from e3app.ranking import (
    DEFAULT_RANKING_WEIGHTS,
    RANKING_METHODOLOGY_MARKDOWN,
    RANKING_WEIGHT_LABELS,
    recompute_exploratory_ranking,
    select_ranking_relation,
)
from e3app.thresholds import (
    LOGICAL_THRESHOLD_FIELDS,
    NUMERIC_THRESHOLD_FIELDS,
    RECORDED_MINIMUM_DRUGGABILITY_SCORE,
    ThresholdSettings,
    collect_member_druggability_scores,
    compare_final_druggability_passes,
    evaluate_thresholds,
    final_druggability_settings,
    final_druggability_source_missing_columns,
    select_threshold_relation,
    threshold_settings_from_mapping,
)
from e3app.visualisations import (
    CANDIDATE_METRIC_LABELS,
    EXPRESSION_CONTEXT_LABELS,
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
    prepare_final_gate_druggability_distribution,
    prepare_species_tissue_summary,
    selected_candidate_from_event,
    structural_alignment_plot_columns,
)
from e3app.workflow import workflow_schematic_html

LOGGER = logging.getLogger(__name__)
_WRAPPED_TAB_CSS = """
<style>
div[data-testid="stTabs"] {
    overflow: visible !important;
}
div[data-testid="stTabs"] div[role="tablist"],
div[data-testid="stTabs"] div[data-baseweb="tab-list"] {
    align-items: flex-start !important;
    display: flex !important;
    flex-wrap: wrap !important;
    height: auto !important;
    max-height: none !important;
    overflow-x: visible !important;
    overflow-y: visible !important;
    row-gap: 0.25rem;
    white-space: normal !important;
    width: 100% !important;
}
div[data-testid="stTabs"] button[role="tab"],
div[data-testid="stTabs"] button[data-baseweb="tab"],
div[data-testid="stTabs"] button[data-testid="stTab"] {
    border-bottom: 2px solid transparent;
    flex: 0 0 auto !important;
    min-height: 2.5rem;
    white-space: nowrap;
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"],
div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"],
div[data-testid="stTabs"] button[data-testid="stTab"][aria-selected="true"] {
    border-bottom-color: #ff4b4b;
}
div[data-testid="stTabs"] div[data-baseweb="tab-highlight"],
div[data-testid="stTabs"] button[aria-label*="scroll" i],
div[data-testid="stTabs"] [data-testid="stTabsScrollLeft"],
div[data-testid="stTabs"] [data-testid="stTabsScrollRight"] {
    display: none;
}
</style>
"""


def _display_dataframe(
    *,
    frame: pd.DataFrame | Sequence[dict[str, object]],
    height: int | None = None,
) -> None:
    """Display a table with concise numeric formatting and exact source values.

    Args:
        frame: Data frame or serialisable row dictionaries to display.
        height: Optional Streamlit table height in pixels.
    """
    table = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    number_formats = dataframe_display_formats(frame=table)
    column_widths = dataframe_display_widths(frame=table)
    column_config: dict[str, object] = {}
    for column in table.columns:
        column_name = str(column)
        if column_name in number_formats:
            column_config[column_name] = st.column_config.NumberColumn(
                format=number_formats[column_name],
                width=column_widths[column_name],
            )
        else:
            column_config[column_name] = st.column_config.Column(
                width=column_widths[column_name]
            )
    arguments: dict[str, object] = {
        "data": table,
        "use_container_width": True,
        "hide_index": True,
        "column_config": column_config,
    }
    arguments["height"] = 620 if height is None else height
    arguments["row_height"] = 36
    st.dataframe(**arguments)


def _render_section(
    *,
    connection: object,
    config: AppConfig,
    section: str,
    show_heading: bool = True,
) -> None:
    """Render one scientific section with independent table controls."""
    specification = SECTION_SPECS[section]
    if show_heading:
        st.subheader(str(specification["title"]))
        st.caption(str(specification["description"]))
    relations = relations_for_section(connection, section)
    if not relations:
        st.info(
            "This release does not contain a recognised relation for this section. "
            "Unavailable evidence is not interpreted as a biological negative."
        )
        return
    relation = st.selectbox(
        "Result table",
        relations,
        key=f"{section}_relation",
    )
    columns = relation_columns(connection, relation)
    selected = st.multiselect(
        "Columns to display",
        columns,
        default=default_columns(section, columns),
        key=f"{section}_columns",
        help="Every available source column remains selectable for audit and export.",
    )
    requested = st.number_input(
        "Rows to display",
        min_value=1,
        max_value=config.max_rows,
        value=min(100, config.max_rows),
        key=f"{section}_rows",
    )
    if not selected:
        st.warning("Select at least one column.")
        return
    result = preview_selected_columns(
        connection,
        relation,
        selected,
        int(requested),
    )
    _display_dataframe(frame=result)
    render_table_downloads(
        frame=result,
        file_stem=f"{section}_{relation}",
        tsv_label="Download displayed rows as TSV",
        excel_label="Download displayed rows as Excel",
        key=f"{section}_download",
    )


def _render_structural_alignment_section(
    *,
    connection: object,
    config: AppConfig,
) -> None:
    """Render an interactive 3D-alignment evidence map and complete tables."""
    specification = SECTION_SPECS["structural_alignment"]
    st.subheader(str(specification["title"]))
    st.caption(str(specification["description"]))
    st.info(
        "The interactive map combines minimum TM-score and 3D pocket overlap. "
        "Dashed lines show the recorded 0.50 thresholds; same-position support "
        "also requires a pocket-centroid distance of at most 8 Å. Hover, zoom "
        "and pan to inspect groups. Rotatable coordinate models remain in "
        "3D structures & pockets."
    )
    relations = relations_for_section(connection, "structural_alignment")
    compatible: list[tuple[str, list[str]]] = []
    for relation in relations:
        columns = structural_alignment_plot_columns(
            available=relation_columns(connection, relation)
        )
        if columns:
            compatible.append((relation, columns))
    if compatible:
        relation_names = [relation for relation, _ in compatible]
        preferred = (
            "structural_alignment_summary"
            if "structural_alignment_summary" in relation_names
            else relation_names[0]
        )
        plot_relation = st.selectbox(
            "Alignment relation to visualise",
            relation_names,
            index=relation_names.index(preferred),
            key="structural_alignment_plot_relation",
        )
        plot_columns = dict(compatible)[plot_relation]
        requested = st.number_input(
            "Maximum alignment points",
            min_value=1,
            max_value=config.max_rows,
            value=min(config.max_rows, 1972),
            key="structural_alignment_plot_rows",
        )
        plot_rows = preview_selected_columns(
            connection,
            plot_relation,
            plot_columns,
            int(requested),
        )
        figure = build_structural_alignment_figure(frame=plot_rows)
        st.plotly_chart(
            figure,
            use_container_width=True,
            key="structural_alignment_evidence_map",
        )
        with st.expander("Alignment rows behind the visualisation"):
            _display_dataframe(frame=plot_rows, height=520)
            render_table_downloads(
                frame=plot_rows,
                file_stem=f"structural_alignment_visualisation_{plot_relation}",
                tsv_label="Download plotted alignment rows as TSV",
                excel_label="Download plotted alignment rows as Excel",
                key="structural_alignment_plot_download",
            )
    else:
        st.info(
            "No structural-alignment relation contains both a TM-score and a "
            "3D pocket-overlap fraction, so the evidence map is unavailable."
        )
    st.markdown("#### Complete 3D alignment evidence tables")
    _render_section(
        connection=connection,
        config=config,
        section="structural_alignment",
        show_heading=False,
    )


def _ranking_source_columns(*, available: Sequence[str]) -> list[str]:
    """Return the bounded source columns needed by the weighting explorer."""
    preferred = (
        "final_evolutionary_rank",
        "final_rank",
        "computational_rank",
        "evolutionary_group_key",
        "primary_group_type",
        "primary_group_id",
        "lead_cluster_id",
        "cluster_id",
        "boss_review_status",
        "grant_aligned_prediction_status",
        "grant_aligned_base_pass",
        "grant_aligned_final_pass",
        "lead_discovery_score",
        "discovery_score",
        "lead_orthology_score",
        "orthology_score",
        "lead_domain_score",
        "domain_score",
        "lead_expression_score",
        "expression_score",
        "minimum_druggability_score",
        "mean_pocket_plddt_fraction",
        "all_assessed_members_pass_mapping",
        "predictor_agreement_fraction",
        "pocket_conservation_score",
        "three_dimensional_pocket_score",
        "three_dimensional_alignment_status",
        "evidence_completeness_fraction",
        "prestructure_score",
        "ligandability_score",
        "structural_score",
        "final_score",
    )
    return [column for column in preferred if column in available]


def _ranking_source_is_complete(*, columns: Sequence[str]) -> bool:
    """Return whether a relation contains all formula component families."""
    available = set(columns)
    alternatives = (
        ("lead_discovery_score", "discovery_score"),
        ("lead_orthology_score", "orthology_score"),
        ("lead_domain_score", "domain_score"),
        ("lead_expression_score", "expression_score"),
    )
    required = {
        "minimum_druggability_score",
        "mean_pocket_plddt_fraction",
        "all_assessed_members_pass_mapping",
        "predictor_agreement_fraction",
        "pocket_conservation_score",
        "three_dimensional_pocket_score",
    }
    return required.issubset(available) and all(
        any(candidate in available for candidate in family)
        for family in alternatives
    )


def _ranking_weight_sliders(*, group: str) -> dict[str, float]:
    """Render one group of raw sliders that will be normalised to sum to one."""
    defaults = DEFAULT_RANKING_WEIGHTS[group]
    labels = RANKING_WEIGHT_LABELS[group]
    columns = st.columns(2)
    values: dict[str, float] = {}
    for index, (component, default) in enumerate(defaults.items()):
        with columns[index % 2]:
            values[component] = st.slider(
                labels[component],
                min_value=0.0,
                max_value=1.0,
                value=default,
                step=0.05,
                key=f"ranking_weight_{group}_{component}",
            )
    total = sum(values.values())
    if total > 0:
        effective = ", ".join(
            f"{labels[name]} {value / total:.1%}"
            for name, value in values.items()
        )
        st.caption(f"Effective normalised weights: {effective}.")
    return values


def _reset_ranking_weights() -> None:
    """Restore every sensitivity control to the recorded production profile."""
    for group, weights in DEFAULT_RANKING_WEIGHTS.items():
        for component, value in weights.items():
            st.session_state[f"ranking_weight_{group}_{component}"] = value
    st.session_state["ranking_weight_three_dimensional"] = 0.0
    st.session_state["ranking_preserve_gate_tier"] = True


def _render_ranking_sensitivity(
    *, connection: object, config: AppConfig
) -> None:
    """Render a read-only, formula-driven weighting sensitivity explorer."""
    relation = select_ranking_relation(relation_names=list_relations(connection))
    if relation is None:
        st.info("No recognised ranking relation is available for weight sensitivity.")
        return
    available = relation_columns(connection, relation)
    if not _ranking_source_is_complete(columns=available):
        st.info(
            "This compatibility relation does not retain every component needed "
            "to recalculate the documented formulas. The explanation above still "
            "describes the recorded production ranking."
        )
        return
    selected = _ranking_source_columns(available=available)
    source_count = relation_count(connection, relation)
    row_limit = min(config.max_rows, 5000)
    frame = preview_selected_columns(
        connection,
        relation,
        selected,
        row_limit,
    )
    st.caption(
        f"Sensitivity source: `{relation}`; {len(frame):,} of "
        f"{source_count:,} rows loaded under the configured row cap."
    )
    if len(frame) < source_count:
        st.warning(
            "The exploratory rank covers only the bounded rows loaded above. "
            "Raise the application's maximum-row setting to compare the full relation."
        )
    if st.button(
        "Reset recorded ranking weights",
        key="ranking_reset_weights",
    ):
        _reset_ranking_weights()
        st.rerun()
    st.markdown("#### Pre-structure weights")
    prestructure = _ranking_weight_sliders(group="prestructure")
    st.markdown("#### Ligandability subcomponent weights")
    ligandability = _ranking_weight_sliders(group="ligandability")
    st.markdown("#### Structural-score weights")
    structural = _ranking_weight_sliders(group="structural")
    st.markdown("#### Final-score weights")
    final = _ranking_weight_sliders(group="final")
    three_dimensional = st.slider(
        "Optional 3D-refinement weight (recorded production default: 0.00)",
        min_value=0.0,
        max_value=1.0,
        value=0.0,
        step=0.05,
        key="ranking_weight_three_dimensional",
        help=(
            "Applied only to structurally assessed groups. The recorded profile "
            "used 3D agreement as a gate and did not reweight the score."
        ),
    )
    preserve_gate_tier = st.checkbox(
        "Keep the recorded hard-gate pass tier ahead of score",
        value=True,
        key="ranking_preserve_gate_tier",
        help=(
            "Recommended. Turning this off makes the sensitivity order score-only; "
            "it does not change any recorded gate field."
        ),
    )
    try:
        ranked = recompute_exploratory_ranking(
            frame=frame,
            prestructure_weights=prestructure,
            ligandability_weights=ligandability,
            structural_weights=structural,
            final_weights=final,
            three_dimensional_weight=three_dimensional,
            preserve_gate_tier=preserve_gate_tier,
        )
    except (TypeError, ValueError) as exc:
        st.warning(str(exc))
        return
    rows_to_show = st.number_input(
        "Exploratory ranked rows to display",
        min_value=1,
        max_value=max(1, min(len(ranked), 500)),
        value=max(1, min(len(ranked), 100)),
        key="ranking_rows_to_show",
    )
    _display_dataframe(frame=ranked.head(int(rows_to_show)), height=620)
    render_table_downloads(
        frame=ranked,
        file_stem="exploratory_computational_reweighting",
        tsv_label="Download exploratory ranking as TSV",
        excel_label="Download exploratory ranking as Excel",
        key="ranking_sensitivity_download",
    )


def _render_final_druggability_sensitivity(
    *,
    connection: object,
    config: AppConfig,
) -> None:
    """Render a focused sensitivity analysis for the last strict gate.

    Args:
        connection: Open read-only DuckDB connection.
        config: Validated application configuration.
    """
    st.markdown("### Sensitivity analysis: final all-members druggability gate")
    st.warning(
        "This control does not alter the authoritative recorded result. It changes "
        "only the final minimum-member druggability threshold in memory; every "
        "other recorded pre-structure and structural gate remains fixed."
    )
    st.caption(
        "The rule is inclusive: a group passes this gate when its minimum selected-"
        "pocket druggability score is greater than or equal to the selected value. "
        "The recorded production threshold is 0.50."
    )
    reset_column, _ = st.columns([1, 3])
    with reset_column:
        if st.button(
            "Reset to recorded 0.50",
            key="recommendation_druggability_reset",
        ):
            st.session_state["recommendation_druggability_threshold"] = (
                RECORDED_MINIMUM_DRUGGABILITY_SCORE
            )
    selected_threshold = st.slider(
        "Minimum member druggability required for every assessed member",
        min_value=0.0,
        max_value=1.0,
        value=RECORDED_MINIMUM_DRUGGABILITY_SCORE,
        step=0.01,
        key="recommendation_druggability_threshold",
        help=(
            "Only this one gate changes. Lower values are more permissive; higher "
            "values are more stringent. Equality passes because the rule uses ≥."
        ),
    )

    relation = select_threshold_relation(list_relations(connection))
    if relation is None:
        st.info(
            "No evolutionary-group relation is available for this focused "
            "sensitivity analysis. The recorded recommendation tables above remain "
            "available."
        )
        return
    available = relation_columns(connection, relation)
    missing = final_druggability_source_missing_columns(available)
    if missing:
        st.info(
            f"`{relation}` does not retain every field required to recalculate the "
            "complete final gate intersection. Missing: " + ", ".join(missing) + "."
        )
        return

    row_limit = min(config.max_rows, 10_000)
    selected_settings = final_druggability_settings(
        minimum_druggability_score=float(selected_threshold),
    )
    recorded_settings = final_druggability_settings(
        minimum_druggability_score=RECORDED_MINIMUM_DRUGGABILITY_SCORE,
    )
    try:
        _, selected_rows, selected_summary = evaluate_thresholds(
            connection,
            selected_settings,
            row_limit,
        )
        if float(selected_threshold) == RECORDED_MINIMUM_DRUGGABILITY_SCORE:
            recorded_rows = selected_rows.copy()
            recorded_summary = dict(selected_summary)
        else:
            _, recorded_rows, recorded_summary = evaluate_thresholds(
                connection,
                recorded_settings,
                row_limit,
            )
        selected_rows, changed_rows = compare_final_druggability_passes(
            recorded=recorded_rows,
            selected=selected_rows,
        )
    except AppError as exc:
        st.warning(str(exc))
        return

    recorded_passes = recorded_summary["pass_count"]
    selected_passes = selected_summary["pass_count"]
    difference = selected_passes - recorded_passes
    metric_one, metric_two, metric_three = st.columns(3)
    metric_one.metric("Recorded passes at 0.50", recorded_passes)
    metric_two.metric(
        f"Sensitivity passes at {selected_threshold:.2f}",
        selected_passes,
        delta=f"{difference:+d} versus recorded",
        delta_color="off",
    )
    metric_three.metric(
        "Groups changing pass status",
        len(changed_rows),
    )
    st.caption(
        f"Sensitivity source: `{relation}`. The displayed list contains groups "
        f"passing every fixed recorded gate when minimum member druggability is "
        f"required to be ≥ {selected_threshold:.2f}."
    )
    st.markdown("#### Member druggability distributions at the last gate")
    try:
        _, eligible_rows, _ = evaluate_thresholds(
            connection,
            final_druggability_settings(minimum_druggability_score=0.0),
            row_limit,
        )
        cluster_column = next(
            (
                column
                for column in ("lead_cluster_id", "cluster_id")
                if column in eligible_rows.columns
            ),
            None,
        )
        if cluster_column is None:
            raise AppError("Eligible groups lack a lead cluster identifier")
        score_groups = eligible_rows.copy()
        rank_column = next(
            (
                column
                for column in ("final_evolutionary_rank", "final_rank")
                if column in score_groups.columns
            ),
            None,
        )
        if rank_column is not None:
            score_groups["_boxplot_rank"] = pd.to_numeric(
                score_groups[rank_column],
                errors="coerce",
            )
            score_groups = score_groups.sort_values(
                ["_boxplot_rank", cluster_column],
                na_position="last",
                kind="stable",
            )
        score_groups = score_groups.drop_duplicates(cluster_column).head(30)
        score_relation, member_scores = collect_member_druggability_scores(
            connection=connection,
            cluster_ids=(
                score_groups[cluster_column].dropna().astype(str).tolist()
            ),
            max_rows=10_000,
        )
        plot_rows, truncated = prepare_final_gate_druggability_distribution(
            scores=member_scores,
            eligible_groups=eligible_rows,
            max_groups=30,
        )
        figure = build_final_gate_druggability_boxplot(
            frame=plot_rows,
            threshold=float(selected_threshold),
        )
    except AppError as exc:
        st.info(f"The member-level box plot is unavailable: {exc}")
    else:
        st.plotly_chart(
            figure,
            width="stretch",
            config={"displaylogo": False},
            key="recommendation_druggability_boxplot",
        )
        st.caption(
            "Each point is one assessed member's retained selected-pocket score. "
            "Boxes summarise lead clusters that pass every other fixed final gate; "
            f"the dashed line is the selected threshold. Score source: `{score_relation}`."
        )
        if truncated:
            st.info("The plot is limited to the first 30 eligible groups by final rank.")
    if selected_rows.empty:
        st.info("No evolutionary group passes the complete selected gate intersection.")
    else:
        _display_dataframe(frame=selected_rows, height=620)
        render_table_downloads(
            frame=selected_rows,
            file_stem=(
                "final_druggability_sensitivity_"
                f"threshold_{selected_threshold:.2f}".replace(".", "p")
            ),
            tsv_label="Download sensitivity candidate list as TSV",
            excel_label="Download sensitivity candidate list as Excel",
            key="recommendation_druggability_download",
        )
    with st.expander("Groups entering or leaving relative to recorded 0.50"):
        if changed_rows.empty:
            st.info("No group changes pass status at the selected threshold.")
        else:
            _display_dataframe(frame=changed_rows, height=360)


def _render_computational_recommendations(
    *, connection: object, config: AppConfig
) -> None:
    """Render recommendations, detailed formulas and weight sensitivity."""
    specification = SECTION_SPECS["final_recommendations"]
    st.subheader(str(specification["title"]))
    st.caption(str(specification["description"]))
    st.info(
        "A full explanation of every ranking formula, recorded weight, ordering "
        "rule and tie-break appears below the result table. A focused final-gate "
        "slider and a non-authoritative weighting-sensitivity explorer are also "
        "provided without rewriting the recorded result."
    )
    _render_section(
        connection=connection,
        config=config,
        section="final_recommendations",
        show_heading=False,
    )
    _render_final_druggability_sensitivity(
        connection=connection,
        config=config,
    )
    st.markdown(RANKING_METHODOLOGY_MARKDOWN)
    with st.expander(
        "Alternative weighting sensitivity explorer",
        expanded=False,
    ):
        st.warning(
            "This explorer changes only an in-memory sensitivity ranking. It does "
            "not rewrite the authoritative rank, gate decisions or source resource."
        )
        _render_ranking_sensitivity(connection=connection, config=config)


def _render_expression_section(
    *,
    connection: object,
    config: AppConfig,
) -> None:
    """Render candidate expression with explicit tissue and evidence-state controls."""
    relations = relations_for_section(connection, "expression")
    if "candidate_expression_context_summary" not in relations:
        st.warning(
            "This data release does not yet contain candidate-by-tissue expression rows. "
            "The legacy summary can distinguish mapping status, but zero count fields on "
            "NOT_MAPPED rows mean no mapped evidence, not measured zero expression."
        )
        _render_section(connection=connection, config=config, section="expression")
        return
    relation = "candidate_expression_context_summary"
    st.subheader("Candidate expression by tissue and biological context")
    st.caption(
        "Each row is one gene in one Atlas experiment group. Expression is the Atlas "
        "median TPM (TPM ≥ 0.5 is positive); the minimum, quartiles and maximum remain "
        "available. FPKM is used only when an experiment has no TPM matrix."
    )
    species_values = distinct_text_values(
        connection=connection,
        relation=relation,
        column="species_column",
    )
    tissue_values = distinct_text_values(
        connection=connection,
        relation=relation,
        column="organism_part",
    )
    metadata_values = distinct_text_values(
        connection=connection,
        relation=relation,
        column="metadata_status",
    )
    filter_one, filter_two, filter_three = st.columns(3)
    with filter_one:
        species = st.selectbox(
            "Species",
            options=["All", *species_values],
            key="expression_context_species",
        )
    with filter_two:
        tissue = st.selectbox(
            "Tissue / organism part",
            options=["All", *tissue_values],
            key="expression_context_tissue",
        )
    with filter_three:
        search_text = st.text_input(
            "Group, accession or gene contains",
            value="",
            key="expression_context_search",
        )
    status_one, status_two = st.columns(2)
    with status_one:
        metadata_status = st.selectbox(
            "Tissue-metadata status",
            options=["All", *metadata_values],
            key="expression_context_metadata_status",
        )
    with status_two:
        expression_positive = st.selectbox(
            "Median expression support",
            options=["All", "Positive", "Below threshold"],
            key="expression_context_positive",
        )
    available = relation_columns(connection, relation)
    selected = st.multiselect(
        "Columns to display",
        available,
        default=default_columns("expression", available),
        key="expression_context_columns",
    )
    maximum_rows = st.number_input(
        "Maximum rows",
        min_value=1,
        max_value=min(config.max_rows, 10_000),
        value=min(config.max_rows, 1000),
        key="expression_context_rows",
    )
    if not selected:
        st.warning("Select at least one column.")
        return
    result = filter_expression_context(
        connection=connection,
        relation=relation,
        selected_columns=selected,
        species=species,
        organism_part=tissue,
        metadata_status=metadata_status,
        expression_positive=expression_positive,
        search_text=search_text,
        maximum_rows=int(maximum_rows),
    )
    _display_dataframe(frame=result, height=650)
    render_table_downloads(
        frame=result,
        file_stem="candidate_expression_by_tissue",
        tsv_label="Download filtered candidate-by-tissue rows as TSV",
        excel_label="Download filtered candidate-by-tissue rows as Excel",
        key="expression_context_download",
    )
    with st.expander("Mapping summary and audit relations"):
        _render_section(connection=connection, config=config, section="expression")
    _render_expression_section_visualisations(
        connection=connection,
        expression_relation=relation,
    )


def _render_overview(*, connection: object, config: AppConfig) -> None:
    """Render corrected group-level outcomes and interpretation boundaries."""
    st.subheader("Grant-aligned evidence overview")
    metrics = grant_overview(connection)
    first, second, third, fourth = st.columns(4)
    first.metric(
        "Evolutionary groups assessed",
        f"{metrics['candidate_count']:,}",
    )
    second.metric(
        "Milestone 1 pre-structure passes",
        f"{metrics['prestructure_pass_count']:,}",
    )
    third.metric(
        "All current stringent gates passed",
        f"{metrics['final_pass_count']:,}",
    )
    fourth.metric(
        "Structurally assessed groups",
        f"{metrics['structural_assessed_count']:,}",
    )

    milestone_one, milestone_two, boundary = st.columns(3)
    with milestone_one:
        st.markdown("#### Milestone 1: conservation resource")
        st.write(
            "Candidate discovery, explicit OrthoFinder group IDs and members, "
            "target-species breadth, E3-domain support and Expression Atlas evidence."
        )
    with milestone_two:
        st.markdown("#### Milestone 2: conserved chemical starting space")
        st.write(
            "Reusable pocket evidence, pocket-bearing region conservation, FASTA "
            "coordinates and US-align/TM-align pocket equivalence. The zero stringent "
            "passes is a result of the current gates, not an unfinished placeholder."
        )
    with boundary:
        st.markdown("#### Interpretation boundary")
        st.write(
            "These are computational recommendations. E3 activity, compound binding "
            "and induced degradation still require biological and chemistry validation."
        )

    relations = list_relations(connection)
    overview = resource_overview(connection, relations)
    st.markdown("#### Loaded evidence relations")
    if overview.empty:
        st.info("No result relations are available.")
    else:
        _display_dataframe(frame=overview)
    st.caption(
        f"Source mode: {config.source_mode}; read-only source: {config.source_path}"
    )


def _render_workflow_schematic() -> None:
    """Render the complete method and evidence-dependency process map."""
    st.subheader("End-to-end method and evidence workflow")
    st.caption(
        "Follow the arrows from controlled inputs to the app-ready computational "
        "recommendations. Parallel boxes show evidence streams that were generated "
        "independently before reconciliation."
    )
    st.info(
        "The arrows represent computational dependencies and evidence integration, "
        "not proof of biological causality. Stage 09c is an optional chemistry "
        "hand-off and did not contribute to the recorded Milestone 1 ranking."
    )
    st.markdown(workflow_schematic_html(), unsafe_allow_html=True)


def _sync_threshold_control(field: str, source: str) -> None:
    """Synchronise one slider and typed numeric control in session state."""
    source_key = f"threshold_{field}_{source}"
    target = "number" if source == "slider" else "slider"
    st.session_state[f"threshold_{field}_{target}"] = st.session_state[source_key]


def _threshold_pair(field: str, label: str, default: float) -> float:
    """Render paired threshold slider and exact-value input."""
    slider_key = f"threshold_{field}_slider"
    number_key = f"threshold_{field}_number"
    st.session_state.setdefault(slider_key, default)
    st.session_state.setdefault(number_key, default)
    slider_column, number_column = st.columns((3, 1))
    with slider_column:
        st.slider(
            label,
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            key=slider_key,
            on_change=_sync_threshold_control,
            args=(field, "slider"),
        )
    with number_column:
        st.number_input(
            "Type exact value",
            min_value=0.0,
            max_value=1.0,
            step=0.01,
            key=number_key,
            on_change=_sync_threshold_control,
            args=(field, "number"),
            label_visibility="visible",
        )
    st.caption(SLIDER_HELP[field])
    return float(st.session_state[number_key])


def _render_glossary() -> None:
    """Render plain-language terms and the exact recorded scientific rules."""
    st.subheader("Glossary and computational rules")
    st.info(
        "This expanded glossary combines project-wide technical terminology, the complete "
        "218-field final-candidate data dictionary and the recorded top-200 computational "
        "rules. Threshold-explorer changes create sensitivity lists and do not rewrite the "
        "recorded primary result. Every glossary row is available in the browser below; "
        "downloading is optional."
    )
    sections = glossary_sections()
    selected_section = st.selectbox(
        "Glossary section",
        options=("All sections", *sections),
        key="glossary_section",
    )
    all_rows = [
        {"Section": section, **row}
        for section in sections
        for row in glossary_rows(section)
    ]
    rows = (
        all_rows
        if selected_section == "All sections"
        else [row for row in all_rows if row["Section"] == selected_section]
    )
    st.caption(f"{len(rows):,} glossary rows are available in this browser table.")
    _display_dataframe(frame=rows, height=760)
    export = pd.DataFrame(all_rows)
    render_table_downloads(
        frame=export,
        file_stem="aria_e3_scientific_glossary",
        tsv_label="Download complete glossary as TSV",
        excel_label="Download complete glossary as Excel",
        key="glossary_download",
    )


def _reset_threshold_controls() -> None:
    """Restore the completed analysis thresholds in session state."""
    defaults = asdict(ThresholdSettings())
    for field in NUMERIC_THRESHOLD_FIELDS:
        st.session_state[f"threshold_{field}_slider"] = defaults[field]
        st.session_state[f"threshold_{field}_number"] = defaults[field]
    for field in LOGICAL_THRESHOLD_FIELDS:
        st.session_state[f"threshold_{field}"] = defaults[field]
    st.session_state["threshold_mode"] = defaults["mode"]
    st.session_state["threshold_result_scope"] = defaults["result_scope"]


def _active_threshold_settings() -> ThresholdSettings:
    """Render explorer controls and return their validated settings."""
    defaults = ThresholdSettings()
    if st.button("Reset current defaults", key="threshold_reset"):
        _reset_threshold_controls()
        st.rerun()
    st.radio(
        "Prioritisation view",
        options=("prestructure", "structural"),
        format_func=lambda value: {
            "prestructure": "Pre-structure prioritisation",
            "structural": "Structurally informed prioritisation",
        }[value],
        key="threshold_mode",
        horizontal=True,
    )
    st.selectbox(
        "Rows to show",
        options=("passing", "pass_near", "all"),
        format_func=lambda value: {
            "passing": "Passing candidates only",
            "pass_near": "Passes and one-gate near-misses",
            "all": "All evaluated groups",
        }[value],
        key="threshold_result_scope",
    )
    st.markdown("##### Pre-structure thresholds")
    values: dict[str, object] = {
        "mode": st.session_state["threshold_mode"],
        "result_scope": st.session_state["threshold_result_scope"],
        "target_species_fraction": _threshold_pair(
            "target_species_fraction",
            "Minimum target-species fraction",
            defaults.target_species_fraction,
        ),
        "mandatory_species_fraction": _threshold_pair(
            "mandatory_species_fraction",
            "Minimum mandatory-species fraction",
            defaults.mandatory_species_fraction,
        ),
        "domain_species_fraction": _threshold_pair(
            "domain_species_fraction",
            "Minimum domain-supported assessed-species fraction",
            defaults.domain_species_fraction,
        ),
        "expression_species_fraction": _threshold_pair(
            "expression_species_fraction",
            "Minimum expression-supported assessed-species fraction",
            defaults.expression_species_fraction,
        ),
    }
    evidence_one, evidence_two = st.columns(2)
    with evidence_one:
        values["require_domain_evidence"] = st.checkbox(
            "Require assessable domain evidence",
            value=defaults.require_domain_evidence,
            key="threshold_require_domain_evidence",
        )
    with evidence_two:
        values["require_expression_evidence"] = st.checkbox(
            "Require assessable expression evidence",
            value=defaults.require_expression_evidence,
            key="threshold_require_expression_evidence",
        )

    if values["mode"] == "structural":
        st.markdown("##### Structural thresholds")
        values["structural_species_fraction"] = _threshold_pair(
            "structural_species_fraction",
            "Minimum structurally supported species fraction",
            defaults.structural_species_fraction,
        )
        values["minimum_druggability_score"] = _threshold_pair(
            "minimum_druggability_score",
            "Minimum member druggability score",
            defaults.minimum_druggability_score,
        )
        structural_one, structural_two, structural_three = st.columns(3)
        with structural_one:
            values["require_conserved_region"] = st.checkbox(
                "Require conserved pocket-bearing sequence region",
                value=defaults.require_conserved_region,
                key="threshold_require_conserved_region",
            )
        with structural_two:
            values["require_all_member_mapping"] = st.checkbox(
                "Require every assessed member to pass pocket mapping",
                value=defaults.require_all_member_mapping,
                key="threshold_require_all_member_mapping",
            )
        with structural_three:
            values["require_strict_3d"] = st.checkbox(
                "Require strictly conserved corresponding 3D pocket",
                value=defaults.require_strict_3d,
                key="threshold_require_strict_3d",
            )
        values["include_not_assessed"] = st.checkbox(
            "Also display groups not structurally assessed",
            value=defaults.include_not_assessed,
            key="threshold_include_not_assessed",
            help="These groups remain labelled NOT_STRUCTURALLY_ASSESSED.",
        )
    return threshold_settings_from_mapping(values, defaults=defaults)


def _render_threshold_explorer(
    *,
    connection: object,
    config: AppConfig,
) -> None:
    """Render interactive pre-structure and structural sensitivity lists."""
    st.subheader("Explore alternative candidate thresholds")
    st.info(
        "The recorded primary analysis remains unchanged. This view filters values "
        "already stored in DuckDB; it does not rerun any scientific calculation."
    )
    control_column, explanation_column = st.columns((2, 1))
    with control_column:
        settings = _active_threshold_settings()
        requested_rows = st.number_input(
            "Maximum displayed rows",
            min_value=1,
            max_value=min(config.max_rows, 10_000),
            value=min(config.max_rows, 1000),
            key="threshold_max_rows",
        )
    with explanation_column:
        st.markdown("##### Interpretation")
        st.markdown(
            "**PASS** meets every active gate. **NEAR_MISS** fails exactly one. "
            "**NOT_STRUCTURALLY_ASSESSED** means the group was outside the 200 "
            "groups taken through 3D assessment; it is not a structural failure."
        )
        st.caption(
            "Pocket-region and strict 3D statuses use the recorded production "
            "calculations. Changing coordinate, overlap or TM-score rules requires "
            "rerunning the scientific workflow."
        )
    relation, result, summary = evaluate_thresholds(
        connection,
        settings,
        int(requested_rows),
    )
    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "Evaluated evolutionary groups",
        f"{summary['evaluated_count']:,}",
    )
    metric_columns[1].metric("Custom passes", f"{summary['pass_count']:,}")
    metric_columns[2].metric(
        "One-gate near-misses",
        f"{summary['near_miss_count']:,}",
    )
    metric_columns[3].metric(
        "Structurally assessed",
        f"{summary['structurally_assessed_count']:,}",
    )
    if relation == "final_evolutionary_candidate_prioritisation":
        st.caption(f"Using `{relation}`: one row per evolutionary group.")
    else:
        st.caption(
            f"Using `{relation}` as a compatibility source, with one deterministic "
            "lead row retained per evolutionary group."
        )
    _display_dataframe(frame=result, height=700)
    render_table_downloads(
        frame=result,
        file_stem=f"aria_e3_{settings.mode}_custom_thresholds",
        tsv_label="Download custom candidate list as TSV",
        excel_label="Download custom candidate list as Excel",
        key="threshold_download",
    )


def _render_pocket_review(
    *,
    bundle: PocketReviewBundle,
    focus: str,
) -> None:
    """Render a selected self-contained structure or alignment group page."""
    title = (
        "Selected-group 3D structures and pockets"
        if focus == "structure"
        else "Selected-group pocket-annotated alignment"
    )
    st.subheader(title)
    if not bundle.available:
        st.warning(bundle.reason)
        st.code("--pocket-review-dir /path/to/pocket_review")
        return
    labels = group_choice_labels(bundle)
    group_page = st.selectbox(
        "Evolutionary group",
        options=list(labels),
        format_func=lambda value: labels[value],
        key=f"pocket_review_{focus}_group",
        help="Type to search by rank, HOG/orthogroup, lead cluster or accession.",
    )
    row = selected_group_row(bundle, group_page)
    st.caption(
        f"Review rank {int(row['review_rank'])} | evolutionary group "
        f"{row['primary_group_id']} | lead DeepClust cluster "
        f"{row['lead_cluster_id']} | reference {row['reference_accession']} | "
        f"{row['alignment_sequence_count']} aligned sequences"
    )
    document = read_group_html(bundle, group_page, focus)
    components.html(document, height=1100, scrolling=True)
    members = selected_group_members(bundle, int(row["review_rank"]), focus)
    member_title = (
        "Displayed protein models"
        if focus == "structure"
        else "OrthoFinder-group member sequence identifiers"
    )
    st.markdown(f"#### {member_title}")
    _display_dataframe(frame=members)
    safe_group = "".join(
        character if character.isalnum() or character in "_.-" else "_"
        for character in str(row["primary_group_id"])
    )
    render_table_downloads(
        frame=members,
        file_stem=f"{safe_group}_{focus}_members",
        tsv_label="Download selected member table as TSV",
        excel_label="Download selected member table as Excel",
        key=f"pocket_review_{focus}_members_download",
    )
    st.download_button(
        label="Download the self-contained group review HTML",
        data=document,
        file_name=f"{safe_group}_pocket_review.html",
        mime="text/html",
        key=f"pocket_review_{focus}_html_download",
    )
    st.caption(
        "The embedded report includes the linear pocket-position tracks, retained "
        "pocket evidence and exact alignment/FASTA/structure coordinate audit."
    )
    if focus == "structure":
        matrix = read_review_html(bundle, "evidence_matrix.html")
        with st.expander("Cross-group structural evidence matrix"):
            st.caption(
                "Compare strict rank-one and exploratory top-five pocket evidence "
                "across the full structurally assessed review set."
            )
            components.html(matrix, height=900, scrolling=True)
            st.download_button(
                "Download cross-group evidence matrix HTML",
                data=matrix,
                file_name="e3_cross_group_pocket_evidence_matrix.html",
                mime="text/html",
                key="pocket_review_matrix_download",
            )


def _render_search(*, connection: object, max_rows: int) -> None:
    """Render cross-relation exact accession search."""
    st.subheader("Candidate or member accession search")
    st.caption(
        "Searches recognised accession fields and semicolon-delimited candidate lists "
        "across every loaded relation."
    )
    query = st.text_input("UniProt or project accession", placeholder="Q9SA03")
    if not query:
        return
    matches = search_accession(connection, query, min(max_rows, 1000))
    if matches.empty:
        st.warning("No exact accession match was found in recognised columns.")
    else:
        _display_dataframe(frame=matches)


def _render_all_results(
    *,
    connection: object,
    config: AppConfig,
    relations: Sequence[str],
) -> None:
    """Render a schema-agnostic bounded result browser."""
    st.subheader("All imported results")
    st.caption(
        "Use this audit view for relations not covered by a grant-facing section. "
        "Queries remain bounded and execute inside DuckDB."
    )
    if not relations:
        st.info("No relations are available to browse.")
        return
    relation = st.selectbox("Relation", relations, key="all_results_relation")
    available = relation_columns(connection, relation)
    selected = st.multiselect(
        "Columns to display",
        available,
        default=list(available[: min(12, len(available))]),
        key="all_results_columns",
    )
    requested = st.number_input(
        "Rows to display",
        min_value=1,
        max_value=config.max_rows,
        value=min(100, config.max_rows),
        key="all_results_rows",
    )
    if selected:
        result = preview_selected_columns(
            connection,
            relation,
            selected,
            int(requested),
        )
        _display_dataframe(frame=result)
        render_table_downloads(
            frame=result,
            file_stem=f"all_results_{relation}",
            tsv_label="Download displayed rows as TSV",
            excel_label="Download displayed rows as Excel",
            key="all_results_download",
        )
    else:
        st.warning("Select at least one column.")


def _candidate_expression_link_column(
    *,
    landscape_columns: Sequence[str],
    expression_columns: Sequence[str],
) -> str | None:
    """Choose an exact identifier shared by candidate and expression relations."""
    return next(
        (
            column
            for column in ("primary_group_id", "cluster_id")
            if column in landscape_columns and column in expression_columns
        ),
        None,
    )


def _linked_candidate_row(
    frame: pd.DataFrame,
    candidate_key: str | None,
) -> pd.Series:
    """Return the linked candidate row, falling back to the first ranked row."""
    if candidate_key:
        matches = frame[frame["_candidate_key"].eq(candidate_key)]
        if not matches.empty:
            return matches.iloc[0]
    return frame.iloc[0]


def _render_candidate_landscape(
    *,
    connection: object,
    frame: pd.DataFrame,
    relation: str,
    identifier_column: str,
    rank_column: str | None,
    metric_columns: Sequence[str],
    colour_columns: Sequence[str],
    config: AppConfig,
) -> str:
    """Render the selectable multi-axis candidate landscape and evidence table."""
    st.subheader("Interactive candidate landscape")
    st.caption(
        "Choose any two documented evidence scales. Point colour and size add two "
        "further dimensions; selecting a point links the evidence tables and "
        "expression views below."
    )
    control_one, control_two, control_three, control_four = st.columns(4)
    default_x = (
        "expression_species_fraction"
        if "expression_species_fraction" in metric_columns
        else metric_columns[0]
    )
    default_y = (
        "final_score"
        if "final_score" in metric_columns
        else metric_columns[min(1, len(metric_columns) - 1)]
    )
    with control_one:
        x_column = st.selectbox(
            "X-axis",
            metric_columns,
            index=list(metric_columns).index(default_x),
            format_func=lambda column: CANDIDATE_METRIC_LABELS[column],
            key="visual_landscape_x",
        )
    with control_two:
        y_column = st.selectbox(
            "Y-axis",
            metric_columns,
            index=list(metric_columns).index(default_y),
            format_func=lambda column: CANDIDATE_METRIC_LABELS[column],
            key="visual_landscape_y",
        )
    with control_three:
        colour_options = [None, *colour_columns]
        colour_column = st.selectbox(
            "Point colour",
            colour_options,
            format_func=lambda column: (
                "Single colour"
                if column is None
                else CANDIDATE_METRIC_LABELS.get(
                    column, column.replace("_", " ").title()
                )
            ),
            key="visual_landscape_colour",
        )
    with control_four:
        size_options = [None, *metric_columns]
        size_column = st.selectbox(
            "Point size",
            size_options,
            format_func=lambda column: (
                "Fixed size" if column is None else CANDIDATE_METRIC_LABELS[column]
            ),
            key="visual_landscape_size",
        )
    figure = build_candidate_landscape_figure(
        frame=frame,
        x_column=x_column,
        y_column=y_column,
        colour_column=colour_column,
        size_column=size_column,
    )
    selection = st.plotly_chart(
        figure,
        use_container_width=True,
        key="visual_candidate_landscape_plot",
        on_select="rerun",
        selection_mode="points",
    )
    selected_from_plot = selected_candidate_from_event(
        event=selection,
        frame=frame,
    )
    options = frame["_candidate_key"].astype(str).tolist()
    labels = candidate_display_labels(frame=frame, rank_column=rank_column)
    if selected_from_plot in options:
        st.session_state["visual_selected_candidate"] = selected_from_plot
    current = st.session_state.get("visual_selected_candidate")
    if current not in options:
        st.session_state["visual_selected_candidate"] = options[0]
    selected_key = st.selectbox(
        "Selected candidate",
        options,
        format_func=lambda value: labels[value],
        key="visual_selected_candidate",
        help="Select a point above or type to search the ranked candidate list.",
    )
    row = _linked_candidate_row(frame, selected_key)
    display_columns = [
        column
        for column in (
            rank_column,
            identifier_column,
            "primary_group_id",
            "cluster_id",
            "candidate_accessions",
            "final_score",
            "prestructure_score",
            "target_species_fraction",
            "domain_species_fraction",
            "expression_species_fraction",
            "expression_evidence_coverage_fraction",
            "ligandability_score",
            "pocket_conservation_score",
            "structural_species_fraction",
            "recommendation_status",
            "grant_aligned_prediction_status",
            "inclusion_reasons",
            "exclusion_reasons",
            "missing_evidence",
        )
        if column is not None and column in frame.columns
    ]
    st.markdown("#### Selected candidate summary")
    _display_dataframe(
        frame=pd.DataFrame([row[display_columns].to_dict()]),
    )
    identifiers = candidate_identifiers_from_row(row=row)
    evidence_relations = candidate_evidence_relations(
        connection=connection,
        identifiers=identifiers,
    )
    st.markdown("#### Evidence rows behind the selected candidate")
    if not evidence_relations:
        st.info("No loaded relation contains a compatible exact candidate identifier.")
        return selected_key
    evidence_relation = st.selectbox(
        "Supporting evidence table",
        evidence_relations,
        index=(
            evidence_relations.index(relation)
            if relation in evidence_relations
            else 0
        ),
        key="visual_evidence_relation",
    )
    evidence_limit = st.number_input(
        "Maximum supporting rows",
        min_value=1,
        max_value=min(config.max_rows, 10_000),
        value=min(config.max_rows, 1000),
        key="visual_evidence_rows",
    )
    evidence = collect_candidate_evidence(
        connection=connection,
        relation=evidence_relation,
        identifiers=identifiers,
        maximum_rows=int(evidence_limit),
    )
    _display_dataframe(frame=evidence, height=520)
    render_table_downloads(
        frame=evidence,
        file_stem=f"{selected_key}_{evidence_relation}",
        tsv_label="Download selected candidate evidence as TSV",
        excel_label="Download selected candidate evidence as Excel",
        key="visual_evidence_download",
    )
    return selected_key


def _expression_candidate_options(
    *,
    frame: pd.DataFrame,
    link_column: str,
    rank_column: str | None,
) -> tuple[list[str], dict[str, str]]:
    """Build de-duplicated expression-link choices from ranked candidates."""
    options = []
    labels = {}
    for _, row in frame.iterrows():
        value = row.get(link_column)
        if value is None or pd.isna(value) or not str(value).strip():
            continue
        key = str(value).strip()
        if key in labels:
            continue
        rank = row.get(rank_column) if rank_column is not None else None
        options.append(key)
        labels[key] = (
            key if rank is None or pd.isna(rank) else f"Rank {int(rank):,} — {key}"
        )
    return options, labels


def _render_expression_heatmap(
    *,
    connection: object,
    frame: pd.DataFrame,
    selected_key: str | None,
    rank_column: str | None,
    expression_relation: str,
    key_prefix: str = "visual",
) -> None:
    """Render a linked cross-species candidate expression heatmap."""
    st.subheader("Cross-species expression heatmap")
    st.caption(
        "Each cell is the median for one candidate, species and biological "
        "context. Blank cells are unavailable mapped contexts, not measured zero."
    )
    expression_columns = relation_columns(connection, expression_relation)
    link_column = _candidate_expression_link_column(
        landscape_columns=frame.columns,
        expression_columns=expression_columns,
    )
    if link_column is None:
        st.info("Candidate and expression relations have no shared exact group identifier.")
        return
    options, labels = _expression_candidate_options(
        frame=frame,
        link_column=link_column,
        rank_column=rank_column,
    )
    selected_row = _linked_candidate_row(frame, selected_key)
    linked_value = str(selected_row.get(link_column, "")).strip()
    candidate_key = f"{key_prefix}_heatmap_candidates"
    current = list(st.session_state.get(candidate_key, []))
    if linked_value and linked_value not in current:
        current = [linked_value, *current]
    if not current:
        current = options[: min(10, len(options))]
    st.session_state[candidate_key] = [
        value for value in current if value in options
    ][:25]
    selected_candidates = st.multiselect(
        "Candidate groups (maximum 25)",
        options,
        format_func=lambda value: labels[value],
        key=candidate_key,
    )
    if not selected_candidates:
        st.info("Select at least one candidate group.")
        return
    if len(selected_candidates) > 25:
        st.warning("Only the first 25 selected candidate groups are plotted.")
        selected_candidates = selected_candidates[:25]
    contexts = [
        column for column in EXPRESSION_CONTEXT_LABELS if column in expression_columns
    ]
    units = distinct_text_values(
        connection=connection,
        relation=expression_relation,
        column="expression_unit",
    )
    species_values = distinct_text_values(
        connection=connection,
        relation=expression_relation,
        column="species_column",
    )
    if not contexts or not units:
        st.info("This expression relation lacks context labels or expression units.")
        return
    control_one, control_two, control_three, control_four = st.columns(4)
    with control_one:
        context_column = st.selectbox(
            "Heatmap context",
            contexts,
            format_func=lambda column: EXPRESSION_CONTEXT_LABELS[column],
            key=f"{key_prefix}_heatmap_context",
        )
    with control_two:
        expression_unit = st.selectbox(
            "Expression unit",
            units,
            key=f"{key_prefix}_heatmap_unit",
        )
    with control_three:
        species = st.selectbox(
            "Species",
            ["All", *species_values],
            key=f"{key_prefix}_heatmap_species",
        )
    with control_four:
        log_transform = st.checkbox(
            "Use log2(1 + expression)",
            value=True,
            key=f"{key_prefix}_heatmap_log",
        )
    cells = collect_expression_heatmap(
        connection=connection,
        relation=expression_relation,
        candidate_column=link_column,
        candidate_ids=selected_candidates,
        context_column=context_column,
        expression_unit=expression_unit,
        species=species,
    )
    if cells.empty:
        st.info("No mapped expression rows match the selected candidates and filters.")
        return
    figure = build_expression_heatmap_figure(
        cells=cells,
        log_transform=log_transform,
    )
    st.plotly_chart(
        figure,
        use_container_width=True,
        key=f"{key_prefix}_expression_heatmap_plot",
    )
    st.markdown("#### Aggregated heatmap cells")
    _display_dataframe(frame=cells, height=460)
    render_table_downloads(
        frame=cells,
        file_stem=f"{key_prefix}_candidate_expression_heatmap_cells",
        tsv_label="Download expression heatmap cells as TSV",
        excel_label="Download expression heatmap cells as Excel",
        key=f"{key_prefix}_heatmap_download",
    )


def _render_expression_section_visualisations(
    *,
    connection: object,
    expression_relation: str,
) -> None:
    """Place the heatmap and volcano views beside expression evidence tables."""
    st.markdown("### Expression visualisations")
    st.caption(
        "These are the same scientific views exposed in Visual explorer, placed "
        "here so expression evidence and its visual summaries can be reviewed "
        "without changing the main section."
    )
    visual_tabs = st.tabs(("Expression heatmap", "Volcano eligibility"))
    with visual_tabs[0]:
        expression_columns = relation_columns(connection, expression_relation)
        link_column = next(
            (
                column
                for column in ("primary_group_id", "cluster_id")
                if column in expression_columns
            ),
            None,
        )
        if link_column is None:
            st.info(
                "The expression relation has no stable candidate-group identifier "
                "for a heatmap."
            )
        else:
            identifiers = distinct_text_values(
                connection=connection,
                relation=expression_relation,
                column=link_column,
            )
            if not identifiers:
                st.info("No mapped candidate groups are available for a heatmap.")
            else:
                frame = pd.DataFrame(
                    {
                        link_column: identifiers,
                        "_candidate_key": identifiers,
                    }
                )
                _render_expression_heatmap(
                    connection=connection,
                    frame=frame,
                    selected_key=None,
                    rank_column=None,
                    expression_relation=expression_relation,
                    key_prefix="expression_section",
                )
    with visual_tabs[1]:
        _render_volcano_view(
            connection=connection,
            key_prefix="expression_section",
        )


def _render_species_tissue_profiles(
    *,
    connection: object,
    frame: pd.DataFrame,
    selected_key: str,
    rank_column: str | None,
    expression_relation: str,
) -> None:
    """Render every mapped tissue profile for a linked candidate by species."""
    st.subheader("Linked species and tissue expression profiles")
    st.caption(
        "Select a candidate once and inspect all available tissue-annotated Atlas "
        "contexts separately for each species. The plot aggregates every matching "
        "context before applying its output bound, so the source-row display limit "
        "cannot truncate a tissue profile. Error bars span the observed range."
    )
    expression_columns = relation_columns(connection, expression_relation)
    link_column = _candidate_expression_link_column(
        landscape_columns=frame.columns,
        expression_columns=expression_columns,
    )
    if link_column is None:
        st.info("Candidate and expression relations have no shared exact group identifier.")
        return
    options, labels = _expression_candidate_options(
        frame=frame,
        link_column=link_column,
        rank_column=rank_column,
    )
    selected_row = _linked_candidate_row(frame, selected_key)
    linked_value = str(selected_row.get(link_column, "")).strip()
    if linked_value in options:
        st.session_state["visual_profile_candidate"] = linked_value
    current = st.session_state.get("visual_profile_candidate")
    if current not in options:
        st.session_state["visual_profile_candidate"] = options[0]
    candidate_id = st.selectbox(
        "Candidate group",
        options,
        format_func=lambda value: labels[value],
        key="visual_profile_candidate",
    )
    units = distinct_text_values(
        connection=connection,
        relation=expression_relation,
        column="expression_unit",
    )
    species_values = distinct_text_values(
        connection=connection,
        relation=expression_relation,
        column="species_column",
    )
    if not units:
        st.info("The candidate expression relation has no explicit expression unit.")
        return
    control_one, control_two, control_three, control_four = st.columns(4)
    with control_one:
        expression_unit = st.selectbox(
            "Expression unit",
            units,
            key="visual_profile_unit",
        )
    with control_two:
        species = st.selectbox(
            "Species filter",
            ["All", *species_values],
            key="visual_profile_species",
        )
    with control_three:
        log_transform = st.checkbox(
            "Use log2(1 + expression)",
            value=True,
            key="visual_profile_log",
        )
    with control_four:
        maximum_rows = st.number_input(
            "Maximum exact source rows",
            min_value=100,
            max_value=50_000,
            value=10_000,
            step=100,
            key="visual_profile_rows",
        )
    summary = collect_expression_tissue_summary(
        connection=connection,
        relation=expression_relation,
        candidate_column=link_column,
        candidate_id=candidate_id,
        expression_unit=expression_unit,
        species=species,
    )
    if summary.empty:
        st.info("No mapped expression rows match the selected candidate and filters.")
        return
    rows = collect_expression_profile_rows(
        connection=connection,
        relation=expression_relation,
        candidate_column=link_column,
        candidate_id=candidate_id,
        expression_unit=expression_unit,
        species=species,
        maximum_rows=int(maximum_rows),
    )
    profile = prepare_species_tissue_summary(
        summary=summary,
        log_transform=log_transform,
    )
    figure = build_species_tissue_profile_figure(
        profile=profile,
        expression_unit=expression_unit,
        log_transform=log_transform,
    )
    st.plotly_chart(
        figure,
        use_container_width=True,
        key="visual_species_tissue_profile_plot",
    )
    evidence_state_columns = [
        column
        for column in (
            "expression_supported_species",
            "expression_assessed_negative_species",
            "expression_unavailable_species",
            "lead_expression_supported_species",
            "lead_expression_assessed_negative_species",
            "lead_expression_unavailable_species",
            "expression_species_fraction",
            "expression_evidence_coverage_fraction",
        )
        if column in selected_row.index
    ]
    if evidence_state_columns:
        st.markdown("#### Group-level expression evidence states")
        _display_dataframe(
            frame=pd.DataFrame(
                [selected_row[evidence_state_columns].to_dict()]
            ),
        )
    st.markdown("#### Aggregated species/tissue profile")
    _display_dataframe(frame=profile)
    st.markdown("#### Exact Expression Atlas rows behind the profile")
    if len(rows) >= int(maximum_rows):
        st.info(
            "The exact-row table reached its selected display/download limit. "
            "The plotted species/tissue summary is still complete because it was "
            "aggregated before that limit."
        )
    _display_dataframe(frame=rows, height=620)
    render_table_downloads(
        frame=rows,
        file_stem=f"{candidate_id}_species_tissue_expression",
        tsv_label="Download exact species/tissue expression rows as TSV",
        excel_label="Download exact species/tissue expression rows as Excel",
        key="visual_profile_download",
    )


def _render_volcano_view(
    *,
    connection: object,
    key_prefix: str = "visual",
) -> None:
    """Render a volcano plot only when a real differential relation exists."""
    st.subheader("Differential-expression volcano plot")
    capabilities = differential_expression_relations(connection=connection)
    if not capabilities:
        st.info(
            "This release contains absolute Expression Atlas context summaries, "
            "not candidate-level differential tests with both log2 fold changes "
            "and P/FDR/Q values. A volcano plot would therefore be statistically "
            "invalid and is not fabricated. This tab activates automatically if a "
            "future release includes those fields."
        )
        return
    labels = {
        capability["relation"]: (
            f"{capability['relation']} — {capability['effect_column']} versus "
            f"{capability['significance_column']}"
        )
        for capability in capabilities
    }
    relation = st.selectbox(
        "Differential-expression relation",
        list(labels),
        format_func=lambda value: labels[value],
        key=f"{key_prefix}_volcano_relation",
    )
    capability = next(
        item for item in capabilities if item["relation"] == relation
    )
    threshold_one, threshold_two = st.columns(2)
    with threshold_one:
        effect_threshold = st.number_input(
            "Absolute log2 fold-change threshold",
            min_value=0.0,
            max_value=20.0,
            value=1.0,
            step=0.1,
            key=f"{key_prefix}_volcano_effect",
        )
    with threshold_two:
        significance_threshold = st.number_input(
            "Significance threshold",
            min_value=0.000001,
            max_value=1.0,
            value=0.05,
            format="%.6f",
            key=f"{key_prefix}_volcano_significance",
        )
    rows = collect_differential_expression(
        connection=connection,
        capability=capability,
    )
    figure = build_volcano_figure(
        rows=rows,
        effect_threshold=float(effect_threshold),
        significance_threshold=float(significance_threshold),
        significance_label=capability["significance_column"],
    )
    st.plotly_chart(
        figure,
        use_container_width=True,
        key=f"{key_prefix}_volcano_plot",
    )
    _display_dataframe(frame=rows, height=520)
    render_table_downloads(
        frame=rows,
        file_stem=f"{relation}_volcano_rows",
        tsv_label="Download plotted differential-expression rows as TSV",
        excel_label="Download plotted differential-expression rows as Excel",
        key=f"{key_prefix}_volcano_download",
    )


def _render_visual_explorer(
    *,
    connection: object,
    config: AppConfig,
) -> None:
    """Render linked candidate, heatmap, species/tissue and volcano views."""
    relation = select_candidate_landscape_relation(connection=connection)
    if relation is None:
        st.info("No recognised candidate-level relation is available for visualisation.")
        return
    available = relation_columns(connection, relation)
    selected_columns = candidate_landscape_columns(available=available)
    identifier_column = candidate_identifier_column(available=available)
    if identifier_column is None:
        st.info("The candidate relation has no stable identifier.")
        return
    metric_columns = candidate_metric_columns(available=available)
    colour_columns = candidate_colour_columns(available=available)
    rank_column = candidate_rank_column(available=available)
    raw_frame = collect_candidate_landscape(
        connection=connection,
        relation=relation,
        selected_columns=selected_columns,
        maximum_rows=5000,
    )
    frame = prepare_candidate_landscape(
        frame=raw_frame,
        identifier_column=identifier_column,
        metric_columns=metric_columns,
    )
    st.caption(
        f"Authoritative visualisation relation: `{relation}`; "
        f"{len(frame):,} distinct candidate groups loaded."
    )
    visual_tabs = st.tabs(
        [
            "Candidate landscape",
            "Expression heatmap",
            "Species & tissue expression",
            "Volcano eligibility",
        ]
    )
    with visual_tabs[0]:
        selected_key = _render_candidate_landscape(
            connection=connection,
            frame=frame,
            relation=relation,
            identifier_column=identifier_column,
            rank_column=rank_column,
            metric_columns=metric_columns,
            colour_columns=colour_columns,
            config=config,
        )
    expression_relation = "candidate_expression_context_summary"
    if expression_relation not in list_relations(connection):
        with visual_tabs[1]:
            st.info("This release has no candidate-by-context expression relation.")
        with visual_tabs[2]:
            st.info("This release has no candidate-by-context expression relation.")
    else:
        with visual_tabs[1]:
            _render_expression_heatmap(
                connection=connection,
                frame=frame,
                selected_key=selected_key,
                rank_column=rank_column,
                expression_relation=expression_relation,
            )
        with visual_tabs[2]:
            _render_species_tissue_profiles(
                connection=connection,
                frame=frame,
                selected_key=selected_key,
                rank_column=rank_column,
                expression_relation=expression_relation,
            )
    with visual_tabs[3]:
        _render_volcano_view(connection=connection)


def render_app() -> None:
    """Render the complete point-and-click ARIA E3 resource explorer."""
    st.set_page_config(page_title="ARIA Plant E3 Resource", layout="wide")
    st.markdown(_WRAPPED_TAB_CSS, unsafe_allow_html=True)
    st.title("ARIA plant E3 discovery and ligandability resource")
    st.caption(
        "Read-only Python companion to the R Shiny reporter. DuckDB performs "
        "bounded relational queries; pandas receives only displayed results."
    )
    try:
        config = config_from_environment()
        validate_config(config)
    except AppError as exc:
        st.error(str(exc))
        st.stop()
        return
    pocket_review = prepare_pocket_review(config)
    LOGGER.info(
        "Opening E3 app source_mode=%s source=%s pocket_review=%s",
        config.source_mode,
        config.source_path,
        pocket_review.path,
    )

    st.sidebar.header("Data release")
    st.sidebar.code(str(config.source_path))
    st.sidebar.caption(f"Source mode: {config.source_mode}")
    if config.expression_duckdb:
        st.sidebar.caption(f"Raw Expression Atlas: {config.expression_duckdb}")
    if pocket_review.available:
        st.sidebar.success(f"Pocket review: {pocket_review.path}")
    else:
        st.sidebar.warning("Portable pocket review is not configured.")
    st.sidebar.caption(f"Maximum rows per query: {config.max_rows:,}")
    st.sidebar.info(
        "Missing annotation or expression resources are shown as unavailable "
        "evidence, never silently converted into a biological negative."
    )

    try:
        with open_resource(config) as connection:
            relations = list_relations(connection)
            tabs = st.tabs(
                [
                    "Overview",
                    "Workflow schematic",
                    "Glossary",
                    "Computational recommendations",
                    "Threshold explorer",
                    "Visual explorer",
                    "Candidates",
                    "Orthology",
                    "Domains",
                    "Expression",
                    "Ligandability",
                    "Pocket conservation",
                    "3D structures & pockets",
                    "Pocket-aligned sequences",
                    "3D alignment",
                    "Computational chemistry",
                    "Accession search",
                    "All results",
                    "Provenance and QC",
                ]
            )
            with tabs[0]:
                _render_overview(connection=connection, config=config)
            with tabs[1]:
                _render_workflow_schematic()
            with tabs[2]:
                _render_glossary()
            with tabs[3]:
                _render_computational_recommendations(
                    connection=connection,
                    config=config,
                )
            with tabs[4]:
                _render_threshold_explorer(connection=connection, config=config)
            with tabs[5]:
                _render_visual_explorer(connection=connection, config=config)
            for tab, section in zip(
                tabs[6:12],
                (
                    "candidates",
                    "orthology",
                    "domains",
                    "expression",
                    "ligandability",
                    "pocket_conservation",
                ),
            ):
                with tab:
                    if section == "expression":
                        _render_expression_section(
                            connection=connection,
                            config=config,
                        )
                    else:
                        _render_section(
                            connection=connection,
                            config=config,
                            section=section,
                        )
            with tabs[12]:
                _render_pocket_review(bundle=pocket_review, focus="structure")
            with tabs[13]:
                _render_pocket_review(bundle=pocket_review, focus="alignment")
            with tabs[14]:
                _render_structural_alignment_section(
                    connection=connection,
                    config=config,
                )
            with tabs[15]:
                _render_section(
                    connection=connection,
                    config=config,
                    section="computational_chemistry",
                )
            with tabs[16]:
                _render_search(connection=connection, max_rows=config.max_rows)
            with tabs[17]:
                _render_all_results(
                    connection=connection,
                    config=config,
                    relations=relations,
                )
            with tabs[18]:
                _render_section(
                    connection=connection,
                    config=config,
                    section="provenance",
                )
    except AppError as exc:
        LOGGER.exception("The E3 application could not render")
        st.error(str(exc))
        st.stop()


if __name__ == "__main__":
    render_app()
