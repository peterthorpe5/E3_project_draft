"""Guided Streamlit interface for the generic protein pocket workbench."""

from __future__ import annotations

import csv
import itertools
import json
import os
import uuid
from dataclasses import asdict
from importlib.resources import files as package_files
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from pocket_workbench.annotations import (
    pocket_alignment_data,
    pocket_alignment_document,
)
from pocket_workbench.conservation_ui import conservation_page
from pocket_workbench.core import (
    ComparisonSettings,
    WorkbenchError,
    inside,
    load_project,
    safe_id,
)
from pocket_workbench.database import TABLES, pack_project, query_table, workbook_bytes
from pocket_workbench.evidence import aligner_agreement, comparison_audit
from pocket_workbench.external_ui import external_jump, external_page
from pocket_workbench.groups import AF3_INSPECTOR_URL, inspector_bundle, source_link
from pocket_workbench.help_content import field_help, glossary_rows, methods_text
from pocket_workbench.importing import import_project, read_fasta
from pocket_workbench.jobs import start_job
from pocket_workbench.presentation import (
    METHOD_LABELS,
    analysis_label,
    dataset_summary,
    evidence_figure,
    model_labels,
    pocket_rank,
    ranked_pockets,
    similarity_figure,
)
from pocket_workbench.runtime import available_cpus, execution_info
from pocket_workbench.viewers import (
    alignment_document,
    model_viewer_records,
    sequence_position_columns,
    structure_document,
)


def analysis_enabled() -> bool:
    """Return whether the operator opted into analysis workers on this host."""
    return os.getenv("POCKET_WORKBENCH_ALLOW_JOBS", "0") == "1"


def batch_notice() -> None:
    """Explain the prepared-data workflow next to optional analysis controls."""
    if not analysis_enabled():
        st.info(
            "Browsing prepared results. Run the supplied Slurm build on Dundee HPC, "
            "then open its finished app resource here. Analysis jobs are disabled "
            "in this session."
        )


def tsv_bytes(*, rows: list[dict]) -> bytes:
    """Encode browser-download rows as TSV.

    Args:
        rows: Filtered records.

    Returns:
        UTF-8 TSV bytes.
    """
    return pd.DataFrame(rows).to_csv(sep="\t", index=False).encode()


def upload_file(*, uploaded, directory: Path) -> Path:
    """Save one uploaded file using its bounded basename and streamed bytes.

    Args:
        uploaded: Streamlit uploaded file.
        directory: Session-owned import directory.

    Returns:
        Saved path.
    """
    filename = Path(uploaded.name).name
    if filename in {"", ".", ".."} or "\\" in filename:
        raise WorkbenchError("Upload a file with a regular basename")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if path.exists():
        raise WorkbenchError(f"Two uploads share the filename {filename}; rename one")
    uploaded.seek(0)
    with path.open("wb") as output:
        while block := uploaded.read(1024 * 1024):
            output.write(block)
    return path


def show_table(
    *, rows: list[dict], key: str, glossary_term: str = "", readable_ids: bool = True
) -> None:
    """Show a searchable evidence table with matching TSV/Excel downloads.

    Args:
        rows: Table records.
        key: Unique widget prefix.
        glossary_term: Optional shared metric explanation.
        readable_ids: Shorten identifiers on screen; downloads retain exact IDs.
    """
    if not rows:
        st.info("No records match this selection.")
        return
    query = st.text_input(
        "Search this table",
        key=f"{key}_search",
        help="Search all displayed fields using literal text.",
    )
    frame = pd.DataFrame(rows)
    if query:
        frame = frame.loc[
            frame.astype(str)
            .apply(lambda column: column.str.contains(query, case=False, regex=False))
            .any(axis=1)
        ]
    st.caption(
        f"{len(frame):,} displayed records"
        + (" · " + field_help(term=glossary_term) if glossary_term else "")
    )
    displayed = frame.copy()
    if readable_ids:
        for column in ("sample_id", "reference", "mobile", "parent_sample_id"):
            if column in displayed:
                labels = model_labels(
                    identifiers=[v for v in displayed[column] if isinstance(v, str)]
                )
                displayed[column] = displayed[column].map(lambda v: labels.get(v, v))
    decisions = (
        "position_supported",
        "fold_supported",
        "complete_mapping",
        "rank_one_position_and_fold",
        "rank_one_conserved",
        "rank_one_both_aligners",
        "rank_one_conserved_both_aligners",
        "top_k_both_aligners",
        "quality_screen_pass",
        "conservation_supported",
        "near_cut_boundary",
        "near_very_low_confidence",
    )
    for column in decisions:
        if column in displayed:
            displayed[column] = displayed[column].map(
                lambda v: "Yes" if v is True else "No" if v is False else "Not assessed"
            )
    for column in ("rank_one_position", "top_k_position", "confidence_status"):
        if column in displayed:
            displayed[column] = displayed[column].map(
                lambda v: v.replace("_", " ").capitalize() if isinstance(v, str) else v
            )
    st.dataframe(
        displayed,
        width="stretch",
        hide_index=True,
        column_config={
            "sample_id": "Model",
            "reference": "Reference model",
            "mobile": "Compared model",
            "sequence_id": "Representative FASTA ID",
            "pocket_id": "Pocket ID",
            "rank": "Method rank",
            "method": "Evidence source",
            "confidence_status": "Local pocket confidence",
            "rank_one_position": "Rank-one position",
            "reference_rank": "Original reference rank",
            "mobile_rank": "Original compared rank",
            "conservation_supported": "Conservation rule met",
            "rank_one_position_and_fold": "Rank-one position + fold",
            "rank_one_conserved": st.column_config.TextColumn(
                "Rank-one lining + fold",
                help=(
                    "Requires the saved position, fold, residue-match and chemical"
                    " thresholds. Missing evidence remains not assessed."
                ),
            ),
            "top_k_position": "Any tested member position",
            "best_tested_member_rank": "Best-overlap member rank",
            "best_tested_mobile_pocket": "Best-overlap member pocket ID",
            "rank_one_overlap": st.column_config.NumberColumn(
                "Rank-one overlap", format="%.3f"
            ),
            "best_tested_overlap": st.column_config.NumberColumn(
                "Best tested overlap", format="%.3f"
            ),
            "mean_plddt": st.column_config.NumberColumn(
                "Mean pLDDT", help=field_help(term="pLDDT"), format="%.2f"
            ),
            "centroid_distance": st.column_config.NumberColumn(
                "Centroid distance (Å)",
                help=field_help(term="Centroid distance"),
                format="%.3f",
            ),
            "symmetric_overlap": st.column_config.NumberColumn(
                "Symmetric overlap",
                help=field_help(term="Symmetric overlap"),
                format="%.3f",
            ),
            "sequence_jaccard": st.column_config.NumberColumn(
                "Sequence Jaccard", help=field_help(term="Jaccard index"), format="%.3f"
            ),
            "review_rank": st.column_config.NumberColumn(
                "Review rank", help=field_help(term="Review rank")
            ),
            "druggability_score": st.column_config.NumberColumn(
                "fpocket druggability",
                help=field_help(term="Druggability"),
                format="%.3f",
            ),
            "p2rank_rescore_score": st.column_config.NumberColumn(
                "P2Rank cavity rescore", help=field_help(term="Rescore"), format="%.3f"
            ),
            "volume_a3": st.column_config.NumberColumn(
                "Volume (Å³)", help=field_help(term="Volume"), format="%.2f"
            ),
            "probability": st.column_config.NumberColumn(
                "Method probability", help=field_help(term="Probability"), format="%.3f"
            ),
            "mutual_match_fraction": st.column_config.NumberColumn(
                "Mutual-nearest fraction",
                help=field_help(term="Mutual-nearest match fraction"),
                format="%.3f",
            ),
            "rmsd": st.column_config.NumberColumn("RMSD (Å)", format="%.2f"),
            "tm_reference": st.column_config.NumberColumn(
                "Reference TM-score", format="%.3f"
            ),
            "tm_mobile": st.column_config.NumberColumn(
                "Compared TM-score", format="%.3f"
            ),
            "minimum_tm": st.column_config.NumberColumn(
                "Minimum TM-score", format="%.3f"
            ),
            "reference_coverage": st.column_config.NumberColumn(
                "Reference coverage fraction", format="%.3f"
            ),
            "mobile_coverage": st.column_config.NumberColumn(
                "Compared coverage fraction", format="%.3f"
            ),
            "position_supported": st.column_config.TextColumn(
                "Position supported", help=field_help(term="Position supported")
            ),
            "fold_supported": st.column_config.TextColumn(
                "Region fold supported", help=field_help(term="Fold support")
            ),
            "complete_mapping": st.column_config.TextColumn(
                "Complete residue mapping", help=field_help(term="Complete mapping")
            ),
        },
    )
    filtered = json.loads(frame.to_json(orient="records"))
    first, second = st.columns(2)
    first.download_button(
        "Download displayed TSV",
        tsv_bytes(rows=filtered),
        file_name=f"{key}.tsv",
        mime="text/tab-separated-values",
        key=f"{key}_tsv",
    )
    second.download_button(
        "Download displayed Excel",
        workbook_bytes(
            tables={"Evidence": filtered},
            notes=(
                field_help(term=glossary_term)
                if glossary_term
                else (
                    "Filtered workbench evidence. Read Methods and glossary for metric"
                    " interpretation."
                )
            ),
        ),
        file_name=f"{key}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key}_xlsx",
    )


