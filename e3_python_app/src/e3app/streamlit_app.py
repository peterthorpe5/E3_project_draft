"""Grant-focused Streamlit presentation over DuckDB and portable review data."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Sequence

import streamlit as st
import streamlit.components.v1 as components

from e3app.config import AppConfig, config_from_environment, validate_config
from e3app.data import (
    SECTION_SPECS,
    default_columns,
    grant_overview,
    list_relations,
    open_resource,
    preview_selected_columns,
    relation_columns,
    relations_for_section,
    resource_overview,
    search_accession,
)
from e3app.errors import AppError
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
    return float(st.session_state[number_key])


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
                    "Computational recommendations",
                    "Threshold explorer",
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
                _render_section(
                    connection=connection,
                    config=config,
                    section="final_recommendations",
                )
            with tabs[2]:
                _render_threshold_explorer(connection=connection, config=config)
            for tab, section in zip(
                tabs[3:9],
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
                    _render_section(
                        connection=connection,
                        config=config,
                        section=section,
                    )
            with tabs[9]:
                _render_pocket_review(bundle=pocket_review, focus="structure")
            with tabs[10]:
                _render_pocket_review(bundle=pocket_review, focus="alignment")
            with tabs[11]:
                _render_section(
                    connection=connection,
                    config=config,
                    section="structural_alignment",
                )
            with tabs[12]:
                _render_search(connection=connection, max_rows=config.max_rows)
            with tabs[13]:
                _render_all_results(
                    connection=connection,
                    config=config,
                    relations=relations,
                )
            with tabs[14]:
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
