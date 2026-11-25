"""Inspect full-model WhatRes diagnostics and the geometry of mapped pocket residues."""

from __future__ import annotations

import logging
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pandas as pd
import streamlit as st

from e3app.errors import AppError
from e3app.exports import safe_file_stem
from e3app.glossary import (
    GEOMETRY_SURPRISE_DEFINITION,
    POCKET_GEOMETRY_COLUMNS,
    RESIDUE_GEOMETRY_COLUMNS,
)
from e3app.research.linked_features import read_group_evidence, review_member_evidence
from e3app.whatres import WHATRES_CITATION, WhatResTarget
from e3app.whatres_residues import (
    ResidueReport, link_residue_geometry, native_geometry_view, score_residue_geometry,
)

LOGGER = logging.getLogger(__name__)
RESIDUE_ACTION = "Calculate per-residue geometry"
RESIDUE_HELP = (
    "WhatRes assesses the first model with its neighbouring chains. The amino acid and the atoms "
    "present determine which measurements are available. Select a residue to see its total, "
    "outliers and worst metric. Grey indicates missing geometry. The darkest surprise colour "
    "starts at the 95th percentile of assessed residues in this model. The table gives the "
    "full numeric value."
)
POCKET_HELP = (
    "For example, if 4 of 12 assessed residues have an outlier, **Flagged (%)** is 33.3%. "
    "If one of the four has two outliers and the other three have one each, **Total outliers** "
    "is 5. A residue shared by two pockets contributes to each pocket's summary. WhatRes "
    "reports realism and apparent resolution for the whole model."
)


def show_geometry_help(
    *, label: str, columns: dict[str, tuple[str, str, str]], notes: str,
) -> None:
    """Explain the scoring method and table terms in a touch-accessible popover.

    Args:
        label: Visible label of the question-mark control.
        columns: Display label, unit and definition keyed by measurement field.
        notes: Interpretation specific to this table.
    """
    with st.popover(label=label):
        st.markdown(body=f"**Geometry surprise** — {GEOMETRY_SURPRISE_DEFINITION}")
        st.markdown(body=(
            "For a bond length, the reference median contributes 0. A value at the 5th or 95th "
            "percentile contributes about 3.32. These contributions add up on a raw score scale. "
            "Several moderate deviations can raise the total even if none crosses a flag threshold."
        ))
        st.markdown(body=(
            "**Outlier** — With the published settings, a measurement is flagged below the 1st "
            "or above the 99th reference percentile. The Ramachandran check (**rama2D**) looks "
            "at the two backbone torsion angles φ and ψ together. It flags pairs below the 2nd "
            "density percentile for that amino acid."
        ))
        st.markdown(body="\n".join(
            f"- **{title}** — {definition}" for field, (title, _, definition) in columns.items()
            if field != "residue_score"
        ))
        st.markdown(body=notes)
        st.markdown(body=WHATRES_CITATION)


def show_geometry_table(*, frame: pd.DataFrame, columns: dict[str, tuple[str, str, str]]) -> None:
    """Display the selected measurements with a definition on every column header.

    Args:
        frame: Source rows with their original numerical values and missing values.
        columns: Ordered mapping of fields to display labels, units and definitions.
    """
    labels = {field: label for field, (label, _, _) in columns.items()}
    st.dataframe(
        data=frame[list(labels)].rename(columns=labels), hide_index=True,
        column_config={
            label: st.column_config.Column(label=label, help=definition)
            for label, _, definition in columns.values()
        },
    )


def geometry_download(
    *, frame: pd.DataFrame, report: ResidueReport, target: WhatResTarget, key: str, kind: str,
) -> None:
    """Download all rows with provenance for the selected model.

    Args:
        frame: Complete residue records or pocket membership summaries.
        report: Coordinate and software identities.
        target: Model selection shown in the app.
        key: Widget namespace.
        kind: Residue or pocket export label and filename component.
    """
    export = frame.assign(model=target.label, model_sha256=report.model_sha256,
                          scored_pdb_sha256=report.scored_pdb_sha256,
                          input_format=report.input_format, whatres_version=report.whatres_version)
    stem = safe_file_stem(value=target.label)
    st.download_button(
        label=f"Download {kind} geometry (TSV)",
        data=export.to_csv(sep="\t", index=False, na_rep="", lineterminator="\n"),
        file_name=f"{stem}_{report.model_sha256[:12]}_{kind}_geometry.tsv",
        mime="text/tab-separated-values", key=f"{key}_whatres_{kind}_tsv", on_click="ignore",
    )


def show_pocket_geometry(*, evidence: dict, report: ResidueReport,
                         target: WhatResTarget, key: str) -> None:
    """Show mapped coverage and local geometry summaries above the linked pocket tracks.

    Args:
        evidence: Geometry-enriched model and verified pockets.
        report: Scored model identities.
        target: Selected protein.
        key: Widget namespace.
    """
    rows = [{"pocket": pocket["number"], "rank": pocket["rank"], **pocket["geometry"],
             "mapped_positions": " ".join(map(str, pocket["positions"]))}
            for pocket in evidence["pockets"]]
    if not rows:
        st.caption("Pocket geometry needs mapped pocket residues from this exact model.")
        return
    st.markdown("#### Pocket geometry")
    frame = pd.DataFrame(rows)
    columns = POCKET_GEOMETRY_COLUMNS.copy()
    if frame["median_plddt"].isna().all():
        del columns["median_plddt"]
    st.caption("Higher surprise means more unusual local geometry. One flagged residue can "
               "have several outlier measurements.")
    show_geometry_help(label="❓ Pocket geometry help", columns=columns, notes=POCKET_HELP)
    show_geometry_table(frame=frame, columns=columns)
    geometry_download(frame=frame, report=report, target=target, key=key, kind="pocket")


