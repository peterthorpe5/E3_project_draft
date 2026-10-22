"""Lazy protein research UI shared by E3 and the standalone generic application."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from pathlib import Path
from typing import Mapping

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from .catalogue import browse_clusters, open_catalogue
from .common import ResearchConfig, ResearchError, iter_fasta, load_config
from .deepclust_exchange import centroid_list
from .guidance import (
    FIELD_HELP,
    GLOSSARY,
    OPERATION_NAMES,
    PAGE_GUIDES,
    SECTIONS,
    job_label,
    provider_problem,
    retrievable_cluster_ids,
    user_guide,
)
from .jobs import artifact_path, cancel_job, job_directory, list_jobs, submit_job
from .viewers import auspice_dataset_url, nightingale_features, viewer_document

LOGGER = logging.getLogger(__name__)


def navigate_research(
    *,
    section: str,
    discovery_mode: str = "",
    analysis_task: str = "",
    source_job: str = "",
    source_artifact: str = "",
    job_id: str = "",
    input_route: str = "",
) -> None:
    """Move between workflow pages using a widget callback before the next render.

    Args:
        section: Destination workbench page.
        discovery_mode: Optional discovery route.
        analysis_task: Optional family-analysis task.
        source_job: Optional completed source job.
        source_artifact: Optional unaligned source FASTA.
        job_id: Optional job to focus in Jobs.
        input_route: Optional completed-job or upload input route.

    Raises:
        ResearchError: If a destination or paired source is invalid.
    """
    if section not in SECTIONS or bool(source_job) != bool(source_artifact):
        raise ResearchError("Choose a valid workbench destination and complete FASTA source")
    if discovery_mode and discovery_mode not in {
        "E3 ranked groups",
        "Sequence identifiers",
        "Known global centroids",
        "Global cluster ranking",
        "Import extracted cluster",
    }:
        raise ResearchError("Unknown discovery route")
    if analysis_task and analysis_task not in {
        "Stricter subclusters",
        "Alignment and tree",
        "Representative homology search",
    }:
        raise ResearchError("Unknown family-analysis task")
    if input_route and input_route not in {"Completed job", "Upload FASTA"}:
        raise ResearchError("Unknown protein input route")
    st.session_state["research_section"] = section
    if discovery_mode:
        st.session_state["research_discovery_mode"] = discovery_mode
    if analysis_task:
        st.session_state["research_analysis_task"] = analysis_task
    if source_job:
        st.session_state["analyse_route"] = "Completed job"
        st.session_state["analyse_source"] = (source_job, source_artifact)
    elif input_route:
        st.session_state["analyse_route"] = input_route
    if job_id:
        state_key = {
            "Alignments and trees": "research_alignment_job",
            "Models": "research_model_job",
            "Annotations": "research_annotation_job",
            "Discover": "research_mapping_job",
        }.get(section, "research_job")
        st.session_state[state_key] = job_id


def render_next_action(*, label: str, key: str, primary: bool = False, **destination: str) -> None:
    """Offer an explicit next step without submitting another analysis.

    Args:
        label: User-facing action.
        key: Unique button identity.
        primary: Emphasise the recommended entry point.
        **destination: Named navigation arguments.
    """
    st.button(
        label,
        key=key,
        on_click=navigate_research,
        kwargs=destination,
        help="Open the next page and review its inputs. This does not queue a job.",
        type="primary" if primary else "secondary",
    )


def render_page_guidance(*, section: str) -> None:
    """Explain the current page's aim, inputs, outputs and next action.

    Args:
        section: Page with a registered guide.
    """
    title, aim, instructions = PAGE_GUIDES[section]
    st.subheader(title)
    st.write(aim)
    with st.expander("How to use this page · inputs, steps and outputs"):
        st.markdown(instructions)


def render_start(*, config: ResearchConfig, connection: object | None) -> None:
    """Offer project-aware entry points while retaining generic FASTA workflows.

    Args:
        config: Current workspace profile.
        connection: Optional source-project adapter connection.
    """
    st.subheader("Start with one protein family")
    st.write(
        "The aim is to collect a relevant family, compare its protein sequences and inspect "
        "conservation and relationships. Structure and annotation predictions are optional."
    )
    columns = st.columns(3)
    for column, title, body in zip(
        columns,
        ("1 · Find and collect", "2 · Analyse the family", "3 · Inspect and download"),
        (
            "Map protein IDs to global DeepClust clusters, then retrieve their sequences. "
            "You can also start with your own unaligned protein FASTA.",
            "Create stricter subclusters if the family is broad. Align the complete family, "
            "one subcluster, or an explicitly selected sample.",
            "Explore alignments and trees, inspect optional models/annotations, and use Jobs "
            "for progress and complete downloads.",
        ),
        strict=True,
    ):
        with column:
            st.markdown(f"**{title}**")
            st.write(body)
    st.markdown("#### What are you starting with?")
    if connection is not None:
        st.info(
            "Recommended for this E3 session: begin with one ranked E3 HOG or discovery "
            "cluster. Its member/source accessions and linked seeds are used for exact "
            "mapping; a medoid is not calculated automatically."
        )
        render_next_action(
            label="Start from E3 groups (recommended)",
            key="start_e3",
            section="Discover",
            discovery_mode="E3 ranked groups",
            primary=True,
        )
    else:
        st.info(
            "This is a standalone protein session. Start with sequence IDs or a FASTA. "
            "E3 ranked groups is available when this workbench is opened inside the full E3 app."
        )
    left, right = st.columns(2)
    with left:
        render_next_action(
            label="I have protein sequence IDs",
            key="start_ids",
            section="Discover",
            discovery_mode="Sequence identifiers",
        )
        render_next_action(
            label="I know a global DeepClust centroid",
            key="start_centroid",
            section="Discover",
            discovery_mode="Known global centroids",
        )
    with right:
        render_next_action(
            label="I have a protein FASTA",
            key="start_fasta",
            section="Family analysis",
            analysis_task="Alignment and tree",
            input_route="Upload FASTA",
        )
        render_next_action(
            label="I have an exported DeepClust cluster",
            key="start_export",
            section="Discover",
            discovery_mode="Import extracted cluster",
        )
    st.caption(
        "A sequence ID, a local project group and a global centroid are different inputs. "
        "Use the question-mark help beside each control for examples. No analysis starts "
        "until you click a Queue button."
    )
    with st.expander("What is available in this session?"):
        st.write(
            "These checks show local setup, not network service availability or worker health."
        )
        st.table(
            pd.DataFrame(
                [
                    {
                        "Input": label,
                        "Setup": (
                            "File available"
                            if value and Path(value).expanduser().is_file()
                            else "Needs configuration / mount"
                        ),
                    }
                    for label, value in (
                        ("DeepClust cluster index", config.index),
                        ("DeepClust sequence-to-cluster map", config.sequence_map),
                        ("DeepClust sequence data", config.sequences),
                        ("Reviewed cluster/species index (optional)", config.cluster_taxonomy),
                    )
                ]
            )
        )
        st.write(
            "Uploaded FASTA analysis and completed results can be used independently of DeepClust."
        )
    render_next_action(label="Review jobs and existing results", key="start_jobs", section="Jobs")


def render_help(*, connection: object | None) -> None:
    """Render reusable user help without requiring scientific data or external services.

    Args:
        connection: Optional adapter; controls inclusion of E3-specific instructions.
    """
    st.subheader("Help & glossary")
    st.write(
        "Use Start here to choose an input. Follow the three core steps; predictions are optional."
    )
    guide = user_guide(include_e3=connection is not None)
    st.download_button(
        "Download the workbench user guide",
        data=guide,
        file_name="protein_research_user_guide.txt",
        mime="text/plain",
    )
    for title, aim, instructions in PAGE_GUIDES.values():
        with st.expander(title):
            st.write(aim)
            st.markdown(instructions)
    with st.expander("FASTA example and identifier rules", expanded=True):
        st.code(
            ">protein_A Example protein\nMAAKLVVAGL\n>protein_B Another protein\nMAAKLVIAGL\n",
            language="text",
        )
        st.write(FIELD_HELP["upload"])
        st.write(
            "To select the first protein, enter protein_A. Keep actual accessions and source "
            "prefixes exactly as supplied; do not rename real DeepClust headers."
        )
    with st.expander("Glossary"):
        for term, meaning in GLOSSARY.items():
            st.markdown(f"**{term}:** {meaning}")
    with st.expander("Troubleshooting · queued jobs, missing IDs and unavailable tools"):
        st.markdown(guide.split("## Troubleshooting\n\n", 1)[1])


def split_identifiers(*, value: str) -> list[str]:
    """Parse pasted newline/comma/semicolon identifiers without changing their case.

    Args:
        value: Pasted identifiers; whitespace separates entries.

    Returns:
        Unique identifiers in their original order.
    """
    return list(dict.fromkeys(value.replace(",", " ").replace(";", " ").split()))


def completed_manifests(*, config: ResearchConfig, operation: str = "") -> dict[str, dict]:
    """Collect bounded recent completed manifests without loading scientific artifacts.

    Args:
        config: Workspace profile.
        operation: Optional exact operation filter.

    Returns:
        Job IDs and manifest dictionaries; corrupt manifests raise a controlled diagnostic.
    """
    result = {}
    for job in list_jobs(workspace=config.workspace):
        if job["status"] != "COMPLETE" or (operation and job["operation"] != operation):
            continue
        path = job_directory(workspace=config.workspace, job_id=job["job_id"]) / "manifest.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(manifest.get("artifacts"), dict)
                or manifest.get("job_id") != job["job_id"]
            ):
                raise ValueError("Invalid manifest")
            result[job["job_id"]] = manifest
        except (OSError, ValueError, TypeError) as exc:
            raise ResearchError(
                "A completed job manifest is corrupt; inspect the worker workspace"
            ) from exc
    return result


def read_table(*, path: Path, maximum_rows: int = 10_000) -> pd.DataFrame:
    """Read a bounded preview without coercing accessions or literal NA identifiers.

    Args:
        path: Checksummed TSV artifact.
        maximum_rows: Preview cap; full files remain available as artifacts.

    Returns:
        String-valued table suitable for exact joins and safe display.
    """
    return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, nrows=maximum_rows)


def render_input(*, config: ResearchConfig, key: str) -> tuple[dict[str, object], str | None]:
    """Select an uploaded FASTA or a complete checksummed prior-job FASTA artifact.

    Args:
        config: Current workspace.
        key: Unique UI control namespace.

    Returns:
        Source parameters and optional uploaded FASTA content.
    """
    manifests = completed_manifests(config=config)
    options = [
        (job_id, name)
        for job_id, manifest in manifests.items()
        for name in manifest["artifacts"]
        if name.endswith((".fasta", ".faa", ".fa")) and name != "alignment.fasta"
    ]
    route = st.radio(
        "Protein input",
        ["Completed job", "Upload FASTA"],
        horizontal=True,
        key=f"{key}_route",
        help=FIELD_HELP["protein_input"],
        index=0 if options else 1,
    )
    if route == "Upload FASTA":
        uploaded = st.file_uploader(
            "Protein FASTA (maximum 20 MB)",
            type=["fa", "faa", "fasta"],
            key=f"{key}_upload",
            help=FIELD_HELP["upload"],
        )
        with st.expander("What should the FASTA look like?"):
            st.code(">protein_A\nMAAKLVVAGL\n>protein_B\nMAAKLVIAGL\n", language="text")
            st.write(FIELD_HELP["upload"])
        if uploaded is None:
            return {}, None
        if uploaded.size > 20_000_000:
            raise ResearchError("Uploaded FASTA exceeds 20 MB")
        try:
            return {}, uploaded.getvalue().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResearchError("FASTA must be UTF-8 text") from exc
    if not options:
        st.info(
            "No completed FASTA is available. Upload a protein FASTA, or first retrieve/import "
            "a cluster in Discover and wait for its job to complete."
        )
        return {}, None
    labels = {
        item: job_label(job_id=item[0], record=manifests[item[0]], artifact=item[1])
        for item in options
    }
    if st.session_state.get(f"{key}_source") not in options:
        st.session_state.pop(f"{key}_source", None)
    selected = st.selectbox(
        "Complete source FASTA",
        options=options,
        format_func=labels.__getitem__,
        help=FIELD_HELP["source"],
        key=f"{key}_source",
    )
    manifest = manifests[selected[0]]
    if manifest.get("operation") == "retrieve" and "clusters.tsv" in manifest["artifacts"]:
        clusters = read_table(
            path=artifact_path(
                workspace=config.workspace, job_id=selected[0], artifact="clusters.tsv"
            )
        )
        matched = clusters[clusters["fasta_artifact"] == selected[1]]
        if not matched.empty:
            cluster = matched.iloc[0]
            st.caption(
                f"Input family: {cluster['cluster_id']} · "
                f"{cluster['retrieved_members']} retrieved proteins"
            )
    if manifest.get("operation") == "align" and manifest.get("parameters", {}).get(
        "allow_sampling"
    ):
        st.warning(
            "This FASTA comes from an alignment job with sampling enabled. It represents "
            "that analysed selection; use the original retrieval FASTA for the full family."
        )
    st.caption(f"Selected source: {selected[1]} · job {selected[0]}")
    return {"source_job": selected[0], "source_artifact": selected[1]}, None


def queue_action(
    *,
    config: ResearchConfig,
    operation: str,
    parameters: Mapping[str, object],
    fasta: str | None = None,
) -> None:
    """Queue one explicit user action and display its durable job identifier.

    Args:
        config: Workspace profile.
        operation: Validated analysis type.
        parameters: Scientific controls from the visible form.
        fasta: Optional uploaded protein FASTA.
    """
    job_id = submit_job(
        workspace=config.workspace, operation=operation, parameters=parameters, fasta=fasta
    )
    LOGGER.info("Workbench queued %s job %s", operation, job_id)
    st.success(f"Queued: {OPERATION_NAMES.get(operation, operation)} · job {job_id}.")
    st.info(
        "Next: open Jobs and wait for COMPLETE. The analysis worker executes the request; "
        "a queued job has not started yet. You can leave the browser open or return later."
    )
    render_next_action(
        label="Track this job",
        key=f"track_{job_id}",
        section="Jobs",
        job_id=job_id,
    )


def render_deepclust_import(*, config: ResearchConfig) -> None:
    """Queue one selected upstream FASTA export without a global database installation.

    Args:
        config: Research workspace and sequence bounds.
    """
    st.write(
        "Import a selected cluster exported by drostlab/deepclust_dataretrieval with "
        "--per-clust-output 1. The global database is needed on the extraction machine; "
        "this app needs only the resulting FASTA."
    )
    st.caption(
        "Keep exact identifiers and source prefixes, for example NR_UGC79169.1. "
        "A sequence accession or local E3 group ID is not necessarily a global centroid."
    )
    with st.form("research_deepclust_import"):
        identifier = st.text_input(
            "Exact DeepClust centroid ID", placeholder="NR_UGC79169.1", help=FIELD_HELP["centroid"]
        )
        uploaded = st.file_uploader(
            "Per-cluster FASTA export (maximum 20 MB)",
            type=["fa", "faa", "fasta"],
            key="deepclust_export",
            help="Upload one cluster exported with --per-clust-output 1. " + FIELD_HELP["upload"],
        )
        provenance = st.text_input(
            "Export source / database release",
            help="Record who extracted the cluster and the database release/date. "
            "This is retained in the source audit; it is required for reproducibility.",
            placeholder="For example: database holder; DeepClust release; export date",
        )
        expected = st.number_input(
            "Expected published member count (0 if unavailable)",
            min_value=0,
            max_value=config.max_sequences,
            value=0,
            help="If the published count is known, enter it so incomplete exports are rejected. "
            "Zero means unknown; a successful import then does not establish global completeness.",
        )
        st.caption(
            "The centroid must occur in the FASTA. A supplied member count is checked; "
            "membership and completeness otherwise remain those of the supplied export. "
            "For larger files use the import-deepclust command in DEEPCLUST_EXCHANGE.md."
        )
        queued = st.form_submit_button(
            "Queue cluster import", help="Validate and save the supplied cluster on the worker."
        )
    if queued:
        if uploaded is None:
            raise ResearchError("Select a per-cluster FASTA export before importing")
        if not provenance.strip():
            raise ResearchError("Supply the export source and database release")
        centroid_list(identifiers=[identifier])
        if uploaded.size > 20_000_000:
            raise ResearchError(
                "FASTA export exceeds 20 MB; use the local import-deepclust command"
            )
        try:
            fasta = uploaded.getvalue().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResearchError("FASTA export must be UTF-8 text") from exc
        queue_action(
            config=config,
            operation="import_cluster",
            parameters={
                "cluster_id": identifier,
                "source_label": provenance,
                "expected_members": expected or None,
            },
            fasta=fasta,
        )
    st.info(
        "After the worker completes the import, select its cluster.fasta under Family analysis "
        "to recluster or align it. Jobs contains the membership, length summary and source audit."
    )


def render_discovery(*, config: ResearchConfig, connection: object | None) -> None:
    """Render global rankings, exact-sequence linking and the optional E3 selection adapter.

    Args:
        config: DeepClust source profile.
        connection: Optional immutable E3 connection; absent in generic mode.
    """
    render_page_guidance(section="Discover")
    modes = [
        "Global cluster ranking",
        "Sequence identifiers",
        "Known global centroids",
        "Import extracted cluster",
    ]
    if not config.index or not Path(config.index).expanduser().is_file():
        modes.insert(0, modes.pop())
    if connection is not None:
        modes.insert(0, "E3 ranked groups")
    if st.session_state.get("research_discovery_mode") not in modes:
        st.session_state.pop("research_discovery_mode", None)
    mode = st.radio(
        "Discover clusters",
        modes,
        horizontal=True,
        key="research_discovery_mode",
        help=FIELD_HELP["discovery"],
    )
    if mode == "Import extracted cluster":
        render_deepclust_import(config=config)
        return
    if mode == "Global cluster ranking":
        st.write(
            "Browse the global catalogue by published size, or paste a known centroid "
            "directly into Retrieve complete clusters below. Ranking does not map E3 HOGs."
        )
        indexed = bool(config.index and Path(config.index).expanduser().is_file())
        taxonomy_ready = bool(
            config.cluster_taxonomy and Path(config.cluster_taxonomy).expanduser().is_file()
        )
        if not indexed:
            st.info(
                "Global ranking needs the configured DeepClust cluster index. "
                "You can still import an extracted FASTA or analyse your own sequences."
            )
        if not taxonomy_ready:
            st.caption(
                "Species filters are unavailable until a reviewed cluster/species index "
                "is configured. You can browse by size or exact centroid without it."
            )
        with st.form("research_browse"):
            minimum = st.number_input(
                "Minimum published cluster size",
                min_value=1,
                value=3,
                help=FIELD_HELP["minimum_size"],
            )
            exact = st.text_area("Exact global cluster IDs (optional)", help=FIELD_HELP["centroid"])
            taxa = st.text_input(
                "Required species/taxon IDs (optional, e.g. 9606 3702)",
                help=FIELD_HELP["taxa"],
                disabled=not taxonomy_ready,
            )
            all_taxa = st.checkbox(
                "Require every selected species/taxon",
                help=FIELD_HELP["all_taxa"],
                disabled=not taxonomy_ready,
            )
            any_species = st.checkbox(
                "Require at least one reviewed species assignment",
                help=FIELD_HELP["species"],
                disabled=not taxonomy_ready,
            )
            limit = st.number_input(
                "Ranking preview rows",
                min_value=1,
                max_value=10000,
                value=200,
                help=FIELD_HELP["preview"],
            )
            browse = st.form_submit_button(
                "Rank global clusters",
                disabled=not indexed,
                help="Query the configured catalogue. Large mounted files may take time to read.",
            )
        if browse:
            try:
                taxon_ids = [int(value) for value in split_identifiers(value=taxa)]
            except ValueError as exc:
                raise ResearchError(
                    "Species selection uses numeric taxon IDs from reviewed metadata"
                ) from exc
            with open_catalogue(config=config) as catalogue:
                st.session_state["research_clusters"] = browse_clusters(
                    connection=catalogue,
                    minimum_members=minimum,
                    cluster_ids=split_identifiers(value=exact),
                    taxon_ids=taxon_ids if taxonomy_ready else [],
                    require_all_taxa=all_taxa if taxonomy_ready else False,
                    any_annotated_species=any_species if taxonomy_ready else False,
                    limit=limit,
                )
        frame = st.session_state.get("research_clusters")
        if frame is not None:
            st.dataframe(frame, hide_index=True)
            if not frame.empty:
                st.caption(
                    f"{int(frame['qualifying_cluster_count'].iloc[0]):,} clusters qualify; "
                    "preview is size ranked."
                )
                st.plotly_chart(
                    px.bar(
                        frame.head(30),
                        x="member_count",
                        y="cluster_id",
                        orientation="h",
                        log_x=True,
                    ),
                    key="global_cluster_sizes",
                )
                choices = retrievable_cluster_ids(frame=frame)
                chosen = st.multiselect(
                    "Ranked clusters to collect",
                    options=choices,
                    default=choices[:1],
                    help=FIELD_HELP["centroid"],
                )
                if st.button("Use selected ranked clusters for retrieval", disabled=not chosen):
                    st.session_state["research_retrieve_ids"] = "\n".join(chosen)
    elif mode != "Known global centroids":
        if mode == "Sequence identifiers":
            identifiers = split_identifiers(
                value=st.text_area(
                    "Exact sequence IDs or UniProt accessions",
                    help=FIELD_HELP["mapping_ids"],
                    placeholder="One protein identifier per line, for example P12345",
                )
            )
            context = []
        else:
            st.info(
                "Start with one E3 group. Preparation collects its protein IDs and linked "
                "seeds; mapping then finds global membership. No representative or medoid "
                "is calculated by exact ID mapping."
            )
            kind = st.selectbox(
                "E3 selection",
                ["Ranked HOGs", "Ranked discovery clusters"],
                help="Ranked HOGs uses the pre-structural ranking; Ranked discovery clusters "
                "uses the computational cluster ranking. Use an exact local ID to override "
                "top-N. These project groups are distinct from global DeepClust clusters.",
            )
            maximum = st.number_input(
                "Top ranked E3 groups/clusters",
                min_value=1,
                max_value=1000,
                value=1,
                help=FIELD_HELP["project_top"],
            )
            groups = tuple(
                split_identifiers(
                    value=st.text_area(
                        "Specific local HOG/cluster IDs (optional; overrides top-N)",
                        help=FIELD_HELP["project_groups"],
                        placeholder="Paste a full local ID from the E3 table, e.g. 0.HOG0006943",
                    )
                )
            )
            if st.button("Prepare E3 mapping inputs", help=FIELD_HELP["project_top"]):
                from .e3_adapter import select_e3_cluster_inputs, select_e3_inputs

                st.session_state["research_e3_inputs"] = (
                    select_e3_inputs(
                        connection=connection, maximum_groups=maximum, group_ids=groups
                    )
                    if kind == "Ranked HOGs"
                    else select_e3_cluster_inputs(
                        connection=connection, maximum_clusters=maximum, cluster_ids=groups
                    )
                )
                st.session_state["research_e3_selection"] = (kind, maximum, groups)
            if st.session_state.get("research_e3_selection") != (kind, maximum, groups):
                st.info("Prepare the selected E3 inputs before queueing their global mapping.")
                identifiers, context = [], []
            else:
                frame = st.session_state.get("research_e3_inputs")
                if frame is None:
                    identifiers, context = [], []
                else:
                    st.dataframe(frame, hide_index=True)
                    identifiers = frame["input_id"].drop_duplicates().tolist()
                    context = frame.to_dict(orient="records")
        st.caption(
            (
                "Input group IDs and global DeepClust centroid IDs are distinct. Exact "
                "matches, declared aliases, multiple matches and unmatched inputs are "
                "retained."
            )
        )
        mapping_ready = bool(
            config.index
            and config.sequence_map
            and Path(config.index).expanduser().is_file()
            and Path(config.sequence_map).expanduser().is_file()
        )
        if not mapping_ready:
            st.info(
                "Exact mapping needs the configured DeepClust index and sequence-to-cluster "
                "map. Ask the operator to check these files and the database mount."
            )
        st.caption(
            f"{len(identifiers):,} input protein IDs. Mapping returns identifiers and "
            "membership; retrieve the mapped clusters in the next step to obtain sequences."
        )
        if st.button(
            "Queue exact global cluster mapping",
            disabled=not identifiers or not mapping_ready,
            help=FIELD_HELP["mapping_ids"],
        ):
            queue_action(
                config=config,
                operation="resolve",
                parameters={"identifiers": identifiers, "context": context},
            )
    mappings = (
        completed_manifests(config=config, operation="resolve")
        if mode != "Known global centroids"
        else {}
    )
    if mappings:
        st.markdown("#### Review a completed mapping")
        labels = {key: job_label(job_id=key, record=value) for key, value in mappings.items()}
        mapping_job = st.selectbox(
            "Completed sequence mapping",
            options=list(mappings),
            format_func=labels.__getitem__,
            help="Select a COMPLETE exact-mapping job. Check matched, unmatched and multiple "
            "global-cluster outcomes before choosing a family to collect.",
            key="research_mapping_job",
        )
        frame = read_table(
            path=artifact_path(
                workspace=config.workspace,
                job_id=mapping_job,
                artifact="global_cluster_mapping.tsv",
            )
        )
        st.dataframe(frame, hide_index=True)
        st.download_button(
            "Download mapping TSV",
            data=frame.to_csv(sep="\t", index=False),
            file_name="global_cluster_mapping.tsv",
        )
        st.caption(
            (
                "Mapping preview: at most 10,000 rows. The Jobs page provides the "
                "complete mapping artifact."
            )
        )
        choices = retrievable_cluster_ids(frame=frame)
        if choices:
            chosen = st.multiselect(
                "Mapped indexed clusters to collect",
                options=choices,
                default=choices[:1],
                key=f"mapped_clusters_{mapping_job}",
                help=FIELD_HELP["centroid"],
            )
            if st.button("Use selected mapped clusters for retrieval", disabled=not chosen):
                st.session_state["research_retrieve_ids"] = "\n".join(chosen)
        else:
            st.info(
                "This mapping preview has no retrievable indexed cluster. Check unmatched "
                "and MAPPED_WITHOUT_ROW_GROUP_INDEX rows in the complete mapping TSV."
            )
    st.markdown("#### Retrieve complete clusters")
    st.write(
        "Paste global centroid IDs, or use a selection from the ranking/mapping above. "
        "This creates a new retrieval job and saves the selected families on the worker."
    )
    ids = split_identifiers(
        value=st.text_area(
            "Global cluster IDs to retrieve in full",
            key="research_retrieve_ids",
            help=FIELD_HELP["centroid"],
            placeholder="One exact global centroid per line",
        )
    )
    if ids:
        st.download_button(
            "Download centroid list for official extraction tool",
            data=centroid_list(identifiers=ids),
            file_name="centroids.id.txt",
            mime="text/plain",
        )
        st.caption(
            "One exact centroid ID per line, for --centroid_file. Prefixes and accession "
            "versions are preserved; the extraction machine needs the DeepClust database."
        )
    retrieval_ready = bool(
        config.index
        and config.sequences
        and Path(config.index).expanduser().is_file()
        and Path(config.sequences).expanduser().is_file()
    )
    if not retrieval_ready:
        st.info(
            "Complete retrieval requires the configured DeepClust index and sequence data. "
            "An exported per-cluster FASTA can instead be imported using the route above."
        )
    if st.button(
        "Queue complete cluster retrieval",
        disabled=not ids or not retrieval_ready,
        help="Read indexed row groups, collect complete selected clusters, and reconcile "
        "retrieved counts with the published membership before publishing FASTA files.",
    ):
        queue_action(config=config, operation="retrieve", parameters={"cluster_ids": ids})
    with st.expander("Species metadata and source setup"):
        st.write(
            (
                "Use the published local/mounted DeepClust Parquet files. Species "
                "selection requires reviewed sequence_id/species/taxon_id metadata; names"
                " are never guessed from accessions. The official row-group index covers "
                "clusters with at least three members."
            )
        )
        st.caption(
            "This is an operator setup task, not a routine analysis step. After a "
            "successful job, the operator must configure cluster_taxonomy to its output."
        )
        if st.button(
            "Queue reviewed cluster/species index",
            disabled=not config.taxonomy or not config.sequence_map,
            help="Build a potentially large derived index by joining reviewed sequence taxonomy "
            "to global cluster membership. It is not required for identifier mapping or retrieval.",
        ):
            queue_action(config=config, operation="taxonomy_index", parameters={})


def render_analysis(*, config: ResearchConfig) -> None:
    """Render exact subclustering, bounded alignment and representative-search requests.

    Args:
        config: Tool and workspace profile.
    """
    render_page_guidance(section="Family analysis")
    task = st.radio(
        "Family analysis",
        ["Stricter subclusters", "Alignment and tree", "Representative homology search"],
        horizontal=True,
        key="research_analysis_task",
        help="Choose Stricter subclusters for a broad family, Alignment and tree to compare "
        "a selected family, or Representative homology search for similarity evidence "
        "against installed global centroids. Each is a separate queued job.",
    )
    source, fasta = render_input(config=config, key="analyse")
    parameters = dict(source)
    subcluster_choice = ""
    if task == "Alignment and tree" and source:
        manifest = completed_manifests(config=config).get(source["source_job"], {})
        if manifest.get("operation") == "subcluster":
            table = read_table(
                path=artifact_path(
                    workspace=config.workspace,
                    job_id=source["source_job"],
                    artifact="subclusters.tsv",
                )
            )
            labels = {"": "Whole selected family"}
            labels.update(
                {
                    row["subcluster_id"]: f"{row['subcluster_id']} · {row['member_count']} proteins"
                    for row in table.to_dict(orient="records")
                }
            )
            subcluster_choice = st.selectbox(
                "Subcluster to align",
                options=list(labels),
                format_func=labels.__getitem__,
                help=FIELD_HELP["subcluster"],
                key=f"align_subcluster_{source['source_job']}",
            )
            st.caption(
                "Shows up to 10,000 audited subclusters. Full membership and summaries "
                "are available in Jobs."
            )
        else:
            st.caption(
                "This source is a whole family. To choose an audited subcluster, select "
                "the FASTA from a completed subclustering job."
            )
    st.markdown("#### Review settings and queue the analysis")
    with st.form("research_analysis"):
        if task == "Stricter subclusters":
            operation = "subcluster"
            parameters["identity"] = st.number_input(
                "Minimum exact centroid identity (%)",
                min_value=1.0,
                max_value=100.0,
                value=70.0,
                help=FIELD_HELP["identity"],
            )
            parameters["mutual_coverage"] = st.number_input(
                "Minimum coverage in each direction (%)",
                min_value=1.0,
                max_value=100.0,
                value=80.0,
                help=FIELD_HELP["coverage"],
            )
            parameters["evalue"] = st.number_input(
                "Maximum exact E-value",
                min_value=1e-100,
                max_value=1.0,
                value=1e-10,
                format="%.2e",
                help=FIELD_HELP["evalue"],
            )
            st.caption(
                (
                    "DIAMOND DeepClust assignments are audited by exact realignment. Failing "
                    "members become singletons. Thresholds apply to assigned centroids; they "
                    "do not guarantee all-pairs similarity."
                )
            )
        elif task == "Alignment and tree":
            operation = "align"
            parameters["subcluster_id"] = subcluster_choice
            parameters["reference_id"] = st.text_input(
                "Reference/query sequence ID (blank selects first sorted ID)",
                help=FIELD_HELP["reference"],
            )
            parameters["allow_sampling"] = st.checkbox(
                "Use an explicit deterministic sample including the reference",
                help=FIELD_HELP["sampling"],
            )
            size = st.number_input(
                "Sample size, when sampling is selected",
                min_value=1,
                max_value=config.max_alignment_sequences,
                value=min(200, config.max_alignment_sequences),
                help=FIELD_HELP["sample_size"],
            )
            if parameters["allow_sampling"]:
                parameters["sample_size"] = size
            parameters["infer_tree"] = st.checkbox(
                "Infer a FastTree WAG+gamma protein phylogeny", value=True, help=FIELD_HELP["tree"]
            )
            st.caption(
                "Complete selected family unless sampling is selected. Limits: "
                f"{config.max_alignment_sequences:,} sequences and "
                f"{config.max_alignment_cells:,} matrix cells. "
                "Tree branches show divergence, not time."
            )
        else:
            operation = "search"
            st.info(
                "Search all proteins in this input against the installed global-centroid "
                "DIAMOND database (maximum 10,000 query proteins). No medoid is chosen "
                "automatically. For a single-query search, upload a FASTA containing "
                "only your chosen representative. Hits are homology evidence, not proof "
                "of exact cluster membership. Complete hit tables are available in Jobs."
            )
        queued = st.form_submit_button(
            {
                "Stricter subclusters": "Queue stricter subclustering",
                "Alignment and tree": "Queue alignment and tree",
                "Representative homology search": "Queue representative search",
            }[task],
            disabled=not source and not fasta,
            help="Save this input and these settings as a job. The worker runs it; "
            "follow progress and errors in Jobs.",
        )
    if queued:
        queue_action(config=config, operation=operation, parameters=parameters, fasta=fasta)
    completed = completed_manifests(config=config, operation="subcluster")
    if completed:
        st.markdown("#### Completed subclustering results")
        labels = {key: job_label(job_id=key, record=value) for key, value in completed.items()}
        selected = st.selectbox(
            "Completed subcluster job",
            options=list(completed),
            format_func=labels.__getitem__,
            help="Review this result, then use the button below to carry its source "
            "FASTA into the alignment task. Subcluster IDs are specific to this job.",
        )
        frame = read_table(
            path=artifact_path(
                workspace=config.workspace, job_id=selected, artifact="subclusters.tsv"
            )
        )
        st.dataframe(frame, hide_index=True)
        if not frame.empty:
            plot = frame.head(50).copy()
            plot["member_count"] = pd.to_numeric(plot["member_count"])
            st.plotly_chart(
                px.bar(plot, x="subcluster_id", y="member_count", log_y=True),
                key="subcluster_sizes",
            )
        if "sequences.fasta" in completed[selected]["artifacts"]:
            render_next_action(
                label="Align a family or subcluster from this job",
                key="subclusters_to_alignment",
                section="Family analysis",
                analysis_task="Alignment and tree",
                source_job=selected,
                source_artifact="sequences.fasta",
            )


def render_alignments(*, config: ResearchConfig) -> None:
    """Render real JBrowse/AV2 libraries and a configured self-hosted Auspice dataset.

    Args:
        config: Alignment workspace and Auspice URL.
    """
    render_page_guidance(section="Alignments and trees")
    completed = completed_manifests(config=config, operation="align")
    if not completed:
        st.info(
            (
                "Queue an alignment and tree under Family analysis, then open its "
                "completed result here."
            )
        )
        render_next_action(
            label="Set up an alignment",
            key="empty_alignment",
            section="Family analysis",
            analysis_task="Alignment and tree",
        )
        return
    labels = {key: job_label(job_id=key, record=value) for key, value in completed.items()}
    job_id = st.selectbox(
        "Completed alignment",
        options=list(completed),
        format_func=labels.__getitem__,
        help="Choose a COMPLETE alignment job. Its reference, sampling and tree settings "
        "were fixed when the job was queued; this page does not rerun the analysis.",
        key="research_alignment_job",
    )
    summary = json.loads(
        artifact_path(
            workspace=config.workspace, job_id=job_id, artifact="alignment_summary.json"
        ).read_text()
    )
    left, middle, right = st.columns(3)
    left.metric("Aligned proteins", f"{int(summary['aligned_sequence_count']):,}")
    middle.metric("Aligned positions", f"{int(summary['alignment_length']):,}")
    right.metric(
        "Mean gap fraction",
        f"{float(summary['mean_gap_fraction']):.1%}",
        help="Fraction of alignment cells containing a gap. High gaps can reflect "
        "partial sequences, insertions, deletions or a poorly matched family.",
    )
    st.caption(f"Reference protein: {summary['reference_id']}")
    st.caption(
        "Per-sequence statistics compare each protein with this reference. "
        "They are not an all-pairs comparison. BLOSUM62 is a raw score over comparable "
        "positions; it is neither an E-value nor a length-normalised score."
    )
    with st.expander("Technical alignment summary (JSON)"):
        st.json(summary)
    view = st.radio(
        "Alignment viewer",
        ["JBrowse MSA", "Alignment Viewer 2", "Auspice tree", "Statistics"],
        horizontal=True,
        help="JBrowse MSA combines the alignment and tree. Alignment Viewer 2 supports "
        "sorting by similarity to the reference. Statistics gives tables and conservation "
        "plots. Auspice requires a separately configured viewer service.",
    )
    st.caption(
        {
            "JBrowse MSA": "Use the viewer's File/View/Tools menus, sequence search and zoom "
            "controls. When a tree was inferred, it appears in the left panel; "
            "coloured columns are aligned residues.",
            "Alignment Viewer 2": "The reference appears first. Use the viewer controls to "
            "sort sequences by their BLOSUM score to that query and inspect conserved regions.",
            "Auspice tree": "Explore an inferred tree by divergence. Species colours require "
            "reviewed metadata. This view is not a time-calibrated evolutionary history.",
            "Statistics": "Gap fraction measures missing alignment cells. Consensus fraction "
            "uses known residues; lower Shannon entropy indicates stronger conservation. "
            "Member identity is measured against the chosen reference over canonical residues.",
        }[view]
    )
    if view == "Statistics":
        columns = read_table(
            path=artifact_path(
                workspace=config.workspace, job_id=job_id, artifact="alignment_columns.tsv"
            )
        )
        st.dataframe(columns, hide_index=True)
        columns["gap_fraction"] = pd.to_numeric(columns["gap_fraction"])
        columns["alignment_column"] = pd.to_numeric(columns["alignment_column"])
        st.plotly_chart(
            px.line(columns, x="alignment_column", y="gap_fraction"), key="alignment_gaps"
        )
        st.dataframe(
            read_table(
                path=artifact_path(
                    workspace=config.workspace, job_id=job_id, artifact="alignment_members.tsv"
                )
            ),
            hide_index=True,
        )
        return
    artifacts = completed[job_id]["artifacts"]
    if view == "Auspice tree":
        if "auspice.json" not in artifacts:
            st.info(
                (
                    "This job has no inferred tree; request tree inference with at least "
                    "three sequences."
                )
            )
        elif config.auspice_url:
            components.iframe(
                auspice_dataset_url(base_url=config.auspice_url, job_id=job_id),
                height=760,
                scrolling=True,
            )
        else:
            st.info(
                (
                    "Configure auspice_url for your self-hosted Auspice service. Download "
                    "auspice.json from Jobs for portable use. Setup commands are in "
                    "PROTEIN_RESEARCH.md."
                )
            )
        return
    path = artifact_path(workspace=config.workspace, job_id=job_id, artifact="alignment.fasta")
    records = dict(iter_fasta(path=path, aligned=True))
    reference = summary["reference_id"]
    msa = "".join(
        f">{identifier}\n{records[identifier]}\n"
        for identifier in [reference, *[item for item in records if item != reference]]
    )
    tree = (
        artifact_path(workspace=config.workspace, job_id=job_id, artifact="tree.nwk").read_text()
        if "tree.nwk" in artifacts
        else ""
    )
    document = viewer_document(
        viewer="jbrowse" if view == "JBrowse MSA" else "alignment",
        payload={"msa": msa, "tree": tree},
    )
    components.html(document, height=740, scrolling=True)
    st.download_button(
        "Download standalone alignment viewer",
        data=document,
        file_name=f"{job_id}_{'jbrowse' if view == 'JBrowse MSA' else 'av2'}.html",
        mime="text/html",
    )


def render_models(*, config: ResearchConfig) -> None:
    """Queue optional ESMFold jobs and interrogate exact-sequence model evidence.

    Args:
        config: Trusted model providers and workspace.
    """
    render_page_guidance(section="Models")
    source, fasta = render_input(config=config, key="fold")
    engines = {
        "atlas": "ESM Atlas · external service (up to 400 amino acids)",
        "huggingface_endpoint": "Dedicated Hugging Face / ESMFold endpoint · external",
        "local": "Local ESMFold · on the analysis worker",
    }
    engine = st.selectbox(
        "ESMFold route",
        options=list(engines),
        format_func=engines.__getitem__,
        help=FIELD_HELP["fold_engine"],
        key="fold_engine",
    )
    issue = provider_problem(config=config, operation="predict", engine=engine)
    if issue:
        st.warning(issue)
    remote = False
    if engine != "local":
        remote = st.checkbox(
            "Submit these sequences to the selected external provider",
            help=FIELD_HELP["consent"],
            key=f"fold_consent_{engine}",
        )
        if not remote:
            st.caption("Select external submission to enable this remote prediction request.")
    with st.form("research_fold"):
        ids = split_identifiers(
            value=st.text_area(
                "Exact sequence IDs to fold (blank selects input; maximum 100)",
                help=FIELD_HELP["sequence_ids"],
                placeholder="Start with one exact protein ID",
            )
        )
        st.caption(
            (
                "Atlas route: at most 400 residues. The dedicated endpoint and local "
                "limits are operator configured. Hugging Face requires a deployed "
                "endpoint; the model page is not a public inference service. Existing "
                "successful models are reused by sequence and provider."
            )
        )
        queued = st.form_submit_button(
            "Queue ESMFold prediction",
            disabled=bool(issue)
            or (not source and not fasta)
            or (engine != "local" and not remote),
            help="Predict models for the selected proteins. External requests require the "
            "submission selection above. Follow per-protein successes and failures in Jobs.",
        )
    if queued:
        queue_action(
            config=config,
            operation="predict",
            parameters={**source, "sequence_ids": ids, "engine": engine, "remote_allowed": remote},
            fasta=fasta,
        )
    completed = completed_manifests(config=config, operation="predict")
    if not completed:
        return
    st.markdown("#### Inspect completed models")
    labels = {key: job_label(job_id=key, record=value) for key, value in completed.items()}
    selected = st.selectbox(
        "Completed model job",
        options=list(completed),
        format_func=labels.__getitem__,
        help="A completed batch may include individual failures; inspect the per-protein "
        "status table before selecting a successful or reused model.",
        key="research_model_job",
    )
    predictions = read_table(
        path=artifact_path(workspace=config.workspace, job_id=selected, artifact="predictions.tsv")
    )
    st.dataframe(predictions, hide_index=True)
    available = predictions[predictions["status"].isin(["PREDICTED", "REUSED"])]
    if available.empty:
        return
    identifier = st.selectbox(
        "Model to interrogate",
        options=available["sequence_id"].tolist(),
        help="Only proteins with a successfully produced or reused PDB appear here. "
        "The view uses a C-alpha trace coloured by the reported residue confidence.",
    )
    row = available[available["sequence_id"] == identifier].iloc[0]
    model = artifact_path(workspace=config.workspace, job_id=selected, artifact=row["pdb_artifact"])
    st.download_button("Download predicted PDB", data=model.read_bytes(), file_name=model.name)
    residues = read_table(
        path=artifact_path(
            workspace=config.workspace, job_id=selected, artifact=row["residue_artifact"]
        )
    ).copy()
    for column in ("x", "y", "z", "residue_index", "confidence_b_factor"):
        residues[column] = pd.to_numeric(residues[column])
    figure = go.Figure(
        go.Scatter3d(
            x=residues.x,
            y=residues.y,
            z=residues.z,
            mode="lines+markers",
            marker={
                "size": 3,
                "color": residues.confidence_b_factor,
                "cmin": 0,
                "cmax": 100,
                "colorscale": "Viridis",
                "colorbar": {"title": "Confidence"},
            },
            text=residues.residue + residues.residue_index.astype(str),
            hovertemplate="%{text}<extra></extra>",
        )
    )
    figure.update_layout(scene={"aspectmode": "data"}, title="Predicted model · C-alpha trace")
    st.plotly_chart(figure, key="predicted_model_trace")
    st.plotly_chart(
        px.line(residues, x="residue_index", y="confidence_b_factor", range_y=[0, 100]),
        key="model_confidence",
    )
    sequence = "".join(residues["residue"])
    if hashlib.sha256(sequence.encode()).hexdigest() != row["sequence_sha256"]:
        raise ResearchError("Model residue evidence differs from its input sequence")
    annotations = completed_manifests(config=config, operation="annotate")
    labels = {
        "": "No annotation overlay",
        **{key: job_label(job_id=key, record=value) for key, value in annotations.items()},
    }
    annotation_job = st.selectbox(
        "Optional annotation overlay",
        options=list(labels),
        format_func=labels.__getitem__,
        help="Choose an annotation job containing this exact protein sequence. A different "
        "isoform or modified sequence cannot be overlaid on this model.",
    )
    hits = []
    if annotation_job:
        table = artifact_path(
            workspace=config.workspace, job_id=annotation_job, artifact="annotations.tsv"
        )
        with table.open(encoding="utf-8") as handle:
            hits = [
                item
                for item in csv.DictReader(handle, delimiter="\t")
                if item["sequence_id"] == identifier
            ]
    features = nightingale_features(sequence_id=identifier, sequence=sequence, annotations=hits)
    components.html(
        viewer_document(viewer="nightingale", payload={"sequence": sequence, "features": features}),
        height=300,
        scrolling=True,
    )
    st.caption(
        (
            "Reported ESMFold confidence is model evidence. This C-alpha view and "
            "predicted domains do not establish ligandability or experimental "
            "function."
        )
    )


def render_annotations(*, config: ResearchConfig) -> None:
    """Queue eukaryote-aware annotation and display positional Nightingale evidence.

    Args:
        config: Annotation tools, databases and optional EBI contact.
    """
    render_page_guidance(section="Annotations")
    source, fasta = render_input(config=config, key="annotate")
    engines = {
        "interpro_local": "InterProScan · installed locally",
        "interpro_remote": "InterProScan · EMBL-EBI external service",
        "eggnog": "eggNOG-mapper · installed locally",
    }
    engine = st.selectbox(
        "Annotation route",
        options=list(engines),
        format_func=engines.__getitem__,
        help=FIELD_HELP["annotation_engine"],
        key="annotation_engine",
    )
    issue = provider_problem(config=config, operation="annotate", engine=engine)
    if issue:
        st.warning(issue)
    remote = False
    if engine == "interpro_remote":
        remote = st.checkbox(
            "Submit selected sequences to EMBL-EBI InterProScan",
            help=FIELD_HELP["consent"],
            key="annotation_remote_consent",
        )
        if not remote:
            st.caption("Select external submission to enable this remote annotation request.")
    with st.form("research_annotation"):
        ids = split_identifiers(
            value=st.text_area(
                "Exact sequence IDs to annotate (blank selects input)",
                help=FIELD_HELP["sequence_ids"],
            )
        )
        scope, target = "Eukaryota", "2759"
        if engine == "eggnog":
            scope = st.text_input(
                "eggNOG taxonomic scope", value="Eukaryota", help=FIELD_HELP["scope"]
            )
            target = st.text_input(
                "eggNOG target taxon ID", value="2759", help=FIELD_HELP["target_taxon"]
            )
        st.caption(
            (
                "InterProScan predicts signatures/domains. eggNOG transfers "
                "orthology-based annotation within the selected taxonomic scope. No-hit "
                "records remain explicit. These are computational predictions."
            )
        )
        queued = st.form_submit_button(
            "Queue annotation",
            disabled=bool(issue)
            or (not source and not fasta)
            or (engine == "interpro_remote" and not remote),
            help="Run the chosen method for the selected proteins. Inspect no-hit records "
            "as well as predicted annotations after the worker completes the job.",
        )
    if queued:
        queue_action(
            config=config,
            operation="annotate",
            parameters={
                **source,
                "sequence_ids": ids,
                "engine": engine,
                "tax_scope": scope,
                "target_taxon": target,
                "remote_allowed": remote,
            },
            fasta=fasta,
        )
    completed = completed_manifests(config=config, operation="annotate")
    if not completed:
        return
    st.markdown("#### Inspect completed annotation evidence")
    labels = {key: job_label(job_id=key, record=value) for key, value in completed.items()}
    selected = st.selectbox(
        "Completed annotation job",
        options=list(completed),
        format_func=labels.__getitem__,
        help="The audit retains every submitted protein, including those without a hit. "
        "Positional domain/signature predictions are shown below when available.",
        key="research_annotation_job",
    )
    st.dataframe(
        read_table(
            path=artifact_path(
                workspace=config.workspace, job_id=selected, artifact="annotation_audit.tsv"
            )
        ),
        hide_index=True,
    )
    hits = read_table(
        path=artifact_path(workspace=config.workspace, job_id=selected, artifact="annotations.tsv")
    )
    st.dataframe(hits, hide_index=True)
    if hits.empty:
        st.info(
            "No annotation hits were returned for this job. Check the per-protein audit "
            "and method/database coverage; this does not establish absence of function."
        )
    if "start" in hits and not hits.empty:
        identifier = st.selectbox(
            "Protein features",
            options=hits["sequence_id"].drop_duplicates().tolist(),
            help="Select a protein with positional annotations. Nightingale displays "
            "residue coordinates for the exact sequence submitted to this job.",
        )
        from .runner import prepare_input

        directory = job_directory(workspace=config.workspace, job_id=selected)
        request = json.loads((directory / "request.json").read_text())
        input_path = prepare_input(config=config, job=request, output=directory)
        sequence = next(
            (value for key, value in iter_fasta(path=input_path) if key == identifier), ""
        )
        features = nightingale_features(
            sequence_id=identifier, sequence=sequence, annotations=hits.to_dict(orient="records")
        )
        components.html(
            viewer_document(
                viewer="nightingale", payload={"sequence": sequence, "features": features}
            ),
            height=300,
            scrolling=True,
        )


def render_jobs(*, config: ResearchConfig) -> None:
    """Display durable status, diagnostics and verified downloadable scientific artifacts.

    Args:
        config: Writable research workspace.
    """
    render_page_guidance(section="Jobs")
    if st.button(
        "Refresh job status", help="Reload saved status. This does not start or resubmit work."
    ):
        st.rerun()
    jobs = list_jobs(workspace=config.workspace)
    counts = pd.Series([job["status"] for job in jobs], dtype=str).value_counts()
    for column, status in zip(
        st.columns(4), ("QUEUED", "RUNNING", "COMPLETE", "FAILED"), strict=True
    ):
        column.metric(status.title(), int(counts.get(status, 0)))
    if not jobs:
        st.info(
            "No jobs yet. Start in Discover to find a family, or upload a protein FASTA "
            "in Family analysis. The browser saves a request; the analysis worker executes it."
        )
        render_next_action(label="Choose a starting point", key="empty_jobs", section="Start here")
        return
    frame = pd.DataFrame(jobs)
    frame.insert(0, "Task", frame["operation"].map(OPERATION_NAMES).fillna("Research job"))
    st.dataframe(frame.drop(columns=["operation"]), hide_index=True)
    st.caption(
        "Showing the 200 most recent jobs. Times in the saved records are UTC. "
        "Refresh to see updates; changing pages does not submit work."
    )
    labels = {job["job_id"]: job_label(job_id=job["job_id"], record=job) for job in jobs}
    if st.session_state.get("research_job") not in labels:
        st.session_state.pop("research_job", None)
    selected = st.selectbox(
        "Job details",
        options=list(labels),
        format_func=labels.__getitem__,
        key="research_job",
        help="Select by task and timestamp. The short job ID distinguishes repeated analyses; "
        "the full ID is retained in the table and technical record.",
    )
    job = next(item for item in jobs if item["job_id"] == selected)
    directory = job_directory(workspace=config.workspace, job_id=selected)
    st.markdown(f"#### {OPERATION_NAMES.get(job['operation'], 'Research job')} · {job['status']}")
    st.caption(f"Job {selected}")
    status_help = {
        "QUEUED": "Waiting for a worker. It may be busy with another job. If this persists, "
        "ask the operator to check that a worker is running with this same profile/workspace.",
        "RUNNING": "A worker has claimed this job. Low CPU use can mean it is waiting for "
        "a mounted file or external service; refresh status and inspect the worker log if needed.",
        "COMPLETE": "Results were published. Review the summaries, open the next step, "
        "or prepare a complete verified download below.",
        "FAILED": "This job did not complete. Read the error and expand technical details "
        "for its request and logs. Correct the cause before submitting another job.",
        "CANCELLED": "This request was cancelled before a worker claimed it.",
    }
    st.info(status_help.get(job["status"], "Inspect the saved job record for this status."))
    if job["error"]:
        st.error(str(job["error"]))
    if job["status"] == "QUEUED" and st.button(
        "Cancel queued job", help="Cancel only this waiting request. Running work is unaffected."
    ):
        cancel_job(workspace=config.workspace, job_id=selected)
        st.rerun()
    manifest = None
    if job["status"] == "COMPLETE":
        manifest = completed_manifests(config=config)[selected]
        family_labels = {}
        for name in ("clusters.tsv", "cluster_summary.tsv"):
            if name in manifest["artifacts"]:
                result = read_table(
                    path=artifact_path(workspace=config.workspace, job_id=selected, artifact=name)
                )
                st.dataframe(result, hide_index=True)
                if {"fasta_artifact", "cluster_id"}.issubset(result.columns):
                    family_labels.update(
                        dict(zip(result["fasta_artifact"], result["cluster_id"], strict=True))
                    )
        operation = job["operation"]
        if operation in {"retrieve", "import_cluster", "subcluster"}:
            fastas = [
                name
                for name in manifest["artifacts"]
                if name.endswith((".fasta", ".faa", ".fa")) and name != "alignment.fasta"
            ]
            if fastas:
                names = {name: family_labels.get(name, name) for name in fastas}
                fasta_name = st.selectbox(
                    "Family FASTA for the next analysis",
                    options=fastas,
                    format_func=names.__getitem__,
                    help=FIELD_HELP["source"],
                    key=f"job_next_fasta_{selected}",
                )
                render_next_action(
                    label="Analyse this family",
                    key="job_to_analysis",
                    section="Family analysis",
                    analysis_task=(
                        "Alignment and tree"
                        if operation == "subcluster"
                        else "Stricter subclusters"
                    ),
                    source_job=selected,
                    source_artifact=fasta_name,
                )
        elif operation in {"align", "predict", "annotate"}:
            destination = {
                "align": "Alignments and trees",
                "predict": "Models",
                "annotate": "Annotations",
            }[operation]
            render_next_action(
                label=f"Open result in {destination}",
                key="job_to_results",
                section=destination,
                job_id=selected,
            )
        elif operation == "resolve":
            render_next_action(
                label="Review mapping and collect clusters",
                key="job_to_mapping",
                section="Discover",
                discovery_mode="Sequence identifiers",
                job_id=selected,
            )
        st.markdown("#### Download complete result files")
        artifact = st.selectbox(
            "Scientific artifact", options=list(manifest["artifacts"]), help=FIELD_HELP["artifact"]
        )
        record = manifest["artifacts"][artifact]
        if record["bytes"] <= 25_000_000:
            if st.button("Prepare verified download"):
                path = artifact_path(workspace=config.workspace, job_id=selected, artifact=artifact)
                st.download_button(
                    "Download verified artifact", data=path.read_bytes(), file_name=path.name
                )
        else:
            st.info(
                f"Large artifact ({record['bytes']:,} bytes): copy it from the worker workspace. "
                "All bytes are covered by the manifest checksum."
            )
            st.code(str(directory / record["path"]))
    with st.expander("Technical details · parameters, provenance and logs"):
        if manifest is not None:
            st.json(manifest)
        for name in (
            "request.json",
            "worker.log",
            "predictions.tsv",
            "interpro_service_job.json",
            "commands.jsonl",
        ):
            path = directory / name
            if path.is_file() and path.stat().st_size <= 2_000_000:
                st.markdown(f"**{name}**")
                st.code(
                    path.read_text(encoding="utf-8"),
                    language="json" if name.endswith("json") else "text",
                )


def render_research_workbench(*, connection: object | None = None) -> None:
    """Render one selected generic research section, optionally with an E3 adapter.

    Args:
        connection: Optional open E3 resource for top-N or exact-HOG input selection.
    """
    st.header("Protein research workbench")
    st.write(
        (
            "Link protein families to global DeepClust clusters, refine families, "
            "inspect alignments and request optional model or annotation jobs."
        )
    )
    try:
        config = load_config()
        section = st.radio(
            "Workbench page",
            options=SECTIONS,
            horizontal=True,
            key="research_section",
            help=FIELD_HELP["navigation"],
        )
        renderers = {
            "Start here": lambda: render_start(config=config, connection=connection),
            "Discover": lambda: render_discovery(config=config, connection=connection),
            "Family analysis": lambda: render_analysis(config=config),
            "Alignments and trees": lambda: render_alignments(config=config),
            "Models": lambda: render_models(config=config),
            "Annotations": lambda: render_annotations(config=config),
            "Jobs": lambda: render_jobs(config=config),
            "Help & glossary": lambda: render_help(connection=connection),
        }
        renderers[section]()
    except (ResearchError, OSError, ValueError) as exc:
        LOGGER.warning("Protein workbench could not complete the selected action: %s", exc)
        st.error(f"Protein research: {exc}")
        st.info(
            "Check the input and the question-mark help beside its control. If this is a "
            "queued job failure, open Jobs for the saved request and worker diagnostics."
        )
