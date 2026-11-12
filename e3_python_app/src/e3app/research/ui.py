"""Lazy protein research UI shared by E3 and the standalone generic application."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
from pathlib import Path
import shlex
import shutil
import sys
from typing import Mapping

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from e3app.config import AppConfig
from e3app.errors import AppError
from e3app.navigation import CANDIDATE_STAGE, DEEPCLUST_STAGE

from .catalogue import browse_clusters, open_catalogue
from .common import ResearchConfig, ResearchError, iter_fasta, load_config
from .deepclust_exchange import centroid_list
from .guidance import (
    ALIGNMENT_MEMBER_METRICS,
    ALIGNMENT_POSITION_METRICS,
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
from .jobs import (
    artifact_path,
    cancel_job,
    get_job,
    job_directory,
    list_jobs,
    queued_external_provider_job,
    submit_job,
)
from .viewers import auspice_dataset_url, nightingale_features, protein_tree_figure, viewer_document

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
    prepared_fasta: tuple[str, str] | None = None,
    subcluster_id: str = "",
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
        prepared_fasta: Optional labelled unaligned sequences to reuse at the destination.
        subcluster_id: Optional exact audited subcluster to select for alignment.

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
    input_keys = {"Family analysis": "analyse", "Annotations": "annotate", "Models": "fold"}
    if (source_job or input_route or prepared_fasta is not None) and section not in input_keys:
        raise ResearchError("This workbench page does not accept a protein FASTA")
    if prepared_fasta is not None and (source_job or input_route):
        raise ResearchError("Choose one protein input for the destination")
    if subcluster_id and not (
        section == "Family analysis" and analysis_task == "Alignment and tree" and source_job
    ):
        raise ResearchError("An audited subcluster requires its source job and alignment task")
    stage = st.session_state.get("e3_navigation_stage")
    page = st.session_state.get(f"e3_navigation_page_{stage}")
    if stage in {CANDIDATE_STAGE, DEEPCLUST_STAGE} and page in {
        "DeepClust results & FASTA", "JBrowse MSA", "ESMFold & models",
    }:
        st.session_state["e3_navigation_stage"] = DEEPCLUST_STAGE
        st.session_state[f"e3_navigation_page_{DEEPCLUST_STAGE}"] = "DeepClust workbench"
        st.session_state["research_surface"] = "DeepClust workbench"
    st.session_state["research_section"] = section
    if discovery_mode:
        st.session_state["research_discovery_mode"] = discovery_mode
    if analysis_task:
        st.session_state["research_analysis_task"] = analysis_task
    if source_job or input_route or prepared_fasta is not None:
        input_key = input_keys[section]
        route = input_route
        if source_job:
            route = "Completed job"
            st.session_state[f"{input_key}_source"] = (source_job, source_artifact)
            if section == "Family analysis" and analysis_task == "Alignment and tree":
                st.session_state[f"align_subcluster_{source_job}"] = subcluster_id
        elif prepared_fasta is not None:
            route = "Prepared FASTA"
            st.session_state["research_prepared_fasta"] = prepared_fasta
        st.session_state[f"{input_key}_route"] = route
        if section == "Models":
            st.session_state["esmfold_view_route"] = "Predict with ESMFold"
    if job_id:
        state_key = {
            "Alignments and trees": "research_alignment_job",
            "Models": "research_model_job",
            "Annotations": "research_annotation_job",
            "Discover": "research_mapping_job",
        }.get(section, "research_job")
        st.session_state[state_key] = job_id


def render_next_action(
    *, label: str, key: str, primary: bool = False, **destination: str | tuple[str, str],
) -> None:
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


def render_protein_analysis_links(
    *, key: str, source_job: str = "", source_artifact: str = "",
    prepared_fasta: tuple[str, str] | None = None,
) -> None:
    """Offer the same unaligned proteins as input to other workbench analyses.

    Args:
        key: Widget namespace for the current protein selection.
        source_job: Completed job publishing the unaligned proteins.
        source_artifact: The exact FASTA artifact in that job.
        prepared_fasta: Label and unaligned FASTA for a fresh selection.
    """
    source = (
        {"prepared_fasta": prepared_fasta} if prepared_fasta is not None
        else {"source_job": source_job, "source_artifact": source_artifact}
    )
    for column, (label, section, suffix, task) in zip(
        st.columns(3),
        (
            ("Subcluster proteins", "Family analysis", "subcluster", "Stricter subclusters"),
            ("Annotate proteins", "Annotations", "annotate", ""),
            ("Predict models", "Models", "model", ""),
        ),
        strict=True,
    ):
        with column:
            render_next_action(
                label=label, key=f"{key}_{suffix}", section=section, analysis_task=task, **source,
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


def render_start(
    *, config: ResearchConfig, connection: object | None, external_search: bool = False,
) -> None:
    """Offer project-aware entry points while retaining generic FASTA workflows.

    Args:
        config: Current workspace profile.
        connection: Optional source-project adapter connection.
        external_search: Use the external search exchange as the primary route.
    """
    st.subheader("Start with one protein family")
    if external_search:
        st.write("Prepare FASTA for Ken’s search or open its results. Use Family analysis to "
                 "align sequences, and the viewers to open results from any machine.")
        render_next_action(label="Prepare FASTA or import results", key="start_exchange",
                           section="Discover", primary=True)
        return
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
    for job in list_jobs(workspace=config.workspace, operation=operation or None):
        if job["status"] != "COMPLETE":
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


def render_input(
    *, config: ResearchConfig, key: str, published_fasta: tuple[str, str] | None = None,
    hog_connection: object | None = None,
) -> tuple[dict[str, object], str | None]:
    """Select an uploaded FASTA or a complete checksummed prior-job FASTA artifact.

    Args:
        config: Current workspace.
        key: Unique UI control namespace.
        published_fasta: Label and exact FASTA for an explicitly selected E3 protein.
        hog_connection: E3 resource for direct HOG member selection during alignment.

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
    prepared = st.session_state.get("research_prepared_fasta")
    routes = ["Completed job", "Upload FASTA", "Paste FASTA"]
    if prepared:
        routes.append("Prepared FASTA")
    if published_fasta:
        routes.append("Selected E3 protein")
    if hog_connection is not None:
        routes.insert(0, "Published HOG members")
    if st.session_state.get(f"{key}_route") not in routes:
        st.session_state.pop(f"{key}_route", None)
    route = st.radio(
        "Protein input",
        routes,
        horizontal=True,
        key=f"{key}_route",
        help=FIELD_HELP["protein_input"],
        index=routes.index("Completed job" if options else "Upload FASTA"),
    )
    if route == "Published HOG members" and hog_connection is not None:
        from .expansion_ui import render_hog_alignment_input

        return {}, render_hog_alignment_input(config=config, connection=hog_connection, key=key)
    if route == "Prepared FASTA":
        st.caption(f"Prepared protein source: {prepared[0]}")
        return {}, prepared[1]
    if route == "Selected E3 protein" and published_fasta is not None:
        label, fasta = published_fasta
        st.caption(f"Exact released sequence for {label} · {len(fasta.splitlines()[1]):,} residues")
        st.download_button(
            label="Download selected protein FASTA", data=fasta,
            file_name=f"{label.split(' · ', 1)[0]}.fasta", mime="text/plain",
        )
        return {}, fasta
    if route == "Paste FASTA":
        pasted = st.text_area(
            "Protein FASTA text", key=f"{key}_pasted_fasta",
            help="Paste >protein_id followed by its amino-acid sequence. Each ID must be unique.",
        )
        return {}, pasted if pasted.strip() else None
    if route == "Upload FASTA":
        from .expansion_ui import upload_text

        fasta = upload_text(
            label="Protein FASTA",
            types=["fa", "faa", "fasta"],
            key=f"{key}_upload",
            help_text=FIELD_HELP["upload"],
        )
        with st.expander("What should the FASTA look like?"):
            st.code(">protein_A\nMAAKLVVAGL\n>protein_B\nMAAKLVIAGL\n", language="text")
            st.write(FIELD_HELP["upload"])
        return {}, fasta or None
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
    if manifest.get("operation") in {"retrieve", "deepclust_retrieve"} \
            and "clusters.tsv" in manifest["artifacts"]:
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
    interproscan_email: str | None = None,
    run_on_app_host: bool = False,
    external_vm: bool = False,
) -> None:
    """Save a request, start its worker if selected and show its job ID.

    Args:
        config: Workspace profile.
        operation: Validated analysis type.
        parameters: Scientific controls from the visible form.
        fasta: Optional uploaded protein FASTA.
        interproscan_email: Optional contact for the remote annotation job.
        run_on_app_host: Start a one-shot worker from this app.
        external_vm: Use SSH to run the selected subclustering request on the configured VM.
    """
    if run_on_app_host:
        from .local_worker import submit_local_provider_job, submit_local_subcluster

        if operation == "subcluster":
            job_id = submit_local_subcluster(
                config=config, parameters=parameters, fasta=fasta, external_vm=external_vm,
            )
        else:
            job_id = submit_local_provider_job(
                config=config, operation=operation, parameters=parameters, fasta=fasta,
                interproscan_email=interproscan_email,
            )
        st.success(f"Started a background worker for job {job_id}.")
        st.info("Open Jobs and refresh its status to follow the request.")
    else:
        job_id = submit_job(
            workspace=config.workspace, operation=operation, parameters=parameters, fasta=fasta,
            interproscan_email=interproscan_email,
        )
        LOGGER.info("Workbench queued %s job %s", operation, job_id)
        st.success(f"Queued {OPERATION_NAMES.get(operation, operation)} · job {job_id}.")
        st.info("A research worker using this workspace can claim the request. "
                "Jobs shows the command for starting this exact job from a terminal.")
    render_next_action(
        label="Track this job",
        key=f"track_{job_id}",
        section="Jobs",
        job_id=job_id,
    )


