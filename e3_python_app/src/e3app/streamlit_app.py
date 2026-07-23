"""Grant-focused Streamlit presentation over flexible DuckDB/Parquet sources."""

from __future__ import annotations

from typing import Sequence

import streamlit as st

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


def _render_section(
    *,
    connection: object,
    config: AppConfig,
    section: str,
) -> None:
    """Render one scientific section with its own relation and column controls."""
    specification = SECTION_SPECS[section]
    st.subheader(str(specification["title"]))
    st.caption(str(specification["description"]))
    relations = relations_for_section(connection, section)
    if not relations:
        st.info(
            "This release does not contain a recognised relation for this section. "
            "The absence is reported as unavailable evidence, not a biological negative."
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
    """Render grant outcomes, release coverage and interpretation boundaries."""
    st.subheader("Grant-aligned evidence overview")
    metrics = grant_overview(connection)
    first, second, third, fourth = st.columns(4)
    first.metric("Candidate groups", f"{metrics['candidate_count']:,}")
    second.metric("Milestone 1 passes", f"{metrics['prestructure_pass_count']:,}")
    third.metric("Final stringent passes", f"{metrics['final_pass_count']:,}")
    fourth.metric("3D-assessed groups", f"{metrics['structural_assessed_count']:,}")

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
            "coordinates and optional US-align/TM-align pocket equivalence."
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
    """Render a schema-agnostic fallback browser with column controls."""
    st.subheader("All imported results")
    st.caption(
        "Use this audit view for any relation not covered by a grant-facing section. "
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
    """Render the complete grant-focused resource explorer."""
    st.set_page_config(page_title="ARIA Plant E3 Resource", layout="wide")
    st.title("ARIA plant E3 discovery and ligandability resource")
    st.caption(
        "Read-only companion to the R Shiny reporter; DuckDB performs every "
        "bounded query over the integrated database or Parquet evidence."
    )
    try:
        config = config_from_environment()
        validate_config(config)
    except AppError as exc:
        st.error(str(exc))
        st.stop()
        return

    st.sidebar.header("Data release")
    st.sidebar.code(str(config.source_path))
    st.sidebar.caption(f"Source mode: {config.source_mode}")
    if config.expression_duckdb:
        st.sidebar.caption(f"Raw Expression Atlas: {config.expression_duckdb}")
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
                    "Candidates",
                    "Orthology",
                    "Domains",
                    "Expression",
                    "Ligandability",
                    "Pocket conservation",
                    "3D alignment",
                    "Accession search",
                    "All results",
                    "Provenance and QC",
                ]
            )
            with tabs[0]:
                _render_overview(connection=connection, config=config)
            for tab, section in zip(
                tabs[1:8],
                (
                    "candidates",
                    "orthology",
                    "domains",
                    "expression",
                    "ligandability",
                    "pocket_conservation",
                    "structural_alignment",
                ),
            ):
                with tab:
                    _render_section(
                        connection=connection,
                        config=config,
                        section=section,
                    )
            with tabs[8]:
                _render_search(connection=connection, max_rows=config.max_rows)
            with tabs[9]:
                _render_all_results(
                    connection=connection,
                    config=config,
                    relations=relations,
                )
            with tabs[10]:
                _render_section(
                    connection=connection,
                    config=config,
                    section="provenance",
                )
    except AppError as exc:
        st.error(str(exc))
        st.stop()


if __name__ == "__main__":
    render_app()