def import_page(*, workspace: Path, root: Path | None, data: dict | None) -> None:
    """Guide report/model ZIP, FASTA and explicit mapping imports.

    Args:
        workspace: User-selected persistent project parent.
        root: Open resource, if any.
        data: Open project metadata.
    """
    st.header("Start a project")
    st.markdown(
        "**1. Add evidence** · Upload a completed pipeline run ZIP, `report.html`,"
        " model ZIPs or individual PDB/mmCIF files. **2. Add representative FASTA** for"
        " sequence mapping and trees. **3. Create the project** to browse the evidence."
    )
    with st.expander("Which files do I need?", expanded=not bool(data)):
        st.markdown(
            "- **Completed analysis:** ZIP the whole results folder to retain prepared"
            " structures and pocket evidence.\n- **Report only:** opens the existing"
            " tables. Add the matching model ZIPs to enable 3D views.\n- **New"
            " models:** upload one or several AlphaFold ZIPs. Predict pockets from this"
            " app or import a completed run later.\n- **FASTA:** supply one"
            " representative record per sequence. Five models can map to the same"
            " record by exact sequence.\n- **Optional mapping TSV:** `sample_id`,"
            " `sequence_id`, and optional `chain`, `group_id`. A unique exact fragment"
            " needs an explicit sequence mapping."
        )
    with st.form("import_project"):
        files = st.file_uploader(
            "Evidence and model files",
            type=["zip", "html", "pdb", "cif", "mmcif", "duckdb"],
            accept_multiple_files=True,
            help=(
                "ZIPs may contain nested AlphaFold folders or a complete pipeline"
                " results directory. MSA/template folders and large AF3 full-data JSON"
                " are skipped."
            ),
        )
        fasta = st.file_uploader(
            "Representative protein FASTA (optional)",
            type=["fasta", "fa", "faa"],
            help=field_help(term="FASTA"),
        )
        mapping = st.file_uploader(
            "Explicit model-to-FASTA mapping (optional)",
            type=["tsv"],
            help=field_help(term="Mapping TSV"),
        )
        base = st.checkbox(
            "Use the open project as existing evidence",
            value=bool(data),
            disabled=not bool(data),
            help=(
                "Creates a new project with the old evidence and new files. Re-run"
                " comparisons after adding or changing evidence."
            ),
        )
        title = st.text_input(
            "Project title", value=data["title"] if data else "Protein pocket project"
        )
        name = st.text_input(
            "New project folder name",
            value="project_" + uuid.uuid4().hex[:8],
            help=(
                "A new folder inside the workspace shown in the sidebar; existing"
                " folders are preserved."
            ),
        )
        chain = st.text_input(
            "Author chain (leave blank for a single-chain model)",
            help=field_help(term="Chain"),
        )
        confidence = st.selectbox(
            "Interpret structure B fields as",
            ["plddt", "none"],
            help=field_help(term="B-factor"),
        )
        submitted = st.form_submit_button("Create project", type="primary")
    if submitted:
        try:
            safe_id(value=name)
            incoming = workspace / "incoming" / uuid.uuid4().hex
            sources = ([root] if base and root else []) + [
                upload_file(uploaded=file, directory=incoming / str(index))
                for index, file in enumerate(files)
            ]
            fasta_path = (
                upload_file(uploaded=fasta, directory=incoming / "fasta")
                if fasta
                else None
            )
            mapping_path = (
                upload_file(uploaded=mapping, directory=incoming / "mapping")
                if mapping
                else None
            )
            with st.spinner("Preparing models and rebuilding the workbench database…"):
                created = import_project(
                    sources=sources,
                    output=workspace / name,
                    title=title,
                    fasta=fasta_path,
                    mapping=mapping_path,
                    chain=chain.strip(),
                    confidence=confidence,
                )
            st.session_state["resource"] = str(created)
            st.rerun()
        except (ValueError, OSError, RuntimeError) as error:
            st.error(str(error))
    if st.button(
        "Open the synthetic demonstration",
        help=(
            "Three explicitly synthetic models with known transforms, pocket examples"
            " and sequences."
        ),
    ):
        from pocket_workbench.demo import create_demo

        target = workspace / "synthetic_demo"
        if not target.is_dir():
            create_demo(output=target)
        st.session_state["resource"] = str(target)
        st.rerun()


def model_page(*, root: Path, data: dict) -> None:
    """Browse per-model pocket scores and explain confidence and input readiness.

    Args:
        root: Resource directory.
        data: Loaded project.
    """
    st.header("Models and pockets")
    summary = dataset_summary(data=data)
    a, b, c, d = st.columns(4)
    a.metric("Models", len(data["models"]))
    b.metric(
        "With coordinates", sum(bool(row.get("coordinates")) for row in data["models"])
    )
    c.metric(
        "Ranked fpocket cavities",
        sum(row["method"] == "fpocket" for row in data["pockets"]),
    )
    d.metric("Representative sequences", len(data["sequences"]))
    st.caption(
        f"{summary['represented_sequences']} representative sequences have models; "
        f"{summary['fasta_only_sequences']} are FASTA-only. Choose a model and inspect "
        "one pocket first. The viewer opens at its lining residues."
    )
    with st.expander("How to read these results", expanded=False):
        st.markdown(
            "Select a model to inspect its pockets. Review rank applies **within that"
            " model**. Use **Compare structures** to assess whether pockets occupy"
            " corresponding positions after superposition. The original pipeline's"
            " local confidence labels remain visible."
        )
        if not all(row.get("coordinates") for row in data["models"]):
            st.info(
                "This resource has model tables without all coordinates. Use Start /"
                " import, keep the current evidence selected, and add the matching"
                " AlphaFold model ZIPs."
            )
    choices = ["All models"] + [row["sample_id"] for row in data["models"]]
    labels = model_labels(identifiers=choices)
    selected = st.selectbox(
        "Model",
        choices,
        index=1 if len(choices) > 1 else 0,
        format_func=lambda name: labels[name],
        help=field_help(term="Model replicate"),
    )
    methods = sorted({row["method"] for row in data["pockets"]})
    method = st.selectbox(
        "Pocket evidence",
        methods or ["fpocket"],
        index=methods.index("fpocket") if "fpocket" in methods else 0,
        help=(
            "fpocket cavities, independent P2Rank predictions and same-cavity P2Rank"
            " rescoring are retained separately."
        ),
    )
    confident = st.checkbox(
        "Only pockets meeting the imported local confidence rule",
        value=False,
        help=field_help(term="Local pocket confidence"),
    )
    quality_only = False
    if data.get("quality_preparation"):
        quality_only = st.checkbox(
            "Only pockets passing the preparation/context quality screen",
            value=True,
            help=(
                "Requires local pocket confidence, assessed within-region PAE, "
                "complete residue mapping and no flagged cut-end or very-low-"
                "confidence proximity. This is a heuristic, not binding evidence."
            ),
        )
        st.caption(
            "These predictions use retained contiguous regions. Original ranks remain "
            "unchanged when the quality screen hides a pocket. See Input quality for "
            "the parent models, sequence coordinates and rejected regions."
        )
    pockets = ranked_pockets(
        pockets=[
            row
            for row in data["pockets"]
            if row["method"] == method
            and (selected == "All models" or row["sample_id"] == selected)
            and (not quality_only or row.get("quality_screen_pass") is True)
            and (
                not confident
                or row.get("confidence_status") == "meets_local_confidence_rule"
            )
        ]
    )
    columns = [
        "sample_id",
        "review_rank",
        "rank",
        "pocket_id",
        "score",
        "druggability_score",
        "p2rank_rescore_score",
        "probability",
        "volume_a3",
        "mean_plddt",
        "confidence_status",
    ]
    columns = [
        key for key in columns if any(row.get(key) is not None for row in pockets)
    ]
    if data.get("quality_preparation"):
        columns.extend(
            [
                "quality_screen_pass",
                "near_cut_boundary",
                "cut_boundary_distance_a",
                "near_very_low_confidence",
                "uncertain_context_distance_a",
            ]
        )
    if selected != "All models":
        model = next(row for row in data["models"] if row["sample_id"] == selected)
        st.caption(f"Full model identifier: {selected}")
        if model.get("mean_plddt") is not None and model["mean_plddt"] < 50:
            st.warning(
                f"Mean model pLDDT is {model['mean_plddt']:.1f}. Much of this input "
                "may be uncertain. Inspect each pocket's local confidence and the "
                "scope/coverage of any structural fit before interpreting its position."
            )
        if model.get("prepared_model"):
            st.subheader("3D model and predicted pockets")
            metadata = model_viewer_records(
                root=root,
                model=model,
                pockets=pockets,
            )
            metadata["initial_method"] = method
            document = structure_document(
                reference_pdb=inside(
                    root=root, relative=model["prepared_model"]
                ).read_text(),
                reference_label=selected,
                reference_metadata=metadata,
                summary=(
                    "Pocket colours follow original within-model review ranks. "
                    "Display trimming changes this view only. Use precomputed "
                    "structure comparisons for pocket-position evidence."
                ),
            )
            st.iframe(
                document,
                height="content",
                width="stretch",
                alt="Interactive model, ranked pockets and residue confidence controls",
            )
            st.download_button(
                "Download offline model pocket page",
                document,
                file_name=selected + "_pockets.html",
                mime="text/html",
            )
            external_jump(key="model_external_tools", first="model:" + selected)
    st.subheader("Ranked pocket evidence")
    show_table(
        rows=[{key: row.get(key) for key in columns} for row in pockets],
        key="pockets",
        glossary_term="Review rank",
    )
    st.caption(
        "Rows follow original within-model ranks. Full identifiers and numeric values"
        " remain in the downloads."
    )
    with st.expander("Complete pocket records and residue memberships"):
        show_table(rows=pockets, key="pocket_raw", readable_ids=False)
    with st.expander("Model checks and FASTA mapping"):
        show_table(
            rows=[
                {
                    key: row.get(key)
                    for key in (
                        "sample_id",
                        "parent_sample_id",
                        "input_scope",
                        "region_name",
                        "original_start",
                        "original_end",
                        "group_id",
                        "sequence_id",
                        "mapping_status",
                        "status",
                        "mean_plddt",
                        "fraction_ge_threshold",
                        "residue_count",
                        "warnings",
                    )
                }
                for row in data["models"]
            ],
            key="model_checks",
        )
    if selected != "All models":
        model = next(row for row in data["models"] if row["sample_id"] == selected)
        if model.get("prepared_model"):
            path = inside(root=root, relative=model["prepared_model"])
            st.download_button(
                "Download prepared PDB", path.read_bytes(), file_name=selected + ".pdb"
            )
            residues = json.loads(
                inside(root=root, relative=model["coordinates"]).read_text()
            )
            figure = px.line(
                x=[
                    row.get("sequence_position") or row["model_position"]
                    for row in residues
                ],
                y=[row.get("plddt") for row in residues],
                labels={"x": "Sequence/model position", "y": "Residue pLDDT"},
                title="Local structure confidence",
            )
            figure.update_yaxes(range=[0, 100])
            st.plotly_chart(figure, width="stretch")
            st.download_button(
                "Download original-residue map TSV",
                tsv_bytes(rows=residues),
                file_name=selected + "_residue_map.tsv",
            )
    if analysis_enabled():
        with st.expander("Predict pockets for a new model project"):
            st.markdown(
                "Runs the original fpocket, independent P2Rank and fpocket-rescoring"
                " workflow as a background job. A new prediction run is retained inside"
                " this project. Existing comparisons must be recalculated for the new"
                " pocket set."
            )
            with st.form("prediction"):
                fpocket = st.text_input(
                    "fpocket executable",
                    value=os.getenv("POCKET_WORKBENCH_FPOCKET", "fpocket"),
                )
                p2rank = st.text_input(
                    "P2Rank 2.5.1 prank executable",
                    value=os.getenv("POCKET_WORKBENCH_P2RANK", "prank"),
                )
                threads = st.number_input(
                    "Prediction threads",
                    min_value=1,
                    max_value=128,
                    value=min(4, available_cpus()),
                )
                timeout = st.number_input(
                    "Per-command timeout (seconds)",
                    min_value=1,
                    max_value=86400,
                    value=3600,
                )
                predict = st.form_submit_button("Start pocket prediction")
            if predict:
                try:
                    identifier = start_job(
                        root=root,
                        task="predict",
                        options={
                            "fpocket": fpocket,
                            "p2rank": p2rank,
                            "threads": threads,
                            "timeout": timeout,
                        },
                    )
                    st.success(f"Started {identifier}. Follow it on Jobs.")
                except (ValueError, OSError) as error:
                    st.error(str(error))


