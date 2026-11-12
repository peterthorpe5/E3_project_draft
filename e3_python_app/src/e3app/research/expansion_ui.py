"""Dedicated Top-N cluster campaign, quantitative comparisons and shared protein feature UI."""

from __future__ import annotations

import csv
from inspect import signature
from io import StringIO
import json
import os
from pathlib import Path
import re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy.cluster.hierarchy import dendrogram
import streamlit as st
import streamlit.components.v1 as components

from e3app.config import AppConfig
from e3app.errors import AppError
from e3app.external_hog import published_hog_ids
from e3app.navigation import CANDIDATE_STAGE, DEEPCLUST_STAGE
from e3app.pocket_review import prepare_pocket_review, selected_group_alignment_fasta_bytes

from .campaign import CampaignSelection, select_campaign, submit_campaign
from .common import ResearchConfig, ResearchError, iter_fasta
from .comparisons import MAX_COMPARISON_CELLS, MAX_COMPARISON_ROWS, alignment_comparison
from .deepclust_import import PARQUET_UPLOAD_BYTES, extract_family, open_results, results_preview
from .feature_catalogue import (
    feature_contexts, hog_feature_contexts, published_features, recorded_feature_payload,
)
from .jobs import artifact_path
from .remote import ssh_command
from .species_tree import species_display_tree
from .viewer_inputs import (
    TREE_BYTES, UPLOAD_BYTES, read_species_mapping, uploaded_proteins, validate_protein_tree,
)
from .viewers import nightingale_features, viewer_document

EXAMPLE_ALIGNMENT = {
    "Example_A": "MAAKLVVA" "GLTQLKEA" "GLDVAVID" "RHGLDVEQ" "LKAALEAG" "ADVVVVTA" "DKETQLAS",
    "Example_B": "MAAKLIVA" "GLTQLKEA" "GLDVAVID" "RHGLDVEQ" "LKAALEAG" "ADVVIVTA" "DKETQLAS",
    "Example_C": "MSAKLVVA" "GLTQLKDA" "GLDVAVID" "RHGLDVEQ" "LKSALEAG" "ADIVVVTA" "DKETQLAT",
    "Example_D": "MSAKLIVA" "GLTQLKDA" "GLDVAVID" "RHGL--EQ" "LKSALEAG" "ADIVIVTA" "DKETQLAT",
    "Example_E": "MNARLIVA" "GVTQLREA" "GMDVAIVD" "RHGLDVEQ" "LKSALESG" "ADVIVVTA" "DRETQLAT",
    "Example_F": "MNARLIVA" "GVTQLREA" "GMDVAIVD" "RHGLDV-Q" "LKSALESG" "ADVIVITA" "DRETQLAT",
}
EXAMPLE_TREE = (
    "((Example_A:0.03,Example_B:0.03):0.04,"
    "((Example_C:0.04,Example_D:0.05):0.03,(Example_E:0.03,Example_F:0.04):0.06):0.03);"
)


def _resource_identity(*, config: ResearchConfig) -> tuple:
    """Bind prepared campaign inputs to the current E3 resource and research sidecar."""
    values = [str(config.workspace)]
    for key in ("E3_RESOURCE_DUCKDB", "E3_RESOURCE_PARQUET", "E3_RESOURCE_RUN_DIR"):
        value = os.environ.get(key, "")
        path = Path(value).expanduser() if value else None
        stamp = path.stat().st_mtime_ns if path is not None and path.exists() else None
        values.append((key, value, stamp))
    return tuple(values)


def render_deepclust_exchange(*, config: ResearchConfig, connection: object | None) -> None:
    """Prepare FASTA for external search and inspect returned DeepClust exports.

    Args:
        config: Research profile for optional built-in searches.
        connection: Published E3 resource for selecting query proteins.
    """
    from .ui import render_analysis, render_discovery

    st.subheader("DeepClust results and query FASTA")
    st.write("Prepare protein FASTA for Ken’s DeepClust search, then open its exported results.")
    mode = st.radio("What would you like to do?", ["Import Parquet results", "Prepare query FASTA"],
                    horizontal=True, key="deepclust_exchange_mode")
    if mode == "Import Parquet results":
        render_deepclust_parquet()
    else:
        render_query_fasta(connection=connection)
    with st.expander("Built-in DeepClust search"):
        st.caption("Uses this app’s configured DeepClust data and analysis worker.")
        if st.checkbox("Show built-in search controls", key="legacy_deepclust_enabled"):
            route = st.radio("Built-in search", ["Discover", "Top-200 cluster campaign",
                                                 "Representative homology search"],
                             horizontal=True, key="legacy_deepclust_route")
            if route == "Discover":
                render_discovery(config=config, connection=connection)
            elif route == "Top-200 cluster campaign":
                render_campaign(config=config, connection=connection)
            else:
                render_analysis(config=config, enable_search=True)


def render_deepclust_parquet() -> None:
    """Preview an external export and optionally prepare a selected family as FASTA."""
    upload = st.file_uploader("DeepClust results Parquet", type=["parquet"],
                              key="external_deepclust_parquet")
    if upload is None:
        st.caption("Upload a results export from Ken’s app when it is available.")
        return
    if upload.size > PARQUET_UPLOAD_BYTES:
        raise ResearchError("Upload a selected results export of at most 200 MB")
    reader = open_results(content=upload.getvalue())
    preview = results_preview(reader=reader)
    st.caption(f"{reader.metadata.num_rows:,} result rows · showing the first {len(preview):,}")
    st.dataframe(preview, hide_index=True)
    if not st.checkbox("Extract protein FASTA from this export", key="deepclust_extract_fasta"):
        return
    columns = ["", *reader.schema_arrow.names]
    st.caption("Choose the exact ID and amino-acid sequence columns. For a hit-only export, "
               "request the selected sequences from Ken’s app or use a separate protein FASTA.")
    with st.form("external_deepclust_family"):
        identifier = st.selectbox("Protein ID column", columns)
        sequence = st.selectbox("Amino-acid sequence column", columns)
        cluster = st.selectbox("Cluster ID column (optional)", columns)
        value = st.text_input("Exact cluster ID (required if a cluster column is selected)")
        prepare = st.form_submit_button("Prepare selected protein FASTA")
    identity = (upload.file_id, identifier, sequence, cluster, value.strip())
    if prepare:
        st.session_state.pop("deepclust_prepared_family", None)
        fasta = extract_family(reader=reader, id_column=identifier, sequence_column=sequence,
                               cluster_column=cluster, cluster_id=value.strip())
        st.session_state["deepclust_prepared_family"] = (identity, fasta)
        st.session_state["research_prepared_fasta"] = (upload.name, fasta)
    prepared = st.session_state.get("deepclust_prepared_family")
    if prepared and prepared[0] == identity:
        st.success("FASTA ready. Select Prepared FASTA in Family analysis, Annotations or Models.")
        st.download_button("Download selected protein FASTA", data=prepared[1],
                           file_name="deepclust_selected_proteins.fasta", mime="text/plain")