def render_portable_job(
    *, operation: str, parameters: Mapping[str, object], fasta: str | None, prepare: bool,
) -> None:
    """Offer a self-contained request to execute on another machine.

    Args:
        operation: Supported FASTA-based job type.
        parameters: Current form settings.
        fasta: Uploaded, pasted or prepared protein FASTA.
        prepare: Whether the user requested fresh job files.
    """
    from .viewer_inputs import portable_job_archive

    key = f"portable_research_{operation}"
    saved = st.session_state.get(key)
    if not fasta or (not prepare and not saved):
        return
    identity = (hashlib.sha256(fasta.encode()).hexdigest(),
                json.dumps(dict(parameters), sort_keys=True))
    if prepare:
        st.session_state.pop(key, None)
        saved = (identity, portable_job_archive(operation=operation, parameters=parameters,
                                                fasta=fasta))
        st.session_state[key] = saved
    if saved and saved[0] == identity:
        st.download_button("Download job files (ZIP)", data=saved[1],
                           file_name=f"protein_{operation}_job.zip", key=key + "_download",
                           mime="application/zip")


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


def render_analysis(
    *, config: ResearchConfig, enable_search: bool = True, connection: object | None = None,
) -> None:
    """Render exact subclustering, bounded alignment and representative-search requests.

    Args:
        config: Tool and workspace profile.
        enable_search: Expose the optional built-in representative search.
        connection: Optional E3 resource for direct HOG alignment.
    """
    render_page_guidance(section="Family analysis")
    task = st.radio(
        "Family analysis",
        ["Stricter subclusters", "Alignment and tree"] + (
            ["Representative homology search"] if enable_search else []
        ),
        horizontal=True,
        key="research_analysis_task",
        help="Choose Stricter subclusters for a broad family, Alignment and tree to compare "
        "a selected family, or Representative homology search for similarity evidence "
        "against installed global centroids. Each runs as a separate job.",
    )
    source, fasta = render_input(
        config=config, key="analyse",
        hog_connection=connection if task == "Alignment and tree" else None,
    )
    parameters = dict(source)
    hog_source = st.session_state.get("analyse_route") == "Published HOG members"
    if hog_source and fasta:
        parameters["e3_hog_id"] = st.session_state["analyse_hog"]
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
            cluster_key = f"align_subcluster_{source['source_job']}"
            if st.session_state.get(cluster_key) not in labels:
                st.session_state.pop(cluster_key, None)
            subcluster_choice = st.selectbox(
                "Subcluster to align",
                options=list(labels),
                format_func=labels.__getitem__,
                help=FIELD_HELP["subcluster"],
                key=cluster_key,
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
    execution = "Research worker"
    execution_issue = ""
    if task == "Stricter subclusters":
        execution = st.radio(
            "Run subclustering on", ("App host", "External VM (SSH)", "Research worker"),
            key="subcluster_execution", horizontal=True,
            help="The app host runs DIAMOND here. The external VM receives the selected FASTA "
            "over SSH. A research worker picks up the job from this shared workspace.",
        )
        if execution == "App host":
            diamond = shutil.which(config.diamond)
            if diamond:
                st.caption(f"DIAMOND executable · {diamond}")
            else:
                execution_issue = f"DIAMOND is unavailable on the app host ({config.diamond})."
        elif execution == "External VM (SSH)":
            if not config.remote_host or not config.remote_config:
                execution_issue = (
                    "Set remote_host and remote_config in the app's research profile "
                    "to use the external VM."
                )
            elif not shutil.which("ssh"):
                execution_issue = "SSH is unavailable on the machine running the app."
            else:
                st.caption(f"The selected FASTA will be sent to {config.remote_host} over SSH.")
        if execution_issue:
            st.warning(execution_issue)
    st.markdown("#### Review analysis settings")
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
                "DIAMOND 2.2.1 or newer builds a database from the selected FASTA, clusters "
                "it and realigns each member to its assigned centroid. Failed assignments "
                "become singletons."
            )
        elif task == "Alignment and tree":
            operation = "align"
            parameters["subcluster_id"] = subcluster_choice
            if hog_source and fasta:
                ids = [line[1:] for line in fasta.splitlines() if line.startswith(">")]
                parameters["reference_id"] = st.selectbox(
                    label="Reference protein", options=["", *ids],
                    format_func=lambda value: value or "First protein by sorted ID",
                    help=FIELD_HELP["reference"],
                )
            elif not hog_source:
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
        submitted = st.form_submit_button(
            {
                "Stricter subclusters": {
                    "App host": "Run subclustering here",
                    "External VM (SSH)": "Run subclustering on external VM",
                    "Research worker": "Queue stricter subclustering",
                }[execution],
                "Alignment and tree": "Queue alignment and tree",
                "Representative homology search": "Queue representative search",
            }[task],
            disabled=bool(execution_issue) or (not source and not fasta),
            help="Save this input and these settings. Follow progress and errors in Jobs.",
        )
        prepare = operation == "align" and st.form_submit_button(
            "Prepare files for another machine", disabled=not fasta,
            help="Use uploaded, pasted or prepared FASTA for a self-contained job ZIP.",
        )
    if submitted:
        queue_action(
            config=config, operation=operation, parameters=parameters, fasta=fasta,
            run_on_app_host=execution != "Research worker",
            external_vm=execution == "External VM (SSH)",
        )
    if operation == "align":
        render_portable_job(operation=operation, parameters=parameters, fasta=fasta,
                            prepare=prepare)
    completed = (
        completed_manifests(config=config, operation="subcluster")
        if task == "Stricter subclusters" else {}
    )
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
        render_subcluster_result(config=config, job_id=selected, manifest=completed[selected])


