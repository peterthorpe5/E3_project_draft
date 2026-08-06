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
    relation_columns,
    relations_for_section,
    resource_overview,
    search_accession,
    select_candidate_landscape_relation,
)
from e3app.errors import AppError
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
from e3app.thresholds import (
    LOGICAL_THRESHOLD_FIELDS,
    NUMERIC_THRESHOLD_FIELDS,
    ThresholdSettings,
    evaluate_thresholds,
    threshold_settings_from_mapping,
)
from e3app.visualisations import (
    CANDIDATE_METRIC_LABELS,
    EXPRESSION_CONTEXT_LABELS,
    build_candidate_landscape_figure,
    build_expression_heatmap_figure,
    build_species_tissue_profile_figure,
    build_volcano_figure,
    candidate_colour_columns,
    candidate_display_labels,
    candidate_identifier_column,
    candidate_identifiers_from_row,
    candidate_landscape_columns,
    candidate_metric_columns,
    candidate_rank_column,
    prepare_candidate_landscape,
    prepare_species_tissue_summary,
    selected_candidate_from_event,
)

LOGGER = logging.getLogger(__name__)


def _render_section(
    *,
    connection: object,
    config: AppConfig,
    section: str,
) -> None:
    """Render one scientific section with independent table controls."""
    specification = SECTION_SPECS[section]
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
    st.dataframe(result, use_container_width=True, hide_index=True)
    st.download_button(
        "Download displayed rows as TSV",
        data=result.to_csv(sep="\t", index=False),
        file_name=f"{section}_{relation}.tsv",
        mime="text/tab-separated-values",
        key=f"{section}_download",
    )


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
    st.dataframe(result, use_container_width=True, hide_index=True, height=650)
    st.download_button(
        "Download filtered candidate-by-tissue rows as TSV",
        data=result.to_csv(sep="\t", index=False),
        file_name="candidate_expression_by_tissue.tsv",
        mime="text/tab-separated-values",
        key="expression_context_download",
    )
    with st.expander("Mapping summary and audit relations"):
        _render_section(connection=connection, config=config, section="expression")


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
        st.dataframe(overview, use_container_width=True, hide_index=True)
    st.caption(
        f"Source mode: {config.source_mode}; read-only source: {config.source_path}"
    )


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
        "These definitions describe the completed top-200 analysis. Threshold-explorer "
        "changes create sensitivity lists and do not rewrite the recorded primary result."
    )
    selected_section = st.selectbox(
        "Glossary section",
        options=glossary_sections(),
        key="glossary_section",
    )
    rows = glossary_rows(selected_section)
    st.dataframe(rows, use_container_width=True, hide_index=True)
    all_rows = [
        {"Section": section, **row}
        for section in glossary_sections()
        for row in glossary_rows(section)
    ]
    export = pd.DataFrame(all_rows)
    st.download_button(
        "Download complete glossary as TSV",
        data=export.to_csv(sep="\t", index=False),
        file_name="aria_e3_scientific_glossary.tsv",
        mime="text/tab-separated-values",
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
    st.dataframe(result, use_container_width=True, hide_index=True, height=700)
    st.download_button(
        "Download custom candidate list as TSV",
        data=result.to_csv(sep="\t", index=False),
        file_name=f"aria_e3_{settings.mode}_custom_thresholds.tsv",
        mime="text/tab-separated-values",
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
    st.dataframe(members, use_container_width=True, hide_index=True)
    safe_group = "".join(
        character if character.isalnum() or character in "_.-" else "_"
        for character in str(row["primary_group_id"])
    )
    download_one, download_two = st.columns(2)
    with download_one:
        st.download_button(
            "Download selected member table as TSV",
            data=members.to_csv(sep="\t", index=False),
            file_name=f"{safe_group}_{focus}_members.tsv",
            mime="text/tab-separated-values",
            key=f"pocket_review_{focus}_members_download",
        )
    with download_two:
        st.download_button(
            "Download the self-contained group review HTML",
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
        st.dataframe(matches, use_container_width=True, hide_index=True)


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
        st.dataframe(
            preview_selected_columns(
                connection,
                relation,
                selected,
                int(requested),
            ),
            use_container_width=True,
            hide_index=True,
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
    st.dataframe(
        pd.DataFrame([row[display_columns].to_dict()]),
        use_container_width=True,
        hide_index=True,
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
    st.dataframe(evidence, use_container_width=True, hide_index=True, height=520)
    st.download_button(
        "Download selected candidate evidence as TSV",
        data=evidence.to_csv(sep="\t", index=False),
        file_name=f"{selected_key}_{evidence_relation}.tsv".replace(":", "_"),
        mime="text/tab-separated-values",
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
    selected_key: str,
    rank_column: str | None,
    expression_relation: str,
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
    current = list(st.session_state.get("visual_heatmap_candidates", []))
    if linked_value and linked_value not in current:
        current = [linked_value, *current]
    if not current:
        current = options[: min(10, len(options))]
    st.session_state["visual_heatmap_candidates"] = [
        value for value in current if value in options
    ][:25]
    selected_candidates = st.multiselect(
        "Candidate groups (maximum 25)",
        options,
        format_func=lambda value: labels[value],
        key="visual_heatmap_candidates",
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
            key="visual_heatmap_context",
        )
    with control_two:
        expression_unit = st.selectbox(
            "Expression unit",
            units,
            key="visual_heatmap_unit",
        )
    with control_three:
        species = st.selectbox(
            "Species",
            ["All", *species_values],
            key="visual_heatmap_species",
        )
    with control_four:
        log_transform = st.checkbox(
            "Use log2(1 + expression)",
            value=True,
            key="visual_heatmap_log",
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
        key="visual_expression_heatmap_plot",
    )
    st.markdown("#### Aggregated heatmap cells")
    st.dataframe(cells, use_container_width=True, hide_index=True, height=460)
    st.download_button(
        "Download expression heatmap cells as TSV",
        data=cells.to_csv(sep="\t", index=False),
        file_name="candidate_expression_heatmap_cells.tsv",
        mime="text/tab-separated-values",
        key="visual_heatmap_download",
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
        st.dataframe(
            pd.DataFrame([selected_row[evidence_state_columns].to_dict()]),
            use_container_width=True,
            hide_index=True,
        )
    st.markdown("#### Aggregated species/tissue profile")
    st.dataframe(profile, use_container_width=True, hide_index=True)
    st.markdown("#### Exact Expression Atlas rows behind the profile")
    if len(rows) >= int(maximum_rows):
        st.info(
            "The exact-row table reached its selected display/download limit. "
            "The plotted species/tissue summary is still complete because it was "
            "aggregated before that limit."
        )
    st.dataframe(rows, use_container_width=True, hide_index=True, height=620)
    st.download_button(
        "Download exact species/tissue expression rows as TSV",
        data=rows.to_csv(sep="\t", index=False),
        file_name=f"{candidate_id}_species_tissue_expression.tsv".replace(":", "_"),
        mime="text/tab-separated-values",
        key="visual_profile_download",
    )


def _render_volcano_view(*, connection: object) -> None:
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
        key="visual_volcano_relation",
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
            key="visual_volcano_effect",
        )
    with threshold_two:
        significance_threshold = st.number_input(
            "Significance threshold",
            min_value=0.000001,
            max_value=1.0,
            value=0.05,
            format="%.6f",
            key="visual_volcano_significance",
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
    st.plotly_chart(figure, use_container_width=True, key="visual_volcano_plot")
    st.dataframe(rows, use_container_width=True, hide_index=True, height=520)
    st.download_button(
        "Download plotted differential-expression rows as TSV",
        data=rows.to_csv(sep="\t", index=False),
        file_name=f"{relation}_volcano_rows.tsv",
        mime="text/tab-separated-values",
        key="visual_volcano_download",
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
                    "Accession search",
                    "All results",
                    "Provenance and QC",
                ]
            )
            with tabs[0]:
                _render_overview(connection=connection, config=config)
            with tabs[1]:
                _render_glossary()
            with tabs[2]:
                _render_section(
                    connection=connection,
                    config=config,
                    section="final_recommendations",
                )
            with tabs[3]:
                _render_threshold_explorer(connection=connection, config=config)
            with tabs[4]:
                _render_visual_explorer(connection=connection, config=config)
            for tab, section in zip(
                tabs[5:11],
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
            with tabs[11]:
                _render_pocket_review(bundle=pocket_review, focus="structure")
            with tabs[12]:
                _render_pocket_review(bundle=pocket_review, focus="alignment")
            with tabs[13]:
                _render_section(
                    connection=connection,
                    config=config,
                    section="structural_alignment",
                )
            with tabs[14]:
                _render_search(connection=connection, max_rows=config.max_rows)
            with tabs[15]:
                _render_all_results(
                    connection=connection,
                    config=config,
                    relations=relations,
                )
            with tabs[16]:
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