def render_query_fasta(*, connection: object | None) -> None:
    """Collect exact published proteins or user FASTA for a future external request.

    Args:
        connection: Optional published E3 source with sequence-bearing HOG members.
    """
    from e3app.external_hog import collect_external_hog_members

    st.caption("Download the query FASTA for Ken’s app or CLI. API submission will be available "
               "once its interface is defined.")
    modes = (["Published HOG members"] if connection is not None else []) + ["Upload FASTA files"]
    mode = st.radio("Query protein source", modes, horizontal=True, key="ken_query_fasta_source")
    if mode == "Published HOG members":
        with st.form("ken_query_hog"):
            hog = st.text_input(
                label="Exact HOG ID", value=st.session_state.get("ken_query_selected_hog", ""),
                placeholder="N0.HOG0003902",
            )
            if st.form_submit_button("Find HOG proteins"):
                st.session_state["ken_query_selected_hog"] = hog.strip().upper()
        hog = st.session_state.get("ken_query_selected_hog", "")
        if not hog:
            return
        try:
            members = collect_external_hog_members(connection=connection, hog_id=hog,
                                                   maximum_members=10_000)
        except AppError as exc:
            st.warning(str(exc))
            return
        available = members.loc[members.sequence_status.eq("AVAILABLE")].set_index("member_key")
        st.caption(f"{len(available):,} of {len(members):,} HOG members have usable sequences.")
        chosen = st.multiselect("Proteins to include", list(available.index),
                                format_func=available.label.to_dict().__getitem__,
                                key=f"ken_query_members_{hog}")
        if not chosen:
            return
        selected = available.loc[chosen]
        fasta = "".join(f">{row.fasta_identifier}\n{row.protein_sequence}\n"
                        for row in selected.itertuples())
        if len(fasta.encode()) > UPLOAD_BYTES:
            raise ResearchError("Select fewer proteins. Query FASTA is limited to 20 MB")
        st.download_button("Download query ID mapping (TSV)",
                           data=selected[["fasta_identifier", "identifier", "member_species",
                                          "member_raw_identifier"]].to_csv(sep="\t", index=False),
                           file_name="deepclust_query_ids.tsv")
        filename = f"{hog}_deepclust_queries.fasta"
    else:
        files = st.file_uploader("Query protein FASTA files", type=["fa", "faa", "fasta"],
                                 accept_multiple_files=True, key="ken_query_upload")
        if not files:
            return
        if sum(file.size for file in files) > UPLOAD_BYTES:
            raise ResearchError("Combined query FASTA files exceed 20 MB")
        try:
            fasta = "\n".join(file.getvalue().decode("utf-8-sig").rstrip() for file in files) + "\n"
        except UnicodeDecodeError as exc:
            raise ResearchError("Query FASTA files must contain UTF-8 text") from exc
        uploaded_proteins(text=fasta, maximum_records=100_000)
        filename = "deepclust_queries.fasta"
    st.download_button("Download DeepClust query FASTA", data=fasta,
                       file_name=filename, mime="text/plain")
    if st.button("Use this FASTA in the workbench", key="ken_use_query_fasta"):
        st.session_state["research_prepared_fasta"] = (filename, fasta)
        st.success("Select Prepared FASTA in Family analysis, Annotations or Models.")


def render_hog_alignment_input(
    *, config: ResearchConfig, connection: object, key: str, browse: bool = False,
) -> str | None:
    """Select exact released HOG members and prepare their unaligned protein FASTA.

    Args:
        config: Current research profile and resource cache scope.
        connection: Published E3 resource and its sequence authority.
        key: Unique input widget namespace.
        browse: Use a searchable release HOG selector.

    Returns:
        FASTA for the selected available members, or None until selection is ready.
    """
    from e3app.external_hog import collect_external_hog_members, published_hog_ids

    group_key = f"{key}_hog"
    resource = _resource_identity(config=config)
    if browse:
        cached_ids = st.session_state.get(f"{key}_hog_ids")
        if cached_ids is None or cached_ids[0] != resource:
            try:
                ids = published_hog_ids(connection=connection)
            except AppError as exc:
                st.info(str(exc))
                return None
            st.session_state[f"{key}_hog_ids"] = (resource, ids)
        else:
            ids = cached_ids[1]
        if not ids:
            st.info("The loaded E3 release has no published HOG membership. "
                    "Use Family analysis to align an unaligned protein FASTA.")
            return None
        previous = st.session_state.get(group_key, "")
        selected_id = st.selectbox(
            label="HOG to align", options=ids,
            index=ids.index(previous) if previous in ids else None,
            placeholder="Type part of a HOG ID or choose from the list", key=f"{key}_hog_selector",
        )
        st.session_state[group_key] = selected_id or ""
    else:
        input_key = f"{key}_hog_input"
        st.session_state.setdefault(input_key, st.session_state.get(group_key, ""))
        with st.form(key=f"{key}_hog_lookup"):
            entered = st.text_input(
                label="Exact HOG ID", key=input_key, placeholder="N0.HOG0003902",
            )
            if st.form_submit_button(label="Load HOG members"):
                st.session_state[group_key] = entered.strip().upper()
    hog = st.session_state.get(group_key, "")
    if not hog:
        st.caption("Enter a HOG ID from the E3 results to load its published protein sequences.")
        return None
    identity = (resource, hog)
    cache_key = f"{key}_hog_members"
    cached = st.session_state.get(cache_key)
    if cached is None or cached[0] != identity:
        try:
            members = collect_external_hog_members(
                connection=connection, hog_id=hog, maximum_members=10_000,
            )
        except AppError as exc:
            st.info(str(exc))
            return None
        st.session_state[cache_key] = (identity, members)
    else:
        members = cached[1]
    available = members.loc[members["sequence_status"].eq("AVAILABLE")].set_index("member_key")
    st.caption(f"{hog} · {len(available):,} of {len(members):,} members have usable sequences")
    with st.expander(label="HOG membership and sequence availability"):
        st.dataframe(
            data=members[["identifier", "member_species", "member_raw_identifier",
                          "sequence_status"]],
            hide_index=True,
        )
    if available.empty:
        st.info("This release has no usable sequences for the HOG. Open the full E3 release "
                "or upload an unaligned FASTA under Family analysis.")
        return None
    mode = st.radio(
        label="HOG sequences", options=["All available members", "Choose members"],
        horizontal=True, key=f"{key}_hog_mode_{hog}",
    )
    if mode == "Choose members":
        chosen = st.multiselect(
            label="Proteins to align", options=list(available.index),
            format_func=available["label"].to_dict().__getitem__, key=f"{key}_hog_choice_{hog}",
        )
        selected = available.loc[chosen]
    else:
        selected = available
    if selected.empty:
        return None
    fasta = "".join(
        f">{row.fasta_identifier}\n{row.protein_sequence}\n" for row in selected.itertuples()
    )
    if len(fasta.encode()) > UPLOAD_BYTES:
        st.info("The selected FASTA exceeds 20 MB. Choose fewer members to continue in the app.")
        return None
    unit = "protein" if len(selected) == 1 else "proteins"
    st.caption(f"{len(selected):,} {unit} selected for alignment")
    st.download_button(
        label="Download HOG protein FASTA", data=fasta, file_name=f"{hog}_members.fasta",
        mime="text/plain", key=f"{key}_hog_fasta",
    )
    st.download_button(
        label="Download HOG sequence ID mapping (TSV)",
        data=selected[["fasta_identifier", "identifier", "member_species",
                       "member_raw_identifier"]].to_csv(sep="\t", index=False),
        file_name=f"{hog}_alignment_ids.tsv", mime="text/tab-separated-values",
        key=f"{key}_hog_mapping",
    )
    return fasta