def render_subcluster_result(*, config: ResearchConfig, job_id: str, manifest: dict) -> None:
    """Show an audited network, size summary and exact alignment handoff.

    Args:
        config: Workspace containing the completed result.
        job_id: Owning subclustering job.
        manifest: Verified result inventory from that job.
    """
    from .subcluster_network import (
        OVERVIEW_GROUPS,
        load_network_members,
        network_figure,
        network_graphml,
    )

    frame = read_table(path=artifact_path(
        workspace=config.workspace, job_id=job_id, artifact="subclusters.tsv",
    ))
    if frame.empty:
        st.info("This job recorded no subclusters.")
        return
    frame["member_count"] = pd.to_numeric(frame["member_count"])
    st.markdown("#### Subcluster network")
    labels = {"": "Largest subclusters"}
    labels.update({
        row.subcluster_id: f"{row.representative_id} · {row.member_count:,} proteins"
        for row in frame.itertuples(index=False)
    })
    group = st.selectbox(
        "Subcluster to inspect", options=list(labels), format_func=labels.__getitem__,
        key=f"subcluster_network_group_{job_id}",
        help="The overview shows up to 12 subclusters. Choose one centroid to inspect its group.",
    )
    groups = [group] if group else frame["subcluster_id"].head(OVERVIEW_GROUPS).tolist()
    artifacts = manifest["artifacts"]
    membership = "membership.parquet" if "membership.parquet" in artifacts else "membership.tsv"
    try:
        members = load_network_members(
            path=artifact_path(workspace=config.workspace, job_id=job_id, artifact=membership),
            subclusters=groups,
        )
    except ResearchError as exc:
        st.warning(f"The network is unavailable for this result. {exc}")
    else:
        if not members.empty:
            total = members.drop_duplicates("subcluster_id")["cluster_size"].sum()
            st.caption(
                f"Showing {len(members):,} of {total:,} proteins in this view. "
                "Links show passing exact centroid alignments. Isolated nodes are "
                "singletons. Hover over a protein for its audit evidence."
            )
            st.plotly_chart(
                network_figure(members=members), key=f"subcluster_network_{job_id}",
                config={"scrollZoom": True, "displaylogo": False},
            )
            st.download_button(
                "Download displayed network (GraphML)", data=network_graphml(members=members),
                file_name=f"subclusters_{job_id[:12]}_{group or 'overview'}.graphml",
                mime="application/graphml+xml", key=f"subcluster_graphml_{job_id}",
                on_click="ignore",
            )
            with st.expander("Displayed proteins and audit evidence"):
                st.dataframe(members, hide_index=True)
    if "sequences.fasta" in artifacts:
        render_next_action(
            label=("Set up alignment for this subcluster" if group
                   else "Align a family or subcluster from this job"),
            key="subclusters_to_alignment", section="Family analysis",
            analysis_task="Alignment and tree", source_job=job_id,
            source_artifact="sequences.fasta", subcluster_id=group,
        )
    with st.expander("Subcluster sizes and audit summary"):
        st.dataframe(frame, hide_index=True)
        st.plotly_chart(
            px.bar(frame.head(50), x="subcluster_id", y="member_count", log_y=True),
            key=f"subcluster_sizes_{job_id}",
        )


