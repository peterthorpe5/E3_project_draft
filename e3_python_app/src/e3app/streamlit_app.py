"""Grant-focused Streamlit presentation over DuckDB and portable review data."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Sequence

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

from e3app.config import AppConfig, config_from_environment, validate_config
from e3app.deepclust import (
    collect_deepclust_metrics,
    collect_deepclust_summary,
    collect_onekp_coverage_distribution,
    select_deepclust_relation,
)
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
    select_candidate_landscape_relation,
)
from e3app.errors import AppError
from e3app.enriched_hogs import (
    ENRICHED_HOG_LABELS,
    ENRICHED_HOG_MEMBERS,
    ENRICHED_HOG_OVERVIEW,
    collect_enriched_hog_results,
    enriched_hog_capability,
    enriched_hog_columns,
)
from e3app.exports import (
    dataframe_to_fasta_bytes,
    dataframe_display_formats,
    dataframe_display_widths,
    render_plotly_pdf_download,
    render_table_downloads,
)
from e3app.glossary import SLIDER_HELP, glossary_rows, glossary_sections
from e3app.human_hogs import (
    collect_human_hog_members,
    collect_human_hog_summary,
    human_hog_capability,
)
from e3app.pocket_review import (
    PocketReviewBundle,
    group_choice_labels,
    prepare_pocket_review,
    read_group_html,
    read_review_html,
    selected_group_alignment_fasta_bytes,
    selected_group_members,
    selected_group_row,
)
from e3app.prestructure_hogs import (
    collect_prestructure_ranked_hogs,
    prestructure_hog_capability,
)
from e3app.orthology import (
    collect_orthology_group_summary,
    collect_orthology_metrics,
    collect_orthology_size_distribution,
    collect_orthology_species,
    collect_seed_group_members,
    collect_seed_identifiers,
    load_species_taxonomy,
    select_orthology_relation,
    summarise_seed_groups,
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
    paired_threshold_settings,
    select_threshold_relation,
)
from e3app.tab_help import tab_help_text
from e3app.unified_search import (
    collect_unified_search,
    parse_search_terms,
    summarise_unified_search,
)
from e3app.visualisations import (
    ALL_FINAL_GATE_GROUPS,
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
    default_final_gate_druggability_group,
    filter_final_gate_druggability_distribution,
    final_gate_druggability_group_choices,
    prepare_candidate_landscape,
    prepare_final_gate_druggability_distribution,
    prepare_species_tissue_summary,
    selected_candidate_from_event,
    structural_alignment_plot_columns,
    summarise_final_gate_druggability_selection,
)
from e3app.workflow import workflow_schematic_html

LOGGER = logging.getLogger(__name__)
ORTHOLOGY_GROUP_LABELS = {
    "hierarchical_orthogroup": (
        "Root-level phylogenetic HOGs (N0.HOG…; recommended)"
    ),
    "orthogroup": "Original MCL orthogroups (OG…; broader legacy view)",
}
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
        "width": "stretch",
        "hide_index": True,
        "column_config": column_config,
    }
    arguments["height"] = 620 if height is None else height
    arguments["row_height"] = 36
    st.dataframe(**arguments)


def _render_tab_help(*, tab_name: str) -> None:
    """Render collapsed contextual guidance for one top-level tab."""
    with st.expander(label="❓ How to use this tab", expanded=False):
        st.write(tab_help_text(tab_name=tab_name))


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


def _orthology_group_type_control(*, key: str) -> str:
    """Render the shared OrthoFinder group-level selector."""
    selected_group_type = st.radio(
        "OrthoFinder grouping level",
        options=("hierarchical_orthogroup", "orthogroup"),
        format_func=lambda value: ORTHOLOGY_GROUP_LABELS[value],
        horizontal=True,
        key=key,
        help=(
            "HOG means hierarchical orthogroup. The N0 groups reconcile rooted "
            "gene trees with the species tree and are used by final prioritisation. "
            "The OG groups come from the original MCL-based Orthogroups.tsv output "
            "and are retained as a broader legacy view."
        ),
    )
    st.caption(
        "N0.HOG… = root-level phylogenetic hierarchical orthogroup; "
        "OG… = original MCL-based OrthoFinder orthogroup."
    )
    return selected_group_type


def _render_orthofinder_explorer(
    *, connection: object, config: AppConfig
) -> None:
    """Render release-wide OrthoFinder metrics, filters, plots and group table."""
    st.subheader("Expanded cross-species orthology")
    st.caption(
        "This page summarises OrthoFinder membership independently of DeepClust. "
        "The recommended N0 hierarchical orthogroups are phylogenetic evolutionary "
        "groups; the original OG groups are retained as a legacy MCL view. A "
        "DeepClust cluster remains a non-phylogenetic sequence-neighbourhood input "
        "to candidate discovery."
    )
    group_type = _orthology_group_type_control(key="orthology_group_type")
    relation = select_orthology_relation(
        relation_names=list_relations(connection),
        group_type=group_type,
    )
    if relation is None:
        st.info(
            "This release does not contain the selected OrthoFinder membership "
            "relation. Unavailable membership is not interpreted as absence."
        )
        _render_section(connection=connection, config=config, section="orthology")
        return
    try:
        metrics = collect_orthology_metrics(
            connection=connection,
            relation=relation,
        )
        species_values = collect_orthology_species(
            connection=connection,
            relation=relation,
        )
        distribution = collect_orthology_size_distribution(
            connection=connection,
            relation=relation,
        )
    except AppError as exc:
        st.warning(str(exc))
        return
    metric_columns = st.columns(6)
    metric_columns[0].metric("Input sequence memberships", f"{metrics['input_sequences']:,}")
    metric_columns[1].metric("Input species", f"{metrics['input_species']:,}")
    metric_columns[2].metric("OrthoFinder groups", f"{metrics['group_count']:,}")
    metric_columns[3].metric(
        "Groups with E3 seed evidence", f"{metrics['seeded_group_count']:,}"
    )
    metric_columns[4].metric(
        "Groups containing every species",
        f"{metrics['all_species_group_count']:,}",
    )
    metric_columns[5].metric(
        "Largest group",
        f"{metrics['largest_group_size']:,}",
        help=str(metrics["largest_group_id"]),
    )
    st.caption(
        f"Source: `{relation}`. Membership rows are counted as input sequence "
        "memberships; a sequence appearing in separate grouping levels is counted "
        "only within the currently selected level."
    )

    log_x, log_y = st.columns(2)
    with log_x:
        use_log_group_size = st.checkbox(
            "Log-transform group-size axis",
            value=False,
            key="orthology_log_group_size_axis",
        )
    with log_y:
        use_log_group_count = st.checkbox(
            "Log-transform group-count axis",
            value=False,
            key="orthology_log_group_count_axis",
        )
    figure = px.bar(
        distribution,
        x="member_count",
        y="group_count",
        color="species_breadth",
        labels={
            "member_count": "Members in OrthoFinder group",
            "group_count": "Number of groups",
            "species_breadth": "Species breadth",
        },
        title="OrthoFinder group-size distribution",
        color_discrete_map={
            "One species only": "#8c6bb1",
            "Multiple species (not all)": "#3182bd",
            "All input species": "#31a354",
        },
    )
    figure.update_layout(barmode="stack", legend_title_text="Species breadth")
    figure.update_xaxes(type="log" if use_log_group_size else "linear")
    figure.update_yaxes(type="log" if use_log_group_count else "linear")
    st.plotly_chart(
        figure,
        width="stretch",
        key="orthology_size_distribution_plot",
    )
    render_plotly_pdf_download(
        figure=figure,
        file_stem=f"{group_type}_size_distribution",
        label="Download group-size graph as PDF",
        key="orthology_size_distribution_pdf",
    )
    st.caption(
        "The purple category explicitly retains groups whose members all come "
        "from one species; it does not discard them as uninformative."
    )

    st.markdown("#### Filter OrthoFinder groups")
    filter_one, filter_two = st.columns(2)
    with filter_one:
        required_species = st.multiselect(
            "Must contain every selected species",
            species_values,
            key="orthology_required_species",
        )
        breadth = st.selectbox(
            "Species breadth",
            options=("all", "one_species", "multiple_species", "all_species"),
            format_func=lambda value: {
                "all": "All breadth classes",
                "one_species": "One species only",
                "multiple_species": "Multiple species, but not all",
                "all_species": "Every input species",
            }[value],
            key="orthology_breadth",
        )
    taxonomy = load_species_taxonomy()
    mapped_species = set(taxonomy["source_species_name"].dropna().astype(str))
    represented_taxonomy = taxonomy[
        taxonomy["source_species_name"].astype(str).isin(species_values)
    ].copy()
    with filter_two:
        taxonomy_roles = st.multiselect(
            "Must contain a member from any selected curated taxonomy role",
            options=sorted(represented_taxonomy["role"].dropna().astype(str).unique()),
            format_func=lambda value: value.replace("_", " ").title(),
            key="orthology_taxonomy_roles",
            help=(
                "This uses only the release's curated species manifest. Species "
                "without an authoritative mapping remain explicitly unclassified."
            ),
        )
        taxon_labels = {
            str(row.source_species_name): (
                f"{row.canonical_species_name} (NCBI taxon {int(row.taxon_id)})"
            )
            for row in represented_taxonomy.itertuples(index=False)
        }
        selected_taxa = st.multiselect(
            "Curated taxa (any selected taxon)",
            options=list(taxon_labels),
            format_func=taxon_labels.__getitem__,
            key="orthology_taxa",
        )
        seeded_only = st.checkbox(
            "Only groups linked to inherited E3 seed evidence",
            value=False,
            key="orthology_seeded_only",
        )
        maximum_rows = st.number_input(
            "Maximum groups to display",
            min_value=1,
            max_value=min(100_000, max(config.max_rows, 1)),
            value=min(1000, config.max_rows),
            key="orthology_maximum_rows",
        )
    role_species = represented_taxonomy[
        represented_taxonomy["role"].astype(str).isin(taxonomy_roles)
    ]["source_species_name"].dropna().astype(str).tolist()
    if taxonomy_roles and selected_taxa:
        taxonomy_species = sorted(set(role_species).intersection(selected_taxa))
    elif taxonomy_roles:
        taxonomy_species = role_species
    else:
        taxonomy_species = selected_taxa
    unmapped_count = len(set(species_values).difference(mapped_species))
    st.caption(
        f"Curated taxonomy mapping covers {len(set(species_values).intersection(mapped_species))} "
        f"of {len(species_values)} exact source labels; {unmapped_count} remain "
        "unclassified and are not silently assigned."
    )
    try:
        groups = collect_orthology_group_summary(
            connection=connection,
            relation=relation,
            required_species=required_species,
            taxonomy_species=taxonomy_species,
            breadth=breadth,
            seeded_only=seeded_only,
            maximum_rows=int(maximum_rows),
        )
    except AppError as exc:
        st.warning(str(exc))
        return
    if groups.empty:
        st.info("No OrthoFinder group matches the selected filters.")
    else:
        _display_dataframe(frame=groups, height=620)
        render_table_downloads(
            frame=groups,
            file_stem=f"filtered_{group_type}_summary",
            tsv_label="Download filtered groups as TSV",
            excel_label="Download filtered groups as Excel",
            key="orthology_group_summary_download",
        )
    with st.expander("Browse the underlying orthology relations"):
        _render_section(
            connection=connection,
            config=config,
            section="orthology",
            show_heading=False,
        )


def _render_deepclust_onekp_explorer(
    *, connection: object, config: AppConfig
) -> None:
    """Render candidate-relevant DeepClust coverage including parsed 1KP data."""
    st.markdown("### DeepClust and 1KP sequence neighbourhoods")
    st.caption(
        "This is the complementary discovery view. It includes 1KP sequences "
        "that were clustered by DeepClust, but it does not call them "
        "OrthoFinder orthologues. Rows are E3-seeded sequence neighbourhoods; "
        "membership alone is not evidence that every protein is an E3 ligase."
    )
    relation = select_deepclust_relation(
        relation_names=list_relations(connection)
    )
    if relation is None:
        st.info(
            "This release has no compact candidate-evidence relation, so "
            "DeepClust/1KP coverage is unavailable rather than zero."
        )
        return
    try:
        metrics = collect_deepclust_metrics(
            connection=connection,
            relation=relation,
        )
        distribution = collect_onekp_coverage_distribution(
            connection=connection,
            relation=relation,
        )
    except AppError as exc:
        st.warning(str(exc))
        return
    columns = st.columns(6)
    columns[0].metric("E3-seeded neighbourhoods", f"{metrics['cluster_count']:,}")
    columns[1].metric(
        "Raw cluster-member links",
        f"{metrics['raw_cluster_member_links']:,}",
    )
    columns[2].metric(
        "Strict cluster-member links",
        f"{metrics['strict_cluster_member_links']:,}",
    )
    columns[3].metric(
        "Neighbourhoods with raw 1KP",
        f"{metrics['clusters_with_raw_onekp']:,}",
    )
    columns[4].metric(
        "Neighbourhoods with strict 1KP",
        f"{metrics['clusters_with_strict_onekp']:,}",
    )
    columns[5].metric(
        "Strict 1KP cluster-species links",
        f"{metrics['strict_onekp_cluster_species_links']:,}",
        help=(
            "Sum of distinct parsed 1KP species within each cluster. The same "
            "species in two clusters contributes two links."
        ),
    )
    st.caption(
        "Source: `candidate_evidence`, derived from the full 1KP+ discovery "
        "resource. Counts are cluster-member, cluster-sample or cluster-species "
        "links and are labelled that way to avoid implying a global unique count."
    )
    log_x, log_y = st.columns(2)
    with log_x:
        use_log_onekp_species = st.checkbox(
            "Log-transform 1KP-species axis",
            value=False,
            key="deepclust_log_onekp_species_axis",
            help="The zero-coverage bar is omitted by a logarithmic x-axis.",
        )
    with log_y:
        use_log_neighbourhood_count = st.checkbox(
            "Log-transform neighbourhood-count axis",
            value=False,
            key="deepclust_log_neighbourhood_count_axis",
        )
    plotted_distribution = distribution
    if use_log_onekp_species:
        plotted_distribution = distribution[
            distribution["strict_onekp_species_count"] > 0
        ].copy()
        st.caption(
            "The log-scaled 1KP-species axis excludes the zero-coverage bin; "
            "turn log x off to restore it."
        )
    figure = px.bar(
        plotted_distribution,
        x="strict_onekp_species_count",
        y="cluster_count",
        labels={
            "strict_onekp_species_count": "Strict parsed 1KP species in neighbourhood",
            "cluster_count": "E3-seeded DeepClust neighbourhoods",
        },
        title="Strict 1KP species coverage across E3-seeded sequence neighbourhoods",
    )
    figure.update_traces(marker_color="#0b7a75")
    figure.update_xaxes(type="log" if use_log_onekp_species else "linear")
    figure.update_yaxes(
        type="log" if use_log_neighbourhood_count else "linear"
    )
    st.plotly_chart(
        figure,
        width="stretch",
        key="deepclust_onekp_coverage_plot",
    )
    render_plotly_pdf_download(
        figure=figure,
        file_stem="deepclust_onekp_species_coverage",
        label="Download 1KP coverage graph as PDF",
        key="deepclust_onekp_coverage_pdf",
    )

    st.markdown("#### Filter sequence neighbourhoods")
    first, second = st.columns(2)
    with first:
        seed_query = st.text_area(
            "Inherited E3 seed identifier(s)",
            value="",
            key="deepclust_seed_query",
            help=(
                "Paste one or several identifiers separated by spaces, new "
                "lines, commas or semicolons. Blank retains every seed."
            ),
        )
        seed_match_mode = st.radio(
            "When several seeds are entered",
            options=("any", "all"),
            format_func=lambda value: (
                "Match any entered seed" if value == "any" else "Match every entered seed"
            ),
            horizontal=True,
            key="deepclust_seed_match_mode",
        )
        cluster_query = st.text_input(
            "DeepClust representative contains",
            value="",
            key="deepclust_cluster_query",
        )
    with second:
        onekp_mode = st.selectbox(
            "1KP coverage",
            options=("all", "raw", "strict"),
            format_func=lambda value: {
                "all": "All neighbourhoods, including no 1KP coverage",
                "raw": "At least one raw 1KP member",
                "strict": "At least one strict 1KP member",
            }[value],
            key="deepclust_onekp_mode",
        )
        minimum_species = st.number_input(
            "Minimum strict parsed 1KP species",
            min_value=0,
            max_value=1_000_000,
            value=0,
            step=1,
            key="deepclust_minimum_onekp_species",
        )
        maximum_rows = st.number_input(
            "Maximum neighbourhoods to display",
            min_value=1,
            max_value=min(100_000, max(config.max_rows, 1)),
            value=min(1000, max(config.max_rows, 1)),
            step=100,
            key="deepclust_maximum_rows",
        )
    try:
        summary = collect_deepclust_summary(
            connection=connection,
            relation=relation,
            seed_queries=(seed_query,),
            match_mode=seed_match_mode,
            onekp_mode=onekp_mode,
            minimum_strict_onekp_species=int(minimum_species),
            cluster_query=cluster_query,
            maximum_rows=int(maximum_rows),
        )
    except AppError as exc:
        st.warning(str(exc))
        return
    if summary.empty:
        st.info("No DeepClust sequence neighbourhood matches the selected filters.")
        return
    _display_dataframe(frame=summary, height=650)
    render_table_downloads(
        frame=summary,
        file_stem="deepclust_onekp_sequence_neighbourhoods",
        tsv_label="Download filtered neighbourhoods as TSV",
        excel_label="Download filtered neighbourhoods as Excel",
        key="deepclust_onekp_summary_download",
    )
    st.caption(
        "The current integrated release publishes cluster-level 1KP counts, "
        "not its full 25-million-sequence member relation. Exact 1KP member "
        "rows therefore remain unavailable in this panel rather than being inferred."
    )


def _render_orthology_explorer(
    *, connection: object, config: AppConfig
) -> None:
    """Render separate OrthoFinder and DeepClust/1KP evidence views."""
    _render_orthofinder_explorer(connection=connection, config=config)
    st.divider()
    _render_deepclust_onekp_explorer(connection=connection, config=config)


def _seed_member_fasta(*, members: pd.DataFrame) -> bytes:
    """Build unique FASTA identifiers for selected seed-group member rows."""
    export = members.copy()
    export["fasta_identifier"] = (
        export["primary_group_id"].astype(str)
        + "|"
        + export["species"].astype(str)
        + "|"
        + export["internal_id"].astype(str)
    )
    return dataframe_to_fasta_bytes(
        frame=export,
        identifier_column="fasta_identifier",
        sequence_column="protein_sequence",
        description_columns=("raw_identifier", "parsed_accession"),
    )


def _filter_hog_frame(*, frame: pd.DataFrame, query: str) -> pd.DataFrame:
    """Apply a literal case-insensitive HOG/member filter to a result frame."""
    cleaned = query.strip().casefold()
    if not cleaned or frame.empty:
        return frame
    preferred = (
        "hog_id",
        "primary_group_id",
        "human_hog_representatives",
        "arabidopsis_hog_representatives",
        "human_accessions",
        "human_entries",
        "human_raw_identifiers",
        "parsed_accession",
        "parsed_entry",
        "raw_identifier",
        "available_aliases",
        "candidate_accessions",
        "matched_seed_ids_calculated",
        "matched_e3_seeds",
        "seed_protein_names",
    )
    columns = [column for column in preferred if column in frame.columns]
    if not columns:
        return frame.iloc[0:0].copy()
    mask = pd.Series(False, index=frame.index)
    for column in columns:
        mask |= frame[column].fillna("").astype(str).str.casefold().str.contains(
            cleaned,
            regex=False,
        )
    return frame.loc[mask].copy()


def _render_prestructure_ranked_hogs(
    *,
    connection: object,
    config: AppConfig,
) -> None:
    """Render an ungated top-N list using the recorded HOG rank directly."""
    st.subheader("Top pre-structure ranked HOGs")
    st.info(
        "This list applies no target-species, domain, expression, pocket, "
        "druggability or structural gate. It selects root-level N0.HOG… groups "
        "directly by the recorded pre-structure evolutionary-group rank."
    )
    capability = prestructure_hog_capability(connection=connection)
    if not capability["available"]:
        st.warning(
            "The loaded source does not contain both `primary_group_id` and an "
            "authoritative pre-structure evolutionary-group rank."
        )
        return
    maximum_allowed = min(config.max_rows, 10_000)
    controls = st.columns(spec=(1, 2))
    with controls[0]:
        requested_hogs = int(
            st.number_input(
                label="Number of ranked HOGs",
                min_value=1,
                max_value=maximum_allowed,
                value=min(200, maximum_allowed),
                step=50,
                key="prestructure_hog_top_n",
                help=(
                    "Returns this many root-level HOGs in ascending recorded "
                    "pre-structure rank. The default is the requested top 200."
                ),
            )
        )
    with controls[1]:
        filter_text = st.text_input(
            label="Filter within the selected top-ranked HOGs",
            value="",
            key="prestructure_hog_filter",
            placeholder="HOG ID, accession, seed, protein name or representative",
            help=(
                "Filtering changes only the displayed/downloaded subset; it does "
                "not recalculate or renumber the recorded ranking."
            ),
        )
    try:
        ranked_hogs = collect_prestructure_ranked_hogs(
            connection=connection,
            maximum_hogs=requested_hogs,
        )
    except AppError as exc:
        st.warning(str(exc))
        return
    displayed = _filter_hog_frame(frame=ranked_hogs, query=filter_text)
    rank_column = str(capability["rank_column"])
    ranks = pd.to_numeric(displayed[rank_column], errors="coerce").dropna()
    metrics = st.columns(spec=3)
    metrics[0].metric("Ranked HOGs returned", f"{len(displayed):,}")
    metrics[1].metric(
        "Best recorded rank",
        "—" if ranks.empty else f"{int(ranks.min()):,}",
    )
    metrics[2].metric(
        "Lowest recorded rank shown",
        "—" if ranks.empty else f"{int(ranks.max()):,}",
    )
    st.caption(
        f"Authoritative source: `{capability['relation']}`; rank field: "
        f"`{rank_column}`. Human and Arabidopsis representatives are added from "
        "root-level hierarchical membership where available."
    )
    _display_dataframe(frame=displayed, height=720)
    render_table_downloads(
        frame=displayed,
        file_stem=f"top_{requested_hogs}_prestructure_ranked_hogs",
        tsv_label="Download ranked HOGs as TSV",
        excel_label="Download ranked HOGs as Excel",
        key="prestructure_ranked_hogs_download",
    )


def _human_hog_member_fasta(*, members: pd.DataFrame) -> bytes:
    """Build FASTA for HOG-member rows with published protein sequences."""
    if "protein_sequence" not in members.columns:
        return b""
    export = members.loc[
        members["protein_sequence"].fillna("").astype(str).str.strip().ne("")
    ].copy()
    if export.empty:
        return b""
    export["fasta_identifier"] = (
        export["hog_id"].fillna("UNKNOWN_HOG").astype(str)
        + "|"
        + export["species"].fillna("UNKNOWN_SPECIES").astype(str)
        + "|"
        + export["parsed_accession"].fillna("").astype(str)
    )
    return dataframe_to_fasta_bytes(
        frame=export,
        identifier_column="fasta_identifier",
        sequence_column="protein_sequence",
        description_columns=("raw_identifier", "parsed_entry"),
    )


def _render_human_hog_explorer(
    *,
    connection: object,
    config: AppConfig,
    plant_required: bool,
) -> None:
    """Render complete human or plant-and-human root-level HOG evidence."""
    view = "plant_and_human" if plant_required else "human"
    title = "Plant and human HOGs" if plant_required else "Human-containing HOGs"
    stem = "plant_and_human_hogs" if plant_required else "human_hogs"
    st.subheader(title)
    if plant_required:
        st.caption(
            "Root-level phylogenetic hierarchical orthogroups containing at least "
            "one Homo sapiens sequence and at least one member from the 12 curated "
            "target plant species. This is evolutionary co-membership, not evidence "
            "that every member is an E3 ligase."
        )
    else:
        st.caption(
            "Every root-level N0.HOG… containing at least one Homo sapiens sequence. "
            "Candidate-ranking annotations are added where a HOG entered the E3 "
            "prioritisation; unranked HOGs remain visible and are not labelled as "
            "biological failures."
        )
    capability = human_hog_capability(connection=connection)
    if not capability["available"]:
        missing = ", ".join(capability["missing_columns"])
        st.info(
            "This source does not contain complete root-level hierarchical "
            f"membership. Missing fields: {missing}."
        )
        return
    ranking_relation = capability["ranking_relation"]
    st.caption(
        "Ranking source: "
        + (f"`{ranking_relation}`." if ranking_relation else "unavailable in this source.")
    )
    st.caption(
        "Every table repeats the HOG-level human and Arabidopsis representatives. "
        "Each value prefers the parsed protein accession, then the parsed entry, "
        "then the published raw identifier; multiple representatives are separated "
        "by semicolons and absent lineages are blank."
    )
    load_tables = st.checkbox(
        "Load this HOG view",
        value=False,
        key=f"{stem}_load",
        help=(
            "The complete OrthoFinder membership is queried only when selected, "
            "so the other large HOG tab does not load in the background."
        ),
    )
    if not load_tables:
        st.info("Select ‘Load this HOG view’ to query its summary and member tables.")
        return
    controls = st.columns(2)
    with controls[0]:
        maximum_rows = int(
            st.number_input(
                "Maximum rows per downloaded table",
                min_value=100,
                max_value=100_000,
                value=10_000,
                step=1_000,
                key=f"{stem}_maximum_rows",
            )
        )
    with controls[1]:
        filter_text = st.text_input(
            "Filter loaded HOGs or member identifiers",
            value="",
            key=f"{stem}_filter",
            placeholder="N0.HOG…, UniProt accession, entry, seed or name",
        )
    try:
        summary = collect_human_hog_summary(
            connection=connection,
            view=view,
            maximum_rows=maximum_rows,
        )
        human_members = collect_human_hog_members(
            connection=connection,
            view=view,
            member_scope="human",
            maximum_rows=maximum_rows,
        )
        all_members = collect_human_hog_members(
            connection=connection,
            view=view,
            member_scope="all",
            maximum_rows=maximum_rows,
        )
    except AppError as exc:
        st.warning(str(exc))
        return
    all_summary = summary
    all_human_members = human_members
    summary = _filter_hog_frame(frame=all_summary, query=filter_text)
    selected_hogs = set(summary["hog_id"].astype(str)) if not summary.empty else set()
    if filter_text.strip():
        matched_human = _filter_hog_frame(
            frame=all_human_members,
            query=filter_text,
        )
        selected_hogs.update(matched_human["hog_id"].astype(str))
        summary = all_summary[
            all_summary["hog_id"].astype(str).isin(selected_hogs)
        ]
        human_members = all_human_members[
            all_human_members["hog_id"].astype(str).isin(selected_hogs)
        ]
        all_members = all_members[all_members["hog_id"].astype(str).isin(selected_hogs)]
    metric_columns = st.columns(5)
    metric_columns[0].metric("HOGs", f"{len(summary):,}")
    metric_columns[1].metric("Human members", f"{len(human_members):,}")
    plant_members = (
        int((all_members["member_class"] == "TARGET_PLANT").sum())
        if "member_class" in all_members.columns
        else 0
    )
    metric_columns[2].metric("Target-plant members", f"{plant_members:,}")
    ranked = (
        int((summary["ranking_availability"] == "RANKED").sum())
        if "ranking_availability" in summary.columns
        else 0
    )
    metric_columns[3].metric("HOGs in candidate ranking", f"{ranked:,}")
    species_count = (
        all_members["species"].dropna().astype(str).nunique()
        if "species" in all_members.columns
        else 0
    )
    metric_columns[4].metric("Species represented", f"{species_count:,}")
    display_rows = min(config.max_rows, maximum_rows)
    st.markdown("#### HOG summary and candidate ranking")
    _display_dataframe(frame=summary.head(display_rows), height=520)
    render_table_downloads(
        frame=summary,
        file_stem=f"{stem}_summary",
        tsv_label="Download complete HOG summary as TSV",
        excel_label="Download complete HOG summary as Excel",
        key=f"{stem}_summary_download",
    )
    st.markdown("#### Human sequence annotations")
    _display_dataframe(frame=human_members.head(display_rows), height=560)
    render_table_downloads(
        frame=human_members,
        file_stem=f"{stem}_human_members",
        tsv_label="Download human members as TSV",
        excel_label="Download human members as Excel",
        key=f"{stem}_human_download",
    )
    st.markdown("#### Every member of the qualifying HOGs")
    st.caption(
        "Includes human, target-plant and any other named OrthoFinder input "
        "members. Sequence fields are populated only where the integrated release "
        "published candidate-linked member sequences."
    )
    _display_dataframe(frame=all_members.head(display_rows), height=620)
    render_table_downloads(
        frame=all_members,
        file_stem=f"{stem}_all_members",
        tsv_label="Download every HOG member as TSV",
        excel_label="Download every HOG member as Excel",
        key=f"{stem}_all_members_download",
    )
    fasta = _human_hog_member_fasta(members=all_members)
    if fasta:
        st.download_button(
            "Download available HOG-member protein sequences as FASTA",
            data=fasta,
            file_name=f"{stem}_available_member_sequences.fasta",
            mime="text/x-fasta",
            key=f"{stem}_member_fasta_download",
        )
    else:
        st.caption(
            "No protein sequences for these complete HOG memberships were "
            "published in the loaded integrated resource."
        )


def _render_seed_group_explorer(
    *, connection: object, config: AppConfig
) -> None:
    """Search inherited E3 seeds and return all members of matching groups."""
    st.subheader("E3 seed and OrthoFinder-group explorer")
    st.caption(
        "Select one or more inherited E3 seed identifiers to find their root-level "
        "phylogenetic hierarchical orthogroups or original MCL orthogroups, then "
        "inspect every sequence-bearing group member. A seed records prior E3 "
        "evidence; an unseeded member is not labelled non-E3."
    )
    seeds = collect_seed_identifiers(connection=connection)
    if not seeds:
        st.info(
            "This release has no sequence-bearing seeded-group relation, so seed "
            "search and member FASTA export are unavailable."
        )
        return
    group_type = _orthology_group_type_control(key="seed_explorer_group_type")
    relation = select_orthology_relation(
        relation_names=list_relations(connection),
        group_type=group_type,
    )
    species_values = (
        collect_orthology_species(connection=connection, relation=relation)
        if relation is not None
        else []
    )
    control_one, control_two = st.columns(2)
    with control_one:
        selected_seeds = st.multiselect(
            "E3 seed identifiers",
            seeds,
            key="seed_explorer_selected_seeds",
            placeholder="Search and select one or more seeds",
        )
    with control_two:
        match_mode = st.radio(
            "When several seeds are selected",
            options=("any", "all"),
            format_func=lambda value: (
                "Return groups containing any selected seed"
                if value == "any"
                else "Return only groups containing all selected seeds"
            ),
            key="seed_explorer_match_mode",
        )
    if not selected_seeds:
        st.info("Select at least one seed identifier to run the group search.")
        return
    try:
        all_members = collect_seed_group_members(
            connection=connection,
            seed_identifiers=selected_seeds,
            group_type=group_type,
            match_mode=match_mode,
            maximum_rows=min(100_000, max(config.max_rows, 10_000)),
        )
        group_summary = summarise_seed_groups(members=all_members)
    except AppError as exc:
        st.warning(str(exc))
        return
    if group_summary.empty:
        st.info("No OrthoFinder group contains the selected seed combination.")
        return
    st.markdown("#### Matching OrthoFinder groups")
    _display_dataframe(frame=group_summary, height=360)
    render_table_downloads(
        frame=group_summary,
        file_stem="seed_search_matching_groups",
        tsv_label="Download matching groups as TSV",
        excel_label="Download matching groups as Excel",
        key="seed_group_summary_download",
    )
    selected_groups = st.multiselect(
        "Groups to inspect",
        options=group_summary["primary_group_id"].astype(str).tolist(),
        default=group_summary["primary_group_id"].astype(str).tolist(),
        key="seed_explorer_selected_groups",
    )
    selected_species = st.multiselect(
        "Filter the member table by species",
        options=species_values,
        key="seed_explorer_species",
        help="No selection retains every species in the selected groups.",
    )
    members = all_members[
        all_members["primary_group_id"].astype(str).isin(selected_groups)
    ].copy()
    if selected_species:
        members = members[members["species"].astype(str).isin(selected_species)]
    st.markdown("#### Species and members in the selected groups")
    if members.empty:
        st.info("No members match the selected group and species filters.")
        return
    _display_dataframe(frame=members, height=650)
    render_table_downloads(
        frame=members.drop(columns=["protein_sequence"]),
        file_stem="seed_search_group_members",
        tsv_label="Download filtered member table as TSV",
        excel_label="Download filtered member table as Excel",
        key="seed_group_members_download",
    )
    try:
        fasta_payload = _seed_member_fasta(members=members)
    except (TypeError, ValueError) as exc:
        st.caption(f"Member FASTA is unavailable: {exc}")
    else:
        st.download_button(
            "Download filtered member protein sequences as FASTA",
            data=fasta_payload,
            file_name="seed_search_group_members.fasta",
            mime="text/x-fasta",
            key="seed_group_members_fasta_download",
        )
    if len(selected_groups) == 1:
        identifiers = {"primary_group_id": selected_groups[0]}
        evidence_relations = candidate_evidence_relations(
            connection=connection,
            identifiers=identifiers,
        )
        with st.expander("Associated evidence for the selected group"):
            if not evidence_relations:
                st.info("No compatible associated-evidence relation is available.")
            else:
                evidence_relation = st.selectbox(
                    "Evidence relation",
                    evidence_relations,
                    key="seed_explorer_evidence_relation",
                )
                evidence = collect_candidate_evidence(
                    connection=connection,
                    relation=evidence_relation,
                    identifiers=identifiers,
                    maximum_rows=min(config.max_rows, 10_000),
                )
                _display_dataframe(frame=evidence, height=460)
                render_table_downloads(
                    frame=evidence,
                    file_stem=(
                        f"{selected_groups[0]}_{evidence_relation}_evidence"
                    ),
                    tsv_label="Download associated evidence as TSV",
                    excel_label="Download associated evidence as Excel",
                    key="seed_group_evidence_download",
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
            width="stretch",
            key="structural_alignment_evidence_map",
        )
        render_plotly_pdf_download(
            figure=figure,
            file_stem=f"structural_alignment_{plot_relation}",
            label="Download alignment graph as PDF",
            key="structural_alignment_plot_pdf",
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
    st.markdown("#### Member druggability distributions by group")
    try:
        _, assessed_rows, _ = evaluate_thresholds(
            connection,
            final_druggability_settings(
                minimum_druggability_score=0.0,
                result_scope="all",
            ),
            row_limit,
        )
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
        assessed_cluster_column = next(
            (
                column
                for column in ("lead_cluster_id", "cluster_id")
                if column in assessed_rows.columns
            ),
            None,
        )
        if assessed_cluster_column is None:
            raise AppError(
                "Structurally assessed groups lack a lead cluster identifier"
            )
        eligible_cluster_ids = set(
            eligible_rows[cluster_column].dropna().astype(str).str.strip()
        )
        score_groups = assessed_rows.copy()
        score_groups["reaches_final_gate"] = (
            score_groups[assessed_cluster_column]
            .astype("string")
            .str.strip()
            .isin(eligible_cluster_ids)
        )
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
                ["_boxplot_rank", assessed_cluster_column],
                na_position="last",
                kind="stable",
            )
        score_groups = score_groups.drop_duplicates(assessed_cluster_column)
        score_relation, member_scores = collect_member_druggability_scores(
            connection=connection,
            cluster_ids=(
                score_groups[assessed_cluster_column].dropna().astype(str).tolist()
            ),
            max_rows=100_000,
        )
        prepared_rows, prepared_truncated = (
            prepare_final_gate_druggability_distribution(
                scores=member_scores,
                eligible_groups=score_groups,
                max_groups=2_000,
            )
        )
        group_choices = final_gate_druggability_group_choices(frame=prepared_rows)
        default_group = default_final_gate_druggability_group(frame=prepared_rows)
        group_values = list(group_choices)
        selector_key = "recommendation_druggability_group"
        if st.session_state.get(selector_key) not in group_choices:
            st.session_state[selector_key] = default_group
        selected_group = st.selectbox(
            "Evolutionary group to display",
            options=group_values,
            format_func=group_choices.__getitem__,
            key=selector_key,
            help=(
                "Search by rank, evolutionary-group identifier or lead cluster. "
                "Individual choices include every structurally assessed group with "
                "member-level selected-pocket scores."
            ),
        )
        plot_rows, overview_truncated = (
            filter_final_gate_druggability_distribution(
                frame=prepared_rows,
                selection=str(selected_group),
                max_all_groups=30,
            )
        )
        selection_summary = summarise_final_gate_druggability_selection(
            frame=plot_rows,
            threshold=float(selected_threshold),
        )
        figure = build_final_gate_druggability_boxplot(
            frame=plot_rows,
            threshold=float(selected_threshold),
        )
    except AppError as exc:
        st.info(f"The member-level box plot is unavailable: {exc}")
    else:
        if selected_group == ALL_FINAL_GATE_GROUPS:
            st.markdown("**Comparison view: all groups reaching the last gate**")
        else:
            st.markdown(
                "**Selected evolutionary group:** "
                f"{selection_summary['primary_group_id']}  |  "
                "**Lead cluster:** "
                f"{selection_summary['cluster_id']}"
            )
        summary_columns = st.columns(4)
        summary_columns[0].metric(
            "Groups displayed",
            f"{selection_summary['group_count']:,}",
        )
        summary_columns[1].metric(
            "Assessed members",
            f"{selection_summary['member_count']:,}",
        )
        summary_columns[2].metric(
            "Minimum member score",
            f"{selection_summary['minimum_score']:.3f}",
        )
        summary_columns[3].metric(
            f"Status at {selected_threshold:.2f}",
            str(selection_summary["status"]),
        )
        st.plotly_chart(
            figure,
            width="stretch",
            config={"displaylogo": False},
            key="recommendation_druggability_boxplot",
        )
        render_plotly_pdf_download(
            figure=figure,
            file_stem=(
                "final_gate_member_druggability_"
                f"threshold_{selected_threshold:.2f}".replace(".", "p")
            ),
            label="Download druggability box plot as PDF",
            key="recommendation_druggability_boxplot_pdf",
        )
        st.caption(
            "Each point is one assessed member's retained selected-pocket score. "
            "Individual choices show any scored structurally assessed group; the "
            "comparison option shows groups passing every other fixed final gate. "
            "The dashed line is the selected threshold. "
            f"Score source: `{score_relation}`."
        )
        if overview_truncated:
            st.info(
                "The all-groups comparison is limited to the first 30 groups "
                "reaching the last gate by final rank; every scored structurally "
                "assessed group remains available individually in the selector."
            )
        if prepared_truncated:
            st.info(
                "The selector reached its defensive limit of 2,000 structurally "
                "assessed groups."
            )
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
    st.session_state["threshold_result_scope"] = defaults["result_scope"]
    st.session_state.pop("threshold_mode", None)


def _active_threshold_settings() -> tuple[ThresholdSettings, ThresholdSettings]:
    """Render shared controls and return matched settings for both tables."""
    defaults = ThresholdSettings()
    if st.button("Reset current defaults", key="threshold_reset"):
        _reset_threshold_controls()
        st.rerun()
    st.markdown(
        "**Two matched result sets are shown below.** The pre-structure table "
        "uses the biological evidence gates. The structurally informed table "
        "uses the same gates plus every structural requirement."
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

    st.markdown("##### Structural thresholds")
    st.caption(
        "These controls affect only the structurally informed table. The "
        "pre-structure table is unchanged when they move."
    )
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
    return paired_threshold_settings(values=values, defaults=defaults)


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
        prestructure_settings, structural_settings = _active_threshold_settings()
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
    relation, prestructure_result, prestructure_summary = evaluate_thresholds(
        connection,
        prestructure_settings,
        int(requested_rows),
    )
    structural_relation, structural_result, structural_summary = evaluate_thresholds(
        connection,
        structural_settings,
        int(requested_rows),
    )
    if structural_relation != relation:
        raise AppError("Paired threshold evaluations selected different sources")
    metric_columns = st.columns(4)
    metric_columns[0].metric(
        "Evaluated evolutionary groups",
        f"{prestructure_summary['evaluated_count']:,}",
    )
    metric_columns[1].metric(
        "Pre-structure passes",
        f"{prestructure_summary['pass_count']:,}",
    )
    metric_columns[2].metric(
        "Structurally assessed",
        f"{structural_summary['structurally_assessed_count']:,}",
    )
    metric_columns[3].metric(
        "Structurally informed passes",
        f"{structural_summary['pass_count']:,}",
    )
    if relation == "final_evolutionary_candidate_prioritisation":
        st.caption(f"Using `{relation}`: one row per evolutionary group.")
    else:
        st.caption(
            f"Using `{relation}` as a compatibility source, with one deterministic "
            "lead row retained per evolutionary group."
        )
    st.markdown("### Pre-structure candidate list")
    st.caption(
        "Applies target-species, mandatory-species, E3-domain and expression "
        "gates. Structural controls do not affect this table. "
        f"One-gate near-misses: {prestructure_summary['near_miss_count']:,}."
    )
    _display_dataframe(frame=prestructure_result, height=700)
    render_table_downloads(
        frame=prestructure_result,
        file_stem="aria_e3_prestructure_custom_thresholds",
        tsv_label="Download pre-structure candidate list as TSV",
        excel_label="Download pre-structure candidate list as Excel",
        key="threshold_prestructure_download",
    )
    st.markdown("### Structurally informed candidate list")
    st.caption(
        "Applies every pre-structure gate plus pocket conservation, mapping, "
        "structural coverage, member druggability and strict 3D requirements. "
        "Only structurally assessed groups can pass. "
        f"One-gate near-misses: {structural_summary['near_miss_count']:,}."
    )
    _display_dataframe(frame=structural_result, height=700)
    render_table_downloads(
        frame=structural_result,
        file_stem="aria_e3_structural_custom_thresholds",
        tsv_label="Download structurally informed candidate list as TSV",
        excel_label="Download structurally informed candidate list as Excel",
        key="threshold_structural_download",
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
    st.caption(
        "Use **Download current view PDF** or **Download alignment PDF** inside "
        "the embedded report. Legacy compatible reports receive these controls "
        "automatically."
    )
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
    if focus == "alignment":
        try:
            alignment_fasta = selected_group_alignment_fasta_bytes(
                bundle=bundle,
                review_rank=int(row["review_rank"]),
            )
        except AppError as exc:
            st.caption(f"Alignment FASTA is unavailable: {exc}")
        else:
            st.download_button(
                label="Download selected MAFFT alignment as FASTA",
                data=alignment_fasta,
                file_name=f"{safe_group}_mafft_alignment.fasta",
                mime="text/x-fasta",
                key="pocket_review_alignment_fasta_download",
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
    """Render batch-capable cross-relation identifier and name search."""
    st.subheader("Multi-field E3 resource search")
    st.caption(
        "Paste one or several names, N0.HOG… IDs, OG… IDs, E3 seeds, UniProt "
        "accessions, gene names, entries or DeepClust identifiers. The result "
        "records the matched term, source relation and matched field before "
        "returning every available column from that source row."
    )
    with st.form("unified_resource_search"):
        query = st.text_area(
            "Search term(s)",
            value="",
            placeholder=(
                "One item per line, or separated by commas/semicolons\n"
                "Q9SA03\nN0.HOG0002084\nFB27"
            ),
            height=150,
        )
        match_mode = st.radio(
            "Matching method",
            options=("smart", "exact", "contains"),
            format_func=lambda value: {
                "smart": "Smart: exact identifiers plus partial name matching",
                "exact": "Exact identifiers or semicolon-list tokens only",
                "contains": "Literal contains matching across identifiers and names",
            }[value],
            horizontal=True,
        )
        maximum_rows_per_relation = int(
            st.number_input(
                "Maximum matching rows per source relation",
                min_value=1,
                max_value=min(10_000, max(1, max_rows)),
                value=min(250, max(1, max_rows)),
            )
        )
        submitted = st.form_submit_button("Search the complete loaded resource")
    if not submitted:
        return
    try:
        terms = parse_search_terms(value=query)
        matches = collect_unified_search(
            connection=connection,
            search_terms=terms,
            mode=match_mode,
            maximum_rows_per_relation=maximum_rows_per_relation,
            maximum_total_rows=min(100_000, max(10_000, max_rows)),
        )
    except AppError as exc:
        st.warning(str(exc))
        return
    if matches.empty:
        st.warning("No identifier or name match was found in recognised fields.")
        return
    summary = summarise_unified_search(matches=matches)
    matched_terms = summary["search_term"].nunique()
    matched_relations = summary["relation"].nunique()
    metrics = st.columns(3)
    metrics[0].metric("Entered terms matched", f"{matched_terms:,} / {len(terms):,}")
    metrics[1].metric("Source relations", f"{matched_relations:,}")
    metrics[2].metric("Matching source rows", f"{len(matches):,}")
    st.markdown("#### Match summary")
    _display_dataframe(frame=summary, height=360)
    render_table_downloads(
        frame=summary,
        file_stem="unified_search_summary",
        tsv_label="Download search summary as TSV",
        excel_label="Download search summary as Excel",
        key="unified_search_summary_download",
    )
    st.markdown("#### Complete matching rows")
    _display_dataframe(frame=matches, height=650)
    render_table_downloads(
        frame=matches,
        file_stem="unified_search_matches",
        tsv_label="Download complete matches as TSV",
        excel_label="Download complete matches as Excel",
        key="unified_search_matches_download",
    )


def _render_all_results(
    *,
    connection: object,
    config: AppConfig,
    relations: Sequence[str],
) -> None:
    """Render enriched HOG results and raw resource relations."""
    st.subheader("All results and complete HOG information")
    st.caption(
        "The enriched HOG views join membership, human and Arabidopsis "
        "representatives, pre-structure and post-structure rankings, and every "
        "field from the strongest HOG-linked ranking result. Raw relations remain "
        "available for exact source-level audit. Queries are bounded in DuckDB."
    )
    if not relations:
        st.info("No relations are available to browse.")
        return

    capability = enriched_hog_capability(connection=connection)
    virtual_results: list[str] = []
    if capability["available"]:
        virtual_results.append(ENRICHED_HOG_OVERVIEW)
    if capability["membership_available"]:
        virtual_results.append(ENRICHED_HOG_MEMBERS)
    result_choices = [*virtual_results, *relations]
    relation = st.selectbox(
        "Result view",
        result_choices,
        format_func=lambda value: ENRICHED_HOG_LABELS.get(value, value),
        key="all_results_relation",
        help=(
            "Choose an enriched joined view for complete HOG-level information, "
            "or a raw relation for its exact stored rows."
        ),
    )
    is_enriched = relation in ENRICHED_HOG_LABELS
    if is_enriched:
        available = enriched_hog_columns(
            connection=connection,
            result=relation,
        )
        if relation == ENRICHED_HOG_OVERVIEW:
            st.info(
                "One row represents one root HOG. Both canonical rank columns and "
                "the original source ranking fields are selectable. Canonical ranks "
                "use the strongest compatible field available in this release."
            )
        else:
            st.info(
                "One row represents one HOG member. HOG-level annotations and "
                "rankings repeat so each exported member row remains interpretable."
            )
    else:
        available = relation_columns(connection=connection, relation=relation)
        st.info(
            "This is a raw source relation. ‘Select all fields’ includes every "
            "stored field in this relation, but does not join other relations."
        )

    selector_key = f"all_results_columns_{relation}"
    current_selection = [
        column
        for column in st.session_state.get(selector_key, [])
        if column in available
    ]
    if not current_selection and selector_key not in st.session_state:
        current_selection = list(available[: min(18, len(available))])
    st.session_state[selector_key] = current_selection
    actions = st.columns(3)
    if actions[0].button(
        "Select all fields",
        key=f"all_results_select_all_{relation}",
    ):
        st.session_state[selector_key] = list(available)
    if actions[1].button(
        "First 18 fields",
        key=f"all_results_select_first_{relation}",
    ):
        st.session_state[selector_key] = list(available[: min(18, len(available))])
    if actions[2].button(
        "Clear fields",
        key=f"all_results_select_none_{relation}",
    ):
        st.session_state[selector_key] = []
    selected = st.multiselect(
        "Columns to display",
        available,
        key=selector_key,
        help=(
            "Select all fields for a complete export. The first fields in enriched "
            "views include both ranking stages and species representatives."
        ),
    )
    requested = st.number_input(
        "Rows to display",
        min_value=1,
        max_value=config.max_rows,
        value=min(100, config.max_rows),
        key="all_results_rows",
    )
    if selected:
        if is_enriched:
            result = collect_enriched_hog_results(
                connection=connection,
                result=relation,
                selected_columns=selected,
                maximum_rows=int(requested),
            )
        else:
            result = preview_selected_columns(
                connection=connection,
                relation=relation,
                columns=selected,
                limit=int(requested),
            )
        _display_dataframe(frame=result)
        render_table_downloads(
            frame=result,
            file_stem=f"all_results_{relation.strip('_')}",
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
        width="stretch",
        key="visual_candidate_landscape_plot",
        on_select="rerun",
        selection_mode="points",
    )
    render_plotly_pdf_download(
        figure=figure,
        file_stem="candidate_landscape",
        label="Download candidate landscape as PDF",
        key="visual_candidate_landscape_pdf",
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
        width="stretch",
        key=f"{key_prefix}_expression_heatmap_plot",
    )
    render_plotly_pdf_download(
        figure=figure,
        file_stem=f"{key_prefix}_candidate_expression_heatmap",
        label="Download expression heatmap as PDF",
        key=f"{key_prefix}_expression_heatmap_pdf",
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
        width="stretch",
        key="visual_species_tissue_profile_plot",
    )
    render_plotly_pdf_download(
        figure=figure,
        file_stem=f"{candidate_id}_species_tissue_profile",
        label="Download species/tissue graph as PDF",
        key="visual_species_tissue_profile_pdf",
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
        width="stretch",
        key=f"{key_prefix}_volcano_plot",
    )
    render_plotly_pdf_download(
        figure=figure,
        file_stem=f"{relation}_volcano_plot",
        label="Download volcano graph as PDF",
        key=f"{key_prefix}_volcano_pdf",
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
                    "Pre-structure ranked HOGs",
                    "Visual explorer",
                    "Candidates",
                    "Orthology",
                    "Human HOGs",
                    "Plant & human HOGs",
                    "Seed & HOG explorer",
                    "Domains",
                    "Expression",
                    "Ligandability",
                    "Pocket conservation",
                    "3D structures & pockets",
                    "Pocket-aligned sequences",
                    "3D alignment",
                    "Computational chemistry",
                    "Search",
                    "All results",
                    "Provenance and QC",
                ]
            )
            with tabs[0]:
                _render_tab_help(tab_name="Overview")
                _render_overview(connection=connection, config=config)
            with tabs[1]:
                _render_tab_help(tab_name="Workflow schematic")
                _render_workflow_schematic()
            with tabs[2]:
                _render_tab_help(tab_name="Glossary")
                _render_glossary()
            with tabs[3]:
                _render_tab_help(tab_name="Computational recommendations")
                _render_computational_recommendations(
                    connection=connection,
                    config=config,
                )
            with tabs[4]:
                _render_tab_help(tab_name="Threshold explorer")
                _render_threshold_explorer(connection=connection, config=config)
            with tabs[5]:
                _render_tab_help(tab_name="Pre-structure ranked HOGs")
                _render_prestructure_ranked_hogs(
                    connection=connection,
                    config=config,
                )
            with tabs[6]:
                _render_tab_help(tab_name="Visual explorer")
                _render_visual_explorer(connection=connection, config=config)
            with tabs[7]:
                _render_tab_help(tab_name="Candidates")
                _render_section(
                    connection=connection,
                    config=config,
                    section="candidates",
                )
            with tabs[8]:
                _render_tab_help(tab_name="Orthology")
                _render_orthology_explorer(
                    connection=connection,
                    config=config,
                )
            with tabs[9]:
                _render_tab_help(tab_name="Human HOGs")
                _render_human_hog_explorer(
                    connection=connection,
                    config=config,
                    plant_required=False,
                )
            with tabs[10]:
                _render_tab_help(tab_name="Plant & human HOGs")
                _render_human_hog_explorer(
                    connection=connection,
                    config=config,
                    plant_required=True,
                )
            with tabs[11]:
                _render_tab_help(tab_name="Seed & HOG explorer")
                _render_seed_group_explorer(
                    connection=connection,
                    config=config,
                )
            for tab, section, tab_name in zip(
                tabs[12:16],
                ("domains", "expression", "ligandability", "pocket_conservation"),
                ("Domains", "Expression", "Ligandability", "Pocket conservation"),
                strict=True,
            ):
                with tab:
                    _render_tab_help(tab_name=tab_name)
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
            with tabs[16]:
                _render_tab_help(tab_name="3D structures & pockets")
                _render_pocket_review(bundle=pocket_review, focus="structure")
            with tabs[17]:
                _render_tab_help(tab_name="Pocket-aligned sequences")
                _render_pocket_review(bundle=pocket_review, focus="alignment")
            with tabs[18]:
                _render_tab_help(tab_name="3D alignment")
                _render_structural_alignment_section(
                    connection=connection,
                    config=config,
                )
            with tabs[19]:
                _render_tab_help(tab_name="Computational chemistry")
                _render_section(
                    connection=connection,
                    config=config,
                    section="computational_chemistry",
                )
            with tabs[20]:
                _render_tab_help(tab_name="Search")
                _render_search(connection=connection, max_rows=config.max_rows)
            with tabs[21]:
                _render_tab_help(tab_name="All results")
                _render_all_results(
                    connection=connection,
                    config=config,
                    relations=relations,
                )
            with tabs[22]:
                _render_tab_help(tab_name="Provenance and QC")
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
