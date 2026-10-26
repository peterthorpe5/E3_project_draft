"""Top-level resource search, complete HOG dossiers and uncapped result downloads."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Sequence

import duckdb
import pandas as pd
import streamlit as st

from e3app.complete_exports import complete_excel_workbook, complete_tsv_archive
from e3app.config import AppConfig
from e3app.data import list_relations, relation_columns
from e3app.enriched_hogs import (
    ENRICHED_HOG_LABELS,
    ENRICHED_HOG_MEMBERS,
    ENRICHED_HOG_OVERVIEW,
    enriched_hog_capability,
    enriched_hog_columns,
)
from e3app.errors import AppError
from e3app.exports import (
    EXCEL_MIME_TYPE,
    dataframe_display_formats,
    dataframe_display_widths,
    render_table_downloads,
    safe_file_stem,
)
from e3app.protein_dossier import (
    RECORDED_GROUP_RANKINGS,
    build_group_dossier,
    canonical_group_ranks,
    dossier_inventory,
    resolve_search_groups,
)
from e3app.result_queries import (
    ResourceQuery,
    build_result_query,
    build_search_queries,
    preview_query,
    query_count,
    summarise_search_queries,
)
from e3app.unified_search import parse_search_terms

LOGGER = logging.getLogger(__name__)


def source_identity(*, config: AppConfig) -> str:
    """Fingerprint the configured source to prevent stale cross-release downloads.

    Args:
        config: Validated application source configuration.

    Returns:
        A deterministic identity covering the source path and modification state.
    """
    source = Path(config.source_path)
    paths = sorted(source.rglob("*.parquet")) if source.is_dir() else [source]
    state = [(str(path.resolve()), path.stat().st_mtime_ns, path.stat().st_size) for path in paths]
    return hashlib.sha256(repr((str(source.resolve()), state)).encode("utf-8")).hexdigest()


def _show_table(*, frame: pd.DataFrame, height: int = 420) -> None:
    """Show a readable preview with preserved field names and numeric values.

    Args:
        frame: Bounded screen table.
        height: Table height in pixels.
    """
    formats = dataframe_display_formats(frame=frame)
    widths = dataframe_display_widths(frame=frame)
    st.dataframe(
        frame,
        width="stretch",
        height=height,
        hide_index=True,
        column_config={
            column: (
                st.column_config.NumberColumn(column, format=formats[column], width=widths[column])
                if column in formats
                else st.column_config.Column(column, width=widths[column])
            )
            for column in frame.columns
        },
    )


def render_complete_export(
    *,
    connection: duckdb.DuckDBPyConnection,
    queries: Sequence[ResourceQuery],
    description: str,
    source: str,
    key: str,
    file_stem: str,
) -> None:
    """Prepare complete downloads explicitly and invalidate stale prepared payloads.

    Args:
        connection: Open resource connection.
        queries: Complete queries, independent of visible rows and fields.
        description: Applied source and selection provenance.
        source: Current source fingerprint.
        key: Unique widget/cache key for this export panel.
        file_stem: Download filename stem.
    """
    export_format = st.radio(
        "Complete download format",
        options=("tsv", "excel"),
        format_func=lambda value: {"tsv": "TSV archive (ZIP)", "excel": "Excel workbook"}[value],
        horizontal=True,
        key=f"{key}_format",
        help=(
            "Both formats include every matching row and field. TSV retains long sequences "
            "and annotations. Excel splits large tables across sheets and reports a clear "
            "error if a cell exceeds Excel's text limit; use TSV in that case."
        ),
    )
    signature = hashlib.sha256(
        repr((source, queries, description, export_format)).encode()
    ).hexdigest()
    payload_key = f"{key}_prepared"
    prepared = st.session_state.get(payload_key)
    if prepared is not None and prepared[0] != signature:
        st.session_state.pop(payload_key)
        prepared = None
    if st.button("Prepare complete download", key=f"{key}_prepare", disabled=not queries):
        try:
            exporter = complete_tsv_archive if export_format == "tsv" else complete_excel_workbook
            with st.spinner("Preparing every matching row and field…"):
                payload = exporter(connection=connection, queries=queries, description=description)
            prepared = (signature, payload)
            st.session_state[payload_key] = prepared
            LOGGER.info("Prepared complete resource download key=%s bytes=%d", key, len(payload))
        except (AppError, OSError, ValueError) as exc:
            st.session_state.pop(payload_key, None)
            LOGGER.exception("Could not prepare complete resource download %s", key)
            st.error(str(exc))
            return
    if prepared is not None:
        extension = "zip" if export_format == "tsv" else "xlsx"
        label = "TSV ZIP" if export_format == "tsv" else "Excel"
        st.download_button(
            label=f"Download all matching rows and fields ({label})",
            data=prepared[1],
            file_name=f"{safe_file_stem(value=file_stem)}.{extension}",
            mime="application/zip" if export_format == "tsv" else EXCEL_MIME_TYPE,
            key=f"{key}_download",
            on_click="ignore",
        )
        st.caption(f"Prepared complete download: {len(prepared[1]) / 1024**2:.2f} MiB.")


def _preview_fields(*, columns: Sequence[str], key: str) -> list[str]:
    """Choose preview-only fields without restricting complete export contents.

    Args:
        columns: Every field available in the selected result.
        key: Stable per-source widget key.

    Returns:
        Fields to show on screen, including an explicitly empty selection.
    """
    available = list(columns)
    if key in st.session_state:
        st.session_state[key] = [value for value in st.session_state[key] if value in available]
    else:
        st.session_state[key] = available[:18]
    actions = st.columns(2)
    if actions[0].button("Show all fields", key=f"{key}_all"):
        st.session_state[key] = available
    if actions[1].button("Show first 18 fields", key=f"{key}_first"):
        st.session_state[key] = available[:18]
    return st.multiselect(
        "Preview fields",
        available,
        key=key,
        help=(
            "This controls the screen and preview download. Complete downloads "
            "always include all fields."
        ),
    )


def render_all_results(
    *,
    connection: duckdb.DuckDBPyConnection,
    config: AppConfig,
) -> None:
    """Browse complete results with pre-limit filtering and separate full exports.

    Args:
        connection: Open resource connection.
        config: Validated source and screen-preview configuration.
    """
    st.subheader("All results and complete downloads")
    st.caption(
        "Choose a result view and optionally find a HOG, protein or name across the full view. "
        "Rows and fields shown on screen are a preview. Complete downloads include all matching "
        "rows and all fields, regardless of those preview settings."
    )
    relations = list_relations(connection=connection)
    if not relations:
        st.info("No relations are available to browse.")
        return
    capability = enriched_hog_capability(connection=connection)
    virtual = [ENRICHED_HOG_OVERVIEW] if capability["available"] else []
    if capability["membership_available"]:
        virtual.append(ENRICHED_HOG_MEMBERS)
    result = st.selectbox(
        "Result view",
        [*virtual, *relations],
        key="all_results_relation",
        format_func=lambda value: ENRICHED_HOG_LABELS.get(value, value),
        help="Choose joined HOG results with rankings, or an exact raw source relation.",
    )
    filter_text = st.text_area(
        "Find within this complete result (optional)",
        key="all_results_filter",
        placeholder="One HOG, protein accession or name per line; leave empty for all results.",
        help=(
            "Filtering runs before the display limit and searches recognised identifier/name "
            "fields including those hidden in the preview. Use Protein & HOG search for "
            "links across sources."
        ),
        height=90,
    )
    mode = st.selectbox(
        "Result matching method",
        ("smart", "exact", "contains"),
        key="all_results_mode",
        help="Smart uses exact IDs and partial names; exact avoids partial HOG/accession matches.",
    )
    try:
        terms = parse_search_terms(value=filter_text)
        complete = build_result_query(connection=connection, result=result, terms=terms, mode=mode)
        count = query_count(connection=connection, query=complete)
        available = (
            enriched_hog_columns(connection=connection, result=result)
            if result in ENRICHED_HOG_LABELS
            else relation_columns(connection, result)
        )
        st.metric("Complete matching rows", f"{count:,}")
        st.caption(f"Complete result: {count:,} rows × {len(available):,} fields.")
        st.markdown("#### Complete download")
        st.caption(
            "Leave the filter empty to download every row in this result view. Each raw relation "
            "keeps its own granularity. Use a group dossier to collect linked evidence "
            "across sources."
        )
        render_complete_export(
            connection=connection,
            queries=(complete,),
            source=source_identity(config=config),
            description=(
                f"Source: {config.source_path}; result: {result}; "
                f"terms: {terms!r}; mode: {mode}"
            ),
            key="all_results_complete",
            file_stem=f"complete_{result.strip('_')}",
        )
        st.markdown("#### Screen preview")
        selected = _preview_fields(columns=available, key=f"all_results_columns_{result}")
        rows = st.number_input(
            "Rows to display",
            min_value=1,
            max_value=config.max_rows,
            value=min(100, config.max_rows),
            key="all_results_rows",
            help=(
                "Screen preview only. This never limits a complete download or the search scope."
            ),
        )
        if not selected:
            st.info(
                "Choose preview fields to show a table. The complete download remains available."
            )
            return
        preview = preview_query(connection=connection, query=complete, maximum_rows=int(rows))
        preview = preview.loc[:, selected]
        st.caption(
            f"Showing {len(preview):,} of {count:,} matching rows; "
            f"{len(selected):,} preview fields."
        )
        _show_table(frame=preview)
        render_table_downloads(
            frame=preview,
            file_stem=f"preview_{result.strip('_')}",
            tsv_label="Download this preview as TSV",
            excel_label="Download this preview as Excel",
            key="all_results_preview",
        )
    except AppError as exc:
        st.error(str(exc))


def _render_group_dossier(
    *,
    connection: duckdb.DuckDBPyConnection,
    config: AppConfig,
    group_id: str,
) -> None:
    """Show rankings, inventory, source previews and a complete selected-group export.

    Args:
        connection: Open resource connection.
        config: Current source and preview configuration.
        group_id: Exact recorded group selected from complete search results.
    """
    st.markdown(f"#### Evidence dossier: {group_id}")
    queries = build_group_dossier(connection=connection, group_id=group_id)
    inventory = dossier_inventory(connection=connection, queries=queries)
    available = inventory.loc[inventory["complete_rows"] > 0]
    if available.empty:
        st.info("No linked evidence is available for this group in the loaded resource.")
        return
    overview = next((query for query in queries if query.name == ENRICHED_HOG_OVERVIEW), None)
    members = None
    if overview is not None:
        frame = preview_query(connection=connection, query=overview, maximum_rows=1)
        if not frame.empty:
            members = frame.iloc[0]["hog_member_count"]
    ranks = canonical_group_ranks(
        connection=connection,
        query=next((query for query in queries if query.name == RECORDED_GROUP_RANKINGS), None),
    )
    metrics = st.columns(3)
    for column, (label, stage) in zip(
        metrics[:2],
        (
            ("Rank before structural analysis", "Group rank before structural analysis"),
            ("Rank after structural analysis", "Group rank after structural analysis"),
        ),
        strict=True,
    ):
        rank = ranks.loc[ranks["rank_stage"] == stage]
        column.metric(label, "Unavailable" if rank.empty else f"{rank.iloc[0]['numeric_rank']:g}")
    metrics[2].metric(
        "Recorded HOG members", "Unavailable" if pd.isna(members) else f"{int(members):,}"
    )
    if not ranks.empty:
        _show_table(frame=ranks.drop(columns="numeric_rank"), height=150)
    st.caption(
        "Ranks are the recorded resource-wide ranks, not positions within this search. A blank "
        "rank means unavailable. Source tables retain every original ranking/evidence field."
    )
    st.markdown("**Complete evidence inventory**")
    _show_table(frame=available, height=300)
    with st.expander("❓ What does this dossier include?"):
        st.markdown(
            "The joined HOG overview and members, plus raw rows connected through recorded HOG, "
            "contributing-cluster and protein identifiers: rankings, domains, expression, "
            "structure/pocket evidence and other linked annotations present in this release. "
            "Raw rows include the linking fields for audit. Shared identifiers may retain "
            "context from another recorded group; this does not assert identical membership. "
            "External records and structure files in separate review bundles are not embedded. "
            "Missing annotation remains unavailable. The archive manifest also lists "
            "zero-row sources."
        )
    render_complete_export(
        connection=connection,
        queries=queries,
        source=source_identity(config=config),
        description=f"Source: {config.source_path}; complete linked group dossier: {group_id}",
        key="group_dossier_complete",
        file_stem=f"dossier_{group_id}",
    )
    selected_key = "dossier_source"
    sources = available["source"].tolist()
    if st.session_state.get(selected_key) not in sources:
        st.session_state.pop(selected_key, None)
    source = st.selectbox(
        "Inspect an evidence source",
        sources,
        key=selected_key,
        format_func=lambda value: ENRICHED_HOG_LABELS.get(value, value),
        help="Every source listed in the inventory is included in the complete dossier download.",
    )
    query = next(query for query in queries if query.name == source)
    frame = preview_query(
        connection=connection, query=query, maximum_rows=min(config.max_rows, 100)
    )
    st.caption(
        f"Source preview: first {len(frame):,} rows. The dossier contains its "
        "complete rows and fields."
    )
    _show_table(frame=frame, height=500)


def render_resource_search(
    *,
    connection: duckdb.DuckDBPyConnection,
    config: AppConfig,
) -> None:
    """Find proteins/groups across the complete resource and inspect full evidence.

    Args:
        connection: Open resource connection.
        config: Current source and preview configuration.
    """
    st.subheader("Protein & HOG search")
    st.markdown(
        "**1. Find a protein or group. 2. Inspect its HOG and ranks. "
        "3. Download the complete evidence dossier.**"
    )
    with st.expander("❓ Which inputs can I use, and what will I get?"):
        st.markdown(
            "Paste HOG/OG IDs, protein accessions, gene names, FASTA identifiers, seed IDs, "
            "DeepClust identifiers or protein-name fragments, one per line. Smart matching uses "
            "exact identifiers and partial descriptive names. Exact matching is useful for a "
            "specific HOG; contains can find incomplete IDs. Search covers every recognised field "
            "in every loaded relation before any preview limit. Select a discovered group to see "
            "its recorded ranks, complete membership and linked evidence. A direct-match export "
            "retains the original matching rows; a group dossier also follows identifier links."
        )
    source = source_identity(config=config)
    with st.form("unified_resource_search"):
        text = st.text_area(
            "Search term(s)",
            placeholder="Q9SA03\nN0.HOG0004891\nF-box protein",
            help="Paste up to 50 terms, separated by newlines, commas, semicolons or tabs.",
            height=130,
        )
        mode = st.radio(
            "Matching method",
            ("smart", "exact", "contains"),
            horizontal=True,
            help=(
                "Smart: exact IDs and partial names. Exact: whole identifiers/list tokens. "
                "Contains: literal text."
            ),
        )
        submitted = st.form_submit_button("Search the complete loaded resource")
    state_key = "complete_resource_search"
    state = st.session_state.get(state_key)
    if state is not None and state["source"] != source:
        st.session_state.pop(state_key)
        state = None
    if submitted:
        st.session_state.pop(state_key, None)
        try:
            terms = parse_search_terms(value=text)
            with st.spinner("Searching the full resource and resolving group links…"):
                queries = build_search_queries(connection=connection, terms=terms, mode=mode)
                summary = summarise_search_queries(connection=connection, queries=queries)
                matching_sources = set(summary["relation"])
                matching = tuple(query for query in queries if query.name in matching_sources)
                groups = resolve_search_groups(connection=connection, queries=matching)
            state = {
                "source": source,
                "queries": matching,
                "summary": summary,
                "groups": groups,
                "terms": terms,
                "mode": mode,
            }
            st.session_state[state_key] = state
        except AppError as exc:
            st.warning(str(exc))
            return
    if state is None:
        return
    summary = state["summary"]
    if summary.empty:
        st.warning("No identifier or name match was found in the loaded resource.")
        return
    st.caption(f"Applied search: {'; '.join(state['terms'])} · matching: {state['mode']}")
    metrics = st.columns(3)
    metrics[0].metric(
        "Entered terms matched", f"{summary['search_term'].nunique():,} / {len(state['terms']):,}"
    )
    metrics[1].metric("Source relations", f"{summary['relation'].nunique():,}")
    metrics[2].metric("Complete matching source rows", f"{int(summary['matched_rows'].sum()):,}")
    st.caption(
        "Counts include a separate match for each entered term; complete downloads "
        "retain that provenance."
    )
    if state["groups"]:
        group_key = "search_dossier_group"
        if st.session_state.get(group_key) not in state["groups"]:
            st.session_state.pop(group_key, None)
        group_id = st.selectbox(
            "Inspect a HOG or group",
            state["groups"],
            key=group_key,
            help=(
                "All discovered groups are available, including those beyond the "
                "screen preview limit."
            ),
        )
        try:
            _render_group_dossier(connection=connection, config=config, group_id=group_id)
        except AppError as exc:
            st.error(str(exc))
    else:
        st.info(
            "Direct matches were found, but this release has no recorded group link for them. "
            "Their complete source rows remain available below."
        )
    with st.expander(
        "Direct matching rows and complete search downloads", expanded=not state["groups"]
    ):
        _show_table(frame=summary, height=280)
        render_complete_export(
            connection=connection,
            queries=state["queries"],
            source=source,
            description=(
                f"Source: {config.source_path}; direct search: {state['terms']!r}; "
                f"mode: {state['mode']}"
            ),
            key="search_direct_complete",
            file_stem="complete_search_matches",
        )
        selected_key = "search_direct_source"
        sources = [query.name for query in state["queries"]]
        if st.session_state.get(selected_key) not in sources:
            st.session_state.pop(selected_key, None)
        relation = st.selectbox("Preview a direct-match source", sources, key=selected_key)
        query = next(query for query in state["queries"] if query.name == relation)
        rows = st.number_input(
            "Rows in search preview",
            min_value=1,
            max_value=config.max_rows,
            value=min(100, config.max_rows),
            key="search_preview_rows",
            help=(
                "Preview only. Search counts, discovered groups and complete downloads "
                "remain uncapped."
            ),
        )
        frame = preview_query(connection=connection, query=query, maximum_rows=int(rows))
        selected = _preview_fields(columns=frame.columns.tolist(), key=f"search_columns_{relation}")
        if selected:
            _show_table(frame=frame.loc[:, selected], height=480)
