"""Top-level resource search, complete HOG dossiers and uncapped result downloads."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from time import perf_counter
from typing import Mapping, Sequence

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
from e3app.group_lookup import (
    exact_group_terms,
    find_exact_groups,
    group_match_queries,
    quick_group_profile,
)
from e3app.exports import (
    EXCEL_MIME_TYPE,
    dataframe_display_formats,
    dataframe_display_widths,
    render_table_downloads,
    safe_file_stem,
)
from e3app.protein_dossier import (
    build_group_dossier,
    dossier_inventory,
    resolve_search_groups,
)
from e3app.result_queries import (
    ResourceQuery,
    build_result_query,
    build_search_queries,
    preview_query,
    query_count,
    resource_schema,
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
    prepare_label: str = "Prepare complete download",
    download_subject: str = "all matching rows and fields",
) -> None:
    """Prepare complete downloads explicitly and invalidate stale prepared payloads.

    Args:
        connection: Open resource connection.
        queries: Complete queries, independent of visible rows and fields.
        description: Applied source and selection provenance.
        source: Current source fingerprint.
        key: Unique widget/cache key for this export panel.
        file_stem: Download filename stem.
        prepare_label: Explicit preparation action label for this page.
        download_subject: Human-readable scope of the complete download.
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
    if st.button(prepare_label, key=f"{key}_prepare", disabled=not queries):
        try:
            exporter = complete_tsv_archive if export_format == "tsv" else complete_excel_workbook
            with st.spinner("Preparing every matching row and field…", show_time=True):
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
            label=f"Download {download_subject} ({label})",
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
        index=(
            [*virtual, *relations].index("candidate_master_results")
            if "candidate_master_results" in relations
            else 0
        ),
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
        group_scope = exact_group_terms(terms=terms, mode=mode)
        complete = build_result_query(
            connection=connection,
            result=result,
            terms=terms,
            mode=mode,
            hog_ids=group_scope if result in ENRICHED_HOG_LABELS else (),
        )
        source = source_identity(config=config)
        signature = hashlib.sha256(repr((source, complete)).encode()).hexdigest()
        cache_key = "all_results_data_cache"
        if st.session_state.get(cache_key, {}).get("signature") != signature:
            st.session_state[cache_key] = {"signature": signature, "previews": {}}
        cached = st.session_state[cache_key]
        load_preview = True
        if result in ENRICHED_HOG_LABELS:
            load_preview = st.checkbox(
                "Load joined HOG preview and counts",
                value=False,
                key="all_results_joined_preview",
                help="Complete downloads are available without preparing this joined preview.",
            )
        if load_preview and "count" not in cached:
            with st.spinner("Counting complete results…", show_time=True):
                cached["count"] = query_count(connection=connection, query=complete)
        count = cached.get("count")
        available = (
            enriched_hog_columns(connection=connection, result=result)
            if result in ENRICHED_HOG_LABELS
            else relation_columns(connection, result)
        )
        st.metric("Complete matching rows", "On request" if count is None else f"{count:,}")
        st.caption(f"Complete download: all matching rows × {len(available):,} fields.")
        st.markdown("#### Complete download")
        st.caption(
            "Leave the filter empty to download every row in this result view. Each raw relation "
            "keeps its own granularity. Use a group dossier to collect linked evidence "
            "across sources."
        )
        render_complete_export(
            connection=connection,
            queries=(complete,),
            source=source,
            description=(
                f"Source: {config.source_path}; result: {result}; "
                f"terms: {terms!r}; mode: {mode}"
            ),
            key="all_results_complete",
            file_stem=f"complete_{result.strip('_')}",
            prepare_label="Prepare all results download",
            download_subject="all results",
        )
        if not load_preview:
            st.info(
                "Prepare the complete download above, or enable the joined preview to inspect it."
            )
            return
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
        if int(rows) not in cached["previews"]:
            frame = preview_query(
                connection=connection,
                query=complete,
                maximum_rows=int(rows),
            )
            cached["previews"] = {int(rows): frame}
        preview = cached["previews"][int(rows)]
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
    cache: dict[str, object] | None = None,
    schema: Mapping[str, Sequence[str]] | None = None,
) -> None:
    """Show the small group profile first and load full evidence only on request.

    Args:
        connection: Open resource connection.
        config: Current source and preview configuration.
        group_id: Exact recorded group selected by the user.
        cache: Per-search cache of profiles, dossiers and bounded source previews.
        schema: Source catalogue already read for this submitted search.
    """
    cache = {} if cache is None else cache
    group_cache = cache.setdefault(group_id, {})
    st.markdown(f"#### Evidence dossier: {group_id}")
    if "profile" not in group_cache:
        with st.spinner("Reading this group's stored ranks and members…", show_time=True):
            group_cache["profile"] = quick_group_profile(
                connection=connection,
                group_id=group_id,
                maximum_rows=min(config.max_rows, 100),
                schema=schema,
            )
    profile = group_cache["profile"]
    ranks = profile["ranks"]
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
    members = profile["member_count"]
    metrics[2].metric("Recorded HOG members", "Unavailable" if members is None else f"{members:,}")
    st.caption(
        "These are original resource-wide ranks. The full evidence dossier and its "
        "source counts are loaded when requested; preview limits do not limit its downloads."
    )
    if not ranks.empty:
        _show_table(frame=ranks.drop(columns="numeric_rank"), height=150)
    if not profile["members"].empty:
        st.caption(
            f"Member preview from {profile['membership_source']}: "
            f"{len(profile['members']):,} of {members:,} recorded members."
        )
        _show_table(frame=profile["members"], height=220)
    source_id = source_identity(config=config)
    active = (source_id, group_id)
    if st.session_state.get("active_dossier_identity") != active:
        st.session_state.pop("group_dossier_complete_prepared", None)
        st.session_state["active_dossier_identity"] = active
    load_label = (
        "Reload complete evidence dossier"
        if "dossier" in group_cache
        else "Load complete evidence dossier"
    )
    if st.button(
        load_label,
        key="group_dossier_load",
        help=(
            "Find all recorded group, cluster and protein links, then count every source. "
            "The completed dossier is reused while you inspect sources or prepare downloads."
        ),
    ):
        with st.status("Loading complete group evidence…", expanded=True) as status:
            st.write("Finding recorded member and contributing-cluster links…")
            queries = build_group_dossier(
                connection=connection,
                group_id=group_id,
                schema=schema,
            )
            st.write("Counting complete evidence sources…")
            inventory = dossier_inventory(connection=connection, queries=queries)
            group_cache["dossier"] = {"queries": queries, "inventory": inventory, "previews": {}}
            st.session_state.pop("group_dossier_complete_prepared", None)
            status.update(label="Complete evidence dossier ready", state="complete", expanded=False)
    if "dossier" not in group_cache:
        st.info(
            "Load the complete evidence dossier to inspect and download all linked source records."
        )
        return
    dossier = group_cache["dossier"]
    queries = dossier["queries"]
    inventory = dossier["inventory"]
    available = inventory.loc[inventory["complete_rows"] > 0]
    if available.empty:
        st.info("No linked evidence is available for this group in the loaded resource.")
        return
    st.markdown("**Complete evidence inventory**")
    _show_table(frame=available, height=300)
    with st.expander("❓ What does this dossier include?"):
        st.markdown(
            "Every linked raw source row, the joined HOG overview/members, all recorded "
            "group ranking fields and release provenance. Links use recorded group, cluster "
            "and protein identifiers. Shared identifiers retain their original group context. "
            "Separate model/review files and external databases are not embedded."
        )
    render_complete_export(
        connection=connection,
        queries=queries,
        source=source_id,
        description=f"Source: {config.source_path}; complete linked group dossier: {group_id}",
        key="group_dossier_complete",
        file_stem=f"dossier_{group_id}",
    )
    selected_key = "dossier_source"
    sources = available["source"].tolist()
    if st.session_state.get(selected_key) not in sources:
        st.session_state.pop(selected_key, None)
    selected = st.selectbox(
        "Inspect an evidence source",
        sources,
        key=selected_key,
        format_func=lambda value: ENRICHED_HOG_LABELS.get(value, value),
        help="Every source listed is included in the complete dossier download.",
    )
    if selected not in dossier["previews"]:
        query = next(query for query in queries if query.name == selected)
        dossier["previews"][selected] = preview_query(
            connection=connection,
            query=query,
            maximum_rows=min(config.max_rows, 100),
        )
    frame = dossier["previews"][selected]
    st.caption(
        f"Source preview: first {len(frame):,} rows; complete rows and fields are downloadable."
    )
    _show_table(frame=frame, height=500)