def render_campaign(*, config: ResearchConfig, connection: object | None) -> None:
    """Prepare complete E3 inputs, map via the CLI connection and collect selected global clusters.

    Args:
        config: Analysis worker/SSH profile.
        connection: Immutable E3 resource, absent in the generic standalone app.
    """
    from .ui import completed_manifests, job_label, queue_action, read_table, render_next_action

    st.subheader("Top-200 cluster campaign")
    st.write(
        "Start with the published primary evolutionary-group ranking. Map its complete "
        "protein inputs to external DeepClust IDs, then choose global clusters to collect."
    )
    st.caption(
        "Project DeepClust clusters, HOGs and external DeepClust clusters have distinct IDs. "
        "This route keeps their relationships and unresolved mappings in downloadable audits."
    )
    maximum = st.number_input("Top ranked E3 evolutionary groups", min_value=1, max_value=1000,
                              value=200, key="campaign_top_n",
                              help="Select complete published primary groups in rank order.")
    routes = ("ssh", "worker") if config.remote_host else ("worker",)
    transport = st.radio(
        "DeepClust command-line connection", options=routes, horizontal=True,
        format_func=lambda value: ("Existing SSH connection" if value == "ssh"
                                   else "Analysis worker with mounted data"),
        key="campaign_transport",
        help="The analysis worker performs every database query outside the browser.",
    )
    if transport == "ssh":
        st.caption(f"Configured SSH destination: {config.remote_host}")
        ssh_command(config=config)
    elif not config.index or not config.sequence_map:
        st.info(
            "Configure the denbi worker's mounted index, sequence map and sequence Parquet, "
            "or add remote_host/remote_config for the established SSH connection. "
            "Preparing the local E3 inventory remains available."
        )
    identity = (_resource_identity(config=config), int(maximum), transport)
    state = st.session_state.get("deepclust_campaign_inputs", {})
    if state.get("identity") != identity:
        st.session_state.pop("deepclust_campaign_inputs", None)
    if connection is None:
        st.info("Open this page in the E3 app to select its published Top-N groups.")
    if st.button("Prepare complete Top-N E3 mapping inputs", disabled=connection is None,
                 type="primary"):
        st.session_state.pop("deepclust_campaign_inputs", None)
        with st.spinner("Collecting complete published group and member inventories…"):
            selection = select_campaign(connection=connection, maximum_groups=int(maximum))
        st.session_state["deepclust_campaign_inputs"] = {
            "identity": identity, "selection": selection,
        }
    state = st.session_state.get("deepclust_campaign_inputs", {})
    selection = state.get("selection") if state.get("identity") == identity else None
    if isinstance(selection, CampaignSelection):
        st.success(f"Prepared {len(selection.groups):,} groups and {len(selection.inputs):,} "
                   "complete identifier/context rows.")
        st.caption("Rank order is the recorded pre-structure evolutionary-group ranking. "
                   "It includes primary HOGs and orthogroup fallbacks, without changing rankings.")
        st.dataframe(selection.groups, hide_index=True)
        st.download_button("Download prepared E3 group inventory (TSV)",
                           data=selection.groups.to_csv(sep="\t", index=False),
                           file_name="e3_campaign_groups.tsv", mime="text/tab-separated-values")
        st.download_button("Download complete mapping inputs (TSV)",
                           data=selection.inputs.to_csv(sep="\t", index=False),
                           file_name="e3_campaign_inputs.tsv", mime="text/tab-separated-values")
        if st.button("Queue Top-N mapping through the command-line connection"):
            job_id = submit_campaign(config=config, selection=selection, transport=transport)
            st.success(f"Queued complete campaign mapping: {job_id}")
            render_next_action(label="Track campaign mapping", key=f"campaign_{job_id}",
                               section="Jobs", job_id=job_id)
    completed = completed_manifests(config=config, operation="deepclust_map")
    if not completed:
        st.caption("Completed campaigns appear here for size-ranked cluster selection.")
        return
    labels = {key: job_label(job_id=key, record=value) for key, value in completed.items()}
    selected = st.selectbox("Completed DeepClust campaign", options=list(completed),
                            format_func=labels.__getitem__, key="completed_campaign",
                            help="Select a completed mapping campaign.")
    group_path = artifact_path(workspace=config.workspace, job_id=selected,
                               artifact="campaign_groups.tsv")
    groups = read_table(path=group_path, maximum_rows=1000)
    st.dataframe(groups, hide_index=True)
    st.caption("UNMATCHED/PARTIAL/NO_IDENTIFIERS are missing evidence; every requested group "
               "remains in this audit. Multiple external cluster matches are retained.")
    clusters = read_table(path=artifact_path(workspace=config.workspace, job_id=selected,
                                             artifact="global_clusters.tsv"), maximum_rows=10_000)
    st.markdown("#### External clusters, ordered by published size")
    st.dataframe(clusters, hide_index=True)
    st.caption("Preview: at most 10,000 clusters. Full inventories and input-to-cluster "
               "relationships are downloadable in Jobs. Sort any column in the table.")
    if clusters.empty:
        st.info("This campaign has no exact global cluster matches; inspect its mapping audit.")
        return
    sizes = pd.to_numeric(arg=clusters["member_count"], errors="coerce")
    available = clusters.loc[sizes.notna(), "cluster_id"].astype(str).tolist()
    selected_ids = st.multiselect("Mapped external clusters to collect", options=available,
                                  default=available[:1], key="campaign_collect_ids")
    if selected_ids:
        count = sizes.loc[clusters["cluster_id"].astype(str).isin(selected_ids)].sum()
        st.caption(f"Selected published members: {int(count):,}. Extraction is complete for each "
                   "chosen cluster; configured worker count/transfer limits apply.")
    if st.button("Queue complete selected cluster retrieval", disabled=not selected_ids,
                 key="campaign_collect"):
        queue_action(config=config, operation="deepclust_retrieve", parameters={
            "cluster_ids": selected_ids, "transport": transport, "mapping_job": selected,
        })
    st.info("After retrieval completes, select its FASTA in Family analysis, Annotations or "
            "Models. Cluster comparisons reads its size and reviewed taxonomy summaries.")


