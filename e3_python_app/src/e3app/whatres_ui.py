"""Render the same optional model geometry assessment wherever full models are reviewed."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Sequence

import pandas as pd
import streamlit as st

from e3app.errors import AppError
from e3app.whatres import (
    MAX_COORDINATE_BYTES,
    MODEL_ID,
    WHATRES_PAPER,
    WhatResTarget,
    score_whatres,
    whatres_directory,
    whatres_structure_id,
)

MAX_SESSION_SCORES = 64


def render_whatres(*, models: Sequence[WhatResTarget], key: str, recorded: bool = False) -> None:
    """Score an explicitly chosen model and show or export its geometry assessment.

    Args:
        models: Current model selections, with full coordinates or a recorded checksum.
        key: Widget namespace unique to this viewer.
        recorded: Describe how full native models are matched to portable review traces.
    """
    with st.expander("Model geometry (WhatRes)"):
        st.markdown(
            "Realism measures how closely whole-model geometry resembles experimental "
            "structures at the same apparent resolution. Apparent resolution is a geometry "
            f"estimate in ångströms. [WhatRes preprint]({WHATRES_PAPER})"
        )
        try:
            directory = whatres_directory()
        except AppError as exc:
            st.warning(str(exc))
            return
        if directory is None:
            st.caption("Set E3_WHATRES_DIR on the app host to enable local WhatRes scoring.")
            return
        if not models:
            st.caption("This portable review has no unambiguous original-model checksum here.")
            return
        if recorded:
            st.caption(
                "Scores refer to the original native group models. Supply an unchanged "
                "full-atom file with the review's SHA-256. Display trimming applies to the viewer."
            )
        identities = [
            (directory, model.model_sha256 or sha256(model.content or b"").hexdigest(),
             whatres_structure_id(filename=model.filename))
            for model in models
        ]
        scores = st.session_state.setdefault("whatres_session_scores", {})
        selected = 0
        if len(models) > 1:
            selected = st.selectbox(
                label="Model to score", options=list(range(len(models))),
                format_func=lambda index: models[index].label, key=f"{key}_whatres_model",
            )
        target = models[selected]
        identity = identities[selected]
        if identity not in scores:
            content = target.content
            filename = target.filename
            if content is None:
                st.caption(f"{target.label} · original SHA-256 `{target.model_sha256}`")
                uploaded = st.file_uploader(
                    label="Original full-atom structure", type=["pdb", "cif", "mmcif"],
                    key=f"{key}_whatres_coordinates_{target.model_sha256}",
                    help="Upload the original coordinate file for this model, up to 20 MB.",
                )
                if uploaded is not None:
                    if uploaded.size > MAX_COORDINATE_BYTES:
                        st.warning("The original structure exceeds 20 MB.")
                    else:
                        content = uploaded.getvalue()
                        filename = MODEL_ID + Path(uploaded.name).suffix
            if st.button(
                label="Calculate WhatRes scores", key=f"{key}_whatres_score",
                disabled=content is None,
                help="Score this full model on the app host.",
            ):
                try:
                    with st.spinner("Assessing model geometry with WhatRes…", show_time=True):
                        result = score_whatres(
                            directory=directory, content=content, filename=filename,
                            expected_sha256=target.model_sha256,
                        )
                except AppError as exc:
                    st.warning(str(exc))
                else:
                    if len(scores) >= MAX_SESSION_SCORES:
                        del scores[next(iter(scores))]
                    scores[identity] = result
        rows = [
            {"model": model.label, **asdict(scores[model_key])}
            for model, model_key in zip(models, identities, strict=True) if model_key in scores
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
