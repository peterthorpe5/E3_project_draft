"""Readable labels and plots derived only from saved analytical evidence."""

from __future__ import annotations

import json
import logging
import math
import re
from statistics import median

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .core import WorkbenchError

LOGGER = logging.getLogger(__name__)
METHOD_LABELS = {
    "usalign": "US-align",
    "tmalign": "TM-align",
    "sequence_kabsch": "Sequence-guided Kabsch",
}
POCKET_COLOURS = [
    "#D55E00",
    "#0072B2",
    "#009E73",
    "#9B3C86",
    "#A36F00",
    "#CC4778",
    "#386A20",
    "#5947B1",
]


def finite_number(*, value: object) -> float | None:
    """Return a finite numeric value, preserving missing/invalid evidence as None.

    Args:
        value: A saved scalar, not a truth value.

    Returns:
        Finite float or None; never a zero substituted for missing evidence.
    """
    if value is None or isinstance(value, (bool, np.bool_)):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def model_label(*, identifier: str) -> str:
    """Shorten recognised AlphaFold names while retaining replicate/region identity.

    Args:
        identifier: Exact stored sample identifier.

    Returns:
        Display label only; source identifiers are never modified.
    """
    match = re.fullmatch(
        r"(?:fold_)?(.+?)_\d{8}_model_(\d+)(?:__[A-Za-z0-9]{8}_r(\d+))?", identifier
    )
    if match:
        return f"{match[1]} · model {match[2]}" + (
            f" · region {int(match[3])}" if match[3] else ""
        )
    return identifier if len(identifier) <= 56 else identifier[:49] + "…"


def model_labels(*, identifiers: list[str]) -> dict[str, str]:
    """Create collision-free display labels while retaining exact lookup keys.

    Args:
        identifiers: Source identifiers, including possible repeats.

    Returns:
        Stable full-ID to unique display-label mapping.
    """
    labels, used = {}, set()
    for identifier in sorted(set(identifiers)):
        base, suffix = model_label(identifier=identifier), 1
        candidate = base
        while candidate in used:
            candidate = f"{base} [{suffix}]"
            suffix += 1
        labels[identifier] = candidate
        used.add(candidate)
    return labels


def analysis_label(*, engine: str, settings: dict | str, scope: str = "") -> str:
    """Explain a recorded fit without exposing JSON or absent domain endpoints.

    Args:
        engine: Saved aligner name.
        settings: Recorded options as a dictionary or JSON string.
        scope: Saved scope, when available.

    Returns:
        Human-readable description of the saved fit inputs and filters.
    """
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except ValueError:
            LOGGER.warning("An analysis has unreadable settings metadata")
            settings = {}
    if not isinstance(settings, dict):
        settings = {}
    if settings.get("start") is not None and settings.get("end") is not None:
        selected = f"Reference range {settings['start']}–{settings['end']}"
    elif scope == "cleaned_region":
        selected = "Retained region"
    elif settings.get("fit_scope") == "global":
        selected = (
            "Full model"
            if not settings.get("min_plddt")
            else "Independent confidence selection"
        )
    else:
        selected = "Sequence-paired selection"
    cutoff = finite_number(value=settings.get("min_plddt"))
    confidence = f"fit pLDDT ≥{cutoff:g}" if cutoff else "no pLDDT fit filter"
    screen = " · pocket quality screen" if settings.get("quality_screen_only") else ""
    return f"{METHOD_LABELS.get(engine, engine)} · {selected} · {confidence}{screen}"


def pocket_rank(*, pocket: dict) -> int | None:
    """Return a recorded positive integer rank, without substituting a cavity ID.

    Args:
        pocket: Saved pocket record with review rank or method rank.

    Returns:
        Original rank, or None if neither recorded rank is valid.
    """
    for key in ("review_rank", "rank"):
        value = finite_number(value=pocket.get(key))
        if value is not None and value > 0 and value.is_integer():
            return int(value)
    return None


def ranked_pockets(*, pockets: list[dict]) -> list[dict]:
    """Order pockets by actual within-model rank without inventing absent ranks.

    Args:
        pockets: Unmodified pocket records.

    Returns:
        Sorted references to the original records; no scores or ranks are changed.
    """
    return sorted(
        pockets,
        key=lambda p: (
            p.get("sample_id", ""),
            pocket_rank(pocket=p) or math.inf,
            finite_number(value=p.get("pocket_id")) or math.inf,
        ),
    )


def dataset_summary(*, data: dict) -> dict:
    """Summarise imported confidence and sequence coverage without new analysis.

    Args:
        data: Loaded native resource.

    Returns:
        Counts and the median of available model-mean pLDDT values.
    """
    models, sequences = data["models"], data["sequences"]
    means = [
        number
        for model in models
        if (number := finite_number(value=model.get("mean_plddt"))) is not None
        and 0 <= number <= 100
    ]
    represented = {
        m.get("sequence_id") for m in models if m.get("sequence_id") in sequences
    }
    pockets = [p for p in data["pockets"] if p.get("method") == "fpocket"]
    return {
        "models": len(models),
        "with_coordinates": sum(bool(m.get("coordinates")) for m in models),
        "sequences": len(sequences),
        "represented_sequences": len(represented),
        "fasta_only_sequences": len(set(sequences) - represented),
        "median_model_plddt": median(means) if means else None,
        "models_with_confidence": len(means),
        "models_mean_below_50": sum(n < 50 for n in means),
        "fpocket_cavities": len(pockets),
        "locally_confident_cavities": sum(
            p.get("confidence_status") == "meets_local_confidence_rule" for p in pockets
        ),
    }