def comparison_page(*, root: Path, data: dict) -> None:
    """Configure batch fits and browse spatial pocket evidence and 3D overlays.

    Args:
        root: Resource directory.
        data: Loaded project.
    """
    st.header("Compare structures and pocket positions")
    st.markdown(
        "Inspect the saved structural superpositions and choose pocket pairs to "
        "visualise. Fit scope, tool, coverage and pocket evidence remain visible."
    )
    batch_notice()
    models = [row["sample_id"] for row in data["models"] if row.get("coordinates")]
    if len(models) < 2:
        st.info(
            "Add coordinates for at least two models in Start / import to enable"
            " comparisons."
        )
        return
    if analysis_enabled():
        with st.expander("Configure new comparisons on this server"):
            with st.form("comparisons"):
                reference = st.selectbox(
                    "Reference model",
                    models,
                    help=field_help(term="Reference / mobile"),
                )
                mobile = st.multiselect(
                    "Models to compare",
                    models,
                    default=[name for name in models if name != reference][:1],
                    help="The reference itself is excluded from pair generation.",
                )
                all_pairs = st.checkbox(
                    "Compare all pairs among the selected models and reference",
                    help=(
                        "Off: each selected model is compared to the reference. On:"
                        " every unique pair in the selection is assessed."
                    ),
                )
                a, b, c = st.columns(3)
                engine = a.selectbox(
                    "Superposition method",
                    ["auto", "usalign", "sequence_kabsch"],
                    help=(
                        "Auto uses installed USalign; otherwise the sequence-guided"
                        " Kabsch fit is explicitly labelled and has no TM-score."
                    ),
                )
                plddt = b.number_input(
                    "Minimum fit residue pLDDT",
                    min_value=0.0,
                    max_value=100.0,
                    value=70.0,
                    help=field_help(term="Confidence selection"),
                )
                minimum = c.number_input(
                    "Minimum fitted CA atoms",
                    min_value=3,
                    max_value=10000,
                    value=12,
                    help=field_help(term="Coverage"),
                )
                domain = st.checkbox(
                    "Fit a reference sequence region", help=field_help(term="Domain")
                )
                a, b = st.columns(2)
                start = a.number_input(
                    "Reference start (inclusive)", min_value=1, value=1
                )
                end = b.number_input(
                    "Reference end (inclusive)", min_value=1, value=100
                )
                with st.expander("Pocket selection and matching thresholds"):
                    top = st.number_input(
                        "Maximum pockets per model after filtering",
                        min_value=1,
                        max_value=100,
                        value=10,
                    )
                    confident = st.checkbox(
                        "Require locally confident pockets",
                        value=True,
                        help=field_help(term="Local pocket confidence"),
                    )
                    radius = st.number_input(
                        "Residue neighbour distance (Å)",
                        min_value=0.1,
                        value=4.0,
                        help=field_help(term="Symmetric overlap"),
                    )
                    centroid = st.number_input(
                        "Maximum centroid distance (Å)",
                        min_value=0.1,
                        value=8.0,
                        help=field_help(term="Centroid distance"),
                    )
                    overlap = st.slider(
                        "Minimum symmetric overlap",
                        0.0,
                        1.0,
                        0.5,
                        help=field_help(term="Symmetric overlap"),
                    )
                    tm = st.slider(
                        "Minimum TM-score in the compared region",
                        0.0,
                        1.0,
                        0.5,
                        help=field_help(term="Fold support"),
                    )
                    usalign = st.text_input(
                        "USalign executable",
                        value=os.getenv("POCKET_WORKBENCH_USALIGN", "USalign"),
                    )
                submitted = st.form_submit_button(
                    "Start structure comparisons", type="primary"
                )
            if submitted:
                try:
                    selected = [name for name in mobile if name != reference]
                    if domain and all_pairs:
                        raise WorkbenchError(
                            "Use reference-against-selected mode for a reference domain"
                            " range"
                        )
                    pairs = (
                        list(itertools.combinations([reference] + selected, 2))
                        if all_pairs
                        else [(reference, name) for name in selected]
                    )
                    if not pairs or len(pairs) > 2000:
                        raise WorkbenchError("Choose 1–2,000 structure pairs")
                    settings = ComparisonSettings(
                        engine=engine,
                        min_plddt=plddt,
                        min_atoms=minimum,
                        top_pockets=top,
                        confident_only=confident,
                        radius=radius,
                        max_centroid=centroid,
                        min_overlap=overlap,
                        min_tm=tm,
                        start=start if domain else None,
                        end=end if domain else None,
                    )
                    identifier = start_job(
                        root=root,
                        task="compare",
                        options={
                            "pairs": pairs,
                            "settings": asdict(settings),
                            "usalign": usalign,
                        },
                    )
                    st.success(
                        f"Started {identifier}. Follow it on Jobs, then reload the"
                        " project."
                    )
                except (ValueError, OSError) as error:
                    st.error(str(error))
    completed = data["comparisons"]
    if not completed:
        st.info("This resource has no saved structural comparisons yet.")
        return
    labels = model_labels(identifiers=[m["sample_id"] for m in data["models"]])
    fits = query_table(root=root, table="structure_alignments")
    model_by_id = {m["sample_id"]: m for m in data["models"]}
    for fit in fits:
        if all(
            model_by_id.get(fit[k], {}).get("input_scope") == "cleaned_region"
            for k in ("reference", "mobile")
        ):
            fit["scope"] = "cleaned_region"
    fit_by_id = {r["comparison_id"]: r for r in fits}
    pending = st.session_state.pop("requested_comparison", None)
    if pending:
        for index, saved in enumerate(completed):
            if saved["comparison_id"] == pending:
                st.session_state["comparison_reference"] = saved["reference"]
                st.session_state["comparison_mobile"] = saved["mobile"]
                st.session_state["comparison_analysis"] = index
                break
    references = sorted({r["reference"] for r in completed})
    if st.session_state.get("comparison_reference") not in references:
        st.session_state["comparison_reference"] = references[0]
    left, right = st.columns(2)
    reference = left.selectbox(
        "Reference model in saved fit",
        references,
        format_func=lambda name: labels.get(name, name),
        key="comparison_reference",
        help=(
            "Uses the orientation already saved by the aligner. No new fitting is run."
        ),
    )
    mobiles = sorted({r["mobile"] for r in completed if r["reference"] == reference})
    if st.session_state.get("comparison_mobile") not in mobiles:
        st.session_state["comparison_mobile"] = mobiles[0]
    mobile = right.selectbox(
        "Compared model",
        mobiles,
        format_func=lambda name: labels.get(name, name),
        key="comparison_mobile",
    )
    candidates = [
        i
        for i, r in enumerate(completed)
        if r["reference"] == reference and r["mobile"] == mobile
    ]
    if st.session_state.get("comparison_analysis") not in candidates:
        st.session_state["comparison_analysis"] = candidates[0]
    choice = st.selectbox(
        "Saved analysis",
        candidates,
        format_func=lambda i: analysis_label(
            engine=completed[i].get("engine", "unreported"),
            settings=fit_by_id.get(completed[i]["comparison_id"], {}).get(
                "settings", {}
            ),
            scope=fit_by_id.get(completed[i]["comparison_id"], {}).get("scope", ""),
        )
        + " · "
        + completed[i]["status"],
        key="comparison_analysis",
    )
    st.caption(f"Saved orientation: {reference} ← {mobile}")
    with st.expander("Similarity matrix and all saved fits", expanded=False):
        valid = [row for row in fits if row["status"] == "complete"]
        if valid:
            scopes = list(
                dict.fromkeys(
                    (r["engine"], r["settings"], r.get("scope", "")) for r in valid
                )
            )
            selected_scope = st.selectbox(
                "Settings for this matrix",
                range(len(scopes)),
                format_func=lambda i: analysis_label(
                    engine=scopes[i][0], settings=scopes[i][1], scope=scopes[i][2]
                ),
                help="One complete saved analysis scope is shown at a time.",
            )
            selected_fits = [
                r
                for r in valid
                if (r["engine"], r["settings"], r.get("scope", ""))
                == scopes[selected_scope]
            ]
            metrics = ["RMSD"]
            if any(
                r.get("tm_reference") is not None and r.get("tm_mobile") is not None
                for r in selected_fits
            ):
                metrics.insert(0, "Minimum TM-score")
            metric = st.radio("Matrix metric", metrics, horizontal=True)
            st.plotly_chart(
                similarity_figure(fits=selected_fits, metric=metric), width="stretch"
            )
            st.caption(
                "Rows are reference models; columns are compared models. Blank cells"
                " have no saved value. Full identifiers are shown on hover."
                " TM-scores refer to each fit's input region; RMSD also depends on"
                " aligned length."
            )
        with st.expander("Saved fit table"):
            columns = [
                "reference",
                "mobile",
                "engine",
                "status",
                "rmsd",
                "aligned_atoms",
                "reference_coverage",
                "mobile_coverage",
                "tm_reference",
                "tm_mobile",
            ]
            show_table(
                rows=[{k: r.get(k) for k in columns} for r in fits],
                key="structure_overview",
                glossary_term="Coverage",
            )
    result = json.loads(
        inside(root=root, relative=completed[choice]["result_path"]).read_text()
    )
    if result["status"] != "complete":
        st.error(result.get("error", "Comparison failed; inspect Jobs."))
        return
    a, b, c, d = st.columns(4)
    a.metric("RMSD (Å)", f"{result['rmsd']:.3f}", help=field_help(term="RMSD"))
    b.metric("Aligned CA atoms", result["aligned_atoms"])
    c.metric(
        "Minimum TM-score",
        (
            f"{min(result['tm_reference'], result['tm_mobile']):.3f}"
            if result.get("tm_reference") is not None
            else "Unavailable"
        ),
        help=field_help(term="TM-score"),
    )
    d.metric(
        "Lower input CA coverage",
        f"{min(result['reference_coverage'], result['mobile_coverage']):.1%}",
        help=(
            "The smaller fraction of input residues included in the structural"
            " alignment. For a region fit the denominator is that region."
        ),
    )
    st.caption(
        f"Method: {result['engine']}; scope: {result['scope']}. Input-model CA"
        f" coverage: reference {result['reference_coverage']:.1%}, mobile"
        f" {result['mobile_coverage']:.1%}."
    )
    if (
        result.get("tm_reference") is not None
        and result.get("tm_mobile") is not None
        and min(result["tm_reference"], result["tm_mobile"])
        < result.get("settings", {}).get("min_tm", 0.5)
    ):
        st.warning(
            "This fit does not meet its saved fold-support threshold. Inspect its"
            " aligned coverage and the input confidence before interpreting a nearby"
            " pocket as conserved."
        )
    ranks = {
        (p["sample_id"], p["pocket_id"]): pocket_rank(pocket=p)
        for p in data["pockets"]
        if p["method"] == "fpocket"
    }
    matches = sorted(
        result["pocket_matches"],
        key=lambda m: (
            not (
                ranks.get((result["reference"], m["reference_pocket"]))
                == ranks.get((result["mobile"], m["mobile_pocket"]))
                == 1
            ),
            -m.get("symmetric_overlap", 0),
            m.get("centroid_distance", float("inf")),
        ),
    )
    compact = [
        {
            key: row.get(key)
            for key in (
                "reference_pocket",
                "mobile_pocket",
                "centroid_distance",
                "symmetric_overlap",
                "mutual_match_fraction",
                "sequence_jaccard",
                "residue_identity_fraction",
                "chemical_group_conservation",
                "complete_mapping",
                "position_supported",
                "fold_supported",
            )
        }
        for row in matches
    ]
    with st.expander("Complete pocket-pair evidence and downloads"):
        show_table(
            rows=compact, key="pocket_matches", glossary_term="Position supported"
        )
    match = None
    requested_pair = st.session_state.pop("requested_pocket_pair", None)
    if st.session_state.get("comparison_pocket_context") != result["comparison_id"]:
        st.session_state["comparison_pocket_pair"] = 0
        st.session_state["comparison_pocket_context"] = result["comparison_id"]
    if matches:
        if not any(
            ranks.get((result["reference"], m["reference_pocket"]))
            == ranks.get((result["mobile"], m["mobile_pocket"]))
            == 1
            for m in matches
        ):
            st.info(
                "The original rank-one pair is unavailable in this saved fit. Available"
                " alternatives retain their original ranks."
            )
        pair_labels = []
        for row in matches:
            ref_rank = ranks.get((result["reference"], row["reference_pocket"])) or "?"
            mob_rank = ranks.get((result["mobile"], row["mobile_pocket"])) or "?"
            pair_labels.append(
                f"Ref rank {ref_rank} (pocket {row['reference_pocket']}) / "
                f"compared rank {mob_rank} (pocket {row['mobile_pocket']}) · "
                f"overlap {row['symmetric_overlap']:.2f} · "
                f"{row['centroid_distance']:.2f} Å"
            )
        if requested_pair is not None:
            for pair_index, row in enumerate(matches):
                if (row["reference_pocket"], row["mobile_pocket"]) == requested_pair:
                    st.session_state["comparison_pocket_pair"] = pair_index
                    break
        if st.session_state.get("comparison_pocket_pair") not in range(len(matches)):
            st.session_state["comparison_pocket_pair"] = 0
        index = st.selectbox(
            "Pocket pair to inspect in 3D",
            range(len(matches)),
            format_func=lambda i: pair_labels[i],
            key="comparison_pocket_pair",
        )
        match = matches[index]
    else:
        st.info(
            "This saved fit contains no tested pocket pair. The structures can still be"
            " inspected; choosing an independent pocket for display does not create"
            " comparison evidence."
        )
    if st.button(
        "Pocket conservation and alignment quality", key="comparison_conservation"
    ):
        st.session_state["requested_conservation"] = {
            "comparison_id": result["comparison_id"],
            "pair": (
                (match["reference_pocket"], match["mobile_pocket"]) if match else None
            ),
        }
        st.session_state["pending_navigation"] = "Pocket conservation"
        st.rerun()
    reference_model = next(
        row for row in data["models"] if row["sample_id"] == result["reference"]
    )
    reference_pdb = inside(
        root=root, relative=reference_model["prepared_model"]
    ).read_text()
    mobile_pdb = inside(root=root, relative=result["mobile_aligned"]).read_text()
    mobile_model = next(
        row for row in data["models"] if row["sample_id"] == result["mobile"]
    )
    document = structure_document(
        reference_pdb=reference_pdb,
        mobile_pdb=mobile_pdb,
        reference_label=result["reference"],
        mobile_label=result["mobile"],
        match=match,
        reference_metadata=model_viewer_records(
            root=root, model=reference_model, pockets=data["pockets"]
        )
        | ({"initial_display": "none"} if not match else {}),
        mobile_metadata=model_viewer_records(
            root=root, model=mobile_model, pockets=data["pockets"]
        )
        | ({"initial_display": "none"} if not match else {}),
        summary=(
            f"{result['engine']}; RMSD {result['rmsd']:.3f} Å over"
            f" {result['aligned_atoms']} CA atoms. Pocket overlap uses lining CA"
            " proximity. Original residue labels are in the downloadable residue map."
        ),
    )
    st.iframe(
        document,
        height="content",
        width="stretch",
        alt="Saved structural superposition with independently selectable pockets",
    )
    if match and match.get("residue_correspondences"):
        with st.expander(
            "Matched pocket residues: geometry, identity and chemical groups"
        ):
            show_table(rows=match["residue_correspondences"], key="matched_residues")
    a, b, c = st.columns(3)
    a.download_button(
        "Download offline 3D page",
        document,
        file_name=result["comparison_id"] + ".html",
        mime="text/html",
    )
    b.download_button(
        "Download aligned mobile PDB",
        mobile_pdb,
        file_name=result["mobile"] + "_aligned.pdb",
    )
    c.download_button(
        "Download complete fit JSON",
        json.dumps(result, indent=2),
        file_name=result["comparison_id"] + ".json",
    )
    with st.expander("Use another structure viewer"):
        external_jump(
            key="comparison_external_tools",
            first="model:" + result["reference"],
            second="model:" + result["mobile"],
            comparison=result["comparison_id"],
        )
        st.link_button(
            "Open Mol* for local-file viewing", "https://molstar.org/viewer/"
        )
        st.markdown(
            "Download the prepared reference and aligned mobile PDBs to load them"
            " together. The built-in 3Dmol viewer uses the local files directly and"
            " includes no external protein-data requests."
        )


