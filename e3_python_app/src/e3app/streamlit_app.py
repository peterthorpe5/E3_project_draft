"""Thin Streamlit presentation layer for tested DuckDB query services."""

from __future__ import annotations

import streamlit as st

from e3app.config import config_from_environment, validate_config
from e3app.data import (
    list_relations,
    open_read_only,
    preview_relation,
    resource_overview,
    search_accession,
)
from e3app.errors import AppError


def render_app() -> None:
    """Render the complete resource browser with bounded, read-only queries."""

    st.set_page_config(page_title="ARIA E3 Discovery Resource", layout="wide")
    st.title("ARIA plant E3 discovery resource")
    st.caption("Read-only Python companion to the Shiny application")
    try:
        config = config_from_environment()
        validate_config(config)
    except AppError as exc:
        st.error(str(exc))
        st.stop()
        return

    st.sidebar.header("Data release")
    st.sidebar.code(str(config.resource_duckdb))
    if config.expression_duckdb:
        st.sidebar.caption(f"Expression: {config.expression_duckdb}")
    st.sidebar.caption(f"Maximum rows per query: {config.max_rows:,}")

    try:
        with open_read_only(config.resource_duckdb):
            pass
    except AppError as exc:
        st.error(str(exc))
        st.stop()
        return

    with open_read_only(config.resource_duckdb) as connection:
        relations = list_relations(connection)
        overview_tab, browse_tab, search_tab, provenance_tab = st.tabs(
            ["Overview", "Browse", "Accession search", "Provenance and QC"]
        )
        with overview_tab:
            st.subheader("Resource contents")
            if relations:
                overview = resource_overview(connection, relations)
                left, middle, right = st.columns(3)
                left.metric("Relations", len(overview))
                middle.metric("Rows", f"{int(overview['row_count'].sum()):,}")
                right.metric("Capabilities", int(overview["capability"].nunique()))
                st.dataframe(overview, use_container_width=True, hide_index=True)
            else:
                st.info("This DuckDB contains no user tables or views.")
        with browse_tab:
            st.subheader("Bounded table browser")
            if relations:
                relation = st.selectbox("Relation", relations)
                requested = st.number_input(
                    "Rows",
                    min_value=1,
                    max_value=config.max_rows,
                    value=min(100, config.max_rows),
                )
                st.dataframe(
                    preview_relation(connection, relation, int(requested)),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No relations are available to browse.")
        with search_tab:
            st.subheader("Exact accession search")
            query = st.text_input("UniProt or project accession", placeholder="Q9SA03")
            if query:
                matches = search_accession(connection, query, min(config.max_rows, 1000))
                if matches.empty:
                    st.warning("No exact accession match was found in recognised columns.")
                else:
                    st.dataframe(matches, use_container_width=True, hide_index=True)
        with provenance_tab:
            st.subheader("Provenance and quality-control relations")
            overview = resource_overview(connection, relations)
            selected = overview[overview["capability"] == "provenance"]
            if selected.empty:
                st.info("No provenance relation was detected by name or columns.")
            else:
                st.dataframe(selected, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    render_app()