def similarity_figure(*, fits: list[dict], metric: str) -> go.Figure:
    """Draw a readable saved-fit matrix with full identifiers in hover information.

    Args:
        fits: Records already restricted to one complete analysis scope.
        metric: RMSD or Minimum TM-score.

    Returns:
        Directional display matrix; uncomputed cells and diagonals remain blank.
    """
    if metric not in {"RMSD", "Minimum TM-score"}:
        raise WorkbenchError("Choose RMSD or Minimum TM-score")
    valid = [r for r in fits if r.get("status") == "complete"]
    identifiers = sorted({r[k] for r in valid for k in ("reference", "mobile")})
    labels = model_labels(identifiers=identifiers)
    positions = {name: i for i, name in enumerate(identifiers)}
    values = np.full((len(identifiers), len(identifiers)), np.nan)
    for row in sorted(valid, key=lambda r: (r["reference"], r["mobile"])):
        a, b = positions[row["reference"]], positions[row["mobile"]]
        if a == b or not math.isnan(values[a, b]):
            continue
        scores = [
            finite_number(value=row.get(k)) for k in ("tm_reference", "tm_mobile")
        ]
        value = (
            finite_number(value=row.get("rmsd"))
            if metric == "RMSD"
            else min(scores) if all(n is not None for n in scores) else None
        )
        if value is not None:
            values[a, b] = value
    hover = [[[a, b] for b in identifiers] for a in identifiers]
    figure = go.Figure(
        go.Heatmap(
            z=values,
            x=[labels[n] for n in identifiers],
            y=[labels[n] for n in identifiers],
            customdata=hover,
            hoverongaps=False,
            colorscale=(
                "Viridis"
                if metric != "RMSD"
                else [[0, "#167D8D"], [0.5, "#F3F5F7"], [1, "#B74336"]]
            ),
            zmin=0 if metric != "RMSD" else None,
            zmax=1 if metric != "RMSD" else None,
            colorbar={"title": {"text": metric}},
            hovertemplate=(
                "Reference: %{customdata[0]}<br>Compared: %{customdata[1]}<br>"
            )
            + metric
            + ": %{z:.3f}<extra></extra>",
        )
    )
    figure.update_layout(
        height=max(500, min(1000, 230 + 11 * len(identifiers))),
        margin={"l": 140, "r": 45, "t": 40, "b": 160},
        title="Saved directional fits · hover for full identifiers",
        xaxis={
            "title": "Compared model",
            "tickangle": -55,
            "tickfont": {"size": 10},
            "automargin": True,
        },
        yaxis={
            "title": "Reference model",
            "autorange": "reversed",
            "tickfont": {"size": 10},
            "automargin": True,
        },
    )
    return figure


def evidence_figure(*, rows: list[dict], view: str) -> tuple[go.Figure, int]:
    """Plot matching rank-one or alternative-pocket metrics with explicit thresholds.

    Args:
        rows: Saved evidence restricted to one aligner and settings record.
        view: rank_one or alternatives.

    Returns:
        Figure and count omitted because the required numeric evidence is absent.
    """
    if view not in {"rank_one", "alternatives"}:
        raise WorkbenchError("Choose rank_one or alternatives")
    points = []
    y_key = "rank_one_overlap" if view == "rank_one" else "best_tested_overlap"
    for row in rows:
        x, y = finite_number(value=row.get("minimum_tm")), finite_number(
            value=row.get(y_key)
        )
        if x is None or y is None:
            continue
        supported = (
            row.get("rank_one_position") == "supported"
            if view == "rank_one"
            else row.get("best_tested_position_supported") is True
        )
        points.append(
            dict(
                row,
                x=x,
                y=y,
                decision="Position rule met" if supported else "Position rule not met",
            )
        )
    frame = pd.DataFrame(
        points,
        columns=list(
            dict.fromkeys(
                [k for r in points for k in r]
                + ["x", "y", "decision", "reference", "mobile", "scope"]
            )
        ),
    )
    figure = px.scatter(
        frame,
        x="x",
        y="y",
        color="decision",
        symbol="decision",
        color_discrete_map={
            "Position rule met": "#0072B2",
            "Position rule not met": "#D55E00",
        },
        symbol_map={"Position rule met": "circle", "Position rule not met": "x"},
        hover_data=["reference", "mobile", "scope"],
        labels={
            "x": "Minimum TM-score for this fit",
            "y": (
                "Rank-one pocket overlap"
                if view == "rank_one"
                else "Best tested member pocket overlap"
            ),
            "decision": "Pocket position",
        },
    )
    if rows:
        settings = rows[0].get("settings", {})
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except ValueError:
                LOGGER.warning("Evidence plot has unreadable threshold metadata")
                settings = {}
        if not isinstance(settings, dict):
            settings = {}
        for key, direction, label in (
            ("min_tm", "vertical", "Fold threshold"),
            ("min_overlap", "horizontal", "Overlap threshold"),
        ):
            threshold = finite_number(value=settings.get(key))
            if threshold is None or not 0 <= threshold <= 1:
                continue
            draw = figure.add_vline if direction == "vertical" else figure.add_hline
            draw(
                **{("x" if direction == "vertical" else "y"): threshold},
                line_dash="dash" if direction == "vertical" else "dot",
                line_color="#526375",
                annotation_text=label,
            )
    figure.update_traces(marker={"size": 8, "opacity": 0.7})
    figure.update_layout(
        height=470,
        margin={"l": 40, "r": 20, "b": 50, "t": 35},
        legend={"orientation": "h", "y": 1.12, "x": 0},
    )
    figure.update_xaxes(range=[-0.02, 1.02])
    figure.update_yaxes(range=[-0.02, 1.02])
    return figure, len(rows) - len(points)