def render_new_hog_alignment(*, config: ResearchConfig, connection: object) -> None:
    """Prepare HOG sequences and run or export an alignment from the viewer page.

    Args:
        config: Research workspace, executable paths and analysis limits.
        connection: Open E3 release with its HOG membership and protein sequences.
    """
    from .expansion_ui import render_hog_alignment_input
    from .local_worker import submit_local_alignment

    st.caption("Select a HOG to prepare its unaligned protein sequences from this release.")
    fasta = render_hog_alignment_input(
        config=config, connection=connection, key="msa", browse=True,
    )
    if not fasta:
        return
    hog = st.session_state["msa_hog"]
    ids = sorted(line[1:] for line in fasta.splitlines() if line.startswith(">"))
    st.caption("Use the selected HOG proteins in another analysis.")
    render_protein_analysis_links(
        key="selected_hog_members",
        prepared_fasta=(f"{hog} · {len(ids):,} selected proteins", fasta),
    )
    parameters = {"e3_hog_id": hog}
    sample_size = len(ids)
    fasttree_ready = bool(shutil.which(config.fasttree))
    with st.expander("Alignment settings", expanded=True):
        parameters["reference_id"] = st.selectbox(
            label="Reference protein", options=ids, key=f"msa_reference_{hog}",
            help=FIELD_HELP["reference"],
        )
        sample = len(ids) > 1 and st.checkbox(
            label="Use a deterministic sample", key="msa_allow_sampling",
            help=FIELD_HELP["sampling"],
        )
        if sample:
            maximum = min(len(ids), config.max_alignment_sequences)
            sample_size = st.number_input(
                label="Proteins to sample", min_value=1, max_value=maximum,
                value=min(200, maximum), help=FIELD_HELP["sample_size"],
            )
            parameters.update(allow_sampling=True, sample_size=sample_size)
        infer_tree = sample_size >= 3 and st.checkbox(
            label="Infer protein tree with FastTree", value=fasttree_ready,
            help=FIELD_HELP["tree"],
        )
        parameters["infer_tree"] = infer_tree
        st.caption(
            f"Alignment limit of {config.max_alignment_sequences:,} proteins and "
            f"{config.max_alignment_cells:,} matrix cells."
        )

    job_key = f"msa_alignment_job_{config.workspace}_{hog}"
    job_id = st.session_state.get(job_key)
    job = get_job(workspace=config.workspace, job_id=job_id) if job_id else None
    pending = bool(job and job["status"] in {"QUEUED", "RUNNING"})
    can_submit = sample_size <= config.max_alignment_sequences
    if not can_submit:
        st.info("Choose fewer members or enable sampling to submit this alignment.")
    mafft_ready = bool(shutil.which(config.mafft))
    if not mafft_ready:
        st.info(
            "MAFFT is unavailable on the machine running this app. Install MAFFT there, "
            "use a research worker, or download the job files."
        )
    elif infer_tree and not fasttree_ready:
        st.info("Install FastTree here or untick the tree option to run this alignment here.")

    left, middle, right = st.columns(3)
    run_label = "Run MAFFT on this Mac" if sys.platform == "darwin" else "Run MAFFT on app machine"
    if left.button(
        label=run_label, key="msa_align_here", type="primary",
        disabled=(
            not mafft_ready or (infer_tree and not fasttree_ready) or pending or not can_submit
        ),
        help="Runs on the computer where the app was launched, using its installed MAFFT.",
    ):
        st.session_state[job_key] = submit_local_alignment(
            config=config, parameters=parameters, fasta=fasta,
        )
        st.rerun()
    if middle.button(
        label="Queue for research worker", key="msa_queue_alignment",
        disabled=pending or not can_submit,
        help="A running research worker must have access to this queue workspace.",
    ):
        st.session_state[job_key] = submit_job(
            workspace=config.workspace, operation="align", parameters=parameters, fasta=fasta,
        )
        st.rerun()
    prepare = right.button(label="Prepare files for another machine", key="msa_prepare_job")
    render_portable_job(operation="align", parameters=parameters, fasta=fasta, prepare=prepare)
    if not job:
        return
    st.caption(f"{hog} alignment job {job_id} · {job['status']}")
    if pending:
        st.button(label="Refresh alignment status", key="msa_refresh_status")
    if job["error"]:
        st.error(str(job["error"]))
    if job["status"] == "COMPLETE":
        def open_result() -> None:
            """Open the just-completed job in the current JBrowse page."""
            st.session_state["alignment_view_source"] = "Completed alignment job"
            st.session_state["research_alignment_job"] = job_id
            st.session_state["completed_alignment_view"] = "JBrowse MSA"

        st.button(label="Open completed alignment", type="primary", on_click=open_result)
    render_next_action(
        label="View job details", key=f"msa_job_details_{job_id}", section="Jobs", job_id=job_id,
    )