def _venn_figure(*, regions: dict[str, int], labels: list[str]) -> go.Figure:
    """Draw labelled, non-area-proportional two/three-set species Venn regions."""
    figure = go.Figure()
    centres = [(-0.5, 0.2), (0.5, 0.2), (0.0, -0.65)][:len(labels)]
    colours = ["rgba(55,126,184,0.25)", "rgba(228,90,90,0.25)", "rgba(60,165,95,0.25)"]
    for index, ((x, y), colour) in enumerate(zip(centres, colours, strict=False)):
        figure.add_shape(type="circle", x0=x - 0.8, x1=x + 0.8, y0=y - 0.8, y1=y + 0.8,
                         fillcolor=colour, line={"width": 2})
        figure.add_annotation(x=x, y=y + 0.9, text=chr(65 + index), showarrow=False)
    positions = ({"10": (-0.65, 0.2), "01": (0.65, 0.2), "11": (0, 0.2)} if len(labels) == 2
                 else {"100": (-0.8, 0.4), "010": (0.8, 0.4), "001": (0, -1.0),
                       "110": (0, 0.55), "101": (-0.4, -0.25), "011": (0.4, -0.25),
                       "111": (0, 0.0)})
    for region, count in regions.items():
        figure.add_annotation(x=positions[region][0], y=positions[region][1], text=str(count),
                              showarrow=False, font={"size": 18})
    figure.update_layout(height=430, xaxis={"visible": False, "range": [-1.6, 1.6]},
                         yaxis={"visible": False, "scaleanchor": "x", "range": [-1.6, 1.6]})
    return figure


def _comparison_heatmap_figure(
    *, similarity: pd.DataFrame, denominators: pd.DataFrame, identity: bool = False,
) -> go.Figure:
    """Plot a labelled comparison matrix with its exact per-pair denominator.

    Args:
        similarity: Similarity fractions in display order.
        denominators: Matching counts in the same order.
        identity: Format sequence identity as percentages.

    Returns:
        A heatmap whose undefined comparisons remain blank.
    """
    metric = "Identity" if identity else "Similarity"
    count_label = "Comparable residues" if identity else "Denominator"
    value_format = ".1%" if identity else ".3f"
    colourbar = {"title": metric, "tickformat": ".0%"} if identity else None
    return go.Figure(data=go.Heatmap(
        z=similarity.to_numpy(), x=list(similarity.columns), y=list(similarity.index),
        customdata=denominators.to_numpy(), zmin=0, zmax=1, colorscale="Viridis",
        colorbar=colourbar, hoverongaps=False,
        hovertemplate=(
            f"%{{y}} / %{{x}}<br>{metric}: %{{z:{value_format}}}"
            f"<br>{count_label}: %{{customdata}}<extra></extra>"
        ),
    ))