def sequence_page(*, root: Path, data: dict, workspace: Path) -> None:
    """Configure representative sequence alignments and inspect linked phylogenies.

    Args:
        root: Resource directory.
        data: Loaded project.
        workspace: User's import parent.
    """
    st.header("Sequence alignment and trees")
    external_jump(
        key="sequence_external_tools", label="External links and exact sequence inputs"
    )
    st.markdown(
        "Select representative FASTA records rather than individual prediction"
        " replicates. FAMSA runs locally; MAFFT is available when installed. The"
        " inferred tree is an exploratory, unrooted neighbour-joining tree with"
        " recorded filtering and optional bootstrap support."
    )
    batch_notice()
    if not data["sequences"]:
        st.info(
            "Add a representative FASTA or model coordinates through Start / import to"
            " enable sequence analysis."
        )
        return
    if analysis_enabled():
        with st.expander("Configure a new alignment on this server"):
            with st.form("sequence_analysis"):
                selected = st.multiselect(
                    "Representative sequences",
                    list(data["sequences"]),
                    default=list(data["sequences"])[:200],
                    help=field_help(term="Model replicate"),
                )
                engine = st.selectbox(
                    "Alignment method",
                    ["famsa", "mafft"],
                    help=field_help(term="FAMSA"),
                )
                a, b, c = st.columns(3)
                max_gap = a.slider(
                    "Maximum non-canonical fraction per tree column",
                    0.0,
                    0.95,
                    0.5,
                    help=(
                        "Columns with more gaps or ambiguous amino acids are excluded"
                        " from tree inference. The displayed alignment remains"
                        " complete."
                    ),
                )
                bootstrap = b.number_input(
                    "Bootstrap replicates",
                    min_value=0,
                    max_value=200,
                    value=0,
                    help=field_help(term="Bootstrap support"),
                )
                seed = c.number_input("Bootstrap seed", min_value=0, value=42)
                threads = st.number_input(
                    "Alignment threads",
                    min_value=1,
                    max_value=128,
                    value=min(4, available_cpus()),
                )
                with st.expander("Import an existing alignment or tree"):
                    aligned = st.file_uploader(
                        "Aligned protein FASTA",
                        type=["fasta", "fa", "faa", "aln"],
                        help=(
                            "Rows must preserve exactly the selected ungapped"
                            " sequences."
                        ),
                    )
                    newick = st.file_uploader(
                        "Matching Newick tree",
                        type=["nwk", "newick", "tree", "tre"],
                        help=field_help(term="Newick"),
                    )
                submit = st.form_submit_button(
                    "Start alignment and tree analysis", type="primary"
                )
            if submit:
                try:
                    incoming = workspace / "incoming" / uuid.uuid4().hex
                    options = {
                        "sequence_ids": selected,
                        "engine": engine,
                        "max_gap": max_gap,
                        "bootstrap": bootstrap,
                        "seed": seed,
                        "threads": threads,
                    }
                    if aligned:
                        options["aligned_fasta"] = str(
                            upload_file(uploaded=aligned, directory=incoming)
                        )
                    if newick:
                        options["newick"] = str(
                            upload_file(uploaded=newick, directory=incoming / "tree")
                        )
                    if not selected:
                        raise WorkbenchError(
                            "Select at least one representative sequence"
                        )
                    identifier = start_job(root=root, task="sequences", options=options)
                    st.success(
                        f"Started {identifier}. Review Jobs, then reload the project."
                    )
                except (ValueError, OSError) as error:
                    st.error(str(error))
    if not data["sequence_analyses"]:
        return
    analyses = data["sequence_analyses"]
    index = st.selectbox(
        "Completed alignment",
        range(len(analyses)),
        format_func=lambda i: analyses[i]["analysis_id"],
        index=len(analyses) - 1,
    )
    analysis = analyses[index]
    msa = inside(root=root, relative=analysis["alignment_path"]).read_text()
    tree = (
        inside(root=root, relative=analysis["tree_path"]).read_text()
        if analysis.get("tree_path")
        else ""
    )
    st.caption(
        f"{analysis['alignment_method']} · {analysis['sequence_count']} records ·"
        f" {analysis['alignment_length']} columns. Tree: {analysis['tree_method']}."
    )
    viewer = st.radio(
        "Sequence viewer",
        [
            "Pocket-annotated FASTA",
            "Alignment and tree (JBrowse MSA)",
            "Alignment Viewer 2",
        ],
        horizontal=True,
    )
    if viewer == "Pocket-annotated FASTA":
        payload = pocket_alignment_data(
            root=root,
            data=data,
            aligned_records=read_fasta(
                path=inside(root=root, relative=analysis["alignment_path"]),
                aligned=True,
            ),
        )
        document = pocket_alignment_document(payload=payload)
        st.download_button(
            "Download all prepared pocket annotation rows (TSV)",
            tsv_bytes(rows=payload["annotations"]),
            file_name=analysis["analysis_id"] + "_pocket_annotations.tsv",
        )
        st.caption(
            "Pocket tracks include original review ranks 1–10. This download contains"
            " all prepared tracks, regardless of the viewer's display filters."
        )
    else:
        document = alignment_document(
            msa=msa,
            tree=tree,
            viewer=(
                "jbrowse" if viewer.startswith("Alignment and tree") else "alignment"
            ),
        )
    st.iframe(
        document,
        height="content",
        width="stretch",
        alt="Protein sequence alignment, pocket residue tracks or phylogenetic tree",
    )
    a, b, c = st.columns(3)
    a.download_button(
        "Download aligned FASTA", msa, file_name=analysis["analysis_id"] + ".fasta"
    )
    b.download_button(
        "Download offline alignment page",
        document,
        file_name=analysis["analysis_id"] + ".html",
        mime="text/html",
    )
    if tree:
        c.download_button(
            "Download Newick tree", tree, file_name=analysis["analysis_id"] + ".newick"
        )
    aligned_records = read_fasta(
        path=inside(root=root, relative=analysis["alignment_path"]), aligned=True
    )
    mapped_models = [
        row
        for row in data["models"]
        if row.get("coordinates")
        and row.get("sequence_id") in aligned_records
        and row.get("mapping_status")
        not in {"no_exact_fasta_match", "ambiguous_identical_fasta_records"}
    ]
    if mapped_models:
        with st.expander("Locate pocket residues in this alignment"):
            model_id = st.selectbox(
                "Model for the alignment residue map",
                [row["sample_id"] for row in mapped_models],
            )
            model = next(row for row in mapped_models if row["sample_id"] == model_id)
            choices = [
                row
                for row in data["pockets"]
                if row["sample_id"] == model_id and row["method"] == "fpocket"
            ]
            if choices:
                pocket_index = st.selectbox(
                    "Pocket for alignment mapping",
                    range(len(choices)),
                    format_func=lambda i: f"Pocket {choices[i]['pocket_id']}",
                )
                keys = set(choices[pocket_index]["residues"])
                columns = sequence_position_columns(
                    aligned=aligned_records[model["sequence_id"]]
                )
                residues = json.loads(
                    inside(root=root, relative=model["coordinates"]).read_text()
                )
                show_table(
                    rows=[
                        dict(
                            row,
                            alignment_column=columns.get(row.get("sequence_position")),
                        )
                        for row in residues
                        if row["residue_key"] in keys
                    ],
                    key="alignment_residue_map",
                )