def render_alignment_statistics(*, config: ResearchConfig, job_id: str) -> None:
    """Show saved position and protein statistics with their calculation help.

    Args:
        config: Research workspace.
        job_id: Completed alignment supplying both metrics tables.
    """
    for name, heading, metrics in (
        ("alignment_columns.tsv", "Per-position statistics", ALIGNMENT_POSITION_METRICS),
        ("alignment_members.tsv", "Per-protein statistics", ALIGNMENT_MEMBER_METRICS),
    ):
        frame = read_table(
            path=artifact_path(workspace=config.workspace, job_id=job_id, artifact=name)
        )
        st.markdown(f"#### {heading}")
        with st.popover("Metric definitions", icon=":material/help:"):
            for label, description in metrics.values():
                st.markdown(f"**{label}**  \n{description}")
        st.dataframe(
            frame, hide_index=True,
            column_config={
                key: st.column_config.Column(label=label, help=description)
                for key, (label, description) in metrics.items()
            },
        )
        if name == "alignment_columns.tsv":
            st.plotly_chart(
                px.line(
                    frame.assign(
                        gap_fraction=pd.to_numeric(frame["gap_fraction"]),
                        alignment_column=pd.to_numeric(frame["alignment_column"]),
                    ),
                    x="alignment_column", y="gap_fraction", range_y=(0, 1),
                    labels={"alignment_column": "Alignment column", "gap_fraction": "Gap fraction"},
                ),
                key="alignment_gaps",
            )


def render_tree_request(
    *, config: ResearchConfig, alignment_job: str, count: int, jobs: list[dict[str, object]],
) -> None:
    """Offer tree inference for a completed alignment lacking a saved tree.

    Args:
        config: Workspace and app-host FastTree executable.
        alignment_job: Source alignment job ID.
        count: Number of aligned proteins.
        jobs: Recent tree jobs for this alignment, newest first.
    """
    from .local_worker import submit_local_tree

    pending = next((job for job in jobs if job["status"] in {"QUEUED", "RUNNING"}), None)
    if pending:
        status = str(pending["status"]).lower()
        st.info(f"FastTree job {pending['job_id']} is {status}.")
        st.button("Refresh tree status", key=f"refresh_tree_{alignment_job}")
        return
    if jobs and jobs[0]["status"] == "FAILED":
        st.error(f"Tree inference failed. {jobs[0]['error']}")
    st.info("This completed alignment has no saved protein tree.")
    if count < 3:
        st.caption("FastTree requires an alignment of at least three proteins.")
        return
    if not shutil.which(config.fasttree):
        st.warning("FastTree is unavailable on the machine running the app.")
        st.caption(
            "Install FastTree in the app environment and relaunch. Set fasttree in "
            "the research profile if you use a separate executable."
        )
        st.code("conda install -c conda-forge -c bioconda fasttree", language="bash")
        return
    if st.button(
        "Infer tree from this alignment", key=f"infer_tree_{alignment_job}", type="primary",
        help="Run FastTree WAG+gamma on the saved alignment using the app machine.",
    ):
        submit_local_tree(config=config, alignment_job=alignment_job)
        st.rerun()


def render_saved_tree(
    *, config: ResearchConfig, job_id: str, artifacts: set[str],
) -> None:
    """Preview a checksummed protein tree and offer its portable files.

    Args:
        config: Workspace and optional configured Auspice viewer.
        job_id: Completed job containing Newick or Auspice v2 JSON.
        artifacts: Names of the saved tree artifacts.
    """
    from .analysis import auspice_dataset

    newick = ""
    if "tree.nwk" in artifacts:
        newick = artifact_path(
            workspace=config.workspace, job_id=job_id, artifact="tree.nwk",
        ).read_text(encoding="utf-8")
    has_dataset = "auspice.json" in artifacts
    if has_dataset:
        json_text = artifact_path(
            workspace=config.workspace, job_id=job_id, artifact="auspice.json",
        ).read_text(encoding="utf-8")
        try:
            dataset = json.loads(json_text)
        except ValueError as exc:
            raise ResearchError("Could not read the saved Auspice dataset") from exc
    else:
        dataset = auspice_dataset(newick=newick, metadata={}, title="Protein family phylogeny")
        json_text = json.dumps(dataset, indent=2, allow_nan=False) + "\n"
    if config.auspice_url and has_dataset and st.toggle(
        "Use configured Auspice viewer", value=True, key=f"auspice_server_{job_id}",
    ):
        components.iframe(
            auspice_dataset_url(base_url=config.auspice_url, job_id=job_id),
            height=760, scrolling=True,
        )
    else:
        st.plotly_chart(protein_tree_figure(dataset=dataset), key=f"protein_tree_{job_id}")
    if newick:
        st.download_button(
            "Download Newick tree", data=newick, file_name=f"{job_id}.nwk",
            mime="text/plain", key=f"newick_download_{job_id}",
        )
    st.download_button(
        "Download Auspice dataset", data=json_text, file_name=f"{job_id}.json",
        mime="application/json", key=f"auspice_download_{job_id}",
    )