def render_alignment_heatmap(*, records: dict[str, str], job_id: str) -> None:
    """Calculate and download pairwise identity beside a completed alignment.

    Args:
        records: Validated aligned protein records in viewer order.
        job_id: Completed alignment identifier for widget state and downloads.
    """
    identifiers = list(records)
    alignment_length = len(records[identifiers[0]])
    limit = min(MAX_COMPARISON_ROWS, MAX_COMPARISON_CELLS // alignment_length)
    st.markdown("#### Identity heatmap")
    if limit < 1:
        st.info("This alignment exceeds the comparison cell limit.")
        return
    cached = st.session_state.get("alignment_heatmap_result")
    default_selection = (
        list(cached[0][1]) if cached and cached[0][0] == job_id else identifiers[:min(200, limit)]
    )
    with st.form(key=f"identity_heatmap_{job_id}"):
        with st.expander("Choose proteins for the heatmap"):
            selected = st.multiselect(
                "Aligned proteins to compare",
                options=identifiers,
                default=default_selection,
                max_selections=limit,
                key=f"identity_heatmap_proteins_{job_id}",
            )
        calculate = st.form_submit_button("Calculate heatmap")
    st.caption(f"{len(selected):,} of {len(identifiers):,} aligned proteins selected.")
    selection = (job_id, tuple(selected))
    if calculate:
        if not selected:
            st.info("Select at least one aligned protein.")
            return
        selected_records = {identifier: records[identifier] for identifier in selected}
        with st.spinner("Calculating pairwise identity"):
            result = alignment_comparison(records=selected_records)
        cached = (selection, result)
        st.session_state["alignment_heatmap_result"] = cached
    if not cached or cached[0] != selection:
        return
    result = cached[1]
    order = list(result.order)
    similarity = result.similarity.loc[order, order]
    denominators = result.denominators.loc[order, order]
    figure = _comparison_heatmap_figure(
        similarity=similarity, denominators=denominators, identity=True,
    )
    figure.update_yaxes(autorange="reversed")
    st.plotly_chart(figure, key=f"alignment_identity_heatmap_{job_id}")
    st.caption(
        "Identity uses positions with canonical residues in both proteins. "
        "Pairs with no comparable positions appear blank."
    )
    if result.linkage_matrix:
        st.caption("Proteins are ordered by average linkage on 1 − identity.")
    for label, frame, suffix in (
        ("Download identity matrix (TSV)", similarity, "identity"),
        ("Download comparable residue counts (TSV)", denominators, "comparable_residues"),
    ):
        st.download_button(
            label, data=frame.rename_axis(index="identifier").to_csv(sep="\t"),
            file_name=f"{job_id}_{suffix}.tsv", mime="text/tab-separated-values",
            key=f"alignment_heatmap_{suffix}_{job_id}",
        )


def _render_comparison(*, config: ResearchConfig, job_id: str) -> None:
    """Render a completed worker comparison with exact denominators and display hierarchy."""
    from .ui import read_table

    summary = json.loads(artifact_path(workspace=config.workspace, job_id=job_id,
                                       artifact="comparison_summary.json").read_text())
    st.caption(summary["interpretation"])
    similarity = pd.read_csv(filepath_or_buffer=artifact_path(
        workspace=config.workspace, job_id=job_id, artifact="similarity.tsv",
    ), sep="\t", index_col=0, dtype={"identifier": str})
    counts = pd.read_csv(filepath_or_buffer=artifact_path(
        workspace=config.workspace, job_id=job_id, artifact="denominators.tsv",
    ), sep="\t", index_col=0, dtype={"identifier": str})
    original_labels = list(similarity.index)
    order = read_table(path=artifact_path(workspace=config.workspace, job_id=job_id,
                                          artifact="display_order.tsv"))["identifier"].tolist()
    similarity = similarity.loc[order, order]
    counts = counts.loc[order, order]
    st.plotly_chart(
        _comparison_heatmap_figure(similarity=similarity, denominators=counts),
        key=f"comparison_heatmap_{job_id}",
    )
    hierarchy = read_table(path=artifact_path(workspace=config.workspace, job_id=job_id,
                                              artifact="hierarchy.tsv"))
    if not hierarchy.empty:
        tree = dendrogram(Z=hierarchy.to_numpy(dtype=float), labels=original_labels,
                          no_plot=True)
        figure = go.Figure()
        for x, y in zip(tree["icoord"], tree["dcoord"], strict=True):
            figure.add_trace(go.Scatter(x=x, y=y, mode="lines", showlegend=False))
        figure.update_layout(xaxis={"tickmode": "array", "tickvals": [
            5 + 10 * index for index in range(len(tree["ivl"]))
        ], "ticktext": tree["ivl"]}, yaxis_title="1 − similarity (average linkage)")
        st.plotly_chart(figure, key=f"comparison_hierarchy_{job_id}")
    else:
        st.info("Hierarchy unavailable: " + summary["hierarchy_status"]
                + ". Undefined comparisons remain blank rather than being replaced by zero.")
    st.dataframe(similarity, key=f"comparison_matrix_{job_id}")
    if summary["kind"] == "species":
        coverage = read_table(path=artifact_path(workspace=config.workspace, job_id=job_id,
                                                 artifact="classification_coverage.tsv"))
        st.dataframe(coverage, hide_index=True)
        if "venn_regions" in summary:
            labels = summary["venn_cluster_order"]
            st.plotly_chart(_venn_figure(regions=summary["venn_regions"], labels=labels),
                            key=f"species_venn_{job_id}")
            st.table(pd.DataFrame(data={"Set": [chr(65 + i) for i in range(len(labels))],
                                        "Cluster": labels}))
            st.caption("Venn counts are unique reviewed taxa; circles are not area-proportional.")
        rows = read_table(path=artifact_path(workspace=config.workspace, job_id=job_id,
                                             artifact="species_counts.tsv"), maximum_rows=100_000)
        st.dataframe(rows, hide_index=True)
    st.caption("Full matrices, denominators, taxonomy counts and hierarchy TSVs are in Jobs.")


def render_comparisons(*, config: ResearchConfig) -> None:
    """Inspect cluster/subcluster summaries and queue bounded species or alignment comparisons.

    Args:
        config: Current analysis sidecar.
    """
    from .ui import completed_manifests, job_label, queue_action, read_table

    st.subheader("Cluster comparisons")
    manifests = completed_manifests(config=config)
    families = {key: value for key, value in manifests.items() if any(
        name in value["artifacts"] for name in ("cluster_summary.tsv", "subclusters.tsv")
    )}
    if families:
        labels = {key: job_label(job_id=key, record=value) for key, value in families.items()}
        chosen = st.selectbox("Cluster summary job", options=list(families),
                              format_func=labels.__getitem__, key="comparison_family",
                              help="Select a completed family or subcluster summary.")
        manifest = families[chosen]
        name = ("subclusters.tsv" if "subclusters.tsv" in manifest["artifacts"]
                else "cluster_summary.tsv")
        frame = read_table(path=artifact_path(workspace=config.workspace, job_id=chosen,
                                              artifact=name))
        st.dataframe(frame, hide_index=True)
        count_column = "member_count" if "member_count" in frame else "sequence_count"
        id_column = "subcluster_id" if "subcluster_id" in frame else "cluster_id"
        frame[count_column] = pd.to_numeric(arg=frame[count_column], errors="raise")
        st.plotly_chart(px.bar(data_frame=frame.nlargest(n=50, columns=count_column),
                               x=id_column, y=count_column), key="cluster_comparison_sizes")
        st.caption("Largest 50 rows shown in the size chart; the table preview is bounded "
                   "to 10,000 rows. Full summaries remain downloadable.")
        if "cluster_species.tsv" in manifest["artifacts"]:
            selected = st.multiselect("Clusters/subclusters for species comparison",
                                      options=frame[id_column].astype(str).tolist(),
                                      default=frame[id_column].astype(str).head(3).tolist(),
                                      key="species_compare_ids")
            if st.button("Queue species overlap and hierarchical heatmap", disabled=not selected):
                queue_action(config=config, operation="compare", parameters={
                    "kind": "species", "source_job": chosen, "cluster_ids": selected,
                })
        else:
            st.info("Reviewed taxonomy is unavailable for this family. Configure taxonomy "
                    "on the extraction worker to obtain species summaries and overlap diagrams.")
    else:
        st.info("Retrieve a cluster or complete a subclustering job to inspect family summaries.")
    alignments = {key: value for key, value in manifests.items() if value["operation"] == "align"}
    if alignments:
        labels = {key: job_label(job_id=key, record=value) for key, value in alignments.items()}
        chosen = st.selectbox("Alignment for pairwise identity", options=list(alignments),
                              format_func=labels.__getitem__, key="comparison_alignment",
                              help="Select a completed MAFFT alignment.")
        ids = [identifier for identifier, _sequence in iter_fasta(
            path=artifact_path(workspace=config.workspace, job_id=chosen,
                               artifact="alignment.fasta"),
            aligned=True,
        )]
        selected = st.multiselect("Protein rows for pairwise identity", options=ids,
                                  default=ids[:200], key="pairwise_selected_ids")
        st.caption(f"{len(selected):,} of {len(ids):,} aligned proteins selected explicitly. "
                   "At most 1,000 rows per job; gaps and unknown residues are excluded.")
        if st.button("Queue pairwise identity and hierarchical heatmap",
                     disabled=not selected or len(selected) > 1000):
            queue_action(config=config, operation="compare", parameters={
                "kind": "alignment", "source_job": chosen, "sequence_ids": selected,
            })
    completed = completed_manifests(config=config, operation="compare")
    if completed:
        chosen = st.selectbox("Completed quantitative comparison", options=list(completed),
                              key="completed_quantitative_comparison",
                              help="Display a completed worker comparison.")
        _render_comparison(config=config, job_id=chosen)


def open_e3_viewer(
    *, page: str, group_id: str, accession: str = "", species: str = "",
) -> None:
    """Open a dedicated E3 page with the exact selection supplied by its caller.

    Args:
        page: Dedicated destination in Candidate discovery or DeepClust research.
        group_id: Recorded evolutionary group identifier.
        accession: Exact protein accession for the models route.
        species: Recorded species column for the models route.

    Raises:
        ResearchError: If the requested destination is unknown.
    """
    stage = st.session_state.get("e3_navigation_stage")
    if stage not in {CANDIDATE_STAGE, DEEPCLUST_STAGE}:
        stage = CANDIDATE_STAGE
    if page == "Protein feature browser":
        st.session_state["recorded_feature_query"] = group_id
        st.session_state["recorded_feature_search_term"] = group_id
        st.session_state["recorded_feature_handoff_group"] = group_id
        st.session_state["feature_browser_route"] = "Recorded E3 domain features"
        st.session_state.pop("recorded_feature_context", None)
    elif page == "JBrowse MSA":
        st.session_state["published_alignment_group"] = group_id
        st.session_state["published_alignment_input"] = group_id
        st.session_state["alignment_view_source"] = "Published HOG alignment"
    elif page == "Align a HOG":
        page = "JBrowse MSA"
        st.session_state["alignment_view_source"] = "Align a HOG"
        st.session_state["msa_hog"] = group_id
        st.session_state.pop("msa_hog_selector", None)
    elif page == "ESMFold & models":
        st.session_state["selected_e3_model_protein"] = (accession, group_id, species)
        st.session_state["esmfold_view_route"] = "Predict with ESMFold"
        st.session_state["fold_route"] = "Selected E3 protein"
    elif page == "DeepClust results & FASTA":
        stage = DEEPCLUST_STAGE
        st.session_state["deepclust_exchange_mode"] = "Prepare query FASTA"
        st.session_state["ken_query_fasta_source"] = "Published HOG members"
        st.session_state["ken_query_selected_hog"] = group_id
    elif page == "DeepClust workbench":
        stage = DEEPCLUST_STAGE
        st.session_state["research_surface"] = page
        st.session_state["research_section"] = "Family analysis"
        st.session_state["research_analysis_task"] = "Alignment and tree"
        st.session_state["analyse_route"] = "Published HOG members"
        st.session_state["analyse_hog"] = group_id
        st.session_state["analyse_hog_input"] = group_id
    else:
        raise ResearchError("Unknown E3 viewer destination")
    st.session_state["e3_navigation_stage"] = stage
    st.session_state[f"e3_navigation_page_{stage}"] = page


def render_features(
    *, config: ResearchConfig, connection: object | None, dedicated: bool = False,
) -> None:
    """Share Nightingale, arbitrary-sequence annotation and ESMFold across both app contexts.

    Args:
        config: Analysis profile and jobs.
        connection: Optional immutable E3 domain evidence.
        dedicated: Focus the E3 entry point on feature viewing.
    """
    from .ui import render_annotations, render_models

    if not dedicated:
        st.subheader("Nightingale protein features")
    choices = (["Recorded E3 domain features"] if connection is not None else []) + [
        "Upload annotation results",
    ]
    if not dedicated:
        choices += [
            "InterProScan / eggNOG for selected sequences", "ESMFold for selected sequences",
        ]
    route = st.radio("Feature source", options=choices, horizontal=True,
                     key="feature_browser_route",
                     help="Open recorded domains or annotation files from another machine.")
    if route == "Upload annotation results":
        render_uploaded_features(config=config)
        return
    if route == "InterProScan / eggNOG for selected sequences":
        render_annotations(config=config)
        return
    if route == "ESMFold for selected sequences":
        render_models(config=config)
        return
    st.caption("InterPro and Pfam annotations recorded in the loaded E3 release.")
    choice = select_recorded_feature_context(config=config, connection=connection)
    if choice is None:
        return
    accession, group_id, species, raw_identifier = choice
    context = " · ".join(item for item in (group_id, species.replace("_", " ")) if item)
    st.subheader(accession)
    if context:
        st.caption(context)
    if dedicated and group_id:
        alignment, models = st.columns(2)
        alignment.button(
            label="Open this HOG in JBrowse MSA", key="feature_to_msa", on_click=open_e3_viewer,
            kwargs={"page": "JBrowse MSA", "group_id": group_id},
        )
        models.button(
            label="Open ESMFold for this protein", key="feature_to_models", on_click=open_e3_viewer,
            kwargs={
                "page": "ESMFold & models", "group_id": group_id,
                "accession": accession, "species": species,
            },
        )
    try:
        selected = published_features(
            connection=connection, accession=accession, group_id=group_id, species=species,
            raw_identifier=raw_identifier,
        )
    except ResearchError as exc:
        st.info(f"{exc}. Select Upload annotation results to open your own files.")
        return
    if selected.empty:
        st.info("Recorded features are unavailable for this protein in the selected HOG.")
        return
    selected[["primary_group_id", "species_column"]] = selected[
        ["primary_group_id", "species_column"]].fillna("")
    coordinates = ["protein_length", "location_start", "location_end"]
    numeric = selected[coordinates].apply(pd.to_numeric, errors="coerce")
    usable = numeric.notna().all(axis=1) & numeric.gt(0).all(axis=1)
    usable &= numeric.mod(1).eq(0).all(axis=1)
    usable &= numeric.protein_length.le(1_000_000)
    usable &= numeric.location_start.le(numeric.location_end)
    usable &= numeric.location_end.le(numeric.protein_length)
    if not usable.all():
        st.warning(f"{int((~usable).sum()):,} rows lack usable coordinates. See the full evidence.")
    for length in sorted(numeric.loc[usable, "protein_length"].unique()):
        subset = selected.loc[usable & numeric.protein_length.eq(length)].copy()
        subset["member_accession"] = accession
        if numeric.loc[usable, "protein_length"].nunique() > 1:
            st.caption(f"Recorded protein length {int(length):,} residues")
        stem = re.sub(r"[^a-zA-Z0-9_.-]", "_", f"{accession}_{group_id}_{int(length)}")
        show_features(payload=recorded_feature_payload(rows=subset), stem=f"{stem}_features")
    with st.expander("Recorded feature evidence", expanded=True):
        columns = ["entry_accession", "entry_name", "location_start", "location_end",
                   "protein_length", "source_database", "interpro_version"]
        st.dataframe(selected[[field for field in columns if field in selected]], hide_index=True)
        st.download_button("Download complete recorded feature evidence (TSV)",
                           data=selected.to_csv(sep="\t", index=False),
                           file_name="recorded_protein_features.tsv",
                           mime="text/tab-separated-values")


def select_recorded_feature_context(
    *, config: ResearchConfig, connection: object,
) -> tuple[str, str, str, str | None] | None:
    """Offer HOG membership browsing and preserve the exact recorded-protein search.

    Args:
        config: Research profile used to scope the release cache.
        connection: Open E3 resource with optional membership and domain tables.

    Returns:
        Accession, group and species, with an original identifier for HOG selections.
    """
    resource = _resource_identity(config=config)
    cached = st.session_state.get("recorded_feature_hog_ids")
    if cached is None or cached[0] != resource:
        try:
            ids = published_hog_ids(connection=connection)
        except AppError as exc:
            st.info(str(exc))
            ids = ()
        st.session_state["recorded_feature_hog_ids"] = (resource, ids)
    else:
        ids = cached[1]
    mode_key = "recorded_feature_browse_mode"
    requested = st.session_state.pop("recorded_feature_handoff_group", "")
    if requested:
        st.session_state[mode_key] = "HOG" if requested in ids else "Accession or group ID"
        st.session_state["recorded_feature_selected_hog"] = requested
        st.session_state.pop("recorded_feature_hog_picker", None)
        st.session_state.pop("recorded_feature_hog_selection", None)
    if ids and st.radio(
        "Find proteins by", options=("HOG", "Accession or group ID"), horizontal=True, key=mode_key,
    ) == "HOG":
        previous = st.session_state.get("recorded_feature_selected_hog", "")
        hog = st.selectbox(
            "HOG", options=ids, index=ids.index(previous) if previous in ids else None,
            placeholder="Type part of a HOG ID or choose from the list",
            key="recorded_feature_hog_picker",
        )
        st.session_state["recorded_feature_selected_hog"] = hog
        if hog is None:
            return None
        identity = (resource, hog)
        cached_members = st.session_state.get("recorded_feature_hog_members")
        if cached_members is None or cached_members[0] != identity:
            try:
                contexts = hog_feature_contexts(connection=connection, hog_id=hog)
            except AppError as exc:
                st.info(str(exc))
                return None
            st.session_state["recorded_feature_hog_members"] = (identity, contexts)
        else:
            contexts = cached_members[1]
        previous_member = st.session_state.get("recorded_feature_hog_selection")
        index = contexts.index(previous_member) if previous_member in contexts else None
        st.caption(f"{len(contexts):,} published members in {hog}")
        selected = st.selectbox(
            "Protein in this HOG", options=contexts, index=index,
            format_func=lambda row: f"{row[0]} · {row[2].replace('_', ' ')}"
            + (f" · {row[3]}" if row[0] != row[3] else ""),
            placeholder="Type an accession or species, or choose a protein",
            key=f"recorded_feature_hog_protein_{hog}",
        )
        st.session_state["recorded_feature_hog_selection"] = selected
        return selected

    st.session_state.setdefault(
        "recorded_feature_search_term", st.session_state.get("recorded_feature_query", ""),
    )
    with st.form("recorded_feature_search"):
        query = st.text_input(
            label="Accession or HOG ID",
            key="recorded_feature_search_term",
            placeholder="For example, Q5ZC88 or N0.HOG0000390",
        )
        if st.form_submit_button("Find recorded proteins"):
            st.session_state["recorded_feature_query"] = query.strip().upper()
            st.session_state.pop("recorded_feature_context", None)
    query = st.session_state.get("recorded_feature_query", "")
    if query:
        st.caption(f"Showing recorded contexts for {query}")
    try:
        matches = feature_contexts(connection=connection, query=query)
    except ResearchError as exc:
        st.info(f"{exc}. Select Upload annotation results to open your own files.")
        return
    if matches.empty:
        st.info("No recorded coordinates match this search in the loaded release.")
        return
    if len(matches) > 100:
        st.caption("Showing the first 100 matches. Search by accession to narrow the list.")
    contexts = list(matches.head(100).itertuples(index=False, name=None))
    choice = st.selectbox(
        label="Protein · group · species", options=contexts,
        format_func=lambda value: " · ".join(item.replace("_", " ") for item in value if item),
        key="recorded_feature_context",
        index=0 if query and len(contexts) == 1 else None, placeholder="Select a recorded protein",
    )
    return (*choice, None) if choice is not None else None


def show_features(*, payload: dict[str, object], stem: str) -> None:
    """Show a labelled Nightingale viewer and offer the same offline document.

    Args:
        payload: Validated feature tracks and coordinate axis.
        stem: Filename and widget namespace for this selection.
    """
    document = viewer_document(viewer="nightingale", payload=payload)
    features = {(feature["accession"], feature["description"]) for feature in payload["features"]}
    base_height = 182 if payload.get("sequence") else 144
    height = min(620, max(160, base_height + 50 * len(features)))
    components.html(document, height=height, scrolling=True)
    st.download_button("Download Nightingale viewer (HTML)", data=document,
                       file_name=f"{stem}.html", key=f"nightingale_{stem}", mime="text/html")


def upload_text(
    *, label: str, types: list[str], key: str, maximum: int = UPLOAD_BYTES,
    help_text: str | None = None,
) -> str:
    """Read a bounded UTF-8 viewer upload with a visible file requirement.

    Args:
        label: File control label.
        types: Supported filename extensions.
        key: Unique widget key.
        maximum: Maximum upload bytes.
        help_text: Optional instructions displayed beside the upload control.

    Returns:
        Decoded text, or empty text before a file is selected.
    """
    limit_mb = (maximum + 999_999) // 1_000_000
    options = {}
    if "max_upload_size" in signature(st.file_uploader).parameters:
        options["max_upload_size"] = limit_mb
    else:
        st.caption(f"This input accepts up to {limit_mb} MB of text.")
    uploaded = st.file_uploader(label=label, type=types, key=key, help=help_text, **options)
    if uploaded is None:
        return ""
    if uploaded.size > maximum:
        raise ResearchError(f"{label} exceeds {maximum / 1_000_000:g} MB")
    try:
        return uploaded.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ResearchError(f"{label} must contain UTF-8 text") from exc


def render_uploaded_features(*, config: ResearchConfig) -> None:
    """Display worker-produced annotations against the exact uploaded protein FASTA.

    Args:
        config: Protein input limits from the current profile.
    """
    st.caption("Upload annotation_input.fasta and annotations.tsv from a completed annotation job.")
    fasta = upload_text(label="Annotation input FASTA", types=["fa", "faa", "fasta"],
                        key="viewer_annotation_fasta")
    annotations = upload_text(label="Normalised annotations TSV", types=["tsv"],
                              key="viewer_annotation_tsv")
    if not fasta or not annotations:
        return
    records = uploaded_proteins(text=fasta, maximum_records=config.max_alignment_sequences)
    reader = csv.DictReader(StringIO(annotations), delimiter="\t")
    if not {"sequence_id", "sequence_sha256", "start", "end"}.issubset(reader.fieldnames or ()):
        raise ResearchError("Upload the normalised annotations.tsv from the research worker")
    identifier = st.selectbox("Annotated protein", options=list(records))
    sequence = records[identifier]
    rows = [row for row in reader if row["sequence_id"] == identifier]
    features = nightingale_features(sequence_id=identifier, sequence=sequence, annotations=rows)
    show_features(payload={"sequence": sequence, "features": features}, stem="uploaded_features")
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True)


