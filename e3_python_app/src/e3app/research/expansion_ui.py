"""Dedicated Top-N cluster campaign, quantitative comparisons and shared protein feature UI."""

from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scipy.cluster.hierarchy import dendrogram
import streamlit as st
import streamlit.components.v1 as components

from .campaign import CampaignSelection, select_campaign, submit_campaign
from .common import ResearchConfig, ResearchError, iter_fasta
from .feature_catalogue import published_features, recorded_feature_payload
from .jobs import artifact_path
from .remote import ssh_command
from .species_tree import species_display_tree
from .viewers import viewer_document


def _resource_identity(*, config: ResearchConfig) -> tuple:
    """Bind prepared campaign inputs to the current E3 resource and research sidecar."""
    values = [str(config.workspace)]
    for key in ("E3_RESOURCE_DUCKDB", "E3_RESOURCE_PARQUET", "E3_RESOURCE_RUN_DIR"):
        value = os.environ.get(key, "")
        path = Path(value).expanduser() if value else None
        stamp = path.stat().st_mtime_ns if path is not None and path.exists() else None
        values.append((key, value, stamp))
    return tuple(values)


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
    st.plotly_chart(go.Figure(data=go.Heatmap(
        z=similarity.to_numpy(), x=order, y=order, customdata=counts.to_numpy(), zmin=0, zmax=1,
        colorscale="Viridis", hovertemplate="%{y} / %{x}<br>Similarity: %{z:.3f}"
        "<br>Denominator: %{customdata}<extra></extra>",
    )), key=f"comparison_heatmap_{job_id}")
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


def render_features(*, config: ResearchConfig, connection: object | None) -> None:
    """Share Nightingale, arbitrary-sequence annotation and ESMFold across both app contexts.

    Args:
        config: Analysis profile and jobs.
        connection: Optional immutable E3 domain evidence.
    """
    from .ui import render_annotations, render_models

    st.subheader("Protein features")
    choices = (["Recorded E3 domain features"] if connection is not None else []) + [
        "InterProScan / eggNOG for selected sequences", "ESMFold for selected sequences",
    ]
    route = st.radio("Protein feature workflow", options=choices, horizontal=True,
                     key="feature_browser_route",
                     help="Recorded domains or explicit selected-sequence jobs.")
    if route == "InterProScan / eggNOG for selected sequences":
        render_annotations(config=config)
        return
    if route == "ESMFold for selected sequences":
        render_models(config=config)
        return
    accession = st.text_input("Exact published protein accession", key="recorded_feature_accession",
                              help="Exact accession from the published domain evidence.")
    if not accession.strip():
        st.info("Enter an accession from E3 results or choose a sequence workflow above.")
        return
    rows = published_features(connection=connection, accession=accession)
    if rows.empty:
        st.info("No recorded domain hits match this exact accession. InterProScan can annotate "
                "an uploaded/pasted FASTA or proteins from a completed DeepClust job.")
        return
    pairs = rows[["primary_group_id", "species_column"]].astype(str).drop_duplicates()
    contexts = list(pairs.itertuples(index=False, name=None))
    group_id, species = st.selectbox("Recorded annotation context", options=contexts,
                                     format_func=lambda value: " · ".join(value),
                                     help="Keep the recorded group and species context.")
    selected = rows.loc[rows["primary_group_id"].astype(str).eq(group_id)
                        & rows["species_column"].astype(str).eq(species)]
    payload = recorded_feature_payload(rows=selected)
    document = viewer_document(viewer="nightingale", payload=payload)
    components.html(document, height=340, scrolling=True)
    st.caption("This view uses the recorded annotation protein-length axis. It does not claim "
               "a sequence match to a current model. InterProScan jobs provide feature tracks "
               "verified against their exact submitted amino-acid sequences.")
    st.dataframe(selected, hide_index=True)
    st.download_button("Download Nightingale feature viewer", data=document,
                       file_name="recorded_protein_features.html", mime="text/html")
    st.download_button("Download complete recorded feature evidence (TSV)",
                       data=selected.to_csv(sep="\t", index=False),
                       file_name="recorded_protein_features.tsv", mime="text/tab-separated-values")


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
