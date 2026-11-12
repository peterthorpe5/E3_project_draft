"""Interactive and exportable networks of audited DIAMOND assignments."""

from __future__ import annotations

from html import escape
import math
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree as ET

import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import qualitative

from .common import ResearchError

MAX_NODES = 360
OVERVIEW_GROUPS = 12
ID_COLUMNS = (
    "subcluster_id", "sequence_id", "audited_representative_id", "alignment_status",
)
METRICS = ("pident", "representative_coverage", "member_coverage", "evalue", "bitscore")
STATUS_LABELS = {
    "CENTROID_SELF": "DIAMOND centroid",
    "EXACT_THRESHOLDS_PASS": "Passed exact centroid audit",
    "EXACT_THRESHOLDS_FAIL": "Singleton after threshold failure",
    "NO_REALIGNMENT": "Singleton after missing realignment",
    "INVALID_REALIGNMENT": "Singleton after invalid realignment",
}


def load_network_members(*, path: Path, subclusters: Sequence[str]) -> pd.DataFrame:
    """Read a bounded, deterministic preview with the centroid of each chosen subcluster.

    Args:
        path: Verified membership Parquet or legacy TSV.
        subclusters: One or more exact audited subcluster IDs in display order.

    Returns:
        Displayed proteins, complete group sizes and exact centroid evidence.

    Raises:
        ResearchError: If the selection or audited membership schema is invalid.
    """
    if not 1 <= len(subclusters) <= OVERVIEW_GROUPS or len(set(subclusters)) != len(subclusters):
        raise ResearchError(f"Choose 1 to {OVERVIEW_GROUPS} distinct audited subclusters")
    fields = ", ".join([
        *ID_COLUMNS, *(f"try_cast({column} AS DOUBLE) AS {column}" for column in METRICS),
    ])
    with duckdb.connect(config={"threads": 1}) as connection:
        if path.suffix == ".parquet":
            relation = connection.read_parquet(str(path))
        else:
            relation = connection.read_csv(str(path), delimiter="\t", header=True, all_varchar=True)
        if not set((*ID_COLUMNS, *METRICS)).issubset(relation.columns):
            raise ResearchError("The saved membership lacks exact centroid audit fields.")
        relation.create_view(view_name="membership")
        return connection.execute(
            f"""
            WITH selected AS (
                SELECT unnest(?::VARCHAR[]) AS subcluster_id,
                       generate_subscripts(?::VARCHAR[], 1) AS display_order
            ), ranked AS (
                SELECT {fields}, display_order,
                       count(*) OVER (PARTITION BY subcluster_id) AS cluster_size,
                       row_number() OVER (
                           PARTITION BY subcluster_id
                           ORDER BY (sequence_id=audited_representative_id) DESC, sequence_id
                       ) AS display_rank
                FROM membership INNER JOIN selected USING(subcluster_id)
            )
            SELECT * EXCLUDE(display_order, display_rank),
                   CASE WHEN cluster_size=1 THEN 'Singleton'
                        WHEN sequence_id=audited_representative_id THEN 'Centroid'
                        ELSE 'Member' END AS role
            FROM ranked WHERE display_rank<=? ORDER BY display_order,display_rank
            """,
            [list(subclusters), list(subclusters), MAX_NODES // len(subclusters)],
        ).fetchdf()


def network_edges(*, members: pd.DataFrame) -> pd.DataFrame:
    """Select only measured, passing assignments between displayed proteins.

    Args:
        members: Bounded audited membership preview.

    Returns:
        One row per passing centroid-to-member link.
    """
    return members.loc[
        members["alignment_status"].eq("EXACT_THRESHOLDS_PASS")
        & members["sequence_id"].ne(members["audited_representative_id"])
        & members["audited_representative_id"].isin(members["sequence_id"])
    ]


def network_figure(*, members: pd.DataFrame) -> go.Figure:
    """Lay out disjoint centroid stars for pan, zoom and inspection in Plotly.

    Args:
        members: Bounded, ordered audited membership preview.

    Returns:
        Network figure with distinct centre, member and singleton markers.
    """
    figure = go.Figure()
    groups = list(members.groupby("subcluster_id", sort=False))
    columns = min(3, max(1, math.ceil(math.sqrt(len(groups)))))
    coordinates = {}
    colours = {}
    for index, (subcluster_id, group) in enumerate(groups):
        centre_x, centre_y = 2.9 * (index % columns), -2.9 * (index // columns)
        colours[subcluster_id] = qualitative.Safe[index % len(qualitative.Safe)]
        for offset, sequence_id in enumerate(group["sequence_id"]):
            # The loader puts the audited centroid first. A spiral separates larger groups.
            radius = 0.2 + 0.8 * math.sqrt(offset / len(group)) if offset else 0
            angle = offset * math.pi * (3 - math.sqrt(5))
            coordinates[sequence_id] = (
                centre_x + radius * math.cos(angle), centre_y + radius * math.sin(angle),
            )
        fields = str(group["audited_representative_id"].iloc[0]).split("|", 2)
        centroid = fields[1] if len(fields) == 3 and fields[0] in {"sp", "tr"} else fields[0]
        label = centroid if len(centroid) <= 24 else centroid[:21] + "…"
        figure.add_annotation(
            x=centre_x, y=centre_y - 1.23,
            text=f"{escape(label)} · {group['cluster_size'].iloc[0]:,}",
            showarrow=False, font={"size": 12, "color": "#475569"},
        )

    edge_x, edge_y = [], []
    for row in network_edges(members=members).itertuples(index=False):
        start_x, start_y = coordinates[row.audited_representative_id]
        end_x, end_y = coordinates[row.sequence_id]
        edge_x.extend((start_x, end_x, None))
        edge_y.extend((start_y, end_y, None))
    figure.add_scatter(
        x=edge_x, y=edge_y, mode="lines", line={"color": "#91A5BA", "width": 1.2},
        hoverinfo="skip", showlegend=False,
    )
    for role, symbol, size in (("Centroid", "diamond", 16), ("Member", "circle", 9),
                               ("Singleton", "circle-open", 14)):
        subset = members.loc[members["role"].eq(role)]
        if subset.empty:
            continue
        x, y = zip(*(coordinates[identifier] for identifier in subset["sequence_id"]), strict=True)
        hover = []
        for row in subset.itertuples(index=False):
            status = STATUS_LABELS.get(row.alignment_status, row.alignment_status)
            detail = (
                f"<b>{escape(row.sequence_id)}</b><br>{escape(str(status))}"
                f"<br>Subcluster {escape(row.subcluster_id)}"
            )
            if row.alignment_status == "EXACT_THRESHOLDS_PASS":
                detail += (
                    f"<br>Centroid {escape(row.audited_representative_id)}"
                    f"<br>Exact identity {row.pident:.1f}%"
                    f"<br>Centroid coverage {row.representative_coverage:.1f}%"
                    f"<br>Member coverage {row.member_coverage:.1f}%"
                    f"<br>E-value {row.evalue:.2g} · Bitscore {row.bitscore:.1f}"
                )
            hover.append(detail)
        figure.add_scatter(
            name=role, x=x, y=y, mode="markers", hovertext=hover,
            hovertemplate="%{hovertext}<extra></extra>",
            marker={
                "symbol": symbol, "size": size, "line": {"width": 1.2, "color": "#334155"},
                "color": [colours[group_id] for group_id in subset["subcluster_id"]],
            },
        )
    rows = max(1, math.ceil(len(groups) / columns))
    figure.update_layout(
        height=max(440, 200 * rows), dragmode="pan", hovermode="closest",
        plot_bgcolor="#F8FAFC", margin={"l": 12, "r": 12, "t": 18, "b": 30},
        xaxis={"visible": False, "range": [-1.35, 2.9 * (columns - 1) + 1.35]},
        yaxis={
            "visible": False, "range": [-2.9 * (rows - 1) - 1.55, 1.25],
            "scaleanchor": "x", "scaleratio": 1,
        },
        legend={"orientation": "h", "y": -0.02},
    )
    return figure


def network_graphml(*, members: pd.DataFrame) -> bytes:
    """Export the displayed nodes and measured edges for Cytoscape.

    Args:
        members: The same bounded audited membership used by the figure.

    Returns:
        UTF-8 GraphML with original protein IDs and exact alignment attributes.
    """
    root = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    node_fields = ("sequence_id", "subcluster_id", "role", "alignment_status")
    for domain, names, kind in (("node", node_fields, "string"), ("edge", METRICS, "double")):
        for name in names:
            ET.SubElement(root, "key", {
                "id": name, "for": domain, "attr.name": name, "attr.type": kind,
            })
    graph = ET.SubElement(root, "graph", id="subclusters", edgedefault="undirected")
    node_ids = {}
    for index, row in enumerate(members.itertuples(index=False)):
        node_ids[row.sequence_id] = identifier = f"protein_{index}"
        node = ET.SubElement(graph, "node", id=identifier)
        for name in node_fields:
            ET.SubElement(node, "data", key=name).text = str(getattr(row, name))
    for row in network_edges(members=members).itertuples(index=False):
        edge = ET.SubElement(
            graph, "edge", source=node_ids[row.audited_representative_id],
            target=node_ids[row.sequence_id],
        )
        for name in METRICS:
            value = getattr(row, name)
            if pd.notna(value) and math.isfinite(value):
                ET.SubElement(edge, "data", key=name).text = str(value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