def render_uploaded_alignment(*, config: ResearchConfig, example: bool = False) -> None:
    """Open a ready-made alignment with optional protein or reviewed species tree.

    Args:
        config: Rendering limits and optional reviewed species backbone.
        example: Use an explicitly labelled synthetic alignment.
    """
    if example:
        st.caption("Example with synthetic sequences and a demonstration tree.")
        render_jbrowse(records=EXAMPLE_ALIGNMENT, tree=EXAMPLE_TREE, stem="example_jbrowse_msa")
        return
    st.caption("Upload a gapped protein FASTA from MAFFT or another aligner. A tree is optional.")
    msa = upload_text(
        label="Aligned protein FASTA", types=["fa", "faa", "fasta", "aln"],
        key="viewer_aligned_fasta",
        help_text="The file must be in FASTA format, with one equal-length row per protein.",
    )
    if not msa:
        return
    records = uploaded_proteins(text=msa, aligned=True,
                                maximum_records=config.max_alignment_sequences,
                                maximum_cells=config.max_alignment_cells)
    tree = ""
    kind = st.radio(
        label="Tree beside the MSA", options=["No tree", "Protein tree", "Reviewed species tree"],
        horizontal=True, key="viewer_uploaded_tree_kind",
    )
    if kind != "No tree":
        newick = upload_text(label=f"{kind} (Newick)", types=["nwk", "newick", "tree", "nh"],
                             key=f"viewer_tree_{kind}", maximum=TREE_BYTES)
        if kind == "Protein tree" and newick:
            tree = validate_protein_tree(newick=newick, identifiers=list(records))
        elif kind == "Reviewed species tree":
            mapping = upload_text(label="Reviewed sequence-to-species mapping (TSV)",
                                  types=["tsv"], key="viewer_species_mapping")
            if newick and mapping:
                tree, audit = species_display_tree(
                    newick=newick, sequence_ids=list(records),
                    metadata=read_species_mapping(text=mapping),
                )
                st.download_button("Download species-tree mapping audit (TSV)",
                                   data=pd.DataFrame(audit).to_csv(sep="\t", index=False),
                                   file_name="msa_species_mapping.tsv")
            else:
                st.info("Supply a species tree and mapping with sequence_id, species and "
                        "taxon_id. The alignment is available below while you select files.")
    render_jbrowse(records=records, tree=tree, stem="jbrowse_msa")


