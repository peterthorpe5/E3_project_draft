"""Render the same optional model geometry assessment wherever full models are reviewed."""

from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from typing import Sequence

import pandas as pd
import streamlit as st

from e3app.alphafold_hog_bundle import AlphaFoldHogBundle
from e3app.errors import AppError
from e3app.exports import safe_file_stem
from e3app.research.retrieval_ui import render_alphafold_retrieval
from e3app.whatres import (
    MAX_COORDINATE_BYTES,
    MODEL_ID,
    WHATRES_CITATION,
    WHATRES_VERSION,
    WhatResTarget,
    score_whatres,
    score_whatres_bundle,
    whatres_directory,
    whatres_structure_id,
)

MAX_SESSION_SCORES = 64
FULL_MODEL_BUTTON = "Retrieve full model from AlphaFold Database"
WHATRES_SETUP = (
    "https://github.com/peterthorpe5/E3_project_draft/blob/main/"
    "e3_python_app/README.md#optional-local-setup"
)


def _review_coordinates(*, target: WhatResTarget, key: str) -> WhatResTarget:
    """Offer full coordinates for the selected trace and identify the file's provenance."""
    use_alphafold = bool(target.alphafold_accession)
    if use_alphafold and target.model_sha256:
        source = st.radio(
            label="Full model source", options=("AlphaFold Database", "Original review file"),
            horizontal=True, key=f"{key}_whatres_source",
            help="Retrieve a full model by UniProt accession or upload the file used in the run.",
        )
        use_alphafold = source == "AlphaFold Database"
    if use_alphafold:
        downloaded = render_alphafold_retrieval(
            members=pd.DataFrame([{
                "member_parsed_accession": target.alphafold_accession,
                "member_raw_identifier": target.alphafold_accession,
                "member_species": target.species,
            }]),
            group_id=target.group_id,
            scope=repr((target.label, target.species, target.model_sha256)),
            key=f"{key}_whatres_full_model", single=True, button_label=FULL_MODEL_BUTTON,
        )
        if downloaded is None:
            return target
        coordinates, _ = downloaded
        if sha256(coordinates).hexdigest() == target.model_sha256:
            st.caption("The retrieved coordinates match the original review SHA-256.")
            return replace(
                target, content=coordinates, filename="alphafold.cif", from_alphafold_database=True,
            )
        if target.model_sha256:
            st.info("The retrieved coordinates have a different SHA-256 from the review file.")
        st.caption("The score for this download is labelled current AlphaFold Database.")
        return replace(
            target, label=f"{target.label} · current AlphaFold Database",
            content=coordinates, filename="alphafold.cif", model_sha256="",
            from_alphafold_database=True,
        )
    st.caption(f"{target.label} · original SHA-256 `{target.model_sha256}`")
    uploaded = st.file_uploader(
        label="Original full-atom structure", type=["pdb", "cif", "mmcif"],
        key=f"{key}_whatres_coordinates_{target.model_sha256}",
        help="Use the unchanged coordinate file from the original E3 run, up to 20 MB.",
    )
    if uploaded is None:
        return target
    if uploaded.size > MAX_COORDINATE_BYTES:
        st.warning("The original structure exceeds 20 MB.")
        return target
    content = uploaded.getvalue()
    if sha256(content).hexdigest() != target.model_sha256:
        st.warning("The supplied model SHA-256 differs from the original review model.")
        return target
    return replace(
        target, content=content, filename=MODEL_ID + Path(uploaded.name).suffix,
    )


def _score_identity(*, target: WhatResTarget, directory: Path) -> tuple[Path, str, str]:
    """Identify reusable scores by installation, original coordinate bytes and PDB ID."""
    digest = target.model_sha256 or (
        sha256(target.content).hexdigest() if target.content is not None else ""
    )
    return directory, digest, whatres_structure_id(filename=target.filename)