@st.fragment(run_every="5s")
def jobs_page(*, root: Path) -> None:
    """Poll persisted statuses without tying worker life to a browser connection.

    Args:
        root: Resource directory.
    """
    st.header("Jobs and logs")
    info = execution_info(root=root)
    st.info(
        f"App host: {info['hostname']} · "
        + (
            "analysis workers enabled here"
            if analysis_enabled()
            else "browsing prepared results"
        )
        + ". This app does not submit jobs to another machine."
    )
    with st.expander("Execution environment and tool availability", expanded=True):
        st.json(info)
    build_status = root / "provenance" / "build_status.json"
    if build_status.is_file():
        with st.expander("Recorded HPC build"):
            st.json(json.loads(build_status.read_text()))
    st.caption(
        "Workers continue independently of browser refreshes. This page refreshes every"
        " five seconds while open."
    )
    files = sorted((root / "jobs").glob("*/status.json"), reverse=True)
    if not files:
        st.info("No background jobs have been started for this project.")
        return
    for path in files:
        status = json.loads(path.read_text())
        with st.expander(
            f"{status['job_id']} · {status['task']} · {status['status']}",
            expanded=status["status"] in {"running", "queued", "failed"},
        ):
            st.json(status)
            log = path.parent / "worker.log"
            if log.is_file():
                with log.open("rb") as handle:
                    handle.seek(max(0, log.stat().st_size - 15000))
                    text = handle.read().decode(errors="replace")
                st.code(text or "Waiting for worker output…")