def render_published_alignment(
    *, config: ResearchConfig, app_config: AppConfig, can_align_hog: bool = False,
) -> None:
    """Open an exact HOG's recorded plant review alignment, if exported.

    Args:
        config: Protein alignment rendering limits.
        app_config: Loaded resource and optional plant review bundle.
        can_align_hog: Published HOG inputs can be selected on this page.
    """
    st.caption("Look up the aligned sequences exported with the plant pocket review.")
    st.session_state.setdefault(
        "published_alignment_input", st.session_state.get("published_alignment_group", ""),
    )
    with st.form(key="published_hog_alignment"):
        entered = st.text_input(
            label="Exact HOG ID", key="published_alignment_input", placeholder="N0.HOG0000390",
        )
        if st.form_submit_button(label="Find published alignment"):
            st.session_state["published_alignment_group"] = entered.strip().upper()
    group_id = st.session_state.get("published_alignment_group", "")
    if can_align_hog:
        st.button(
            label="Align this HOG" if group_id else "Start a new HOG alignment",
            on_click=open_e3_viewer, kwargs={"page": "Align a HOG", "group_id": group_id},
            help="Load the unaligned protein sequences directly from the E3 release.",
        )
    if not group_id:
        return
    st.caption(f"Selected HOG {group_id}")
    if not can_align_hog:
        st.button(
            label="Align this HOG", on_click=open_e3_viewer,
            kwargs={"page": "DeepClust workbench", "group_id": group_id},
            help="Set up a new sequence alignment from the HOG's published members.",
        )
    bundle = prepare_pocket_review(config=app_config)
    if bundle.available:
        hits = bundle.index.loc[bundle.index["primary_group_id"].astype(str).eq(group_id)]
        if len(hits) == 1:
            try:
                fasta = selected_group_alignment_fasta_bytes(
                    bundle=bundle, review_rank=int(hits.iloc[0]["review_rank"]),
                )
            except AppError as exc:
                st.info(str(exc))
            else:
                records = uploaded_proteins(
                    text=fasta.decode("utf-8"), aligned=True,
                    maximum_records=config.max_alignment_sequences,
                    maximum_cells=config.max_alignment_cells,
                )
                st.caption("Published MAFFT alignment from the plant pocket-review sequence set.")
                stem = re.sub(r"[^a-zA-Z0-9_.-]", "_", group_id)
                render_jbrowse(records=records, tree="", stem=f"{stem}_pocket_review_msa")
                st.download_button(
                    label="Download published aligned FASTA", data=fasta,
                    file_name=f"{stem}_pocket_review_alignment.fasta", mime="text/plain",
                )
                return
        else:
            st.info(f"No unique plant pocket-review alignment is available for {group_id}.")
    else:
        st.info("The plant pocket-review bundle is unavailable in this app session.")
    st.button(
        label="Prepare HOG member FASTA", on_click=open_e3_viewer,
        kwargs={"page": "DeepClust results & FASTA", "group_id": group_id},
        help="Select published HOG sequences for alignment in the workbench or on another machine.",
    )


