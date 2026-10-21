"""Lazy protein research UI shared by E3 and the standalone generic application."""

from __future__ import annotations

import csv
import hashlib
import json
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
from .jobs import artifact_path, cancel_job, job_directory, list_jobs, submit_job
from .viewers import auspice_dataset_url, nightingale_features, viewer_document


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
        if name.endswith((".fasta", ".faa", ".fa"))
    ]
    route = st.radio(
        "Protein input", ["Completed job", "Upload FASTA"], horizontal=True, key=f"{key}_route"
    )
    if route == "Upload FASTA":
        uploaded = st.file_uploader(
            "Protein FASTA (maximum 20 MB)", type=["fa", "faa", "fasta"], key=f"{key}_upload"
        )
        if uploaded is None:
            return {}, None
        if uploaded.size > 20_000_000:
            raise ResearchError("Uploaded FASTA exceeds 20 MB")
        try:
            return {}, uploaded.getvalue().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ResearchError("FASTA must be UTF-8 text") from exc
    if not options:
        st.info("Retrieve a global cluster first, or upload a protein FASTA.")
        return {}, None
    selected = st.selectbox(
        "Complete source FASTA",
        options=options,
        format_func=lambda item: f"{item[0][:12]} · {item[1]}",
        key=f"{key}_source",
    )
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
    st.success(f"Queued {operation} job {job_id}. The research worker will execute it.")


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
        identifier = st.text_input("Exact DeepClust centroid ID", placeholder="NR_UGC79169.1")
        uploaded = st.file_uploader(
            "Per-cluster FASTA export (maximum 20 MB)",
            type=["fa", "faa", "fasta"],
            key="deepclust_export",
        )
        provenance = st.text_input("Export source / database release")
        expected = st.number_input(
            "Expected published member count (0 if unavailable)",
            min_value=0,
            max_value=config.max_sequences,
            value=0,
        )
        st.caption(
            "The centroid must occur in the FASTA. A supplied member count is checked; "
            "membership and completeness otherwise remain those of the supplied export. "
            "For larger files use the import-deepclust command in DEEPCLUST_EXCHANGE.md."
        )
        queued = st.form_submit_button("Queue cluster import")
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
    modes = ["Global cluster ranking", "Sequence identifiers", "Import extracted cluster"]
    if not config.index or not Path(config.index).expanduser().is_file():
        modes.insert(0, modes.pop())
    if connection is not None:
        modes.append("E3 ranked groups")
    mode = st.radio("Discover clusters", modes, horizontal=True)
    if mode == "Import extracted cluster":
        render_deepclust_import(config=config)
        return
    if mode == "Global cluster ranking":
        with st.form("research_browse"):
            minimum = st.number_input("Minimum published cluster size", min_value=1, value=3)
            exact = st.text_area("Exact global cluster IDs (optional)")
            taxa = st.text_input("Required species/taxon IDs (optional, e.g. 9606 3702)")
            all_taxa = st.checkbox("Require every selected species/taxon")
            any_species = st.checkbox("Require at least one reviewed species assignment")
            limit = st.number_input("Ranking preview rows", min_value=1, max_value=10000, value=200)
            browse = st.form_submit_button("Rank global clusters")
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
                    taxon_ids=taxon_ids,
                    require_all_taxa=all_taxa,
                    any_annotated_species=any_species,
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
    else:
        if mode == "Sequence identifiers":
            identifiers = split_identifiers(
                value=st.text_area("Exact sequence IDs or UniProt accessions")
            )
            context = []
        else:
            kind = st.selectbox("E3 selection", ["Ranked HOGs", "Ranked discovery clusters"])
            maximum = st.number_input(
                "Top ranked E3 groups/clusters", min_value=1, max_value=1000, value=200
            )
            groups = tuple(
                split_identifiers(
                    value=st.text_area("Specific local HOG/cluster IDs (optional; overrides top-N)")
                )
            )
            if st.button("Prepare E3 mapping inputs"):
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
                return
            frame = st.session_state.get("research_e3_inputs")
            if frame is None:
                return
            st.dataframe(frame, hide_index=True)
            identifiers, context = frame["input_id"].drop_duplicates().tolist(), frame.to_dict(
                orient="records"
            )
        st.caption(
            (
                "Input group IDs and global DeepClust centroid IDs are distinct. Exact "
                "matches, declared aliases, multiple matches and unmatched inputs are "
                "retained."
            )
        )
        if st.button("Queue exact global cluster mapping", disabled=not identifiers):
            queue_action(
                config=config,
                operation="resolve",
                parameters={"identifiers": identifiers, "context": context},
            )
    mappings = completed_manifests(config=config, operation="resolve")
    if mappings:
        mapping_job = st.selectbox("Completed sequence mapping", options=list(mappings))
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
    ids = split_identifiers(value=st.text_area("Global cluster IDs to retrieve in full"))
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
    if st.button("Queue complete cluster retrieval", disabled=not ids):
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
        if st.button("Queue reviewed cluster/species index"):
            queue_action(config=config, operation="taxonomy_index", parameters={})