def render_whatres(
    *, models: Sequence[WhatResTarget], key: str, recorded: bool = False, prompt: str = "",
) -> WhatResTarget | None:
    """Score an explicitly chosen model and show or export its geometry assessment.

    Args:
        models: Current model selections, with full coordinates or a recorded checksum.
        key: Widget namespace unique to this viewer.
        recorded: Describe how full native models are matched to portable review traces.
        prompt: How to supply a full model when the caller has no selection yet.

    Returns:
        The selected full coordinates and their provenance, when available.
    """
    with st.expander("Model geometry (WhatRes)", expanded=True):
        with st.popover("❓ WhatRes help"):
            st.markdown(
                "**Realism (0–100)** describes how typical the model's atomic geometry "
                "is of experimental structures at a similar apparent resolution. "
                "Higher values indicate more experimental-like geometry.\n\n"
                "**Apparent resolution (Å)** is an estimate from the coordinates. "
                "WhatRes scores whole-model geometry. Read it alongside pLDDT "
                "for local confidence and the evidence for each pocket.\n\n"
                "**Why a full model?** WhatRes uses backbone and side-chain atoms to "
                "assess properties such as bond lengths and angles. The portable review "
                "stores Cα positions for display."
            )
            if recorded:
                st.markdown(
                    "**Which model will I score?** Use **AlphaFold Database** to retrieve "
                    "the current file when a UniProt accession is available. A matching "
                    "SHA-256 identifies the original review file. A different download "
                    "is labelled with its current source. To score the reviewed model, "
                    "you can upload its original full-atom PDB or mmCIF. "
                    "Viewer trimming is a display control."
                )
            st.markdown(
                "Scoring runs on the machine hosting the app. Installation is needed once. "
                "Export `E3_WHATRES_DIR` in your launch shell and restart Streamlit. "
                f"[WhatRes installation instructions]({WHATRES_SETUP})"
            )
            st.markdown(WHATRES_CITATION)
        directory = None
        try:
            directory = whatres_directory()
        except AppError as exc:
            st.warning(str(exc))
        if directory is None:
            st.markdown(
                "**WhatRes setup needed.** Install it on the app host, then set "
                "`E3_WHATRES_DIR` and restart the app. "
                f"[Installation instructions]({WHATRES_SETUP})"
            )
        else:
            st.caption(f"WhatRes v{WHATRES_VERSION} is ready on the app host.")
        target = None
        selected = None
        if models:
            selected = models[0]
            if len(models) > 1:
                index = st.selectbox(
                    label="Model to score", options=list(range(len(models))),
                    format_func=lambda index: models[index].label, key=f"{key}_whatres_model",
                )
                selected = models[index]
            target = selected
            if selected.content is None:
                target = _review_coordinates(target=selected, key=key)
        else:
            st.caption(prompt or "This selection has no saved checksum or supported accession.")
        identity = (
            _score_identity(target=target, directory=directory)
            if target is not None and directory is not None else None
        )
        scores = st.session_state.setdefault("whatres_session_scores", {})
        can_score = directory is not None and target is not None and target.content is not None
        if identity not in scores and st.button(
            label="Calculate WhatRes scores", key=f"{key}_whatres_score",
            disabled=not can_score,
            help="Choose a full coordinate model and set up WhatRes to score it on this app host.",
        ) and can_score:
            try:
                with st.spinner("Assessing model geometry with WhatRes…", show_time=True):
                    result = score_whatres(
                        directory=directory, content=target.content, filename=target.filename,
                        expected_sha256=target.model_sha256,
                    )
            except AppError as exc:
                st.warning(str(exc))
            else:
                if len(scores) >= MAX_SESSION_SCORES:
                    del scores[next(iter(scores))]
                scores[identity] = result
        if directory is None or target is None:
            return target if target is not None and target.content is not None else None
        shown = list(models)
        if target.label != selected.label:
            shown.append(target)
        identities = [_score_identity(target=model, directory=directory) for model in shown]
        rows = [
            {"model": model.label, **asdict(scores[model_key])}
            for model, model_key in zip(shown, identities, strict=True) if model_key in scores
        ]
        if rows:
            table = pd.DataFrame(rows)
            st.dataframe(
                table[["model", "realism", "apparent_resolution", "note"]].rename(columns={
                    "model": "Model", "realism": "Realism (0–100)",
                    "apparent_resolution": "Apparent resolution (Å)", "note": "WhatRes note",
                }),
                hide_index=True,
            )
            st.download_button(
                label="Download WhatRes scores (TSV)",
                data=table.to_csv(sep="\t", index=False, lineterminator="\n"),
                file_name="whatres_model_geometry.tsv", mime="text/tab-separated-values",
                key=f"{key}_whatres_tsv", on_click="ignore",
            )
        return target if target.content is not None else None