def render_jbrowse(*, records: dict[str, str], tree: str, stem: str) -> None:
    """Open a validated alignment in a readable frame sized to the number of rows.

    Args:
        records: Validated aligned protein records in their intended display order.
        tree: Optional Newick tree using those record IDs.
        stem: Download filename stem.
    """
    sequence_count = len(records)
    alignment_length = len(next(iter(records.values())))
    row_height = 26 if sequence_count <= 16 else 19
    height = min(640, max(250, 118 + row_height * sequence_count))
    st.caption(f"{sequence_count:,} proteins · {alignment_length:,} aligned positions. "
               "Use the toolbar to zoom or fit the alignment.")
    document = viewer_document(
        viewer="jbrowse", payload={
            "msa": "".join(f">{name}\n{sequence}\n" for name, sequence in records.items()),
            "tree": tree, "alignment_length": alignment_length, "row_height": row_height,
            "height": height,
        },
    )
    components.html(document, height=height + 42, scrolling=True)
    st.download_button("Download standalone JBrowse MSA viewer", data=document,
                       file_name=f"{stem}.html", mime="text/html")


def species_view(
    *, config: ResearchConfig, job_id: str, records: dict[str, str], default_tree: str,
) -> str:
    """Offer an explicit reviewed species backbone for a completed JBrowse MSA selection.

    Args:
        config: Optional configured species tree and current sidecar.
        job_id: Completed alignment job with reviewed metadata.
        records: All exact aligned protein rows.
        default_tree: Existing inferred protein tree, if available.

    Returns:
        Selected display tree, or empty text if requested species evidence is unavailable.
    """
    from .ui import completed_manifests

    choice = st.radio("Tree beside the MSA",
                      options=("Inferred protein tree", "Reviewed species tree"),
                      horizontal=True, key="msa_tree_kind",
                      help="Protein inference and reviewed species backbones are distinct.")
    if choice == "Inferred protein tree":
        return default_tree
    uploaded = st.file_uploader("Reviewed species tree (Newick)",
                                type=["nwk", "nh", "newick", "tree"],
                                key="msa_species_tree")
    text = ""
    if uploaded is not None:
        if uploaded.size > 2_000_000:
            raise ResearchError("Species tree exceeds 2 MB")
        text = uploaded.getvalue().decode("utf-8")
    elif config.species_tree:
        path = Path(config.species_tree).expanduser()
        if path.stat().st_size > 2_000_000:
            raise ResearchError("Species tree exceeds 2 MB")
        text = path.read_text(encoding="utf-8")
    if not text:
        st.info("Upload a reviewed species Newick tree or configure species_tree. Tip names "
                "must match reviewed species labels or taxon IDs exactly.")
        return ""
    metadata = {}
    manifest = completed_manifests(config=config, operation="align")[job_id]
    if "member_taxonomy.tsv" in manifest["artifacts"]:
        frame = pd.read_csv(filepath_or_buffer=artifact_path(
            workspace=config.workspace, job_id=job_id, artifact="member_taxonomy.tsv",
        ), sep="\t", dtype=str, keep_default_na=False)
        metadata = {row["sequence_id"]: row for row in frame.to_dict(orient="records")}
    uploaded_metadata = st.file_uploader("Reviewed sequence-to-species mapping (optional TSV)",
                                         type=["tsv"], key="msa_species_metadata")
    if uploaded_metadata is not None:
        if uploaded_metadata.size > 20_000_000:
            raise ResearchError("Species mapping exceeds 20 MB")
        frame = pd.read_csv(filepath_or_buffer=StringIO(uploaded_metadata.getvalue().decode()),
                            sep="\t", dtype=str, keep_default_na=False)
        if not {"sequence_id", "species", "taxon_id"}.issubset(frame):
            raise ResearchError("Species mapping requires sequence_id/species/taxon_id")
        if frame["sequence_id"].duplicated().any():
            raise ResearchError("Each sequence needs one reviewed species mapping")
        metadata = {row["sequence_id"]: row for row in frame.to_dict(orient="records")}
    try:
        tree, audit = species_display_tree(
            newick=text, sequence_ids=list(records), metadata=metadata)
    except ResearchError as exc:
        st.warning(str(exc))
        return ""
    st.caption("Reviewed species backbone. Multiple proteins within a species are grouped "
               "in a display polytomy; those branches do not infer paralogue relationships.")
    st.download_button("Download species display tree", data=tree,
                       file_name="msa_species_display.nwk", mime="text/plain")
    st.download_button("Download species-tree mapping audit (TSV)",
                       data=pd.DataFrame(data=audit).to_csv(sep="\t", index=False),
                       file_name="msa_species_mapping.tsv", mime="text/tab-separated-values")
    return tree