@st.cache_data(show_spinner=False, max_entries=16)
def cached_audit(root_string: str, revision: int, top_k: int) -> list[dict]:
    """Cache immutable revision-scoped evidence summaries.

    Args:
        root_string: Exact resource path.
        revision: Cache invalidation revision from project.json.
        top_k: Original member-pocket rank cutoff.

    Returns:
        Rank-preserving comparison audit.
    """
    root = Path(root_string)
    return comparison_audit(root=root, data=load_project(root=root), top_k=top_k)


def evidence_page(*, root: Path, data: dict) -> None:
    """Show E3-style strict/sensitivity evidence without species-specific gates.

    Args:
        root: Prepared project directory.
        data: Loaded native evidence.
    """
    st.header("Structural evidence and top-k review")
    st.markdown(
        "Rank-one pocket results remain separate from alternative-pocket sensitivity."
        " Each row records its aligner and fit scope; unassessed evidence stays"
        " explicit."
    )
    top_k = st.select_slider(
        "Member-pocket sensitivity rank limit",
        options=[1, 3, 5, 10],
        value=5,
        help=(
            "Reference rank one is fixed. Alternative member pockets up to this "
            "original within-model rank are inspected without replacing rank one."
        ),
    )
    rows = cached_audit(str(root), data.get("revision", 0), top_k)
    if not rows:
        st.info("Load a resource with precomputed structural comparisons.")
        return
    scopes = list(dict.fromkeys((r["engine"], r["settings"], r["scope"]) for r in rows))
    selected = st.selectbox(
        "Evidence map scope",
        range(len(scopes)),
        format_func=lambda i: analysis_label(
            engine=scopes[i][0], settings=scopes[i][1], scope=scopes[i][2]
        ),
        help=(
            "Plots, counts and the summary table below use this same saved analysis"
            " scope."
        ),
    )
    engine, settings, scope = scopes[selected]
    scoped = [
        r
        for r in rows
        if (r["engine"], r["settings"], r["scope"]) == (engine, settings, scope)
    ]
    a, b, c, d = st.columns(4)
    a.metric("Fits in selected scope", len(scoped))
    b.metric(
        "Rank-one position + fold",
        sum(r["rank_one_position_and_fold"] is True for r in scoped),
    )
    c.metric(
        "Rank-one position unassessed",
        sum(r["rank_one_position"] == "not_assessed" for r in scoped),
    )
    d.metric(
        "Top-k position support",
        sum(r["top_k_position"] == "supported" for r in scoped),
        help=(
            "Number of saved fits with any position-supported tested member pocket"
            " among original ranks 1 through k. This includes member rank one."
        ),
    )
    st.caption(
        f"This dataset contains {len(rows):,} saved fits across"
        f" {len({(r['reference'],r['mobile']) for r in rows}):,} model pairs. Counts"
        " above use the selected scope only. No support under a threshold is not"
        " experimental evidence of no binding."
    )
    view = st.radio(
        "Pocket evidence to plot",
        ["Original rank-one pair", "Best tested member pocket"],
        horizontal=True,
        help=(
            "The second view keeps reference rank one fixed and tests member ranks 1"
            " through the selected limit. It does not replace the rank-one conclusion."
        ),
    )
    figure, omitted = evidence_figure(
        rows=scoped,
        view="rank_one" if view == "Original rank-one pair" else "alternatives",
    )
    if omitted < len(scoped):
        st.plotly_chart(figure, width="stretch")
    else:
        st.info(
            "No fits in this scope have both the required TM-score and pocket overlap"
            " for this plot. Sequence-guided Kabsch does not report a TM-score."
            " Inspect saved pocket-position evidence in the table or 3D view, or"
            " choose another available saved analysis scope."
        )
    st.caption(
        f"{omitted:,} fits omitted from the plot because a required TM-score or pocket"
        " overlap is unavailable. The overlap threshold alone is insufficient:"
        " centroid distance and complete mapping also affect the position rule."
    )
    if view == "Best tested member pocket":
        st.caption(
            "The plotted pair has the highest overlap. It can fail another position"
            " rule even when a different tested pocket passes; the top-k card counts"
            " any passing pair."
        )
    with st.expander("How to read strict and sensitivity evidence", expanded=True):
        st.markdown(
            "**Rank-one position** tests the two original rank-one cavities. "
            "**Position + fold** also requires the saved TM-score threshold. "
            "**Not assessed** means the requested pair was absent or excluded by "
            "the saved filters. **Best tested member pocket** shows the highest "
            "overlap among original member ranks 1 through the selected limit, "
            "with reference rank one fixed. Point colour describes that plotted "
            "pocket pair. The vertical line marks the fold threshold; the horizontal "
            "line marks the overlap threshold. A supported alternative does not "
            "change the original rank-one result."
        )
    summary_columns = [
        "reference",
        "mobile",
        "rank_one_position",
        "rank_one_position_and_fold",
        "rank_one_conserved",
        "minimum_tm",
        "rank_one_overlap",
        "best_tested_overlap",
        "best_tested_member_rank",
        "best_tested_mobile_pocket",
        "top_k_position",
        "reference_coverage",
        "mobile_coverage",
    ]
    show_table(
        rows=[{k: r.get(k) for k in summary_columns} for r in scoped],
        key="structural_audit",
        glossary_term="Fold support",
    )
    labels = model_labels(
        identifiers=[r[k] for r in scoped for k in ("reference", "mobile")]
    )
    selected_fit = st.selectbox(
        "Saved fit to open in 3D",
        range(len(scoped)),
        format_func=lambda i: (
            labels[scoped[i]["reference"]] + " ← " + labels[scoped[i]["mobile"]]
        ),
    )
    if st.button("Open this fit in Compare structures", key="evidence_open_fit"):
        st.session_state["requested_comparison"] = scoped[selected_fit]["comparison_id"]
        st.session_state["pending_navigation"] = "Compare structures"
        st.rerun()
    if st.button("Open conservation detail", key="evidence_conservation"):
        st.session_state["requested_conservation"] = {
            "comparison_id": scoped[selected_fit]["comparison_id"],
            "pair": None,
        }
        st.session_state["pending_navigation"] = "Pocket conservation"
        st.rerun()
    with st.expander("Complete audit records and settings"):
        show_table(rows=scoped, key="structural_audit_raw", readable_ids=False)
    with st.expander(
        "USalign / TMalign agreement on the same member pocket", expanded=False
    ):
        agreement = aligner_agreement(rows=rows)
        st.caption(
            "Agreement requires both tools and the same member pocket. Missing tool"
            " evidence remains not assessed."
        )
        show_table(
            rows=[
                {
                    k: r.get(k)
                    for k in (
                        "reference",
                        "mobile",
                        "available_aligners",
                        "rank_one_both_aligners",
                        "rank_one_conserved_both_aligners",
                        "top_k_same_member_pockets",
                        "top_k_both_aligners",
                    )
                }
                for r in agreement
            ],
            key="aligner_agreement",
        )