def render_analysis(*, config: ResearchConfig) -> None:
    """Render exact subclustering, bounded alignment and representative-search requests.

    Args:
        config: Tool and workspace profile.
    """
    task = st.radio(
        "Family analysis",
        ["Stricter subclusters", "Alignment and tree", "Representative homology search"],
        horizontal=True,
    )
    source, fasta = render_input(config=config, key="analyse")
    parameters = dict(source)
    with st.form("research_analysis"):
        if task == "Stricter subclusters":
            operation = "subcluster"
            parameters["identity"] = st.number_input(
                "Minimum exact centroid identity (%)", min_value=1.0, max_value=100.0, value=70.0
            )
            parameters["mutual_coverage"] = st.number_input(
                "Minimum coverage in each direction (%)", min_value=1.0, max_value=100.0, value=80.0
            )
            parameters["evalue"] = st.number_input(
                "Maximum exact E-value", min_value=1e-100, max_value=1.0, value=1e-10, format="%.2e"
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
            parameters["subcluster_id"] = st.text_input("Exact audited subcluster ID (optional)")
            parameters["reference_id"] = st.text_input(
                "Reference/query sequence ID (blank selects first ID)"
            )
            parameters["allow_sampling"] = st.checkbox(
                "Use an explicit deterministic sample including the reference"
            )
            size = st.number_input(
                "Sample size, when sampling is selected",
                min_value=1,
                max_value=config.max_alignment_sequences,
                value=min(200, config.max_alignment_sequences),
            )
            if parameters["allow_sampling"]:
                parameters["sample_size"] = size
            parameters["infer_tree"] = st.checkbox(
                "Infer a FastTree WAG+gamma protein phylogeny", value=True
            )
            st.caption(
                "Complete selected family unless sampling is selected. Limits: "
                f"{config.max_alignment_sequences:,} sequences and "
                f"{config.max_alignment_cells:,} matrix cells. "
                "Tree branches show divergence, not time."
            )
        else:
            operation = "search"
            st.caption(
                (
                    "Optional installed global centroid DIAMOND database. Results are "
                    "homology evidence, separate from exact database membership."
                )
            )
        queued = st.form_submit_button(
            "Queue family analysis", disabled=not source and fasta is None
        )
    if queued:
        queue_action(config=config, operation=operation, parameters=parameters, fasta=fasta)
    completed = completed_manifests(config=config, operation="subcluster")
    if completed:
        selected = st.selectbox("Completed subcluster job", options=list(completed))
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


def render_alignments(*, config: ResearchConfig) -> None:
    """Render real JBrowse/AV2 libraries and a configured self-hosted Auspice dataset.

    Args:
        config: Alignment workspace and Auspice URL.
    """
    completed = completed_manifests(config=config, operation="align")
    if not completed:
        st.info(
            (
                "Queue an alignment and tree under Family analysis, then open its "
                "completed result here."
            )
        )
        return
    job_id = st.selectbox("Completed alignment", options=list(completed))
    summary = json.loads(
        artifact_path(
            workspace=config.workspace, job_id=job_id, artifact="alignment_summary.json"
        ).read_text()
    )
    st.json(summary)
    view = st.radio(
        "Alignment viewer",
        ["JBrowse MSA", "Alignment Viewer 2", "Auspice tree", "Statistics"],
        horizontal=True,
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
    source, fasta = render_input(config=config, key="fold")
    with st.form("research_fold"):
        ids = split_identifiers(
            value=st.text_area("Exact sequence IDs to fold (blank selects input; maximum 100)")
        )
        engine = st.selectbox("ESMFold route", options=["atlas", "huggingface_endpoint", "local"])
        remote = st.checkbox("Submit these sequences to the selected external provider")
        st.caption(
            (
                "Atlas route: at most 400 residues. The dedicated endpoint and local "
                "limits are operator configured. Hugging Face requires a deployed "
                "endpoint; the model page is not a public inference service. Existing "
                "successful models are reused by sequence and provider."
            )
        )
        queued = st.form_submit_button(
            "Queue ESMFold prediction", disabled=not source and fasta is None
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
    selected = st.selectbox("Completed model job", options=list(completed))
    predictions = read_table(
        path=artifact_path(workspace=config.workspace, job_id=selected, artifact="predictions.tsv")
    )
    st.dataframe(predictions, hide_index=True)
    available = predictions[predictions["status"].isin(["PREDICTED", "REUSED"])]
    if available.empty:
        return
    identifier = st.selectbox("Model to interrogate", options=available["sequence_id"].tolist())
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
    annotation_job = st.selectbox("Optional annotation overlay", options=["", *annotations])
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
    source, fasta = render_input(config=config, key="annotate")
    with st.form("research_annotation"):
        ids = split_identifiers(
            value=st.text_area("Exact sequence IDs to annotate (blank selects input)")
        )
        engine = st.selectbox(
            "Annotation route", options=["interpro_local", "interpro_remote", "eggnog"]
        )
        scope = st.text_input("eggNOG taxonomic scope", value="Eukaryota")
        target = st.text_input("eggNOG target taxon ID", value="2759")
        remote = st.checkbox("Submit selected sequences to EMBL-EBI InterProScan")
        st.caption(
            (
                "InterProScan predicts signatures/domains. eggNOG transfers "
                "orthology-based annotation within the selected taxonomic scope. No-hit "
                "records remain explicit. These are computational predictions."
            )
        )
        queued = st.form_submit_button("Queue annotation", disabled=not source and fasta is None)
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
    selected = st.selectbox("Completed annotation job", options=list(completed))
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
    if "start" in hits and not hits.empty:
        identifier = st.selectbox(
            "Protein features", options=hits["sequence_id"].drop_duplicates().tolist()
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
    if st.button("Refresh job status"):
        st.rerun()
    jobs = list_jobs(workspace=config.workspace)
    st.dataframe(pd.DataFrame(jobs), hide_index=True)
    if not jobs:
        st.info("No jobs yet. The web process submits work; start a research worker to execute it.")
        return
    selected = st.selectbox("Job details", options=[job["job_id"] for job in jobs])
    job = next(item for item in jobs if item["job_id"] == selected)
    directory = job_directory(workspace=config.workspace, job_id=selected)
    if job["status"] == "QUEUED" and st.button("Cancel queued job"):
        cancel_job(workspace=config.workspace, job_id=selected)
        st.rerun()
    if job["status"] == "COMPLETE":
        manifest = completed_manifests(config=config)[selected]
        st.json(manifest)
        artifact = st.selectbox("Scientific artifact", options=list(manifest["artifacts"]))
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
        for name in ("clusters.tsv", "cluster_summary.tsv"):
            if name in manifest["artifacts"]:
                st.dataframe(
                    read_table(
                        path=artifact_path(
                            workspace=config.workspace, job_id=selected, artifact=name
                        )
                    ),
                    hide_index=True,
                )
    if job["error"]:
        st.error(str(job["error"]))
    for name in (
        "request.json",
        "worker.log",
        "predictions.tsv",
        "interpro_service_job.json",
        "commands.jsonl",
    ):
        path = directory / name
        if path.is_file() and path.stat().st_size <= 2_000_000:
            with st.expander(name):
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
            "Research section",
            options=[
                "Discover",
                "Family analysis",
                "Alignments and trees",
                "Models",
                "Annotations",
                "Jobs",
            ],
            horizontal=True,
        )
        renderers = {
            "Discover": lambda: render_discovery(config=config, connection=connection),
            "Family analysis": lambda: render_analysis(config=config),
            "Alignments and trees": lambda: render_alignments(config=config),
            "Models": lambda: render_models(config=config),
            "Annotations": lambda: render_annotations(config=config),
            "Jobs": lambda: render_jobs(config=config),
        }
        renderers[section]()
    except (ResearchError, OSError, ValueError) as exc:
        st.error(f"Protein research: {exc}")