def render_alignments(
    *, config: ResearchConfig, dedicated: bool = False, app_config: AppConfig | None = None,
    connection: object | None = None,
) -> None:
    """Render alignment viewers, protein-tree inference and saved statistics.

    Args:
        config: Alignment workspace and Auspice URL.
        dedicated: Present the focused JBrowse page.
        app_config: Optional published E3 resources for the HOG alignment route.
        connection: Optional loaded E3 release for collecting unaligned HOG sequences.
    """
    from .expansion_ui import render_published_alignment, render_uploaded_alignment

    if not dedicated:
        render_page_guidance(section="Alignments and trees")
    options = ["Try an example", "Upload alignment files", "Completed alignment job"]
    if app_config is not None:
        options.append("Published HOG alignment")
    if connection is not None:
        options.insert(0, "Align a HOG")
    completed = completed_manifests(config=config, operation="align") if not dedicated else {}
    source = st.radio("Alignment source", options, horizontal=True, key="alignment_view_source",
                      index=options.index("Completed alignment job") if completed else 0,
                      help="Start with HOG sequences or open an existing protein alignment.")
    if source == "Align a HOG":
        render_new_hog_alignment(config=config, connection=connection)
        return
    if source == "Published HOG alignment":
        render_published_alignment(
            config=config, app_config=app_config, can_align_hog=connection is not None,
        )
        return
    if source != "Completed alignment job":
        render_uploaded_alignment(config=config, example=source == "Try an example")
        if not dedicated:
            render_next_action(label="Set up an alignment", key="empty_alignment",
                               section="Family analysis", analysis_task="Alignment and tree")
        return
    if dedicated:
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
        "are saved with the job. The Auspice tree view can infer a tree from its saved alignment.",
        key="research_alignment_job",
    )
    summary = json.loads(
        artifact_path(
            workspace=config.workspace, job_id=job_id, artifact="alignment_summary.json"
        ).read_text()
    )
    left, middle, right = st.columns(3)
    left.metric(
        "Aligned proteins", f"{int(summary['aligned_sequence_count']):,}",
        help="Number of protein sequences in this saved alignment, including the reference.",
    )
    middle.metric(
        "Aligned positions", f"{int(summary['alignment_length']):,}",
        help="Number of columns across the alignment, including columns with gaps.",
    )
    right.metric(
        "Mean gap fraction",
        f"{float(summary['mean_gap_fraction']):.1%}",
        help="Number of gap cells divided by all cells in the alignment. This is the "
        "average gap fraction across columns.",
    )
    st.caption(f"Reference protein: {summary['reference_id']}")
    with st.expander("Technical alignment summary (JSON)"):
        st.json(summary)
    artifacts = completed[job_id]["artifacts"]
    if "sequences.fasta" in artifacts:
        st.caption("Use the proteins from this completed alignment in another analysis.")
        render_protein_analysis_links(
            key=f"alignment_members_{job_id}", source_job=job_id, source_artifact="sequences.fasta",
        )
    view = st.radio(
        "Alignment viewer",
        ["JBrowse MSA", "Alignment Viewer 2", "Auspice tree", "Statistics"],
        horizontal=True,
        help="JBrowse MSA combines the alignment and tree. Alignment Viewer 2 supports "
        "sorting by similarity to the reference. Statistics gives tables and conservation "
        "plots. Auspice tree opens a saved protein tree or lets you infer one with FastTree.",
        key="completed_alignment_view",
    )
    st.caption(
        {
            "JBrowse MSA": "Use the viewer's File/View/Tools menus, sequence search and zoom "
            "controls. When a tree was inferred, it appears in the left panel; "
            "coloured columns are aligned residues.",
            "Alignment Viewer 2": "The reference appears first. Use the viewer controls to "
            "sort sequences by their BLOSUM score to that query and inspect conserved regions.",
            "Auspice tree": "Explore the inferred protein tree. Branch lengths are measured "
            "in substitutions per site.",
            "Statistics": "Per-protein metrics use the selected reference. Read consensus "
            "and entropy alongside the canonical residue fraction.",
        }[view]
    )
    if view == "Statistics":
        render_alignment_statistics(config=config, job_id=job_id)
        return
    tree_id, tree_jobs = job_id, []
    tree_artifacts = {"tree.nwk", "auspice.json"}.intersection(artifacts)
    if not tree_artifacts and view in {"Auspice tree", "JBrowse MSA"}:
        tree_jobs = list_jobs(workspace=config.workspace, operation="tree", source_job=job_id)
        saved = next((job for job in tree_jobs if job["status"] == "COMPLETE"), None)
        if saved:
            tree_id = str(saved["job_id"])
            tree_artifacts = {"tree.nwk", "auspice.json"}
    if view == "Auspice tree":
        if tree_artifacts:
            render_saved_tree(config=config, job_id=tree_id, artifacts=tree_artifacts)
        else:
            render_tree_request(
                config=config, alignment_job=job_id,
                count=int(summary["aligned_sequence_count"]), jobs=tree_jobs,
            )
        return
    path = artifact_path(workspace=config.workspace, job_id=job_id, artifact="alignment.fasta")
    records = dict(iter_fasta(path=path, aligned=True))
    reference = summary["reference_id"]
    ordered = {reference: records[reference], **records}
    tree = (
        artifact_path(
            workspace=config.workspace, job_id=tree_id, artifact="tree.nwk",
        ).read_text(encoding="utf-8")
        if "tree.nwk" in tree_artifacts
        else ""
    )
    if view == "JBrowse MSA":
        from .expansion_ui import render_alignment_heatmap, render_jbrowse, species_view

        show_heatmap = st.toggle(
            "Show identity heatmap beside JBrowse", value=True, key="show_alignment_heatmap",
        )
        viewer_column, heatmap_column = (
            st.columns((3, 2), gap="medium") if show_heatmap else (st.container(), None)
        )
        with viewer_column:
            tree = species_view(config=config, job_id=job_id, records=records, default_tree=tree)
            render_jbrowse(records=ordered, tree=tree, stem=f"{job_id}_jbrowse")
        if heatmap_column is not None:
            with heatmap_column:
                render_alignment_heatmap(records=ordered, job_id=job_id)
        return
    msa = "".join(f">{name}\n{sequence}\n" for name, sequence in ordered.items())
    document = viewer_document(
        viewer="alignment", payload={"msa": msa, "tree": tree},
    )
    components.html(document, height=740, scrolling=True)
    st.download_button(
        "Download standalone alignment viewer",
        data=document,
        file_name=f"{job_id}_av2.html",
        mime="text/html",
    )


def external_execution_on_app_host(*, key: str) -> bool:
    """Select where a hosted provider request is sent from.

    Args:
        key: Unique identifier for the execution selector.

    Returns:
        Whether the app should start its own worker for the submitted request.
    """
    return st.radio(
        "Send the external request from",
        ("App host", "Research worker"),
        horizontal=True,
        key=key,
        help="App host starts a background worker now. Research worker saves the request "
        "for a worker using this workspace. The selected provider performs the analysis.",
    ) == "App host"