def render_whatres_bundle(
    *, bundle: AlphaFoldHogBundle | None, hog_id: str, key: str,
) -> None:
    """Show the batch geometry workflow and export scores for the current HOG request.

    Args:
        bundle: Model ZIP already prepared in this session for the current selection.
        hog_id: Current hierarchical orthogroup identifier.
        key: Widget namespace for the calling page.
    """
    state_key = f"{key}_whatres_batch_results"
    with st.expander("HOG geometry (WhatRes)", expanded=True):
        with st.popover("❓ HOG WhatRes help"):
            st.markdown(
                "Prepare the model ZIP, then score its downloaded structures on the app host. "
                "The TSV includes a row for each requested accession and records missing "
                "downloads and scoring errors. The medians use the models with both scores. "
                "Realism (0–100) measures how experimental-like the geometry is at "
                "the estimated apparent resolution (Å)."
            )
            st.markdown(WHATRES_CITATION)
        if bundle is None or not bundle.included_count:
            st.session_state.pop(state_key, None)
            st.caption("Prepare the model ZIP with at least one available model to score the HOG.")
            return
        directory = None
        try:
            directory = whatres_directory()
        except AppError as exc:
            st.warning(str(exc))
        if directory is None:
            st.session_state.pop(state_key, None)
            st.markdown(
                "Install WhatRes on the app host, export `E3_WHATRES_DIR` and restart the app. "
                f"[WhatRes installation instructions]({WHATRES_SETUP})"
            )
            return
        identity = (directory, hog_id, bundle.records)
        previous = st.session_state.get(state_key)
        frame = None
        if previous is not None and previous[0] == identity:
            frame = previous[1]
        else:
            st.session_state.pop(state_key, None)
        st.caption(
            f"{bundle.included_count:,} of {bundle.requested_count:,} models ready to score."
        )
        if st.button(
            label="Calculate WhatRes scores for prepared HOG models", key=f"{key}_whatres_batch",
            help=(
                "Scores the models already in the ZIP. Keep this tab open while the scores run."
            ),
        ):
            bar = st.progress(0, text="Starting WhatRes…")

            def update_progress(*, completed: int, total: int) -> None:
                """Show how many requested accessions have been processed.

                Args:
                    completed: Number of accessions processed so far.
                    total: Number of accessions requested for the ZIP.
                """
                bar.progress(completed / total, text=f"Processed {completed:,} of {total:,}.")

            frame = score_whatres_bundle(
                directory=directory, bundle=bundle, hog_id=hog_id, progress=update_progress,
            )
            st.session_state[state_key] = (identity, frame)
        if frame is None:
            return
        scored = frame.loc[frame["scoring_status"].eq("scored")]
        columns = st.columns(3)
        columns[0].metric("Models scored", f"{len(scored):,} / {len(frame):,}")
        if not scored.empty:
            columns[1].metric("Median realism", f"{scored['realism'].median():.2f}")
            columns[2].metric(
                "Median apparent resolution", f"{scored['apparent_resolution'].median():.2f} Å",
            )
        st.dataframe(
            frame[
                [
                    "accession", "species", "retrieval_status", "scoring_status",
                    "realism", "apparent_resolution", "note", "detail",
                ]
            ].rename(columns={
                "accession": "Accession", "species": "Species",
                "retrieval_status": "Download", "scoring_status": "Scoring",
                "realism": "Realism (0–100)", "apparent_resolution": "Apparent resolution (Å)",
                "note": "WhatRes note", "detail": "Details",
            }),
            hide_index=True,
        )
        st.download_button(
            label="Download HOG WhatRes scores (TSV)",
            data=frame.to_csv(sep="\t", index=False, lineterminator="\n"),
            file_name=f"{safe_file_stem(value=hog_id)}_whatres.tsv",
            mime="text/tab-separated-values", key=f"{key}_whatres_batch_tsv", on_click="ignore",
        )