def _render_direct_matches(
    *,
    connection: duckdb.DuckDBPyConnection,
    config: AppConfig,
    state: dict[str, object],
) -> None:
    """Render cached direct matches, deferring a group search's full source scan.

    Args:
        connection: Open resource connection.
        config: Current source and preview configuration.
        state: Submitted search, catalogue, matching queries and cached previews.
    """
    with st.expander(
        "Direct matching rows and complete search downloads", expanded=not state["groups"]
    ):
        if state["summary"] is None:
            if not st.button(
                "Load direct matching rows",
                key="search_direct_load",
                help=(
                    "Search group-ID fields across every source and count complete matches. "
                    "This does not limit the HOG lookup or full dossier download."
                ),
            ):
                st.caption("Direct source counts and previews are loaded on request.")
                return
            with st.spinner("Counting direct group-ID matches across all sources…", show_time=True):
                queries = group_match_queries(
                    connection=connection,
                    terms=state["terms"],
                    schema=state["schema"],
                )
                summary = summarise_search_queries(connection=connection, queries=queries)
                matching_sources = set(summary["relation"])
                state["queries"] = tuple(
                    query for query in queries if query.name in matching_sources
                )
                state["summary"] = summary
        summary = state["summary"]
        if summary.empty:
            st.info("No direct matching source rows were found.")
            return
        _show_table(frame=summary, height=280)
        render_complete_export(
            connection=connection,
            queries=state["queries"],
            source=state["source"],
            description=(
                f"Source: {config.source_path}; direct search: {state['terms']!r}; "
                f"mode: {state['mode']}; group_only: {state['group_only']}"
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
        rows = int(
            st.number_input(
                "Rows in search preview",
                min_value=1,
                max_value=config.max_rows,
                value=min(100, config.max_rows),
                key="search_preview_rows",
                help="Preview only; complete downloads retain every matching row and field.",
            )
        )
        preview_key = (relation, rows)
        previews = state.setdefault("direct_previews", {})
        if preview_key not in previews:
            previews[preview_key] = preview_query(
                connection=connection, query=query, maximum_rows=rows
            )
        frame = previews[preview_key]
        selected = _preview_fields(columns=frame.columns.tolist(), key=f"search_columns_{relation}")
        if selected:
            _show_table(frame=frame.loc[:, selected], height=480)


def render_resource_search(
    *,
    connection: duckdb.DuckDBPyConnection,
    config: AppConfig,
) -> None:
    """Open exact HOG/OG profiles promptly and defer complete evidence expansion.

    Args:
        connection: Open resource connection.
        config: Current source and preview configuration.
    """
    st.subheader("Protein & HOG search")
    st.markdown(
        "**1. Find a protein or group. 2. Inspect original ranks and members. "
        "3. Load the complete evidence dossier to download every linked record.**"
    )
    with st.expander("❓ Which inputs can I use, and what will I get?"):
        st.markdown(
            "Paste complete HOG/OG IDs for a direct group lookup, or protein accessions, "
            "gene names, seed/DeepClust IDs and name fragments for a wider resource search. "
            "Exact group lookups open ranks and members first. Full source counts, linked "
            "evidence and downloads are loaded explicitly and cached for the current release. "
            "Contains matching and the wider-search option inspect all recognised fields."
        )
    source = source_identity(config=config)
    with st.form("unified_resource_search"):
        text = st.text_area(
            "Search term(s)",
            placeholder="Q9SA03\nN0.HOG0004891\nF-box protein",
            help="Up to 50 terms, separated by newlines, commas, semicolons or tabs.",
            height=130,
        )
        mode = st.radio(
            "Matching method",
            ("smart", "exact", "contains"),
            horizontal=True,
            help="Smart uses exact IDs and partial names; contains supports incomplete IDs.",
        )
        wider = st.checkbox(
            "Search names and all identifier fields as well",
            key="search_wider_fields",
            help="For complete HOG/OG IDs, the default reads group records directly. "
            "Enable this to also search references in other recognised fields.",
        )
        submitted = st.form_submit_button("Search the complete loaded resource")
    state_key = "complete_resource_search"
    state = st.session_state.get(state_key)
    required = {"source", "group_only", "group_cache", "schema", "elapsed_seconds"}
    if state is not None and (not required.issubset(state) or state["source"] != source):
        st.session_state.pop(state_key)
        state = None
    if submitted:
        st.session_state.pop(state_key, None)
        try:
            terms = parse_search_terms(value=text)
            if not terms:
                raise AppError("Enter at least one search term")
            start = perf_counter()
            catalogue = resource_schema(connection=connection)
            group_terms = () if wider else exact_group_terms(terms=terms, mode=mode)
            if group_terms:
                with st.spinner("Finding the recorded HOG / group…", show_time=True):
                    groups = find_exact_groups(
                        connection=connection, terms=group_terms, schema=catalogue
                    )
                queries, summary = (), None
                terms = group_terms
            else:
                with st.spinner(
                    "Searching identifiers and names across the full resource…", show_time=True
                ):
                    queries = build_search_queries(
                        connection=connection,
                        terms=terms,
                        mode=mode,
                        schema=catalogue,
                    )
                    summary = summarise_search_queries(connection=connection, queries=queries)
                    matching_sources = set(summary["relation"])
                    queries = tuple(query for query in queries if query.name in matching_sources)
                    groups = resolve_search_groups(
                        connection=connection, queries=queries, schema=catalogue
                    )
            elapsed = perf_counter() - start
            state = {
                "source": source,
                "queries": queries,
                "summary": summary,
                "groups": groups,
                "terms": terms,
                "mode": mode,
                "group_only": bool(group_terms),
                "schema": catalogue,
                "group_cache": {},
                "elapsed_seconds": elapsed,
            }
            st.session_state[state_key] = state
            LOGGER.info(
                "Resource search group_only=%s groups=%d elapsed_seconds=%.3f",
                bool(group_terms),
                len(groups),
                elapsed,
            )
        except AppError as exc:
            st.warning(str(exc))
            return
    if state is None:
        return
    summary = state["summary"]
    st.caption(f"Applied search: {'; '.join(state['terms'])} · matching: {state['mode']}")
    st.caption(
        f"Lookup completed in {state['elapsed_seconds']:.2f} seconds. "
        "Full evidence loads on request."
    )
    if state["group_only"]:
        missing = [term for term in state["terms"] if term not in state["groups"]]
        if missing:
            st.warning("No recorded group found for: " + "; ".join(missing))
        metrics = st.columns(2)
        metrics[0].metric(
            "Entered terms matched", f"{len(state['groups']):,} / {len(state['terms']):,}"
        )
        metrics[1].metric("Recorded groups", f"{len(state['groups']):,}")
    else:
        if summary.empty:
            st.warning("No identifier or name match was found in the loaded resource.")
            return
        metrics = st.columns(3)
        metrics[0].metric(
            "Entered terms matched",
            f"{summary['search_term'].nunique():,} / {len(state['terms']):,}",
        )
        metrics[1].metric("Source relations", f"{summary['relation'].nunique():,}")
        metrics[2].metric(
            "Complete matching source rows", f"{int(summary['matched_rows'].sum()):,}"
        )
    if state["groups"]:
        group_key = "search_dossier_group"
        if st.session_state.get(group_key) not in state["groups"]:
            st.session_state.pop(group_key, None)
        group_id = st.selectbox(
            "Inspect a HOG or group",
            state["groups"],
            key=group_key,
            help="Every discovered group is available, independently of preview limits.",
        )
        try:
            _render_group_dossier(
                connection=connection,
                config=config,
                group_id=group_id,
                cache=state["group_cache"],
                schema=state["schema"],
            )
        except AppError as exc:
            st.error(str(exc))
    elif not state["group_only"]:
        st.info("Direct matches were found, but this release has no recorded group link for them.")
    try:
        _render_direct_matches(connection=connection, config=config, state=state)
    except AppError as exc:
        st.error(str(exc))