def render_models(
    *, config: ResearchConfig, dedicated: bool = False, connection: object | None = None,
) -> None:
    """Queue optional ESMFold jobs and interrogate exact-sequence model evidence.

    Args:
        config: Trusted model providers and workspace.
        dedicated: Open the model file route in the named ESMFold page.
        connection: Optional E3 sequence release for a selected protein.
    """
    route = st.radio("Model workflow", ["Open an existing PDB", "Predict with ESMFold"],
                     horizontal=True, index=0 if dedicated else 1, key="esmfold_view_route",
                     help="Inspect a model file or open the prediction and completed-job forms.")
    if route == "Open an existing PDB":
        render_uploaded_model()
        return
    render_page_guidance(section="Models")
    st.caption("Start an external prediction, queue a job for a research worker, "
               "or prepare the files for another machine.")
    published_fasta = None
    selection = st.session_state.get("selected_e3_model_protein") if dedicated else None
    if connection is not None and selection:
        from .e3_adapter import published_protein_fasta

        accession, group_id, species = selection
        try:
            published_fasta = published_protein_fasta(
                connection=connection, accession=accession, hog_id=group_id, species=species,
            )
        except AppError as exc:
            LOGGER.info("Selected E3 model sequence unavailable: %s", exc)
            st.info(f"Exact released sequence unavailable for {accession} in {group_id}. "
                    "Upload or paste the protein’s FASTA to continue.")
    elif dedicated and connection is not None:
        st.caption("To use a released protein sequence, open ESMFold from its feature record.")
    source, fasta = render_input(config=config, key="fold", published_fasta=published_fasta)
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
    if (engine == "atlas" and published_fasta and fasta == published_fasta[1]
            and len(fasta.splitlines()[1]) > 400):
        issue = ("This protein exceeds the ESM Atlas limit of 400 residues. "
                 "Choose a configured dedicated endpoint or local ESMFold.")
    if issue:
        st.warning(issue)
    remote = False
    run_on_app_host = False
    if engine != "local":
        remote = st.checkbox(
            "Submit these sequences to the selected external provider",
            help=FIELD_HELP["consent"],
            key=f"fold_consent_{engine}",
        )
        if not remote:
            st.caption("Select external submission to enable this remote prediction request.")
        run_on_app_host = external_execution_on_app_host(key="fold_execution")
    if not source and not fasta:
        st.caption("Select a protein FASTA to enable prediction or file preparation.")
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
            "Start ESMFold prediction" if run_on_app_host else "Queue ESMFold prediction",
            disabled=bool(issue)
            or (not source and not fasta)
            or (engine != "local" and not remote),
            help="Predict models for the selected proteins. External requests require the "
            "submission selection above. Follow per-protein successes and failures in Jobs.",
        )
        prepare = st.form_submit_button("Prepare files for another machine", disabled=not fasta
                                        or (engine != "local" and not remote))
    parameters = {**source, "sequence_ids": ids, "engine": engine, "remote_allowed": remote}
    if queued:
        queue_action(
            config=config,
            operation="predict",
            parameters=parameters,
            fasta=fasta,
            run_on_app_host=run_on_app_host,
        )
    render_portable_job(operation="predict", parameters=parameters, fasta=fasta, prepare=prepare)
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
    render_model_trace(residues=residues)
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


def render_model_trace(*, residues: pd.DataFrame) -> None:
    """Show coordinates and reported per-residue confidence for a predicted model.

    Args:
        residues: Validated per-residue coordinate evidence.
    """
    residues = residues.copy()
    for column in ("x", "y", "z", "residue_index", "confidence_b_factor"):
        residues[column] = pd.to_numeric(residues[column])
    figure = go.Figure(go.Scatter3d(
        x=residues.x, y=residues.y, z=residues.z, mode="lines+markers",
        marker={"size": 3, "color": residues.confidence_b_factor, "cmin": 0, "cmax": 100,
                "colorscale": "Viridis", "colorbar": {"title": "Confidence"}},
        text=residues.residue + residues.residue_index.astype(str),
        hovertemplate="%{text}<extra></extra>",
    ))
    figure.update_layout(scene={"aspectmode": "data"}, title="Predicted model · C-alpha trace")
    st.plotly_chart(figure, key="predicted_model_trace")
    st.plotly_chart(px.line(residues, x="residue_index", y="confidence_b_factor", range_y=[0, 100]),
                    key="model_confidence")


