"""Focused pocket conservation, distance and alignment-quality inspection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pandas as pd
import plotly.express as px
import streamlit as st

from .conservation_review import fit_quality, pocket_pair_rows, pocket_review
from .core import inside
from .external_ui import external_jump
from .presentation import analysis_label, finite_number, model_labels


@st.cache_data(show_spinner=False, max_entries=32)
def cached_review_result(*, root: str, relative: str, mtime_ns: int) -> dict:
    """Read an existing fit, invalidating the cache when that result file changes.

    Args:
        root: Native resource path.
        relative: Bounded saved result path.
        mtime_ns: Source modification time included in the cache key.

    Returns:
        Saved comparison JSON; no analysis or database write is performed.
    """
    return json.loads(inside(root=Path(root), relative=relative).read_text())


def quality_panel(*, result: dict) -> None:
    """Display fit denominators and quality metrics beside their actual scope.

    Args:
        result: Saved comparison.
    """
    fit = fit_quality(result=result)
    st.subheader("Alignment quality")
    a, b, c, d = st.columns(4)
    a.metric(
        "RMSD of aligned Cα (Å)",
        f"{fit['rmsd']:.3f}" if fit["rmsd"] is not None else "Unavailable",
    )
    b.metric(
        "Aligned Cα pairs",
        (
            f"{fit['aligned_atoms']:,.0f}"
            if fit["aligned_atoms"] is not None
            else "Unavailable"
        ),
    )
    c.metric(
        "Reference input coverage",
        (
            f"{fit['reference_coverage']:.1%}"
            if fit["reference_coverage"] is not None
            else "Unavailable"
        ),
    )
    d.metric(
        "Compared input coverage",
        (
            f"{fit['mobile_coverage']:.1%}"
            if fit["mobile_coverage"] is not None
            else "Unavailable"
        ),
    )
    a, b, c = st.columns(3)
    for column, label, key in (
        (a, "Reference-normalised TM-score", "tm_reference"),
        (b, "Compared-normalised TM-score", "tm_mobile"),
        (c, "Minimum TM-score", "minimum_tm"),
    ):
        column.metric(
            label, f"{fit[key]:.3f}" if fit[key] is not None else "Unavailable"
        )
    st.caption(
        analysis_label(
            engine=fit["engine"],
            settings=result.get("settings", {}),
            scope=fit["scope"],
        )
        + f" · recorded scope: {fit['scope']}. Coverage uses the selected fit inputs; "
        "RMSD describes only the aligned Cα pairs. A short-fragment fit does not "
        "establish whole-protein conservation."
    )
    if (
        fit["reference_fit_residues"] is not None
        and fit["mobile_fit_residues"] is not None
    ):
        st.caption(
            f"Fit input sizes: {fit['reference_fit_residues']:,.0f} reference and "
            f"{fit['mobile_fit_residues']:,.0f} compared Cα residues."
        )
    if fit["fold_supported"] is False:
        st.warning(
            f"Minimum TM-score {fit['minimum_tm']:.3f} is below the saved "
            f"{fit['thresholds']['min_tm']:.3f} fold threshold. A nearby pocket under "
            "this weak fit is insufficient evidence of a conserved pocket."
        )
    elif fit["minimum_tm"] is None:
        st.info(
            "No TM-score was supplied for this fit. Sequence-guided Kabsch does not"
            " provide TM-scores; fold and combined conservation evidence remain"
            " unassessed."
        )
    if fit["legacy_thresholds"]:
        st.caption(
            "Established legacy defaults supply missing threshold fields: "
            + ", ".join(fit["legacy_thresholds"])
            + "."
        )


def distance_panel(*, result: dict, match: dict, render_table: Callable) -> None:
    """Show saved matched-residue distances without implying all residues were matched.

    Args:
        result: Saved structural fit.
        match: Selected saved pocket pair.
        render_table: Existing typed table/download renderer.
    """
    review = pocket_review(result=result, match=match)
    st.subheader("Matched lining-residue distances")
    a, b, c, d = st.columns(4)
    for column, label, key in (
        (a, "Saved matched pairs", "matched_pairs"),
        (b, "Mean Cα distance (Å)", "mean_ca_distance"),
        (c, "Median Cα distance (Å)", "median_ca_distance"),
        (d, "Maximum Cα distance (Å)", "maximum_ca_distance"),
    ):
        value = review[key]
        column.metric(
            label,
            (
                "Unavailable"
                if value is None
                else f"{value:,.0f}" if key == "matched_pairs" else f"{value:.3f}"
            ),
        )
    rows = match.get("residue_correspondences")
    rows = rows if isinstance(rows, list) else []
    if review["distance_status"] == "available":
        plotted = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            distance = finite_number(value=row.get("ca_distance"))
            if distance is None or distance < 0:
                continue
            plotted.append(
                dict(
                    row,
                    matched_pair=index,
                    identity_status={
                        True: "Same amino acid",
                        False: "Different amino acid",
                    }.get(row.get("residue_identity"), "Identity unassessed"),
                )
            )
        frame = pd.DataFrame(plotted)
        for column in (
            "reference_residue",
            "mobile_residue",
            "reference_fasta_position",
            "mobile_fasta_position",
        ):
            if column not in frame:
                frame[column] = None
        figure = px.scatter(
            frame,
            x="matched_pair",
            y="ca_distance",
            color="identity_status",
            symbol="identity_status",
            color_discrete_map={
                "Same amino acid": "#0072B2",
                "Different amino acid": "#D55E00",
                "Identity unassessed": "#65798A",
            },
            hover_data=[
                "reference_residue",
                "mobile_residue",
                "reference_fasta_position",
                "mobile_fasta_position",
            ],
            labels={
                "matched_pair": "Saved matched residue pair",
                "ca_distance": "Cα distance after the saved fit (Å)",
                "identity_status": "Pocket residue identity",
            },
        )
        radius = review["fit"]["thresholds"]["radius"]
        if radius is not None:
            figure.add_hline(
                y=radius,
                line_dash="dash",
                annotation_text=f"Recorded matching radius: {radius:g} Å",
            )
        figure.update_layout(
            height=330, margin={"t": 45, "b": 45}, legend={"orientation": "h"}
        )
        st.plotly_chart(figure, width="stretch")
    elif review["distance_status"] == "recorded_empty":
        st.info(
            "The saved result records no matched lining-residue pairs within its"
            " matching radius."
        )
    else:
        st.info(
            "Usable residue-level distances were not supplied in this saved result."
        )
    st.caption(
        "These distances describe the saved mutual-nearest lining Cα matches, already "
        "restricted by the recorded matching radius. They do not describe unmatched "
        "residues, all atom pairs or cavity-volume overlap. Directional overlap and "
        "mapping fractions above retain the wider pocket context."
    )
    if review["omitted_distances"]:
        st.caption(
            f"{review['omitted_distances']} rows omitted from the plot/statistics"
            " because their distances are unavailable or invalid."
        )
    if rows:
        with st.expander("Matched residue pairs and exact author/FASTA positions"):
            render_table(
                rows=[r for r in rows if isinstance(r, dict)],
                key="conservation_residue_pairs",
                glossary_term="Mutual-nearest match fraction",
            )


def conservation_page(*, root: Path, data: dict, render_table: Callable) -> None:
    """Inspect a saved pair with explicit rules, distances and fit-quality context.

    Args:
        root: Completed native resource.
        data: Loaded project evidence.
        render_table: Existing table renderer with numeric TSV/Excel downloads.
    """
    st.header("Pocket conservation and alignment quality")
    st.markdown(
        "Inspect whether two saved pockets occupy a matching position, how similar "
        "their lining residues are, and whether the structural fit supports that "
        "interpretation. Missing evidence stays unassessed."
    )
    complete = [c for c in data["comparisons"] if c["status"] == "complete"]
    if not complete:
        st.info("This resource has no complete saved structural alignments to review.")
        return
    labels = model_labels(identifiers=[m["sample_id"] for m in data["models"]])
    pending = st.session_state.pop("requested_conservation", None)
    if pending:
        selected = next(
            (c for c in complete if c["comparison_id"] == pending["comparison_id"]),
            None,
        )
        if selected:
            st.session_state["conservation_reference"] = selected["reference"]
            st.session_state["conservation_mobile"] = selected["mobile"]
            st.session_state["conservation_fit"] = selected["comparison_id"]
    references = sorted({c["reference"] for c in complete})
    if st.session_state.get("conservation_reference") not in references:
        st.session_state["conservation_reference"] = references[0]
    a, b = st.columns(2)
    reference = a.selectbox(
        "Reference model",
        references,
        format_func=lambda k: labels.get(k, k),
        key="conservation_reference",
    )
    mobiles = sorted({c["mobile"] for c in complete if c["reference"] == reference})
    if st.session_state.get("conservation_mobile") not in mobiles:
        st.session_state["conservation_mobile"] = mobiles[0]
    mobile = b.selectbox(
        "Compared model",
        mobiles,
        format_func=lambda k: labels.get(k, k),
        key="conservation_mobile",
    )
    candidates = [
        c for c in complete if c["reference"] == reference and c["mobile"] == mobile
    ]
    results = {}
    for entry in candidates:
        path = inside(root=root, relative=entry["result_path"])
        results[entry["comparison_id"]] = cached_review_result(
            root=str(root),
            relative=entry["result_path"],
            mtime_ns=path.stat().st_mtime_ns,
        )
    if st.session_state.get("conservation_fit") not in results:
        st.session_state["conservation_fit"] = next(iter(results))
    choice = st.selectbox(
        "Saved alignment to assess",
        list(results),
        key="conservation_fit",
        format_func=lambda k: analysis_label(
            engine=results[k]["engine"],
            settings=results[k].get("settings", {}),
            scope=results[k].get("scope", ""),
        ),
    )
    result = results[choice]
    rows = pocket_pair_rows(result=result, pockets=data["pockets"])
    matches = {
        (m["reference_pocket"], m["mobile_pocket"]): m
        for m in result.get("pocket_matches", [])
    }
    pair_keys = [(r["reference_pocket"], r["mobile_pocket"]) for r in rows]
    if st.session_state.get("conservation_pair_context") != choice:
        st.session_state["conservation_pair"] = next(iter(pair_keys), None)
        st.session_state["conservation_pair_context"] = choice
    if pending and pending.get("pair") in pair_keys:
        st.session_state["conservation_pair"] = pending["pair"]
    if st.session_state.get("conservation_pair") not in pair_keys:
        st.session_state["conservation_pair"] = next(iter(pair_keys), None)
    if not rows:
        st.info(
            "No pocket pair was tested in this saved fit. Position and conservation are"
            " unassessed; the alignment quality remains available below."
        )
        quality_panel(result=result)
        return
    by_pair = {(r["reference_pocket"], r["mobile_pocket"]): r for r in rows}
    pair = st.selectbox(
        "Pocket pair",
        pair_keys,
        key="conservation_pair",
        format_func=lambda k: (
            f"Reference rank {by_pair[k]['reference_rank'] or 'unreported'} (pocket"
            f" {k[0]}) / compared rank {by_pair[k]['mobile_rank'] or 'unreported'}"
            f" (pocket {k[1]})"
            + (
                " · original rank-one pair"
                if by_pair[k]["original_rank_one_pair"]
                else " · alternative pair"
            )
        ),
    )
    row, match = by_pair[pair], matches[pair]
    review = pocket_review(result=result, match=match)
    if not row["original_rank_one_pair"]:
        st.info(
            "This is an alternative pocket pair. Its metrics do not replace the"
            " original rank-one conclusion. Ranks retain their recorded values after"
            " filtering."
        )
    a, b = st.columns(2)
    if a.button("Open this pocket pair in 3D"):
        st.session_state["requested_comparison"] = choice
        st.session_state["requested_pocket_pair"] = pair
        st.session_state["pending_navigation"] = "Compare structures"
        st.rerun()
    with b:
        external_jump(
            key="conservation_external_tools",
            first="model:" + reference,
            second="model:" + mobile,
            comparison=choice,
        )
    st.subheader("Position and conservation evidence")
    for column, label, key in zip(
        st.columns(3),
        ("Pocket position", "Fold support", "Conservation rule"),
        ("position_supported", "fold_supported", "conservation_supported"),
    ):
        value = review[key]
        with column:
            st.markdown("**" + label + "**")
            if value is True:
                st.success("Meets recorded rule")
            elif value is False:
                st.warning("Does not meet recorded rule")
            else:
                st.info("Not assessed")
    if review["conservation_supported"] is None:
        st.caption(
            "Combined conservation requires recorded position/fold evidence and"
            " available lining-match/chemical scores. An unassessed result is not a"
            " negative biological finding."
        )
    st.caption(
        "The conservation rule combines pocket position, fold support, mutual-nearest"
        " lining matches and chemical-group agreement. Exact amino-acid identity is"
        " reported separately. These are computational evidence rules, not binding"
        " validation."
    )
    a, b, c, d = st.columns(4)
    for column, label, key, fraction in (
        (a, "Pocket centroid separation (Å)", "centroid_distance", False),
        (b, "Symmetric lining Cα overlap", "symmetric_overlap", True),
        (c, "Reference lining within radius", "reference_fraction", True),
        (d, "Compared lining within radius", "mobile_fraction", True),
    ):
        value = review["metrics"][key]
        column.metric(
            label,
            (
                "Unavailable"
                if value is None
                else f"{value:.1%}" if fraction else f"{value:.3f}"
            ),
        )
    quality_panel(result=result)
    a, b, c = st.columns(3)
    for column, label, key in (
        (a, "Mutual-nearest lining match", "mutual_match_fraction"),
        (b, "Pocket residue identity", "residue_identity_fraction"),
        (c, "Pocket chemical-group agreement", "chemical_group_conservation"),
    ):
        value = review["metrics"][key]
        column.metric(label, f"{value:.1%}" if value is not None else "Unavailable")
    with st.expander("Why each recorded rule passes or fails", expanded=True):
        st.dataframe(
            [
                {
                    **check,
                    "value": (
                        "Unavailable"
                        if check["value"] is None
                        else (
                            str(check["value"])
                            if isinstance(check["value"], bool)
                            else f"{check['value']:.3f}"
                        )
                    ),
                    "threshold": (
                        "Unavailable"
                        if check["threshold"] is None
                        else (
                            str(check["threshold"])
                            if isinstance(check["threshold"], bool)
                            else f"{check['threshold']:.3f}"
                        )
                    ),
                    "passes": {
                        True: "Pass",
                        False: "Does not pass",
                        None: "Not assessed",
                    }[check["passes"]],
                }
                for check in review["checks"]
            ],
            hide_index=True,
            width="stretch",
        )
    for note in review["consistency_notes"]:
        st.warning(
            note + " Inspect the original fit JSON before interpreting the decision."
        )
    distance_panel(result=result, match=match, render_table=render_table)
    with st.expander("Local pocket confidence and preparation context"):
        context = []
        for role, identifier, pocket_id in (
            ("reference", reference, pair[0]),
            ("compared", mobile, pair[1]),
        ):
            pocket = next(
                (
                    p
                    for p in data["pockets"]
                    if p["sample_id"] == identifier
                    and p["method"] == "fpocket"
                    and p["pocket_id"] == pocket_id
                ),
                {},
            )
            context.append(
                dict(
                    role=role,
                    sample_id=identifier,
                    pocket_id=pocket_id,
                    **{
                        key: pocket.get(key)
                        for key in (
                            "mean_plddt",
                            "confidence_status",
                            "quality_screen_pass",
                            "near_cut_boundary",
                            "near_very_low_confidence",
                        )
                    },
                )
            )
        render_table(
            rows=context,
            key="conservation_context",
            glossary_term="Local pocket confidence",
        )
    with st.expander("All tested pocket pairs in this fit and numeric downloads"):
        render_table(
            rows=rows, key="conservation_pairs", glossary_term="Top-k sensitivity"
        )
    with st.expander(
        "Selected-pair alignment and pocket metrics (numeric TSV / Excel)"
    ):
        metrics = dict(
            row,
            **{
                k: review["fit"][k]
                for k in (
                    "rmsd",
                    "aligned_atoms",
                    "tm_reference",
                    "tm_mobile",
                    "minimum_tm",
                    "reference_coverage",
                    "mobile_coverage",
                    "reference_fit_residues",
                    "mobile_fit_residues",
                )
            },
        )
        metrics.update(
            comparison_id=choice,
            reference=reference,
            mobile=mobile,
            engine=result["engine"],
            scope=result.get("scope"),
        )
        render_table(rows=[metrics], key="conservation_selected")