def show_geometry_view(
    *, target: WhatResTarget, key: str, evidence: dict | None = None, inline: bool = False,
) -> dict | None:
    """Colour the verified linked trace or show a native-chain geometry view.

    Args:
        target: Selected model with the optional residue report.
        key: Widget namespace.
        evidence: Optional trace and memberships for the displayed member.
        inline: Return verified evidence for the caller's existing Nightingale viewer.

    Returns:
        Linked evidence for the caller, retaining its selected trace on a mismatch.
    """
    from e3app.research.expansion_ui import show_features

    report = target.residue_report
    if report is None:
        return evidence
    if evidence is not None:
        try:
            linked = link_residue_geometry(evidence=evidence, report=report)
        except AppError as exc:
            st.info(f"{exc} The geometry view below uses the assessed native model.")
        else:
            if "pockets" in evidence:
                show_pocket_geometry(evidence=linked, report=report, target=target, key=key)
            if inline:
                return linked
            payload = {**linked, "features": [], "coordinate_scope": "Native review sequence"}
            show_features(payload={**payload, "model_label": target.label},
                          stem=f"{key}_{report.model_sha256[:12]}_geometry")
            return evidence
    chains = list(dict.fromkeys(row["chain"] for row in report.rows))
    chain = chains[0] if len(chains) == 1 else st.selectbox(
        "Geometry display chain", options=chains, format_func=lambda value: value or "(blank)",
        key=f"{key}_{report.model_sha256}_chain", help=(
            "Choose the chain to display. Measurements retain the context of the full model."
        ),
    )
    payload = native_geometry_view(report=report, chain=chain)
    if payload["model"]:
        st.caption("The axis counts observed residues in this chain. Select a residue for its "
                   "native chain and residue number.")
        show_features(payload={**payload, "model_label": target.label},
                      stem=f"{key}_{report.model_sha256[:12]}_geometry")
    else:
        st.caption("This chain has no Cα positions to display. Its measurements are in the TSV.")
    return evidence


def render_residue_controls(
    *, target: WhatResTarget | None, directory: Path | None, key: str,
    defer_view: bool = False, review_dir: Path | None = None,
) -> WhatResTarget | None:
    """Calculate and export a bounded, session-local residue assessment on demand.

    Args:
        target: Model resolved by the shared WhatRes selector.
        directory: Validated WhatRes installation, if configured.
        key: Widget namespace.
        defer_view: The caller will attach geometry to its selected trace.
        review_dir: Optional native portable group evidence for this member.

    Returns:
        The full model and its selected residue report, when available.
    """
    st.markdown("#### Per-residue geometry")
    show_geometry_help(
        label="❓ Residue geometry help", columns=RESIDUE_GEOMETRY_COLUMNS, notes=RESIDUE_HELP,
    )
    ready = target is not None and target.content is not None
    identity = (directory, sha256(target.content).hexdigest(), Path(target.filename).suffix.lower(),
                target.model_sha256) if ready else None
    reports = st.session_state.setdefault("whatres_residue_reports", {})
    report = reports.get(identity)
    if report is None and st.button(
        RESIDUE_ACTION, key=f"{key}_whatres_residues", disabled=not (directory and ready),
        help="Supply the full-atom model and configure WhatRes on the app host.",
    ) and directory and ready:
        try:
            with st.spinner("Measuring geometry in the full model…", show_time=True):
                report = score_residue_geometry(directory=directory, content=target.content,
                                                filename=target.filename,
                                                expected_sha256=target.model_sha256)
        except AppError as exc:
            st.warning(str(exc))
        else:
            if len(reports) >= 3:
                del reports[next(iter(reports))]
            reports[identity] = report
    if report is None:
        return target if ready else None
    target = replace(target, residue_report=report)
    frame = pd.DataFrame(report.rows).drop(columns=["x", "y", "z"])
    assessed = frame["status"].eq("assessed")
    flagged = frame["n_outliers"].gt(0)
    st.caption(f"{target.label} · {int(assessed.sum()):,}/{len(frame):,} residues assessed · "
               f"{int(flagged.sum()):,} residues with flagged geometry")
    with st.expander("Inspect residue measurements"):
        flagged_only = st.checkbox("Show only residues with outliers", key=f"{key}_flagged_only")
        show_geometry_table(frame=frame[flagged] if flagged_only else frame,
                            columns=RESIDUE_GEOMETRY_COLUMNS)
    geometry_download(frame=frame, report=report, target=target, key=key, kind="residue")
    if not defer_view:
        evidence = None
        if review_dir and target.model_sha256 and target.review_accession:
            try:
                group = read_group_evidence(review_dir=review_dir, group_id=target.group_id)
                if group:
                    evidence = review_member_evidence(
                        group=group, accession=target.review_accession, species=target.species,
                        source=review_dir.name,
                    )
            except (AppError, AttributeError, KeyError, TypeError,
                    ValueError, OverflowError) as exc:
                LOGGER.warning("Could not map reviewed WhatRes pockets: %s", exc)
        if evidence is not None and not evidence.get("model_sha256"):
            # Older group pages identify the native file in the member inventory only.
            evidence = {**evidence, "model_sha256": target.model_sha256}
        if review_dir and evidence is None:
            st.caption("Pocket geometry needs mapped pocket residues from this exact review model.")
        show_geometry_view(target=target, key=key, evidence=evidence)
    return target