def render_uploaded_model() -> None:
    """Inspect an externally produced monomer PDB against its exact FASTA sequence."""
    from .expansion_ui import upload_text
    from .providers import pdb_evidence
    from .viewer_inputs import uploaded_proteins

    st.caption("Open an ESMFold PDB and its original protein FASTA. Confidence is read from the "
               "PDB B-factor field.")
    pdb = upload_text(label="Predicted monomer PDB", types=["pdb"], key="viewer_model_pdb")
    fasta = upload_text(label="Original model input FASTA", types=["fa", "faa", "fasta"],
                        key="viewer_model_fasta")
    if pdb and fasta:
        records = uploaded_proteins(text=fasta)
        identifier = st.selectbox("Original protein ID", options=list(records))
        residues = pdb_evidence(pdb=pdb, expected_sequence=records[identifier])
        render_model_trace(residues=pd.DataFrame(residues))


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
    contact_email = None
    if engine == "interpro_remote":
        contact_email = st.text_input(
            "InterProScan contact email",
            key="interproscan_contact_email",
            placeholder="name@example.org",
            max_chars=254,
            help="EMBL-EBI requires a contact email. An address entered here applies to this "
            "queued job. Leave it blank to use the configured contact, if available. "
            "Files prepared for another machine use that worker's configured address.",
        ).strip() or None
    issue = provider_problem(
        config=config, operation="annotate", engine=engine, contact_email=contact_email,
    )
    if issue:
        st.warning(issue)
    remote = False
    run_on_app_host = False
    if engine == "interpro_remote":
        remote = st.checkbox(
            "Submit selected sequences to EMBL-EBI InterProScan",
            help="Send the selected proteins and contact email to EMBL-EBI. "
            "A remote job can contain up to 25 proteins.",
            key="annotation_remote_consent",
        )
        if not remote:
            st.caption("Select external submission to enable this remote annotation request.")
        run_on_app_host = external_execution_on_app_host(key="annotation_execution")
    with st.form("research_annotation"):
        ids = split_identifiers(
            value=st.text_area(
                "Exact sequence IDs to annotate (blank selects input)",
                help=(
                    FIELD_HELP["sequence_ids"] + " For EMBL-EBI, select up to 25 proteins "
                    "and leave this blank only if the input fits that limit."
                    if engine == "interpro_remote" else FIELD_HELP["sequence_ids"]
                ),
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
            "Start annotation" if run_on_app_host else "Queue annotation",
            disabled=bool(issue)
            or (not source and not fasta)
            or (engine == "interpro_remote" and not remote),
            help="Run the chosen method for the selected proteins. Inspect no-hit records "
            "as well as predicted annotations after the worker completes the job.",
        )
        prepare = st.form_submit_button("Prepare files for another machine", disabled=not fasta
                                        or (engine == "interpro_remote" and not remote))
    parameters = {**source, "sequence_ids": ids, "engine": engine, "tax_scope": scope,
                  "target_taxon": target, "remote_allowed": remote}
    if queued:
        queue_action(
            config=config,
            operation="annotate",
            parameters=parameters,
            fasta=fasta,
            interproscan_email=contact_email,
            run_on_app_host=run_on_app_host,
        )
    render_portable_job(operation="annotate", parameters=parameters, fasta=fasta, prepare=prepare)
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
        "QUEUED": "Waiting for a worker to claim this job. You can use the command below "
        "to start this request from a terminal.",
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
    if job["status"] == "QUEUED":
        if job["operation"] == "subcluster":
            from .local_worker import start_queued_subcluster

            if st.button(
                "Start this subclustering job", key=f"start_subcluster_{selected}",
                help="Run the saved job. Earlier jobs use DIAMOND on the app host.",
                type="primary",
            ):
                start_queued_subcluster(config=config, job_id=selected)
                st.success("Started a worker for this saved request. Refresh for updates.")
        elif job["operation"] in {"annotate", "predict"} and queued_external_provider_job(
            workspace=config.workspace, job_id=selected,
        ):
            from .local_worker import start_queued_provider_job

            if st.button(
                "Start this external job on the app host",
                key=f"start_external_job_{selected}",
                help="Start a background worker for this saved request and its selected provider.",
                type="primary",
            ):
                start_queued_provider_job(config=config, job_id=selected)
                st.success(
                    "Started a worker for this saved request. Refresh job status for updates."
                )
        with st.expander("Run this queued job from a terminal"):
            st.write(f"Queue workspace: `{config.workspace}`")
            command = ["protein-research-workbench"]
            profile = os.environ.get("E3_RESEARCH_CONFIG", "")
            if profile:
                command.extend(["--config", str(Path(profile).expanduser().resolve())])
            st.caption("Run on a machine with access to this workspace, using the app's "
                       "research profile and the research environment.")
            st.code(shlex.join([*command, "doctor"]), language="bash")
            st.code(shlex.join([*command, "worker", "--once", "--job-id", selected]),
                    language="bash")
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
        if operation == "subcluster":
            render_subcluster_result(config=config, job_id=selected, manifest=manifest)
        elif operation in {"retrieve", "deepclust_retrieve", "import_cluster"}:
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
                    analysis_task="Stricter subclusters",
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
            "local_worker.log",
            "predictions.tsv",
            "interpro_service_job.json",
            "subcluster_ssh.log",
            "vm_worker.log",
            "vm_commands.jsonl",
            "commands.jsonl",
        ):
            path = directory / name
            if path.is_file() and path.stat().st_size <= 2_000_000:
                st.markdown(f"**{name}**")
                st.code(
                    path.read_text(encoding="utf-8"),
                    language="json" if name.endswith("json") else "text",
                )


def render_research_workbench(
    *, connection: object | None = None, initial_section: str = "Start here",
    title: str = "Protein research workbench", dedicated: bool = False,
    external_search: bool = False, app_config: AppConfig | None = None,
) -> None:
    """Render one selected generic research section, optionally with an E3 adapter.

    Args:
        connection: Optional open E3 resource for top-N or exact-HOG input selection.
        initial_section: First page when entering a different application surface.
        title: Application surface heading.
        dedicated: Render just the named viewer or import page.
        external_search: Prioritise external DeepClust FASTA and Parquet exchange.
        app_config: Published E3 resource settings for the dedicated HOG alignment viewer.
    """
    st.header(title)
    try:
        from .expansion_ui import (
            render_campaign, render_comparisons, render_deepclust_exchange, render_features,
        )

        config = load_config()
        discover = render_deepclust_exchange if external_search else render_discovery
        section = initial_section
        if not dedicated:
            sections = [value for value in SECTIONS
                        if not external_search or value != "Top-200 cluster campaign"]
            if (st.session_state.get("research_surface") != title
                    or st.session_state.get("research_section") not in sections):
                st.session_state["research_surface"] = title
                st.session_state["research_section"] = initial_section
            section = st.radio(
                "Workbench page", options=sections, horizontal=True, key="research_section",
                format_func=lambda value: (
                    "DeepClust results & FASTA"
                    if external_search and value == "Discover" else value
                ),
                help=FIELD_HELP["navigation"],
            )
        renderers = {
            "Start here": lambda: render_start(config=config, connection=connection,
                                               external_search=external_search),
            "Discover": lambda: discover(config=config, connection=connection),
            "Top-200 cluster campaign": lambda: render_campaign(
                config=config, connection=connection,
            ),
            "Cluster comparisons": lambda: render_comparisons(config=config),
            "Protein features": lambda: render_features(
                config=config, connection=connection, dedicated=dedicated,
            ),
            "Family analysis": lambda: render_analysis(
                config=config, enable_search=not external_search, connection=connection,
            ),
            "Alignments and trees": lambda: render_alignments(
                config=config, dedicated=dedicated, app_config=app_config, connection=connection,
            ),
            "Models": lambda: render_models(
                config=config, dedicated=dedicated, connection=connection,
            ),
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