def group_page(*, root: Path, data: dict) -> None:
    """Browse HOG/generic group models and prepare manual external-viewer uploads.

    Args:
        root: Native project directory.
        data: Loaded project evidence.
    """
    st.header("HOG and model group comparison")
    st.markdown(
        "Select a supplied HOG or model group, inspect its members and open saved "
        "comparisons. The external Inspector hand-off uses your existing local models."
    )
    groups = sorted(
        {m.get("hog_id") or m.get("group_id") or "Ungrouped" for m in data["models"]}
    )
    selected = st.selectbox("HOG or model group", groups)
    members = [
        m
        for m in data["models"]
        if (m.get("hog_id") or m.get("group_id") or "Ungrouped") == selected
    ]
    labels = model_labels(identifiers=[m["sample_id"] for m in members])
    a, b = st.columns(2)
    a.metric("Models in this group", len(members))
    b.metric(
        "Mapped representative sequences",
        len({m.get("sequence_id") for m in members if m.get("sequence_id")}),
    )
    if not any(m.get("hog_id") for m in members):
        st.info(
            "This is a supplied model group. No explicit HOG membership was provided."
            " Replicates remain separate models."
        )
    st.caption(
        "HOG membership is used only when supplied explicitly. Generic group_id "
        "values do not establish orthology. An optional mapping TSV can provide "
        "hog_id, group_id, source_accession and source_url."
    )
    member_columns = [
        "sample_id",
        "sequence_id",
        "residue_count",
        "mean_plddt",
        "mapping_status",
    ]
    member_columns += [
        k
        for k in (
            "hog_id",
            "parent_sample_id",
            "original_start",
            "original_end",
            "source_accession",
            "source_url",
        )
        if any(m.get(k) not in (None, "") for m in members)
    ]
    show_table(
        rows=[{k: m.get(k) for k in member_columns} for m in members],
        key="group_members",
    )
    names = {m["sample_id"] for m in members}
    comparisons = [
        row
        for row in data["comparisons"]
        if row["reference"] in names and row["mobile"] in names
    ]
    with st.expander("Precomputed comparisons in this group", expanded=True):
        group_fits = [
            r
            for r in query_table(root=root, table="structure_alignments")
            if r["reference"] in names and r["mobile"] in names
        ]
        show_table(
            rows=[
                {
                    k: r.get(k)
                    for k in (
                        "reference",
                        "mobile",
                        "engine",
                        "status",
                        "rmsd",
                        "aligned_atoms",
                        "tm_reference",
                        "tm_mobile",
                        "reference_coverage",
                        "mobile_coverage",
                    )
                }
                for r in group_fits
            ],
            key="group_comparisons",
        )
        if comparisons:
            fit_labels = [
                labels[r["reference"]]
                + " ← "
                + labels[r["mobile"]]
                + " · "
                + METHOD_LABELS.get(r.get("engine"), r.get("engine", "unreported"))
                for r in comparisons
            ]
            selected_fit = st.selectbox(
                "Group fit to inspect",
                range(len(comparisons)),
                format_func=lambda i: fit_labels[i],
            )
            if st.button("Open this fit in Compare structures", key="group_open_fit"):
                st.session_state["requested_comparison"] = comparisons[selected_fit][
                    "comparison_id"
                ]
                st.session_state["pending_navigation"] = "Compare structures"
                st.rerun()
    external_jump(key="group_external_tools", group=selected)
    st.subheader("Open the external model comparison source")
    st.link_button("Open AlphaFold 3 Multi-Model Inspector", AF3_INSPECTOR_URL)
    selected_models = st.multiselect(
        "Local models for manual Inspector upload",
        [m["sample_id"] for m in members],
        default=[m["sample_id"] for m in members if m.get("prepared_model")],
        format_func=lambda name: labels.get(name, name),
        help="Includes local prepared chains. No model download or alignment is run.",
    )
    fingerprint = (str(root), data.get("revision", 0), tuple(selected_models))
    if st.button("Prepare model ZIP for Inspector", disabled=not selected_models):
        st.session_state["inspector_bundle"] = {
            "fingerprint": fingerprint,
            "payload": inspector_bundle(
                root=root,
                models=[m for m in members if m["sample_id"] in selected_models],
            ),
        }
    stored = st.session_state.get("inspector_bundle", {})
    if stored.get("fingerprint") == fingerprint:
        st.download_button(
            "Download model ZIP for manual Inspector upload",
            stored["payload"],
            file_name="workbench_models_for_inspector.zip",
            mime="application/zip",
        )
    st.info(
        "Download the ZIP, open the external source and choose the ZIP there. "
        "Files are not uploaded automatically. The manifest maps Model indices "
        "to your identifiers. PAE and AF3-specific summary metrics are not supplied "
        "by this prepared-chain compatibility export."
    )
    links = [m for m in members if source_link(value=m.get("source_url", ""))]
    if links:
        record = st.selectbox(
            "Original model source record", links, format_func=lambda m: m["sample_id"]
        )
        st.link_button("Open original source", source_link(value=record["source_url"]))


def quality_page(*, root: Path, data: dict) -> None:
    """Show the saved HPC quality audit without launching any preparation.

    Args:
        root: Completed resource directory.
        data: Loaded project metadata.
    """
    st.header("Input quality and retained regions")
    summary = dataset_summary(data=data)
    a, b, c, d = st.columns(4)
    a.metric("Models", summary["models"])
    b.metric(
        "Median model mean pLDDT",
        (
            f"{summary['median_model_plddt']:.1f}"
            if summary["median_model_plddt"] is not None
            else "Unavailable"
        ),
    )
    c.metric("Locally confident cavities", summary["locally_confident_cavities"])
    d.metric("FASTA records without models", summary["fasta_only_sequences"])
    st.caption(
        "These summaries use the stored input and pocket confidence. A model-wide "
        "mean does not replace assessment of a local pocket or domain orientation."
    )
    records = [
        {
            key: m.get(key)
            for key in (
                "sample_id",
                "sequence_id",
                "residue_count",
                "mean_plddt",
                "fraction_ge_threshold",
                "mapping_status",
                "status",
                "warnings",
            )
        }
        for m in data["models"]
    ]
    available = [r for r in records if r["mean_plddt"] is not None]
    if available:
        confidence = px.histogram(
            pd.DataFrame(available),
            x="mean_plddt",
            nbins=15,
            labels={"mean_plddt": "Mean pLDDT of each input model"},
            title="Distribution of stored model confidence",
            color_discrete_sequence=["#0072B2"],
        )
        confidence.update_xaxes(range=[0, 100])
        confidence.update_layout(height=300, margin={"t": 45, "b": 40})
        st.plotly_chart(confidence, width="stretch")
    with st.expander("Model confidence and exact FASTA mapping", expanded=True):
        show_table(rows=records, key="input_model_confidence", glossary_term="pLDDT")
    if not data.get("quality_preparation"):
        st.info(
            "This resource contains imported input models and confidence annotations. "
            "A separate region-preparation audit was not supplied. The summaries above "
            "remain available; a completed quality-rerun resource also includes the "
            "retained/rejected region and cut-boundary audit here."
        )
        return
    st.markdown(
        "The HPC workflow retains contiguous confidence-supported candidates. "
        "Automatic selections are **not confirmed biological domains**. Original "
        "models and full-length results are preserved in their existing folders. "
        "Cut-end and uncertain-context checks use Cα distances as conservative proxies."
    )
    directory = inside(
        root=root, relative=data["quality_preparation"]["audit_directory"]
    )
    st.json(data["quality_preparation"]["settings"], expanded=False)
    for label, name in (
        ("Original model checks", "Model_QC"),
        ("Retained and rejected regions", "Region_decisions"),
        ("Excluded sequence ranges", "Excluded_ranges"),
        ("Comparison eligibility", "comparison_plan"),
    ):
        path = directory / f"{name}.tsv"
        if path.is_file():
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            with st.expander(label, expanded=name == "Model_QC"):
                show_table(rows=rows, key=name)
    workbook = directory / "quality_audit.xlsx"
    if workbook.is_file():
        st.download_button(
            "Download quality audit Excel",
            workbook.read_bytes(),
            file_name=workbook.name,
        )


def documentation_page() -> None:
    """Show searchable glossary, common questions and downloadable methods."""
    st.header("Methods, glossary and help")
    methods, glossary, questions = st.tabs(
        ["Methods", "Searchable glossary", "Common questions"]
    )
    with methods:
        text = methods_text()
        st.markdown(text)
        st.download_button(
            "Download methods", text, file_name="pocket_workbench_methods.md"
        )
    with glossary:
        show_table(rows=glossary_rows(), key="glossary")
    with questions:
        for title, explanation in [
            (
                "Where can I see whether the pockets align or are conserved?",
                (
                    "Open Pocket conservation, select a saved fit and pocket pair,"
                    " and read the separate position, fold and conservation cards."
                    " Threshold checks explain each result. Centroid and matched"
                    " residue distances sit beside RMSD, aligned CA count, both"
                    " TM-scores and both input coverages. Missing evidence stays"
                    " unassessed; an alternative does not replace rank one."
                ),
            ),
            (
                "How do I use the external viewers with these models?",
                (
                    "Open External links. Download exact local FASTA or saved atomic"
                    " models and matching pocket residue TSVs, then load them in the"
                    " destination viewer. Supported UniProt accessions provide"
                    " populated database links. Inspector ZIP preparation reuses"
                    " local models and can retain an existing saved alignment."
                ),
            ),
            (
                "How can I make a pocket stand out?",
                (
                    "Choose one pocket and use Focus pockets. The default muted local"
                    " protein context makes its bright lining surface easier to see."
                    " Expand Pocket appearance to adjust the surface, markers and"
                    " labels. For an aligned pair, toggle either model to inspect an"
                    " obscured site."
                ),
            ),
            (
                "Is the coloured surface the empty cavity?",
                (
                    "It follows atoms of the selected lining residues. It is not an"
                    " empty cavity volume or the geometric overlap used by the saved"
                    " comparison. Read Lining-atom surface and Symmetric overlap in"
                    " the glossary for those distinctions."
                ),
            ),
            (
                "Why does a pocket remain visible after filtering the protein?",
                (
                    "Context pLDDT and position filters hide background protein only."
                    " Selected lining remains available for inspection. Use Only"
                    " locally confident pockets to filter the pockets themselves."
                    " These display choices do not change predictions or fits."
                ),
            ),
            (
                "Why can I see tables but no structures?",
                (
                    "The HTML report embeds pocket tables but does not contain model"
                    " coordinates. Add the full results ZIP or matching original model"
                    " ZIPs using Start / import."
                ),
            ),
            (
                "Does rank 1 mean the same pocket in different models?",
                (
                    "No. Pocket IDs and ranks are within-model labels. Use a structural"
                    " fit and spatial comparison to assess corresponding positions."
                ),
            ),
            (
                "Which model is the best prediction?",
                (
                    "This app does not interpret _model_0 as the best prediction. It"
                    " preserves every prediction and its confidence; representative"
                    " sequence records are handled separately."
                ),
            ),
            (
                "Why does the fit fail with the default pLDDT threshold?",
                (
                    "The models may have too few mutually mapped high-confidence"
                    " residues in the selected region. Inspect local confidence, select"
                    " an appropriate domain and review the minimum atom requirement."
                ),
            ),
            (
                "Does this reproduce the whole E3 pipeline?",
                (
                    "It provides a generic comparison workflow using the same types of"
                    " geometric evidence. E3-specific orthology, species selection and"
                    " production ranking rules are not inferred for other projects."
                ),
            ),
            (
                "Can I use other structure and sequence viewers?",
                (
                    "Download the self-contained viewer pages, aligned FASTA, Newick"
                    " and superposed PDBs. The built-in third-party viewers run locally"
                    " without a CDN."
                ),
            ),
        ]:
            with st.expander(title):
                st.write(explanation)


def downloads_page(*, root: Path, data: dict, workspace: Path) -> None:
    """Expose typed database, table, workbook and complete resource downloads.

    Args:
        root: Resource directory.
        data: Loaded project.
        workspace: Export parent outside the resource.
    """
    st.header("Downloads and app integration")
    st.info(
        "The HPC build publishes a sibling review ZIP containing index.html, "
        "offline viewers, Excel, DuckDB and app_resource.zip. Copy that ZIP to "
        "share the finished results. Use the project ZIP below to reopen the "
        "current resource in another workbench installation."
    )
    db = root / "pocket_workbench.duckdb"
    st.download_button(
        "Download materialised DuckDB",
        db.read_bytes(),
        file_name="pocket_workbench.duckdb",
    )
    table = st.selectbox(
        "Database table",
        list(TABLES),
        help="The schema and example SQL are documented in docs/SCHEMA.md.",
    )
    show_table(rows=query_table(root=root, table=table), key="database_" + table)
    if st.button("Prepare combined Excel workbook"):
        tables = {
            name: query_table(root=root, table=name)
            for name in (
                "models",
                "pockets",
                "structure_alignments",
                "pocket_matches",
                "sequence_analyses",
            )
        }
        tables["Glossary"] = glossary_rows()
        st.session_state["combined_excel"] = workbook_bytes(
            tables=tables, notes=methods_text()
        )
    if "combined_excel" in st.session_state:
        st.download_button(
            "Download combined Excel workbook",
            st.session_state["combined_excel"],
            file_name="pocket_workbench.xlsx",
        )
    if st.button("Prepare complete project ZIP"):
        target = workspace / "exports" / (uuid.uuid4().hex + ".zip")
        pack_project(root=root, output=target)
        st.session_state["project_zip"] = str(target)
    if "project_zip" in st.session_state:
        path = Path(st.session_state["project_zip"])
        if path.stat().st_size <= 512 * 1024**2:
            st.download_button(
                "Download complete project ZIP",
                path.read_bytes(),
                file_name=root.name + ".zip",
            )
        else:
            st.info(
                "The prepared ZIP exceeds the browser download bound. Copy it from the"
                f" server: {path}"
            )
    with st.expander("Recorded input provenance"):
        st.json(data["provenance"])


def main() -> None:
    """Render the app with an explicit project, guided navigation and shared help."""
    st.set_page_config(
        page_title="Protein pocket workbench", page_icon="🧬", layout="wide"
    )
    style = package_files("pocket_workbench").joinpath("assets", "app.css").read_text()
    st.markdown("<style>" + style + "</style>", unsafe_allow_html=True)
    workspace = (
        Path(
            os.getenv(
                "POCKET_WORKBENCH_WORKSPACE",
                str(Path.home() / "protein_pocket_workbench_projects"),
            )
        )
        .expanduser()
        .resolve()
    )
    workspace.mkdir(parents=True, exist_ok=True)
    if "resource" not in st.session_state:
        st.session_state["resource"] = os.getenv("POCKET_WORKBENCH_RESOURCE", "")
    if "navigation_page" not in st.session_state:
        st.session_state["navigation_page"] = (
            "Models & pockets" if st.session_state["resource"] else "Start / import"
        )
    pending_navigation = st.session_state.pop("pending_navigation", None)
    if pending_navigation:
        st.session_state["navigation_page"] = pending_navigation
    with st.sidebar:
        st.title("Pocket workbench")
        st.caption("Sequence · structure · pocket evidence")
        st.caption(
            "Analysis controls enabled"
            if analysis_enabled()
            else "Browse prepared HPC results"
        )
        resource = st.text_input(
            "Open project directory",
            value=st.session_state["resource"],
            help=(
                "A prepared workbench resource containing project.json. Use Start /"
                " import for pipeline output folders and ZIPs."
            ),
        )
        if st.button("Open / reload project"):
            st.session_state["resource"] = resource
            st.session_state.pop("combined_excel", None)
            st.session_state.pop("project_zip", None)
            st.rerun()
        page = st.radio(
            "Go to",
            [
                "Start / import",
                "Models & pockets",
                "Input quality",
                "Compare structures",
                "Pocket conservation",
                "Structural evidence",
                "HOG / model groups",
                "External links",
                "Alignment & trees",
                "Jobs",
                "Methods & glossary",
                "Downloads",
            ],
            key="navigation_page",
        )
        with st.expander("Project and host details"):
            st.caption("Open resource")
            st.code(
                st.session_state["resource"] or "No resource selected", language=None
            )
            st.caption(f"Project workspace: {workspace}")
            st.caption(f"App host: {execution_info()['hostname']}")
    root, data = None, None
    if st.session_state["resource"]:
        try:
            root = Path(st.session_state["resource"]).expanduser().resolve()
            data = load_project(root=root)
        except (ValueError, OSError) as error:
            st.error(str(error))
    st.title(data["title"] if data else "Protein pocket workbench")
    st.caption(
        "Browse predicted pockets, precomputed structure comparisons and "
        "pocket-annotated protein sequence alignments."
    )
    try:
        if page == "Start / import":
            import_page(workspace=workspace, root=root if data else None, data=data)
        elif page == "Methods & glossary":
            documentation_page()
        elif not data:
            st.info("Create or open a project through Start / import to use this page.")
        elif page == "Models & pockets":
            model_page(root=root, data=data)
        elif page == "Input quality":
            quality_page(root=root, data=data)
        elif page == "Compare structures":
            comparison_page(root=root, data=data)
        elif page == "Pocket conservation":
            conservation_page(root=root, data=data, render_table=show_table)
        elif page == "Structural evidence":
            evidence_page(root=root, data=data)
        elif page == "HOG / model groups":
            group_page(root=root, data=data)
        elif page == "External links":
            external_page(root=root, data=data)
        elif page == "Alignment & trees":
            sequence_page(root=root, data=data, workspace=workspace)
        elif page == "Jobs":
            jobs_page(root=root)
        elif page == "Downloads":
            downloads_page(root=root, data=data, workspace=workspace)
    except (ValueError, OSError, RuntimeError) as error:
        st.error(str(error))


if __name__ == "__main__":
    main()
