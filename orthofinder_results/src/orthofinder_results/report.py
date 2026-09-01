"""Offline interactive HTML reporting for OrthoFinder result resources."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .errors import PublicationError
from .io_utils import atomic_write_text

_LOGGER = logging.getLogger("orthofinder_results.report")
_MAX_BROWSER_DISTANCE_PAIRS = 1_000_000

_REPORT_GROUP_FIELDS = (
    "group_type",
    "hierarchy_node",
    "group_id",
    "legacy_orthogroup_id",
    "gene_tree_parent_clade",
    "member_count",
    "species_count",
    "single_copy_species_count",
    "max_copies_per_species",
    "mean_copies_per_species",
    "is_singleton",
)
_REPORT_GROUP_SPECIES_FIELDS = (
    "group_type",
    "hierarchy_node",
    "group_id",
    "species_label",
    "species_member_count",
    "member_fraction",
)
_REPORT_DISTANCE_STATISTIC_FIELDS = (
    "group_type",
    "hierarchy_node",
    "group_id",
    "distance_method",
    "computation_status",
    "member_identifier_resolution",
    "total_member_count",
    "sampled_member_count",
    "distance_pair_count",
    "unresolved_pair_count",
    "minimum_distance",
    "q05_distance",
    "q25_distance",
    "median_distance",
    "mean_distance",
    "q75_distance",
    "q95_distance",
    "maximum_distance",
    "population_stddev_distance",
    "mean_comparable_sites",
    "source_file",
    "failure_reason",
)


def build_interactive_report(
    *,
    output_path: Path,
    run_metadata: Mapping[str, Any],
    group_statistics: Sequence[Mapping[str, Any]],
    network_group_statistics: Sequence[Mapping[str, Any]],
    memberships: Sequence[Mapping[str, Any]],
    group_species_statistics: Sequence[Mapping[str, Any]],
    distances: Sequence[Mapping[str, Any]],
    distance_statistics: Sequence[Mapping[str, Any]],
    total_group_statistic_count: int,
    total_membership_count: int,
    max_network_groups: int,
    max_network_members: int,
    nearest_neighbours: int,
    overview_statistics: Mapping[str, Any] | None = None,
    tree_nodes: Sequence[Mapping[str, Any]] = (),
    tree_edges: Sequence[Mapping[str, Any]] = (),
    sequence_identifiers: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Write a self-contained Cytoscape-style results browser.

    Args:
        output_path: Final HTML path.
        run_metadata: Run version, adapter and capability metadata.
        group_statistics: Group rows embedded in the searchable summary table.
        network_group_statistics: Complete summaries for network-selected groups.
        memberships: Bounded member rows for network-rendered groups.
        group_species_statistics: Full per-species counts for rendered groups.
        distances: Bounded pairwise distances for network-rendered groups.
        distance_statistics: Per-group distance summaries.
        total_group_statistic_count: Complete analytical group count.
        total_membership_count: Complete analytical membership count.
        max_network_groups: Declared maximum interactive networks.
        max_network_members: Declared maximum nodes per network.
        nearest_neighbours: Maximum nearest-neighbour edges retained per node.
        overview_statistics: Complete-authority preaggregates by group level.
        tree_nodes: Normalised nodes for report-selected resolved gene trees.
        tree_edges: Normalised edges for report-selected resolved gene trees.
        sequence_identifiers: Identifier aliases for report-selected members.

    Raises:
        ValueError: If browser-safety limits are invalid.
        PublicationError: If the bundled network assets cannot be found.
    """

    if max_network_groups <= 0:
        raise ValueError("max_network_groups must be positive.")
    if max_network_members < 2:
        raise ValueError("max_network_members must be at least two.")
    if nearest_neighbours <= 0:
        raise ValueError("nearest_neighbours must be positive.")
    pair_budget = (
        max_network_groups * max_network_members * (max_network_members - 1) // 2
    )
    if pair_budget > _MAX_BROWSER_DISTANCE_PAIRS:
        raise ValueError(
            "The requested network bounds exceed the browser pair-distance budget."
        )
    embedded_group_keys = {
        _group_key(row) for row in (*group_statistics, *network_group_statistics)
    }
    embedded_distance_statistics = [
        row for row in distance_statistics if _group_key(row) in embedded_group_keys
    ]
    vis_javascript, vis_stylesheet = _load_vis_network_assets()
    networks = _build_network_payload(
        group_statistics=network_group_statistics,
        memberships=memberships,
        distances=distances,
        distance_statistics=embedded_distance_statistics,
        max_groups=max_network_groups,
        max_members=max_network_members,
        nearest_neighbours=nearest_neighbours,
        tree_nodes=tree_nodes,
        tree_edges=tree_edges,
        sequence_identifiers=sequence_identifiers,
    )
    payload = {
        "run": dict(run_metadata),
        "groupStatistics": [
            _compact_record(row=row, fields=_REPORT_GROUP_FIELDS)
            for row in group_statistics
        ],
        "networkGroupStatistics": [
            _compact_record(row=row, fields=_REPORT_GROUP_FIELDS)
            for row in network_group_statistics
        ],
        "groupSpeciesStatistics": [
            _compact_record(row=row, fields=_REPORT_GROUP_SPECIES_FIELDS)
            for row in group_species_statistics
        ],
        "distanceStatistics": [
            _compact_record(row=row, fields=_REPORT_DISTANCE_STATISTIC_FIELDS)
            for row in embedded_distance_statistics
        ],
        "overviewStatistics": dict(overview_statistics or {}),
        "networks": networks,
        "limits": {
            "embeddedGroupStatisticCount": len(group_statistics),
            "totalGroupStatisticCount": total_group_statistic_count,
            "embeddedMembershipCount": len(memberships),
            "totalMembershipCount": total_membership_count,
            "maxNetworkGroups": max_network_groups,
            "maxNetworkMembers": max_network_members,
            "nearestNeighbours": nearest_neighbours,
        },
    }
    title = html.escape(str(run_metadata.get("run_id", "OrthoFinder results")))
    payload_json = _safe_script_json(payload)
    payload_size = len(payload_json.encode("utf-8"))
    _LOGGER.info(
        "HTML payload prepared: groups=%s, network_groups=%s, memberships=%s, "
        "distance_rows=%s, payload_bytes=%s.",
        f"{len(group_statistics):,}",
        f"{len(networks):,}",
        f"{len(memberships):,}",
        f"{len(distances):,}",
        f"{payload_size:,}",
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>OrthoFinder results — {title}</title>
  <style>{vis_stylesheet}</style>
  <style>
    :root {{ --ink:#172033; --muted:#586174; --panel:#ffffff; --line:#d9deea;
      --accent:#3558c8; --soft:#f4f6fb; --warn:#9a5a00; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:var(--soft);
      font-family:Arial,Helvetica,sans-serif; line-height:1.35; }}
    header {{ padding:1.2rem 1.5rem; color:white;
      background:linear-gradient(120deg,#233b82,#2e70a5); }}
    header h1 {{ margin:0 0 .25rem; font-size:1.55rem; }}
    header p {{ margin:0; opacity:.9; }}
    main {{ max-width:1600px; margin:auto; padding:1rem; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
      gap:.7rem; margin-bottom:1rem; }}
    .card,.panel {{ background:var(--panel); border:1px solid var(--line);
      border-radius:10px; box-shadow:0 2px 8px rgba(23,32,51,.06); }}
    .card {{ padding:.75rem 1rem; }}
    .card .label {{ color:var(--muted); font-size:.78rem; text-transform:uppercase; }}
    .card .value {{ font-size:1.25rem; font-weight:700; overflow-wrap:anywhere; }}
    .panel {{ padding:1rem; margin-bottom:1rem; }}
    .panel h2 {{ margin:.1rem 0 .8rem; font-size:1.15rem; }}
    .panel h3 {{ margin:.1rem 0 .35rem; font-size:.95rem; }}
    .controls {{ display:flex; flex-wrap:wrap; gap:.65rem; align-items:end; }}
    label {{ display:flex; flex-direction:column; gap:.25rem; color:var(--muted);
      font-size:.8rem; }}
    label.check {{ flex-direction:row; align-items:center; gap:.4rem; padding:.5rem .2rem; }}
    label.check input {{ width:auto; margin:0; }}
    select,input,button {{ font:inherit; padding:.48rem .58rem; border:1px solid #aeb7ca;
      border-radius:6px; background:white; color:var(--ink); }}
    button {{ cursor:pointer; background:#eef2ff; border-color:#9dafef; }}
    .network-section {{ border:1px solid var(--line); border-radius:9px; padding:.8rem;
      margin-top:1rem; }}
    .network-section h3 {{ font-size:1.05rem; }}
    .network-canvas {{ height:580px; border:1px solid var(--line); border-radius:8px;
      margin-top:.6rem; background:#fff; }}
    .plot-canvas {{ min-height:500px; border:1px solid var(--line); border-radius:8px;
      margin-top:.6rem; background:#fff; overflow:auto; }}
    .plot-canvas svg {{ display:block; min-width:760px; width:100%; }}
    .matrix-canvas {{ overflow:auto; margin-top:.6rem; }}
    .matrix-canvas canvas {{ display:block; width:min(760px,100%); height:auto;
      border:1px solid var(--line); background:#fff; }}
    .network-support-grid {{ display:grid; grid-template-columns:repeat(3,minmax(240px,1fr));
      gap:1rem; margin-top:1rem; }}
    .detail {{ border-left:1px solid var(--line); padding-left:1rem; overflow-wrap:anywhere; }}
    .detail dl {{ display:grid; grid-template-columns:auto 1fr; gap:.35rem .65rem; }}
    .detail dt {{ font-weight:700; }} .detail dd {{ margin:0; }}
    .notice {{ color:var(--warn); background:#fff7e8; border:1px solid #eed09e;
      padding:.65rem; border-radius:7px; margin:.7rem 0; }}
    .quality-badge {{ display:inline-block; padding:.22rem .48rem; border-radius:999px;
      font-size:.75rem; font-weight:700; letter-spacing:.03em; margin-right:.45rem; }}
    .quality-badge.poor {{ color:#7b1420; background:#ffe8eb; border:1px solid #e8a8b0; }}
    .quality-badge.moderate {{ color:#7a4e00; background:#fff2d2; border:1px solid #e8c66e; }}
    .quality-badge.better {{ color:#155b3b; background:#e5f7ee; border:1px solid #8cc9aa; }}
    .network-key {{ display:flex; flex-wrap:wrap; gap:.45rem 1rem; margin:.65rem 0;
      color:var(--muted); font-size:.8rem; }}
    .key-item {{ display:flex; align-items:center; gap:.35rem; }}
    .line-key {{ display:inline-block; width:30px; border-top:2px solid #7786a8; }}
    .line-key.connector {{ border-top:2px dashed #b7791f; }}
    .medoid-key {{ color:#b8860b; font-size:1.35rem; line-height:1; }}
    .legend {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
      gap:.25rem; max-height:220px; overflow:auto; margin-top:.45rem; }}
    .legend-item {{ display:flex; align-items:center; gap:.4rem; padding:.3rem .4rem;
      border:1px solid #e1e5ed; border-radius:5px; background:#fff; text-align:left;
      min-width:0; }}
    .legend-item:hover {{ background:#f3f6fd; }}
    .legend-swatch {{ width:14px; height:14px; flex:0 0 14px; border:1px solid #4b5563;
      border-radius:50%; }}
    .legend-label {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .fatal {{ color:#7b1420; background:#fff0f2; border:1px solid #e8a8b0;
      padding:.8rem; border-radius:7px; margin-bottom:1rem; white-space:pre-wrap; }}
    .histogram {{ display:flex; align-items:flex-end; gap:3px; height:130px;
      border-bottom:1px solid #9aa4b7; padding-top:.5rem; }}
    .bar {{ flex:1; min-width:4px; background:#5577d5; border-radius:3px 3px 0 0; }}
    .chart-grid {{ display:grid; grid-template-columns:repeat(2,minmax(300px,1fr)); gap:.8rem; }}
    .chart-card {{ border:1px solid var(--line); border-radius:8px; padding:.75rem; min-width:0; }}
    .chart-card.wide {{ grid-column:1 / -1; }}
    .chart {{ min-height:250px; }}
    .chart svg {{ width:100%; height:250px; display:block; overflow:visible; }}
    .chart .axis {{ stroke:#8993a8; stroke-width:1; }}
    .chart .grid {{ stroke:#e5e8ef; stroke-width:1; }}
    .chart text {{ fill:var(--muted); font-size:11px; }}
    .chart .plot-bar {{ fill:#5577d5; }}
    .chart .plot-point {{ fill:#d7633c; fill-opacity:.65; stroke:#8b3219; stroke-width:.45; }}
    .pcoa-edge {{ stroke:#a7afbf; stroke-width:.8; }}
    .pcoa-edge.connector {{ stroke:#b7791f; stroke-dasharray:5 4; }}
    .protein-point {{ stroke:#4b5563; stroke-width:1; cursor:pointer; }}
    .protein-point.medoid {{ stroke:#b8860b; stroke-width:3; }}
    .protein-point.selected {{ stroke:#111827; stroke-width:4; }}
    .tree-edge {{ fill:none; stroke:#68748b; stroke-width:1; }}
    .tree-leaf {{ cursor:pointer; stroke:#4b5563; stroke-width:.8; }}
    .tree-leaf.medoid {{ stroke:#b8860b; stroke-width:2.5; }}
    .tree-leaf.selected {{ stroke:#111827; stroke-width:3.5; }}
    .diagnostics-table tr[data-group-key] {{ cursor:pointer; }}
    .selected-row td {{ background:#e8eefc; }}
    .heatmap th.rotate {{ height:145px; vertical-align:bottom; padding:0 .2rem .35rem; }}
    .heatmap th.rotate > span {{ display:inline-block; writing-mode:vertical-rl;
      transform:rotate(180deg); max-height:135px; overflow:hidden; text-overflow:ellipsis; }}
    .heatmap td.copy {{ text-align:center; min-width:28px; font-variant-numeric:tabular-nums; }}
    .scroll {{ overflow:auto; max-height:500px; border:1px solid var(--line); }}
    table {{ width:100%; border-collapse:collapse; font-size:.82rem; }}
    th,td {{ padding:.42rem .5rem; text-align:left; border-bottom:1px solid #e6e9f1;
      white-space:nowrap; }}
    th {{ position:sticky; top:0; background:#edf1f8; z-index:2; }}
    tr:hover td {{ background:#f5f7fd; }}
    .pager {{ display:flex; gap:.5rem; align-items:center; margin-top:.6rem; }}
    .small {{ color:var(--muted); font-size:.78rem; }}
    @media (max-width:900px) {{ .network-support-grid,.chart-grid {{ grid-template-columns:1fr; }}
      .detail {{ border-left:0; padding-left:0; }} .network-canvas {{ height:480px; }}
      .plot-canvas {{ min-height:420px; }} }}
  </style>
  <script>{vis_javascript}</script>
</head>
<body>
<header><h1>OrthoFinder results interrogation</h1><p>Run {title} · offline interactive report</p></header>
<main>
  <div id="render-error" class="fatal" hidden></div>
  <section class="cards" id="run-cards"></section>
  <section class="panel">
    <h2>Run-wide visual summary</h2>
    <div class="controls"><label>Group level<select id="overview-level"></select></label></div>
    <div id="overview-notice" class="notice"></div>
    <div class="chart-grid">
      <article class="chart-card"><h3>Complete cluster-size distribution</h3>
        <div id="cluster-size-chart" class="chart" role="img" aria-label="Cluster-size histogram"></div>
        <p class="small">Exact full-authority log₂ bins; the level-specific denominator is shown above.</p></article>
      <article class="chart-card"><h3>Complete species-breadth distribution</h3>
        <div id="species-breadth-chart" class="chart" role="img" aria-label="Species-breadth histogram"></div>
        <p class="small">Exact number of represented species per group in the complete authority.</p></article>
      <article class="chart-card"><h3>Complete copy-number complexity</h3>
        <div id="copy-complexity-chart" class="chart" role="img" aria-label="Maximum copies per species histogram"></div>
        <p class="small">Exact maximum paralogue count in any one species; log₂ bins.</p></article>
      <article class="chart-card"><h3>Cluster size versus species breadth — embedded sample</h3>
        <div id="size-breadth-chart" class="chart" role="img" aria-label="Cluster size versus species breadth scatter plot"></div>
        <p class="small">Up to 2,000 deterministic embedded rows; this panel is sampled and the y-axis is log-scaled.</p></article>
      <article class="chart-card"><h3>Mean distance versus analytical group size — selected pilot</h3>
        <div id="distance-coverage-chart" class="chart" role="img" aria-label="Mean distance versus analytical group size scatter plot"></div>
        <p class="small">Selected distance-pilot groups only. Distances use their explicit displayed sample; x uses the full analytical group size.</p></article>
      <article class="chart-card"><h3>Exact copy counts for displayed network groups</h3>
        <label>Cell scale<select id="copy-heatmap-scale"><option value="raw">Raw count</option>
          <option value="log1p">log1p(count)</option><option value="presence">Presence/absence</option></select></label>
        <div id="species-heatmap" class="scroll heatmap"></div>
        <p class="small">Rows: groups · columns: species · cells: exact protein-copy counts.
          White-to-red shading follows the selected display scale; hover retains raw counts.</p></article>
      <article class="chart-card wide"><h3>Projection and sparse-topology diagnostics — displayed pilot</h3>
        <div class="scroll diagnostics-table"><table><thead><tr><th>Group</th><th>Analytical members</th>
          <th>Displayed members</th><th>PCoA 1+2 inertia</th><th>Distance correlation</th>
          <th>Normalised stress</th><th>Fit guidance</th><th>Raw kNN components</th></tr></thead>
          <tbody id="projection-diagnostics-table"></tbody></table></div>
        <p class="small">Fit categories are conservative display guidance, not biological acceptance criteria.
          Select a row to open the corresponding group below.</p></article>
    </div>
  </section>
  <section class="panel">
    <h2>Within-group evolutionary and protein-distance views</h2>
    <p class="small">Each selector entry is one OrthoFinder group at the stated authority and hierarchy level. Node fill colour denotes species;
      the gold star denotes the medoid of the displayed distance sample. PCoA is a
      diagnostic projection, the phylogram retains tree branch lengths, the matrix
      retains exact supplied distances, and force-directed spacing is exploratory.</p>
    <div class="controls">
      <label>Group<select id="group-select"></select></label>
      <label>Find member<input id="member-search" type="search" placeholder="Exact or partial ID"></label>
      <label class="check"><input id="show-labels" type="checkbox">Show all labels</label>
      <label class="check"><input id="show-distance-edges" type="checkbox">Show edges on PCoA</label>
      <label class="check"><input id="show-connectors" type="checkbox" checked>Show component connectors</label>
      <button id="fit-topology-network" type="button">Fit topology</button>
    </div>
    <div id="network-notice" class="notice"></div>
    <div class="network-key">
      <span class="key-item"><span class="line-key"></span>Nearest-neighbour edge</span>
      <span class="key-item"><span class="line-key connector"></span>Layout-only component connector</span>
      <span class="key-item"><span class="medoid-key">★</span>Sample medoid</span>
      <span>PCoA edges are hidden by default so they cannot obscure projection geometry.
        Force-directed spacing is exploratory only.</span>
    </div>
    <article class="network-section">
      <h3>1. Diagnostic distance map (PCoA)</h3>
      <p class="small">Axes use one equal geometric scale and show their per-group retained
        positive inertia. Screen spacing is an approximation, not the exact distance authority.</p>
      <div id="distance-network-notice" class="notice"></div>
      <div id="distance-network" class="plot-canvas"></div>
      <details><summary>Projection-quality detail and Shepard plot</summary>
        <p class="small">Display guidance: poor if axes 1+2 retain &lt;25% of positive inertia,
          correlation is &lt;0.60 or undefined, or stress is &gt;0.60; moderate if not poor but
          retained inertia is &lt;40%, correlation is &lt;0.80, or stress is &gt;0.45. Other maps
          are labelled better, not validated. These are not biological gates.</p>
        <div id="shepard-notice" class="small"></div>
        <div id="shepard-chart" class="chart" role="img" aria-label="Input versus projected distance Shepard plot"></div>
      </details>
    </article>
    <article class="network-section">
      <h3>2. Branch-length phylogram</h3>
      <p class="small">This is the resolved gene tree pruned to the displayed proteins.
        Horizontal branch lengths retain the original patristic-distance authority;
        vertical ordering represents topology only.</p>
      <div id="phylogram-notice" class="notice"></div>
      <div id="phylogram" class="plot-canvas"></div>
    </article>
    <article class="network-section">
      <h3>3. Exact displayed distance matrix</h3>
      <p class="small">Every cell retains one exact supplied pairwise distance. The order follows
        the pruned tree when fully resolved and otherwise uses lexical member identifiers.</p>
      <div id="distance-matrix-notice" class="notice"></div>
      <div id="distance-matrix" class="matrix-canvas"></div>
      <div id="distance-matrix-detail" class="small">Move over a cell to inspect its exact value.</div>
    </article>
    <article class="network-section">
      <h3>4. Force-directed neighbour topology</h3>
      <p class="small">This Cytoscape-style view is useful for exploring local relationships
        and topology. Its screen spacing is not a quantitative distance scale.</p>
      <div id="topology-network-notice" class="notice"></div>
      <div id="topology-network" class="network-canvas"></div>
    </article>
    <div class="network-support-grid">
      <aside>
        <h2>Selected member</h2><div id="node-detail" class="small">Click a node to inspect it.</div>
      </aside>
      <aside class="detail">
        <h2>Distance distribution</h2><div id="distance-summary" class="small"></div>
        <div id="histogram" class="histogram" aria-label="Distance histogram"></div>
      </aside>
      <aside class="detail">
        <h2>Species colours</h2>
        <input id="species-filter" type="search" placeholder="Filter species">
        <div id="species-legend" class="legend"></div>
      </aside>
    </div>
    <h2>Rendered members</h2>
    <div class="scroll"><table><thead><tr><th>Member</th><th>Species</th><th>Group</th></tr></thead>
      <tbody id="member-table"></tbody></table></div>
  </section>
  <section class="panel">
    <h2>Group statistics</h2>
    <div id="statistics-notice" class="notice"></div>
    <div class="controls"><label>Filter groups<input id="group-filter" type="search"
      placeholder="Group, node or type"></label></div>
    <div class="scroll"><table><thead><tr><th>Type</th><th>Node</th><th>Group</th>
      <th>Members</th><th>Species</th><th>Max copies/species</th><th>Mean copies/species</th></tr></thead>
      <tbody id="statistics-table"></tbody></table></div>
    <div class="pager"><button id="previous-page" type="button">Previous</button>
      <span id="page-status" class="small"></span><button id="next-page" type="button">Next</button></div>
  </section>
  <p class="small">This report is an exploratory, bounded visualisation. The checksum-bound
    compressed TSV, Parquet and DuckDB resources are the complete analytical authorities.</p>
</main>
<script id="orthofinder-results-data" type="application/json">{payload_json}</script>
<script>
"use strict";
const reportError=document.getElementById("render-error");
function showRenderError(error){{reportError.hidden=false;reportError.textContent=
  "The interactive report could not finish rendering. Details: "+String(error&&error.message||error);}}
window.addEventListener("error",event=>showRenderError(event.error||event.message));
let DATA;
try{{DATA=JSON.parse(document.getElementById("orthofinder-results-data").textContent);}}
catch(error){{showRenderError(error);throw error;}}
const number=v=>v===null||v===undefined||v===""?"not available":Number(v).toLocaleString();
const fixed=v=>v===null||v===undefined||v===""?"not available":Number(v).toFixed(4);
const runCounts=DATA.run.counts||{{}};
const cards=[
  ["Run",DATA.run.run_id],["OrthoFinder",DATA.run.orthofinder_version],
  ["Report package",DATA.run.package_version||""],
  ["Resource package",DATA.run.resource_package_version||DATA.run.package_version||""],
  ["Adapter",DATA.run.adapter_name],["Primary groups",DATA.run.primary_group_authority],
  ["Species",number(runCounts.species_count)],
  ["Analytical groups",number(DATA.limits.totalGroupStatisticCount)],
  ["Analytical memberships",number(DATA.limits.totalMembershipCount)],
  ["Distance groups",number(runCounts.distance_group_count||DATA.distanceStatistics.length)]
];
document.getElementById("run-cards").innerHTML=cards.map(([label,value])=>
  `<div class="card"><div class="label">${{escapeHtml(label)}}</div><div class="value">${{escapeHtml(value)}}</div></div>`).join("");
document.getElementById("statistics-notice").textContent=
  `Embedded ${{number(DATA.limits.embeddedGroupStatisticCount)}} of ${{number(DATA.limits.totalGroupStatisticCount)}} group summaries. `+
  `Complete rows remain in the analytical outputs.`;
const overviewLevel=document.getElementById("overview-level");
const levelRows=[...DATA.groupStatistics,...DATA.networkGroupStatistics];
const aggregateLevels=Object.entries(DATA.overviewStatistics||{{}}).map(([key,row])=>
  ({{key,type:row.groupType,node:row.hierarchyNode}}));
const levelRecords=[...new Map([...aggregateLevels,...levelRows.map(row=>{{const key=`${{row.group_type}}|${{row.hierarchy_node}}`;
  return {{key,type:row.group_type,node:row.hierarchy_node}};}})].map(row=>[row.key,row])).values()].sort((a,b)=>a.key.localeCompare(b.key));
levelRecords.forEach(level=>{{const option=document.createElement("option");option.value=level.key;
  option.textContent=level.node?`${{level.type}} · ${{level.node}}`:level.type;overviewLevel.appendChild(option);}});
const preferredLevel=levelRecords.find(level=>level.type===DATA.run.primary_group_authority&&level.node==="N0")||
  levelRecords.find(level=>level.type===DATA.run.primary_group_authority)||levelRecords[0];
if(preferredLevel)overviewLevel.value=preferredLevel.key;
function selectedOverviewRows(){{return DATA.groupStatistics.filter(row=>
  `${{row.group_type}}|${{row.hierarchy_node}}`===overviewLevel.value);}}
function plotMessage(target,message){{document.getElementById(target).innerHTML=`<p class="small">${{escapeHtml(message)}}</p>`;}}
function renderAggregateHistogram(targetId,metric,xTitle,yTitle){{const counts=(metric?.counts||[]).map(Number),labels=metric?.labels||[];
  if(!counts.length){{plotMessage(targetId,"No complete-authority values are available for this group level.");return;}}
  const width=640,height=250,left=68,right=10,top=10,bottom=62,plotWidth=width-left-right,plotHeight=height-top-bottom;
  const peak=Math.max(...counts,1),barWidth=plotWidth/counts.length;
  const bars=counts.map((count,index)=>{{const h=plotHeight*count/peak,x=left+index*barWidth,y=top+plotHeight-h;
    return `<rect class="plot-bar" x="${{x+1}}" y="${{y}}" width="${{Math.max(1,barWidth-2)}}" height="${{h}}"><title>${{escapeHtml(labels[index])}}: ${{number(count)}} groups</title></rect>`;}}).join("");
  const ticks=[0,.25,.5,.75,1].map(fraction=>{{const y=top+plotHeight*(1-fraction),value=Math.round(peak*fraction);
    return `<line class="grid" x1="${{left}}" y1="${{y}}" x2="${{width-right}}" y2="${{y}}"/><text x="${{left-5}}" y="${{y+4}}" text-anchor="end">${{number(value)}}</text>`;}}).join("");
  const step=Math.max(1,Math.ceil(labels.length/7)),xlabels=labels.map((label,index)=>index%step?"":
    `<text x="${{left+(index+.5)*barWidth}}" y="${{height-39}}" text-anchor="middle">${{escapeHtml(label)}}</text>`).join("");
  const titles=`<text x="${{left+plotWidth/2}}" y="${{height-8}}" text-anchor="middle">${{escapeHtml(xTitle)}}</text>`+
    `<text transform="translate(14 ${{top+plotHeight/2}}) rotate(-90)" text-anchor="middle">${{escapeHtml(yTitle)}}</text>`;
  document.getElementById(targetId).innerHTML=`<svg viewBox="0 0 ${{width}} ${{height}}" aria-hidden="true">${{ticks}}${{bars}}`+
    `<line class="axis" x1="${{left}}" y1="${{top+plotHeight}}" x2="${{width-right}}" y2="${{top+plotHeight}}"/>${{xlabels}}${{titles}}</svg>`;}}
function sampledRows(rows,maximum){{if(rows.length<=maximum)return rows.slice();const ordered=rows.slice().sort((a,b)=>
  `${{a.group_type}}|${{a.hierarchy_node}}|${{a.group_id}}`.localeCompare(`${{b.group_type}}|${{b.hierarchy_node}}|${{b.group_id}}`));
  const stride=ordered.length/maximum;return Array.from({{length:maximum}},(_,index)=>ordered[Math.floor(index*stride)]);}}
function renderScatter(targetId,rows,xField,yField,logY,titleFields,xTitle,yTitle){{const plotted=sampledRows(rows,2000).map(row=>
  ({{row,x:Number(row[xField]),y:Number(row[yField])}})).filter(point=>Number.isFinite(point.x)&&Number.isFinite(point.y));
  if(!plotted.length){{plotMessage(targetId,"No plottable values are available for this group level.");return;}}
  const width=640,height=250,left=72,right=12,top=12,bottom=58,plotWidth=width-left-right,plotHeight=height-top-bottom;
  const maxX=Math.max(...plotted.map(point=>point.x),1),transformY=value=>logY?Math.log2(Math.max(1,value)):value;
  const maxY=Math.max(...plotted.map(point=>transformY(point.y)),1);
  const points=plotted.map(point=>{{const x=left+plotWidth*point.x/maxX,y=top+plotHeight*(1-transformY(point.y)/maxY);
    const title=titleFields.map(field=>`${{field}}=${{point.row[field]??""}}`).join(" · ");
    return `<circle class="plot-point" cx="${{x}}" cy="${{y}}" r="3"><title>${{escapeHtml(title)}}</title></circle>`;}}).join("");
  const grid=[0,.25,.5,.75,1].map(fraction=>{{const y=top+plotHeight*(1-fraction),value=logY?Math.round(2**(maxY*fraction)):fixed(maxY*fraction);
    return `<line class="grid" x1="${{left}}" y1="${{y}}" x2="${{width-right}}" y2="${{y}}"/><text x="${{left-5}}" y="${{y+4}}" text-anchor="end">${{value}}</text>`;}}).join("");
  const titles=`<text x="${{left+plotWidth/2}}" y="${{height-8}}" text-anchor="middle">${{escapeHtml(xTitle)}}</text>`+
    `<text transform="translate(14 ${{top+plotHeight/2}}) rotate(-90)" text-anchor="middle">${{escapeHtml(yTitle)}}</text>`;
  document.getElementById(targetId).innerHTML=`<svg viewBox="0 0 ${{width}} ${{height}}" aria-hidden="true">${{grid}}${{points}}`+
    `<line class="axis" x1="${{left}}" y1="${{top+plotHeight}}" x2="${{width-right}}" y2="${{top+plotHeight}}"/>`+
    `<text x="${{left}}" y="${{height-32}}">0</text><text x="${{width-right}}" y="${{height-32}}" text-anchor="end">${{number(maxX)}}</text>${{titles}}</svg>`;}}
function renderHeatmap(rows){{const target=document.getElementById("species-heatmap"),level=overviewLevel.value;
  const selected=DATA.groupSpeciesStatistics.filter(row=>`${{row.group_type}}|${{row.hierarchy_node}}`===level);
  if(!selected.length){{target.innerHTML='<p class="small">No network-selected groups are available at this level.</p>';return;}}
  const species=[...new Set(selected.map(row=>row.species_label))].sort(),groups=[...new Set(selected.map(row=>row.group_id))].sort();
  const counts=new Map(selected.map(row=>[`${{row.group_id}}\u0000${{row.species_label}}`,Number(row.species_member_count)]));
  const scaleMode=document.getElementById("copy-heatmap-scale").value;
  const scaled=value=>scaleMode==="presence"?(value?1:0):(scaleMode==="log1p"?Math.log1p(value):value);
  const peak=Math.max(...[...counts.values()].map(scaled),1),head=species.map(label=>`<th class="rotate" title="${{escapeHtml(label)}}"><span>${{escapeHtml(label)}}</span></th>`).join("");
  const body=groups.map(group=>`<tr><th>${{escapeHtml(group)}}</th>`+species.map(label=>{{const value=counts.get(`${{group}}\u0000${{label}}`)||0;
    const alpha=value?(.12+.82*scaled(value)/peak):0;return `<td class="copy" style="background:rgba(170,22,38,${{alpha}})" title="${{escapeHtml(group)}} · ${{escapeHtml(label)}} · raw copies=${{value}} · scale=${{scaleMode}}">${{value||""}}</td>`;}}).join("")+"</tr>").join("");
  target.innerHTML=`<table><thead><tr><th>Group</th>${{head}}</tr></thead><tbody>${{body}}</tbody></table>`;}}
function renderProjectionDiagnostics(){{const rows=Object.entries(DATA.networks).filter(([,entry])=>
  `${{entry.distanceSummary.group_type}}|${{entry.distanceSummary.hierarchy_node}}`===overviewLevel.value).sort((a,b)=>
  Number(b[1].distanceProjection?.normalised_stress||-1)-Number(a[1].distanceProjection?.normalised_stress||-1));
  const target=document.getElementById("projection-diagnostics-table");target.innerHTML=rows.map(([key,entry])=>{{const projection=entry.distanceProjection||{{}},metrics=entry.networkMetrics||{{}};
    return `<tr data-group-key="${{escapeHtml(key)}}"><td>${{escapeHtml(entry.distanceSummary.group_id||entry.label)}}</td>`+
      `<td>${{number(entry.analyticalMemberCount)}}</td><td>${{number(entry.displayedMemberCount)}}</td>`+
      `<td>${{projection.two_axis_positive_inertia_fraction==null?"":(100*Number(projection.two_axis_positive_inertia_fraction)).toFixed(1)+"%"}}</td>`+
      `<td>${{projection.distance_correlation==null?"":fixed(projection.distance_correlation)}}</td>`+
      `<td>${{projection.normalised_stress==null?"":fixed(projection.normalised_stress)}}</td>`+
      `<td>${{escapeHtml(projection.quality_category||projection.status||"")}}</td><td>${{number(metrics.rawComponentCount)}}</td></tr>`;}}).join("");
  if(!rows.length)target.innerHTML='<tr><td colspan="8">No displayed distance-pilot groups are available at this level.</td></tr>';
  target.querySelectorAll("tr[data-group-key]").forEach(row=>row.addEventListener("click",()=>{{groupSelect.value=row.dataset.groupKey;renderNetwork();
    document.getElementById("distance-network").scrollIntoView({{behavior:"smooth",block:"center"}});}}));}}
function renderOverview(){{const rows=selectedOverviewRows(),aggregate=(DATA.overviewStatistics||{{}})[overviewLevel.value];
  document.getElementById("overview-notice").textContent=aggregate?
    `Complete-authority histograms describe all ${{number(aggregate.groupCount)}} groups at ${{overviewLevel.options[overviewLevel.selectedIndex]?.text||"this level"}}. `+
    `The two-dimensional size/breadth panel uses ${{number(rows.length)}} deterministic embedded rows; distance and projection panels use only the selected network pilot.`:
    `No full-authority preaggregate is available; ${{number(rows.length)}} embedded summaries are available for this level.`;
  renderAggregateHistogram("cluster-size-chart",aggregate?.memberCount,
    "Members per group (complete log₂ bins)","Group count");
  renderAggregateHistogram("species-breadth-chart",aggregate?.speciesCount,
    "Species represented per group (complete)","Group count");
  renderAggregateHistogram("copy-complexity-chart",aggregate?.maximumCopiesPerSpecies,
    "Maximum copies in one species (complete log₂ bins)","Group count");
  renderScatter("size-breadth-chart",rows,"species_count","member_count",true,
    ["group_id","species_count","member_count","max_copies_per_species"],
    "Species represented per group","Members per group (log₂ scale)");
  const distanceRows=DATA.distanceStatistics.filter(row=>`${{row.group_type}}|${{row.hierarchy_node}}`===overviewLevel.value&&
    row.computation_status!=="UNAVAILABLE"&&Number(row.distance_pair_count)>0);
  renderScatter("distance-coverage-chart",distanceRows,"total_member_count","mean_distance",false,
    ["group_id","distance_method","computation_status","total_member_count","sampled_member_count","mean_distance"],
    "Analytical members per group","Mean pairwise distance in displayed sample");
  renderHeatmap(rows);renderProjectionDiagnostics();}}
overviewLevel.addEventListener("change",renderOverview);
document.getElementById("copy-heatmap-scale").addEventListener("change",()=>renderHeatmap(selectedOverviewRows()));
const groupSelect=document.getElementById("group-select");
Object.keys(DATA.networks).sort().forEach(key=>{{const option=document.createElement("option");
  option.value=key;option.textContent=DATA.networks[key].label;groupSelect.appendChild(option);}});
const showLabels=document.getElementById("show-labels");
const showDistanceEdges=document.getElementById("show-distance-edges");
const showConnectors=document.getElementById("show-connectors");
const speciesFilter=document.getElementById("species-filter");
let topologyNetwork=null;let topologyNodes=null;let topologyEdges=null;
let selectedMemberId="",selectedSpecies="",memberSearchTerm="";
function hasDistanceProjection(entry){{return entry.distanceProjection?.status==="COMPLETE_DISTANCE_PCOA_2D";}}
function visibleNodeRecords(entry){{
  return entry.nodes.map(node=>{{const record={{...node,label:node.isGroup?node.label:(showLabels.checked?node.memberLabel:"")}};
    record.fixed=false;return record;}});}}
function visibleEdgeRecords(entry){{return entry.edges.filter(edge=>
  showConnectors.checked||edge.edgeType!=="COMPONENT_CONNECTOR").map(edge=>({{...edge}}));}}
function bindNodeInspection(currentNetwork,currentNodes,entry){{currentNetwork.on("click",params=>{{
  if(!params.nodes.length)return;const node=currentNodes.get(params.nodes[0]);if(!node.isGroup)selectMember(node.memberLabel,entry,true);
}});}}
function nodeByMember(entry,memberId){{return entry.nodes.find(node=>node.memberLabel===memberId);}}
function inspectMember(memberId,entry){{const node=nodeByMember(entry,memberId);if(!node)return;
  const representative=node.isMedoid?`<dt>Representative</dt><dd>Sample medoid; mean distance `+
    `${{fixed(entry.medoid.mean_distance)}} to ${{number(entry.medoid.comparison_count)}} displayed proteins</dd>`:"";
  document.getElementById("node-detail").innerHTML=`<dl><dt>ID</dt><dd>${{escapeHtml(memberId)}}</dd>`+
    `<dt>Species</dt><dd>${{escapeHtml(node.species||"")}}</dd><dt>Group</dt><dd>${{escapeHtml(entry.label)}}</dd>`+
    representative+`</dl>`;
}}
function selectMember(memberId,entry,focusTopology=false){{selectedMemberId=memberId;selectedSpecies="";inspectMember(memberId,entry);
  if(topologyNetwork&&topologyNodes){{const matches=topologyNodes.get().filter(node=>node.memberLabel===memberId).map(node=>node.id);
    topologyNetwork.selectNodes(matches);if(focusTopology&&matches.length)topologyNetwork.focus(matches[0],{{scale:1.5,animation:true}});}}
  renderPcoa(entry);renderPhylogram(entry);renderDistanceMatrix(entry);renderMembers(entry);}}
function renderPcoa(entry){{const target=document.getElementById("distance-network"),projection=entry.distanceProjection||{{}};
  if(!hasDistanceProjection(entry)){{target.innerHTML=`<p class="small">A diagnostic distance map is unavailable: ${{escapeHtml(projection.reason||"complete distances were not available")}}</p>`;return;}}
  const nodes=entry.nodes.filter(node=>!node.isGroup),nodeMap=new Map(nodes.map(node=>[node.id,node]));
  const xs=nodes.map(node=>Number(node.projectionX)),ys=nodes.map(node=>Number(node.projectionY));
  const xMin=Math.min(...xs),xMax=Math.max(...xs),yMin=Math.min(...ys),yMax=Math.max(...ys),span=Math.max(xMax-xMin,yMax-yMin,1e-12);
  const width=900,height=620,left=82,right=30,top=28,bottom=78,plotWidth=width-left-right,plotHeight=height-top-bottom;
  const scale=Math.min(plotWidth/span,plotHeight/span),drawWidth=span*scale,drawHeight=span*scale;
  const domainX=(xMin+xMax)/2-span/2,domainY=(yMin+yMax)/2-span/2,offsetX=left+(plotWidth-drawWidth)/2,offsetY=top+(plotHeight-drawHeight)/2;
  const px=value=>offsetX+(Number(value)-domainX)*scale,py=value=>offsetY+drawHeight-(Number(value)-domainY)*scale;
  const ticks=[0,.25,.5,.75,1],grid=ticks.map(fraction=>{{const x=offsetX+drawWidth*fraction,y=offsetY+drawHeight*(1-fraction);
    const xValue=domainX+span*fraction,yValue=domainY+span*fraction;
    return `<line class="grid" x1="${{x}}" y1="${{offsetY}}" x2="${{x}}" y2="${{offsetY+drawHeight}}"/>`+
      `<line class="grid" x1="${{offsetX}}" y1="${{y}}" x2="${{offsetX+drawWidth}}" y2="${{y}}"/>`+
      `<text x="${{x}}" y="${{offsetY+drawHeight+21}}" text-anchor="middle">${{xValue.toPrecision(3)}}</text>`+
      `<text x="${{offsetX-8}}" y="${{y+4}}" text-anchor="end">${{yValue.toPrecision(3)}}</text>`;}}).join("");
  const zeroLines=(domainX<=0&&domainX+span>=0?`<line class="axis" x1="${{px(0)}}" y1="${{offsetY}}" x2="${{px(0)}}" y2="${{offsetY+drawHeight}}"/>`:"")+
    (domainY<=0&&domainY+span>=0?`<line class="axis" x1="${{offsetX}}" y1="${{py(0)}}" x2="${{offsetX+drawWidth}}" y2="${{py(0)}}"/>`:"");
  const edges=showDistanceEdges.checked?visibleEdgeRecords(entry).filter(edge=>nodeMap.has(edge.from)&&nodeMap.has(edge.to)).map(edge=>{{const leftNode=nodeMap.get(edge.from),rightNode=nodeMap.get(edge.to);
    return `<line class="pcoa-edge${{edge.edgeType==="COMPONENT_CONNECTOR"?" connector":""}}" x1="${{px(leftNode.projectionX)}}" y1="${{py(leftNode.projectionY)}}" x2="${{px(rightNode.projectionX)}}" y2="${{py(rightNode.projectionY)}}"><title>${{escapeHtml(edge.title||edge.edgeType)}}</title></line>`;}}).join(""):"";
  const points=nodes.map(node=>{{const selected=selectedMemberId===node.memberLabel||(selectedSpecies&&selectedSpecies===node.species)||(memberSearchTerm&&node.memberLabel.toLowerCase().includes(memberSearchTerm));
    const label=showLabels.checked?`<text x="${{px(node.projectionX)+9}}" y="${{py(node.projectionY)+4}}">${{escapeHtml(node.memberLabel)}}</text>`:"";
    const star=node.isMedoid?`<text x="${{px(node.projectionX)}}" y="${{py(node.projectionY)-10}}" text-anchor="middle" fill="#9a6b00">★</text>`:"";
    return `<g data-member="${{escapeHtml(node.memberLabel)}}"><circle class="protein-point${{node.isMedoid?" medoid":""}}${{selected?" selected":""}}" cx="${{px(node.projectionX)}}" cy="${{py(node.projectionY)}}" r="${{node.isMedoid?8:6}}" fill="${{node.speciesColour}}"><title>${{escapeHtml(node.memberLabel)}} · ${{escapeHtml(node.species)}} · PCoA (${{Number(node.projectionX).toPrecision(5)}}, ${{Number(node.projectionY).toPrecision(5)}})</title></circle>${{star}}${{label}}</g>`;}}).join("");
  const axis1=(100*Number(projection.axis_1_positive_inertia_fraction||0)).toFixed(1),axis2=(100*Number(projection.axis_2_positive_inertia_fraction||0)).toFixed(1);
  target.innerHTML=`<svg viewBox="0 0 ${{width}} ${{height}}" role="img" aria-label="PCoA distance map with equal axis scaling">${{grid}}${{zeroLines}}${{edges}}${{points}}`+
    `<line class="axis" x1="${{offsetX}}" y1="${{offsetY+drawHeight}}" x2="${{offsetX+drawWidth}}" y2="${{offsetY+drawHeight}}"/>`+
    `<line class="axis" x1="${{offsetX}}" y1="${{offsetY}}" x2="${{offsetX}}" y2="${{offsetY+drawHeight}}"/>`+
    `<text x="${{offsetX+drawWidth/2}}" y="${{height-18}}" text-anchor="middle">PCoA 1 (${{axis1}}% of positive inertia)</text>`+
    `<text transform="translate(20 ${{offsetY+drawHeight/2}}) rotate(-90)" text-anchor="middle">PCoA 2 (${{axis2}}% of positive inertia)</text></svg>`;
  target.querySelectorAll("[data-member]").forEach(element=>element.addEventListener("click",()=>selectMember(element.dataset.member,entry)));}}
function renderShepard(entry){{const projection=entry.distanceProjection||{{}},points=projection.shepard_points||[],target=document.getElementById("shepard-chart");
  if(!points.length){{plotMessage("shepard-chart","No Shepard-plot points are available.");document.getElementById("shepard-notice").textContent="";return;}}
  const width=640,height=250,left=72,right=18,top=14,bottom=58,plotWidth=width-left-right,plotHeight=height-top-bottom;
  const maximum=Math.max(...points.flat().map(Number),1e-12),px=value=>left+plotWidth*Number(value)/maximum,py=value=>top+plotHeight*(1-Number(value)/maximum);
  const marks=points.map(point=>`<circle class="plot-point" cx="${{px(point[0])}}" cy="${{py(point[1])}}" r="2"><title>Input=${{Number(point[0]).toPrecision(6)}} · projected=${{Number(point[1]).toPrecision(6)}}</title></circle>`).join("");
  target.innerHTML=`<svg viewBox="0 0 ${{width}} ${{height}}"><line class="grid" x1="${{left}}" y1="${{py(0)}}" x2="${{px(maximum)}}" y2="${{py(maximum)}}"/>${{marks}}`+
    `<line class="axis" x1="${{left}}" y1="${{top+plotHeight}}" x2="${{width-right}}" y2="${{top+plotHeight}}"/>`+
    `<line class="axis" x1="${{left}}" y1="${{top}}" x2="${{left}}" y2="${{top+plotHeight}}"/>`+
    `<text x="${{left+plotWidth/2}}" y="${{height-8}}" text-anchor="middle">Input pairwise distance</text>`+
    `<text transform="translate(14 ${{top+plotHeight/2}}) rotate(-90)" text-anchor="middle">Projected 2D distance</text></svg>`;
  document.getElementById("shepard-notice").textContent=`Deterministic ${{number(points.length)}}-point summary of ${{number(projection.shepard_total_pair_count)}} pairs, stratified across the input-distance range. The diagonal denotes perfect preservation.`;}}
function renderPhylogram(entry){{const target=document.getElementById("phylogram"),notice=document.getElementById("phylogram-notice"),tree=entry.phylogram||{{}};
  if(!String(tree.status||"").includes("PRUNED_PHYLOGRAM")){{target.innerHTML=`<p class="small">Phylogram unavailable: ${{escapeHtml(tree.reason||"no resolved tree was supplied")}}</p>`;notice.textContent=tree.reason||"No resolved tree was supplied.";return;}}
  const nodes=tree.nodes||[],nodeMap=new Map(nodes.map(node=>[node.id,node])),width=1040,rowHeight=14,left=48,right=260,top=48,bottom=42;
  const height=Math.max(420,top+bottom+Math.max(1,Number(tree.displayedLeafCount)-1)*rowHeight),plotWidth=width-left-right,maximum=Math.max(Number(tree.maximumRootDistance),1e-12);
  const px=value=>left+plotWidth*Number(value)/maximum,py=node=>top+Number(node.y)*rowHeight;
  const children=new Map();(tree.edges||[]).forEach(edge=>{{if(!children.has(edge.parentId))children.set(edge.parentId,[]);children.get(edge.parentId).push(edge.childId);}});
  const vertical=[...children.entries()].map(([parentId,childIds])=>{{const parent=nodeMap.get(parentId),ys=childIds.map(id=>py(nodeMap.get(id)));
    return `<line class="tree-edge" x1="${{px(parent.x)}}" y1="${{Math.min(...ys)}}" x2="${{px(parent.x)}}" y2="${{Math.max(...ys)}}"/>`;}}).join("");
  const horizontal=(tree.edges||[]).map(edge=>{{const parent=nodeMap.get(edge.parentId),child=nodeMap.get(edge.childId);
    return `<line class="tree-edge" x1="${{px(parent.x)}}" y1="${{py(child)}}" x2="${{px(child.x)}}" y2="${{py(child)}}"><title>Branch length=${{Number(edge.branchLength).toPrecision(6)}}</title></line>`;}}).join("");
  const leaves=nodes.filter(node=>node.isLeaf).map(node=>{{const selected=selectedMemberId===node.memberId||(selectedSpecies&&selectedSpecies===node.species)||(memberSearchTerm&&node.memberId.toLowerCase().includes(memberSearchTerm));
    const label=showLabels.checked||selected||node.isMedoid?`<text x="${{px(node.x)+7}}" y="${{py(node)+4}}">${{escapeHtml(node.memberId)}}</text>`:"";
    const star=node.isMedoid?`<text x="${{px(node.x)}}" y="${{py(node)-7}}" text-anchor="middle" fill="#9a6b00">★</text>`:"";
    return `<g data-member="${{escapeHtml(node.memberId)}}"><circle class="tree-leaf${{node.isMedoid?" medoid":""}}${{selected?" selected":""}}" cx="${{px(node.x)}}" cy="${{py(node)}}" r="${{node.isMedoid?5:3.5}}" fill="${{node.colour}}"><title>${{escapeHtml(node.memberId)}} · ${{escapeHtml(node.species)}} · root distance=${{Number(node.x).toPrecision(6)}}</title></circle>${{star}}${{label}}</g>`;}}).join("");
  const ticks=[0,.25,.5,.75,1].map(fraction=>`<line class="axis" x1="${{left+plotWidth*fraction}}" y1="20" x2="${{left+plotWidth*fraction}}" y2="27"/><text x="${{left+plotWidth*fraction}}" y="15" text-anchor="middle">${{(maximum*fraction).toPrecision(3)}}</text>`).join("");
  target.innerHTML=`<svg viewBox="0 0 ${{width}} ${{height}}" style="height:${{height}}px" role="img" aria-label="Branch-length-scaled resolved gene-tree phylogram">`+
    `<line class="axis" x1="${{left}}" y1="23" x2="${{left+plotWidth}}" y2="23"/>${{ticks}}<text x="${{left+plotWidth/2}}" y="41" text-anchor="middle">Cumulative branch length from displayed root</text>`+
    `${{vertical}}${{horizontal}}${{leaves}}</svg>`;
  notice.textContent=`${{tree.status}} · resolved tree ${{tree.treeId}} · ${{number(tree.displayedLeafCount)}} of ${{number(tree.requestedMemberCount)}} displayed proteins · maximum displayed root distance=${{Number(tree.maximumRootDistance).toPrecision(6)}}. Horizontal lengths are quantitative; vertical spacing is not.`;
  target.querySelectorAll("[data-member]").forEach(element=>element.addEventListener("click",()=>selectMember(element.dataset.member,entry)));}}
function triangularDistance(matrix,left,right){{if(left===right)return 0;let i=Math.min(left,right),j=Math.max(left,right),n=matrix.memberOrder.length;
  return matrix.upperTriangle[i*n-i*(i+1)/2+(j-i-1)];}}
function matrixColour(value,maximum){{const fraction=maximum>0?Math.max(0,Math.min(1,Number(value)/maximum)):0;
  return `rgb(${{Math.round(255-116*fraction)}},${{Math.round(255-247*fraction)}},${{Math.round(255-247*fraction)}})`;}}
function renderDistanceMatrix(entry){{const target=document.getElementById("distance-matrix"),notice=document.getElementById("distance-matrix-notice"),detail=document.getElementById("distance-matrix-detail"),matrix=entry.distanceMatrix||{{}};
  if(matrix.status!=="EXACT_COMPLETE_DISPLAYED_MATRIX"){{target.innerHTML=`<p class="small">Exact matrix unavailable: ${{escapeHtml(matrix.reason||"complete distances were not supplied")}}</p>`;notice.textContent=matrix.reason||"Complete distances were not supplied.";return;}}
  target.innerHTML="";const canvas=document.createElement("canvas"),size=780,margin=104,matrixSize=size-margin-18,n=matrix.memberOrder.length,cell=matrixSize/n;
  canvas.width=size;canvas.height=size;canvas.setAttribute("role","img");canvas.setAttribute("aria-label","Exact pairwise distance matrix");target.appendChild(canvas);
  const context=canvas.getContext("2d"),maximum=Number(matrix.maximum)||0;context.fillStyle="#fff";context.fillRect(0,0,size,size);
  for(let row=0;row<n;row++)for(let column=0;column<n;column++){{context.fillStyle=matrixColour(triangularDistance(matrix,row,column),maximum);context.fillRect(margin+column*cell,margin+row*cell,Math.ceil(cell+.2),Math.ceil(cell+.2));}}
  const step=Math.max(1,Math.ceil(n/12));context.fillStyle="#586174";context.font="10px Arial";
  matrix.memberOrder.forEach((member,index)=>{{if(index%step)return;const position=margin+(index+.5)*cell;context.save();context.translate(position,margin-6);context.rotate(-Math.PI/3);context.fillText(member.slice(0,22),0,0);context.restore();context.textAlign="right";context.fillText(member.slice(0,22),margin-6,position+3);context.textAlign="left";}});
  const selectedIndex=matrix.memberOrder.indexOf(selectedMemberId);if(selectedIndex>=0){{context.strokeStyle="#111827";context.lineWidth=2;context.strokeRect(margin,margin+selectedIndex*cell,matrixSize,cell);context.strokeRect(margin+selectedIndex*cell,margin,cell,matrixSize);}}
  notice.textContent=`${{matrix.status}} · n=${{number(n)}} displayed proteins · ${{number(matrix.pairCount)}} exact pairs · order=${{matrix.orderMethod}} · range=${{Number(matrix.minimum).toPrecision(6)}}–${{Number(matrix.maximum).toPrecision(6)}}.`;
  function matrixCell(event){{const bounds=canvas.getBoundingClientRect(),x=(event.clientX-bounds.left)*canvas.width/bounds.width,y=(event.clientY-bounds.top)*canvas.height/bounds.height;
    const column=Math.floor((x-margin)/cell),row=Math.floor((y-margin)/cell);return row>=0&&column>=0&&row<n&&column<n?[row,column]:null;}}
  canvas.addEventListener("mousemove",event=>{{const indices=matrixCell(event);if(!indices){{detail.textContent="Move over a cell to inspect its exact value.";return;}}
    const [row,column]=indices,value=triangularDistance(matrix,row,column);detail.textContent=`${{matrix.memberOrder[row]}} × ${{matrix.memberOrder[column]}} · exact supplied distance=${{String(value)}}`;}});
  canvas.addEventListener("click",event=>{{const indices=matrixCell(event);if(indices)selectMember(matrix.memberOrder[indices[0]],entry);}});}}
function renderNetwork(){{
  const entry=DATA.networks[groupSelect.value];
  if(!entry){{document.getElementById("network-notice").textContent="No network groups were embedded.";return;}}
  selectedMemberId="";selectedSpecies="";memberSearchTerm="";document.getElementById("member-search").value="";
  if(topologyNetwork)topologyNetwork.destroy();
  const edgeRecords=visibleEdgeRecords(entry);
  topologyNodes=new vis.DataSet(visibleNodeRecords(entry));topologyEdges=new vis.DataSet(edgeRecords.map(edge=>({{...edge}})));
  topologyNetwork=new vis.Network(document.getElementById("topology-network"),{{nodes:topologyNodes,edges:topologyEdges}},{{
    autoResize:true,interaction:{{hover:true,navigationButtons:true,multiselect:true,dragNodes:true}},
    physics:{{solver:"forceAtlas2Based",stabilization:{{iterations:250}}}},
    edges:{{smooth:false,color:{{inherit:false}},font:{{size:9,align:"middle"}}}},
    nodes:{{shape:"dot",size:14,font:{{size:11}},borderWidthSelected:4}}
  }});bindNodeInspection(topologyNetwork,topologyNodes,entry);
  let notice=entry.notice;
  if(entry.medoid&&entry.medoid.member_id)notice+=` Sample medoid: ${{entry.medoid.member_id}} `+
    `(mean distance ${{fixed(entry.medoid.mean_distance)}} within n=${{number(entry.medoid.sample_size)}} displayed proteins).`;
  else if(entry.medoid&&entry.medoid.reason)notice+=` Sample medoid unavailable: ${{entry.medoid.reason}}`;
  document.getElementById("network-notice").textContent=notice;
  const projection=entry.distanceProjection||{{}};
  document.getElementById("distance-network-notice").innerHTML=hasDistanceProjection(entry)?
    `<span class="quality-badge ${{String(projection.quality_category||"").toLowerCase()}}">${{escapeHtml(projection.quality_category||"UNCLASSIFIED")}} 2D fit</span>`+
    `Uses all ${{number(projection.pair_count)}} pairwise distances. PCoA axis 1=${{(100*Number(projection.axis_1_positive_inertia_fraction||0)).toFixed(1)}}% `+
    `and axis 2=${{(100*Number(projection.axis_2_positive_inertia_fraction||0)).toFixed(1)}}% of positive inertia; `+
    `distance correlation=${{projection.distance_correlation==null?"not defined":fixed(projection.distance_correlation)}}; `+
    `normalised stress=${{fixed(projection.normalised_stress)}}; negative inertia=${{(100*Number(projection.negative_inertia_fraction||0)).toFixed(1)}}%. `+
    `${{escapeHtml(projection.quality_explanation||"")}}`:
    `Unavailable: ${{escapeHtml(projection.reason||"complete distances were not available")}}`;
  document.getElementById("topology-network-notice").textContent=
    `Solid edges retain up to ${{number(DATA.limits.nearestNeighbours)}} nearest neighbours per protein. `+
    `Dashed component connectors can be hidden. Screen spacing is not quantitative.`;
  speciesFilter.value="";renderPcoa(entry);renderShepard(entry);renderPhylogram(entry);renderDistanceMatrix(entry);
  renderMembers(entry);renderDistanceHistogram(entry);renderSpeciesLegend(entry);renderProjectionDiagnostics();
}}
function renderMembers(entry){{const target=document.getElementById("member-table");target.innerHTML=entry.members.map(row=>
  `<tr class="${{row.member_id===selectedMemberId?"selected-row":""}}" data-member="${{escapeHtml(row.member_id)}}"><td>${{row.member_id===entry.medoid?.member_id?"★ ":""}}${{escapeHtml(row.member_id)}}</td>`+
  `<td>${{escapeHtml(row.species_label)}}</td><td>${{escapeHtml(entry.label)}}</td></tr>`).join("");
  target.querySelectorAll("tr[data-member]").forEach(row=>row.addEventListener("click",()=>selectMember(row.dataset.member,entry)));}}
function renderSpeciesLegend(entry){{const term=speciesFilter.value.toLowerCase(),target=document.getElementById("species-legend");
  const records=(entry.speciesLegend||[]).filter(record=>record.species.toLowerCase().includes(term));
  target.innerHTML=records.map(record=>`<button type="button" class="legend-item" data-species="${{escapeHtml(record.species)}}" `+
    `title="Select displayed proteins from ${{escapeHtml(record.species)}}"><span class="legend-swatch" `+
    `style="background:${{record.colour}}"></span><span class="legend-label">${{escapeHtml(record.species)}} `+
    `(${{number(record.displayedMemberCount)}})</span></button>`).join("");
  target.querySelectorAll(".legend-item").forEach(item=>item.addEventListener("click",()=>{{
    selectedSpecies=item.dataset.species;selectedMemberId="";const matches=topologyNodes.get().filter(node=>
      node.species===selectedSpecies).map(node=>node.id);
    if(matches.length){{topologyNetwork.selectNodes(matches);topologyNetwork.fit({{nodes:matches,animation:true}});}}
    renderPcoa(entry);renderPhylogram(entry);renderMembers(entry);
  }}));}}
function renderDistanceHistogram(entry){{const histogram=entry.distanceHistogram||{{}},counts=(histogram.counts||[]).map(Number);
  const target=document.getElementById("histogram"),summary=document.getElementById("distance-summary");
  target.innerHTML="";if(!counts.length){{summary.textContent="No pairwise distances were available for this rendered group.";return;}}
  const min=Number(histogram.minimum),max=Number(histogram.maximum);
  const peak=Math.max(...counts,1);counts.forEach((count,index)=>{{const bar=document.createElement("div");bar.className="bar";
    bar.style.height=`${{100*count/peak}}%`;bar.title=`Bin ${{index+1}}: ${{count}} pairs`;target.appendChild(bar);}});
  const s=entry.distanceSummary||{{}};summary.textContent=`${{s.distance_method||"Distance"}} · n=${{number(histogram.pairCount)}} pairs · `+
    `mean=${{fixed(s.mean_distance)}} · median=${{fixed(s.median_distance)}} · range=${{fixed(min)}}–${{fixed(max)}} · ${{s.computation_status||""}}`;}}
groupSelect.addEventListener("change",renderNetwork);
document.getElementById("fit-topology-network").addEventListener("click",()=>topologyNetwork&&topologyNetwork.fit());
showLabels.addEventListener("change",()=>{{const entry=DATA.networks[groupSelect.value];
  if(topologyNodes)topologyNodes.update(visibleNodeRecords(entry).map(node=>({{id:node.id,label:node.label}})));
  renderPcoa(entry);renderPhylogram(entry);}});
showDistanceEdges.addEventListener("change",()=>{{const entry=DATA.networks[groupSelect.value];if(entry)renderPcoa(entry);}});
showConnectors.addEventListener("change",()=>{{const entry=DATA.networks[groupSelect.value];
  if(topologyEdges){{topologyEdges.clear();topologyEdges.add(visibleEdgeRecords(entry));}}if(entry&&showDistanceEdges.checked)renderPcoa(entry);}});
speciesFilter.addEventListener("input",()=>{{const entry=DATA.networks[groupSelect.value];if(entry)renderSpeciesLegend(entry);}});
document.getElementById("member-search").addEventListener("input",event=>{{memberSearchTerm=event.target.value.toLowerCase();
  const entry=DATA.networks[groupSelect.value];if(!entry)return;if(!memberSearchTerm)topologyNetwork.unselectAll();
  else{{const matches=topologyNodes.get().filter(node=>String(node.memberLabel||node.label).toLowerCase().includes(memberSearchTerm)&&!node.isGroup).map(node=>node.id);
    if(matches.length){{topologyNetwork.selectNodes(matches);topologyNetwork.focus(matches[0],{{scale:1.5}});}}}}
  renderPcoa(entry);renderPhylogram(entry);}});
let filtered=DATA.groupStatistics.slice(),page=0;const pageSize=50;
function renderStats(){{const start=page*pageSize,rows=filtered.slice(start,start+pageSize);
  document.getElementById("statistics-table").innerHTML=rows.map(row=>`<tr><td>${{escapeHtml(row.group_type)}}</td>`+
    `<td>${{escapeHtml(row.hierarchy_node)}}</td><td>${{escapeHtml(row.group_id)}}</td><td>${{number(row.member_count)}}</td>`+
    `<td>${{number(row.species_count)}}</td><td>${{number(row.max_copies_per_species)}}</td>`+
    `<td>${{fixed(row.mean_copies_per_species)}}</td></tr>`).join("");
  document.getElementById("page-status").textContent=`Rows ${{filtered.length?start+1:0}}–${{Math.min(start+pageSize,filtered.length)}} of ${{number(filtered.length)}}`;
  document.getElementById("previous-page").disabled=page===0;
  document.getElementById("next-page").disabled=start+pageSize>=filtered.length;}}
document.getElementById("group-filter").addEventListener("input",event=>{{const term=event.target.value.toLowerCase();
  filtered=DATA.groupStatistics.filter(row=>JSON.stringify(row).toLowerCase().includes(term));page=0;renderStats();}});
document.getElementById("previous-page").addEventListener("click",()=>{{if(page>0)page--;renderStats();}});
document.getElementById("next-page").addEventListener("click",()=>{{if((page+1)*pageSize<filtered.length)page++;renderStats();}});
function escapeHtml(value){{return String(value??"").replace(/[&<>"']/g,char=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}}[char]));}}
try{{renderStats();renderOverview();renderNetwork();}}catch(error){{showRenderError(error);throw error;}}
</script>
</body></html>
"""
    atomic_write_text(path=output_path, text=document)


def _build_network_payload(
    *,
    group_statistics: Sequence[Mapping[str, Any]],
    memberships: Sequence[Mapping[str, Any]],
    distances: Sequence[Mapping[str, Any]],
    distance_statistics: Sequence[Mapping[str, Any]],
    max_groups: int,
    max_members: int,
    nearest_neighbours: int,
    tree_nodes: Sequence[Mapping[str, Any]],
    tree_edges: Sequence[Mapping[str, Any]],
    sequence_identifiers: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build bounded network records for browser rendering.

    Args:
        group_statistics: Candidate group summaries.
        memberships: Candidate member rows.
        distances: Candidate pairwise distances.
        distance_statistics: Candidate distance summaries.
        max_groups: Maximum rendered groups.
        max_members: Maximum rendered members per group.
        nearest_neighbours: Edges retained per node.
        tree_nodes: Normalised resolved-gene-tree nodes for selected groups.
        tree_edges: Normalised resolved-gene-tree edges for selected groups.
        sequence_identifiers: Canonical-to-internal identifier mappings.

    Returns:
        JSON-safe network payload keyed by a collision-safe group key.
    """

    members_by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in memberships:
        members_by_key[_group_key(row)].append(row)
    distances_by_key: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in distances:
        distances_by_key[_group_key(row)].append(row)
    summary_by_key = {_group_key(row): dict(row) for row in distance_statistics}
    ordered_statistics = sorted(
        group_statistics,
        key=lambda row: (
            0 if _group_key(row) in distances_by_key else 1,
            -int(row.get("member_count", 0)),
            _group_key(row),
        ),
    )[:max_groups]
    species_palette = _species_palette(
        species_labels=(str(row.get("species_label", "")) for row in memberships)
    )
    nodes_by_tree_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in tree_nodes:
        if str(row.get("tree_type", "")) == "RESOLVED_GENE_TREE":
            nodes_by_tree_id[str(row.get("tree_id", ""))].append(row)
    edges_by_tree_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in tree_edges:
        if str(row.get("tree_type", "")) == "RESOLVED_GENE_TREE":
            edges_by_tree_id[str(row.get("tree_id", ""))].append(row)
    aliases_by_member_species: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in sequence_identifiers:
        aliases_by_member_species[
            (str(row.get("member_id", "")), str(row.get("species_label", "")))
        ].add(str(row.get("internal_id", "")))
    payload: dict[str, Any] = {}
    for network_index, statistic in enumerate(ordered_statistics, start=1):
        key = _group_key(statistic)
        available_members = members_by_key.get(key, [])
        rendered_members = _select_members(
            members=available_members,
            group_key=key,
            max_members=max_members,
        )
        rendered_ids = {str(row["member_id"]) for row in rendered_members}
        group_distances = [
            row
            for row in distances_by_key.get(key, [])
            if str(row["member_a"]) in rendered_ids
            and str(row["member_b"]) in rendered_ids
            and row.get("distance") not in {"", None}
        ]
        medoid = _sample_medoid(
            distance_rows=group_distances,
            member_ids=rendered_ids,
        )
        projection_positions, projection = _distance_projection(
            distance_rows=group_distances,
            member_ids=rendered_ids,
        )
        medoid_id = str(medoid.get("member_id", ""))
        nodes = []
        species_counts: dict[str, int] = defaultdict(int)
        for row in rendered_members:
            member_id = str(row["member_id"])
            species = str(row.get("species_label", ""))
            species_counts[species] += 1
            is_medoid = bool(medoid_id and member_id == medoid_id)
            species_colour = species_palette[species]
            title_parts = [member_id, species]
            if is_medoid:
                title_parts.append(
                    "sample medoid; mean distance="
                    f"{float(medoid['mean_distance']):.6g}"
                )
            nodes.append(
                {
                    "id": member_id,
                    "label": "",
                    "memberLabel": member_id,
                    "title": html.escape(" | ".join(title_parts), quote=True),
                    "species": species,
                    "speciesColour": species_colour,
                    "projectionX": projection_positions.get(member_id, (0.0, 0.0))[0],
                    "projectionY": projection_positions.get(member_id, (0.0, 0.0))[1],
                    "color": {
                        "background": species_colour,
                        "border": "#b8860b" if is_medoid else "#4b5563",
                        "highlight": {
                            "background": species_colour,
                            "border": "#7a4e00" if is_medoid else "#172033",
                        },
                    },
                    "shape": "star" if is_medoid else "dot",
                    "size": 24 if is_medoid else 14,
                    "borderWidth": 5 if is_medoid else 1,
                    "isMedoid": is_medoid,
                    "isGroup": False,
                }
            )
        network_metrics: dict[str, Any]
        if group_distances:
            edges, network_metrics = _connected_network_edges(
                distance_rows=group_distances,
                member_ids=rendered_ids,
                nearest_neighbours=nearest_neighbours,
            )
        else:
            centre = f"__group__:{key}"
            nodes.append(
                {
                    "id": centre,
                    "label": str(statistic["group_id"]),
                    "title": "Membership hub; pairwise distances unavailable",
                    "color": "#1f2a44",
                    "shape": "diamond",
                    "size": 24,
                    "isGroup": True,
                }
            )
            edges = [
                {
                    "from": centre,
                    "to": member_id,
                    "color": "#c8cedb",
                    "dashes": True,
                    "edgeType": "MEMBERSHIP_HUB",
                }
                for member_id in sorted(rendered_ids)
            ]
            network_metrics = {
                "rawComponentCount": None,
                "rawIsolateCount": None,
                "nearestNeighbourEdgeCount": 0,
                "connectorCount": 0,
            }
        phylogram = _phylogram_payload(
            statistic=statistic,
            rendered_members=rendered_members,
            medoid=medoid,
            nodes_by_tree_id=nodes_by_tree_id,
            edges_by_tree_id=edges_by_tree_id,
            aliases_by_member_species=aliases_by_member_species,
            species_palette=species_palette,
        )
        matrix_member_order = phylogram.get("memberOrder", ())
        distance_matrix = _distance_matrix_payload(
            distance_rows=group_distances,
            member_ids=rendered_ids,
            preferred_order=matrix_member_order,
        )
        supplied_count = len(available_members)
        analytical_count = int(statistic.get("member_count", 0))
        notice = (
            f"This is one within-group network. Displayed {len(rendered_members):,} "
            f"of {supplied_count:,} supplied members; analytical group size is "
            f"{analytical_count:,}."
        )
        if group_distances:
            notice += (
                f" The raw {nearest_neighbours}-nearest-neighbour graph has "
                f"{network_metrics['rawComponentCount']:,} component(s) and "
                f"{network_metrics['rawIsolateCount']:,} isolated node(s). "
                f"The {network_metrics['connectorCount']:,} dashed connector(s) are "
                "layout aids, not nearest-neighbour relationships."
            )
        payload[key] = {
            "label": _group_label(statistic),
            "nodes": nodes,
            "edges": edges,
            "speciesLegend": [
                {
                    "species": species,
                    "colour": species_palette[species],
                    "displayedMemberCount": species_counts[species],
                }
                for species in sorted(species_counts)
            ],
            "medoid": medoid,
            "distanceProjection": projection,
            "phylogram": phylogram,
            "distanceMatrix": distance_matrix,
            "networkMetrics": network_metrics,
            "analyticalMemberCount": analytical_count,
            "suppliedMemberCount": supplied_count,
            "displayedMemberCount": len(rendered_members),
            "displayedSpeciesCount": len(species_counts),
            "members": [
                _compact_record(row=row, fields=("member_id", "species_label"))
                for row in rendered_members
            ],
            "distanceHistogram": _distance_histogram(distance_rows=group_distances),
            "distanceSummary": _compact_record(
                row=summary_by_key.get(key, {}),
                fields=_REPORT_DISTANCE_STATISTIC_FIELDS,
            ),
            "notice": notice,
        }
        _LOGGER.info(
            "HTML network prepared: %s/%s, group=%s, displayed_members=%s, "
            "species=%s, raw_components=%s, connectors=%s, projection=%s, "
            "stress=%s, phylogram=%s, distance_matrix=%s.",
            network_index,
            len(ordered_statistics),
            key,
            len(rendered_members),
            len(species_counts),
            network_metrics["rawComponentCount"],
            network_metrics["connectorCount"],
            projection.get("status", "UNAVAILABLE"),
            projection.get("normalised_stress", ""),
            phylogram.get("status", "UNAVAILABLE"),
            distance_matrix.get("status", "UNAVAILABLE"),
        )
    return payload


def _distance_histogram(
    *, distance_rows: Sequence[Mapping[str, Any]], bin_count: int = 20
) -> dict[str, Any]:
    """Return compact fixed-width bins for finite pairwise distances.

    Args:
        distance_rows: Candidate records containing a distance field.
        bin_count: Number of fixed-width bins.

    Returns:
        JSON-safe minimum, maximum, pair count and bin counts, or an empty mapping.
    """

    values = [
        float(row["distance"])
        for row in distance_rows
        if row.get("distance") not in {"", None}
        and math.isfinite(float(row["distance"]))
    ]
    if not values:
        return {}
    minimum = min(values)
    maximum = max(values)
    width = maximum - minimum
    counts = [0] * bin_count
    for value in values:
        index = 0 if width == 0 else min(bin_count - 1, int((value - minimum) / width * bin_count))
        counts[index] += 1
    return {
        "minimum": minimum,
        "maximum": maximum,
        "pairCount": len(values),
        "counts": counts,
    }


def _compact_record(
    *, row: Mapping[str, Any], fields: Sequence[str]
) -> dict[str, Any]:
    """Return only browser-required fields from one analytical record.

    Args:
        row: Full analytical record.
        fields: Ordered fields retained in the report.

    Returns:
        Compact field mapping.
    """

    return {field: row.get(field, "") for field in fields}


def _nearest_neighbour_edges(
    *, distance_rows: Sequence[Mapping[str, Any]], nearest_neighbours: int
) -> list[dict[str, Any]]:
    """Retain an undirected union of each node's nearest neighbours.

    Args:
        distance_rows: Pairwise distance records with finite values.
        nearest_neighbours: Maximum retained neighbours for each endpoint.

    Returns:
        Deduplicated vis-network edge records.
    """

    distance_lookup = _pairwise_distance_lookup(distance_rows=distance_rows)
    neighbours: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for (left, right), distance in distance_lookup.items():
        neighbours[left].append((distance, right))
        neighbours[right].append((distance, left))
    retained: set[tuple[str, str]] = set()
    for member, candidates in neighbours.items():
        for _, neighbour in sorted(candidates)[:nearest_neighbours]:
            edge = tuple(sorted((member, neighbour)))
            retained.add(edge)
    edges = []
    for left, right in sorted(retained):
        distance = distance_lookup[(left, right)]
        edges.append(
            {
                "from": left,
                "to": right,
                "color": "#7786a8",
                "width": 1.25,
                "distance": distance,
                "edgeType": "NEAREST_NEIGHBOUR",
                "title": f"Nearest-neighbour edge; distance={distance:.6g}",
            }
        )
    return edges


def _connected_network_edges(
    *,
    distance_rows: Sequence[Mapping[str, Any]],
    member_ids: set[str],
    nearest_neighbours: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return nearest-neighbour edges plus explicit component connectors.

    The nearest-neighbour union is the scientific view. If it is disconnected,
    Kruskal-style minimum-distance edges join its components solely so the
    browser lays out the whole group together. Connector records are explicitly
    typed and can therefore be hidden without changing the raw graph.

    Args:
        distance_rows: Pairwise distance records with finite values.
        member_ids: Exact members rendered in the network.
        nearest_neighbours: Maximum retained neighbours for each endpoint.

    Returns:
        Combined edge records and raw-network metrics.
    """

    nearest_edges = _nearest_neighbour_edges(
        distance_rows=distance_rows,
        nearest_neighbours=nearest_neighbours,
    )
    parent = {member_id: member_id for member_id in member_ids}

    def find(member_id: str) -> str:
        while parent[member_id] != member_id:
            parent[member_id] = parent[parent[member_id]]
            member_id = parent[member_id]
        return member_id

    def union(left: str, right: str) -> bool:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return False
        if left_root > right_root:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        return True

    degrees = {member_id: 0 for member_id in member_ids}
    for edge in nearest_edges:
        left, right = str(edge["from"]), str(edge["to"])
        if left in parent and right in parent:
            union(left, right)
            degrees[left] += 1
            degrees[right] += 1
    raw_component_count = len({find(member_id) for member_id in member_ids})
    raw_isolate_count = sum(degree == 0 for degree in degrees.values())
    connectors: list[dict[str, Any]] = []
    distance_lookup = _pairwise_distance_lookup(distance_rows=distance_rows)
    for (left, right), distance in sorted(
        distance_lookup.items(), key=lambda item: (item[1], item[0])
    ):
        if left not in parent or right not in parent or not union(left, right):
            continue
        connectors.append(
            {
                "from": left,
                "to": right,
                "color": "#b7791f",
                "width": 1.75,
                "dashes": True,
                "distance": distance,
                "edgeType": "COMPONENT_CONNECTOR",
                "title": (
                    "Component connector (layout only; not a nearest-neighbour "
                    f"edge); distance={distance:.6g}"
                ),
            }
        )
        if len(connectors) == max(0, raw_component_count - 1):
            break
    metrics = {
        "rawComponentCount": raw_component_count,
        "rawIsolateCount": raw_isolate_count,
        "nearestNeighbourEdgeCount": len(nearest_edges),
        "connectorCount": len(connectors),
    }
    return nearest_edges + connectors, metrics


def _pairwise_distance_lookup(
    *, distance_rows: Sequence[Mapping[str, Any]]
) -> dict[tuple[str, str], float]:
    """Return the minimum finite distance for every undirected member pair.

    Args:
        distance_rows: Candidate pairwise distance records.

    Returns:
        Mapping from sorted member pair to finite distance.
    """

    lookup: dict[tuple[str, str], float] = {}
    for row in distance_rows:
        left, right = str(row["member_a"]), str(row["member_b"])
        distance = float(row["distance"])
        if left == right or not math.isfinite(distance):
            continue
        pair = tuple(sorted((left, right)))
        lookup[pair] = min(distance, lookup.get(pair, distance))
    return lookup


def _sample_medoid(
    *,
    distance_rows: Sequence[Mapping[str, Any]],
    member_ids: set[str],
) -> dict[str, Any]:
    """Identify the medoid only when the rendered distance matrix is complete.

    Args:
        distance_rows: Pairwise distance records for rendered members.
        member_ids: Exact members rendered in the network.

    Returns:
        JSON-safe sampled-medoid record or an explicit unavailable record.
    """

    ordered_ids = sorted(member_ids)
    if len(ordered_ids) < 2:
        return {
            "status": "UNAVAILABLE",
            "reason": "At least two rendered members are required.",
        }
    lookup = {
        pair: distance
        for pair, distance in _pairwise_distance_lookup(
            distance_rows=distance_rows
        ).items()
        if pair[0] in member_ids and pair[1] in member_ids
    }
    expected_pairs = len(ordered_ids) * (len(ordered_ids) - 1) // 2
    available_pair_count = len(lookup)
    if available_pair_count != expected_pairs:
        return {
            "status": "UNAVAILABLE_INCOMPLETE_MATRIX",
            "reason": (
                f"A complete rendered distance matrix requires {expected_pairs:,} "
                f"pairs; {available_pair_count:,} were available."
            ),
            "expected_pair_count": expected_pairs,
            "available_pair_count": available_pair_count,
        }
    totals = {member_id: 0.0 for member_id in ordered_ids}
    for (left, right), distance in lookup.items():
        totals[left] += distance
        totals[right] += distance
    denominator = len(ordered_ids) - 1
    member_id = min(ordered_ids, key=lambda value: (totals[value], value))
    return {
        "status": "EXACT_WITHIN_RENDERED_SAMPLE",
        "member_id": member_id,
        "mean_distance": totals[member_id] / denominator,
        "distance_sum": totals[member_id],
        "comparison_count": denominator,
        "sample_size": len(ordered_ids),
    }


def _distance_projection(
    *,
    distance_rows: Sequence[Mapping[str, Any]],
    member_ids: set[str],
) -> tuple[dict[str, tuple[float, float]], dict[str, Any]]:
    """Project a complete pairwise-distance matrix into two dimensions.

    Classical multidimensional scaling, also called principal coordinates
    analysis (PCoA), provides a deterministic two-dimensional approximation of
    all supplied pairwise distances. The returned quality statistics make the
    unavoidable projection distortion explicit.

    Args:
        distance_rows: Pairwise distance records for rendered members.
        member_ids: Exact members rendered in the network.

    Returns:
        Browser-scaled positions and JSON-safe projection metadata.
    """

    ordered_ids = sorted(member_ids)
    if len(ordered_ids) < 2:
        return {}, {
            "status": "UNAVAILABLE",
            "reason": "At least two rendered members are required.",
        }
    lookup = {
        pair: distance
        for pair, distance in _pairwise_distance_lookup(
            distance_rows=distance_rows
        ).items()
        if pair[0] in member_ids and pair[1] in member_ids
    }
    expected_pairs = len(ordered_ids) * (len(ordered_ids) - 1) // 2
    if len(lookup) != expected_pairs:
        return {}, {
            "status": "UNAVAILABLE_INCOMPLETE_MATRIX",
            "reason": (
                f"A complete rendered distance matrix requires {expected_pairs:,} "
                f"pairs; {len(lookup):,} were available."
            ),
            "expected_pair_count": expected_pairs,
            "available_pair_count": len(lookup),
        }

    index_by_id = {member_id: index for index, member_id in enumerate(ordered_ids)}
    matrix = np.zeros((len(ordered_ids), len(ordered_ids)), dtype=float)
    for (left, right), distance in lookup.items():
        left_index, right_index = index_by_id[left], index_by_id[right]
        matrix[left_index, right_index] = distance
        matrix[right_index, left_index] = distance
    squared = matrix**2
    row_means = squared.mean(axis=1)
    centred = -0.5 * (
        squared - row_means[:, None] - row_means[None, :] + squared.mean()
    )
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(centred)
    except np.linalg.LinAlgError as error:
        return {}, {
            "status": "UNAVAILABLE_EIGENDECOMPOSITION_FAILED",
            "reason": f"PCoA eigendecomposition failed: {error}",
        }
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[order]
    eigenvectors = eigenvectors[:, order]
    tolerance = max(float(np.max(np.abs(eigenvalues))), 1.0) * 1e-12
    positive = np.flatnonzero(eigenvalues > tolerance)
    if not positive.size:
        return {}, {
            "status": "UNAVAILABLE_NO_POSITIVE_AXES",
            "reason": "The distance matrix produced no positive PCoA axes.",
        }

    coordinates = np.zeros((len(ordered_ids), 2), dtype=float)
    for axis, eigen_index in enumerate(positive[:2]):
        coordinate = eigenvectors[:, eigen_index] * math.sqrt(
            float(eigenvalues[eigen_index])
        )
        anchor = int(np.argmax(np.abs(coordinate)))
        if coordinate[anchor] < 0:
            coordinate *= -1
        coordinates[:, axis] = coordinate

    upper = np.triu_indices(len(ordered_ids), k=1)
    actual = matrix[upper]
    coordinate_differences = coordinates[:, None, :] - coordinates[None, :, :]
    projected_matrix = np.sqrt(np.sum(coordinate_differences**2, axis=2))
    projected = projected_matrix[upper]
    denominator = float(np.sum(actual**2))
    normalised_stress = (
        math.sqrt(float(np.sum((actual - projected) ** 2)) / denominator)
        if denominator > 0
        else 0.0
    )
    if actual.size > 1 and np.std(actual) > 0 and np.std(projected) > 0:
        distance_correlation: float | None = float(
            np.corrcoef(actual, projected)[0, 1]
        )
    else:
        distance_correlation = None

    positive_sum = float(np.sum(eigenvalues[eigenvalues > tolerance]))
    axis_fractions = [
        float(eigenvalues[index] / positive_sum) if index < len(eigenvalues) else 0.0
        for index in positive[:2]
    ]
    while len(axis_fractions) < 2:
        axis_fractions.append(0.0)
    absolute_sum = float(np.sum(np.abs(eigenvalues)))
    negative_fraction = (
        float(np.sum(np.abs(eigenvalues[eigenvalues < -tolerance])) / absolute_sum)
        if absolute_sum > 0
        else 0.0
    )

    positions = {
        member_id: (
            float(coordinates[index, 0]),
            float(coordinates[index, 1]),
        )
        for index, member_id in enumerate(ordered_ids)
    }
    shepard_limit = 2_000
    pair_order = np.argsort(actual, kind="stable")
    if actual.size > shepard_limit:
        selected_pair_indices = pair_order[
            np.linspace(0, actual.size - 1, shepard_limit, dtype=int)
        ]
    else:
        selected_pair_indices = pair_order
    shepard_points = [
        [float(actual[index]), float(projected[index])]
        for index in selected_pair_indices
    ]
    quality = _projection_quality(
        retained_inertia=sum(axis_fractions),
        distance_correlation=distance_correlation,
        normalised_stress=normalised_stress,
    )
    metadata = {
        "status": "COMPLETE_DISTANCE_PCOA_2D",
        "method": "CLASSICAL_MDS_PCOA",
        "sample_size": len(ordered_ids),
        "pair_count": expected_pairs,
        "axis_1_positive_inertia_fraction": axis_fractions[0],
        "axis_2_positive_inertia_fraction": axis_fractions[1],
        "two_axis_positive_inertia_fraction": sum(axis_fractions),
        "distance_correlation": distance_correlation,
        "normalised_stress": normalised_stress,
        "negative_inertia_fraction": negative_fraction,
        "quality_category": quality[0],
        "quality_explanation": quality[1],
        "shepard_points": shepard_points,
        "shepard_point_count": len(shepard_points),
        "shepard_total_pair_count": expected_pairs,
    }
    return positions, metadata


def _projection_quality(
    *,
    retained_inertia: float,
    distance_correlation: float | None,
    normalised_stress: float,
) -> tuple[str, str]:
    """Classify two-dimensional projection quality for display guidance.

    The thresholds combine three complementary diagnostics. They are deliberately
    conservative and are not biological acceptance criteria.

    Args:
        retained_inertia: Fraction of positive inertia retained by axes one and two.
        distance_correlation: Correlation of input and projected pair distances.
        normalised_stress: Normalised raw stress of the two-dimensional projection.

    Returns:
        Display category and plain-language interpretation.
    """

    if (
        distance_correlation is None
        or retained_inertia < 0.25
        or distance_correlation < 0.60
        or normalised_stress > 0.60
    ):
        return (
            "POOR",
            "Strong two-dimensional distortion: apparent arms, gaps or angles "
            "require confirmation in the phylogram and exact distance matrix.",
        )
    if (
        retained_inertia < 0.40
        or distance_correlation < 0.80
        or normalised_stress > 0.45
    ):
        return (
            "MODERATE",
            "The map is a partial summary: use the phylogram and exact matrix "
            "before interpreting detailed geometry.",
        )
    return (
        "BETTER",
        "The two-dimensional fit is better for this pilot, but screen spacing "
        "remains a projection rather than the exact distance authority.",
    )


def _distance_matrix_payload(
    *,
    distance_rows: Sequence[Mapping[str, Any]],
    member_ids: set[str],
    preferred_order: Sequence[str] = (),
) -> dict[str, Any]:
    """Return an exact bounded triangular distance matrix for browser rendering.

    Args:
        distance_rows: Pairwise distance records for the rendered members.
        member_ids: Exact rendered member identifiers.
        preferred_order: Preferred tree-leaf order when a phylogram is available.

    Returns:
        JSON-safe upper-triangular matrix payload or an explicit unavailable state.
    """

    if len(member_ids) < 2:
        return {
            "status": "UNAVAILABLE",
            "reason": "At least two rendered members are required.",
        }
    preferred = [member_id for member_id in preferred_order if member_id in member_ids]
    ordered_ids = list(dict.fromkeys(preferred))
    ordered_ids.extend(sorted(member_ids.difference(ordered_ids)))
    lookup = {
        pair: distance
        for pair, distance in _pairwise_distance_lookup(
            distance_rows=distance_rows
        ).items()
        if pair[0] in member_ids and pair[1] in member_ids
    }
    expected_pairs = len(ordered_ids) * (len(ordered_ids) - 1) // 2
    if len(lookup) != expected_pairs:
        return {
            "status": "UNAVAILABLE_INCOMPLETE_MATRIX",
            "reason": (
                f"A complete rendered distance matrix requires {expected_pairs:,} "
                f"pairs; {len(lookup):,} were available."
            ),
            "expected_pair_count": expected_pairs,
            "available_pair_count": len(lookup),
        }
    values = [
        lookup[tuple(sorted((left, right)))]
        for left_index, left in enumerate(ordered_ids)
        for right in ordered_ids[left_index + 1 :]
    ]
    return {
        "status": "EXACT_COMPLETE_DISPLAYED_MATRIX",
        "memberOrder": ordered_ids,
        "orderMethod": (
            "PRUNED_GENE_TREE_LEAF_ORDER"
            if len(preferred) == len(member_ids)
            else (
                "PARTIAL_PHYLOGRAM_THEN_LEXICAL_MEMBER_ID"
                if preferred
                else "LEXICAL_MEMBER_ID"
            )
        ),
        "pairCount": expected_pairs,
        "minimum": min(values),
        "maximum": max(values),
        "upperTriangle": values,
    }


def _phylogram_payload(
    *,
    statistic: Mapping[str, Any],
    rendered_members: Sequence[Mapping[str, Any]],
    medoid: Mapping[str, Any],
    nodes_by_tree_id: Mapping[str, Sequence[Mapping[str, Any]]],
    edges_by_tree_id: Mapping[str, Sequence[Mapping[str, Any]]],
    aliases_by_member_species: Mapping[tuple[str, str], set[str]],
    species_palette: Mapping[str, str],
) -> dict[str, Any]:
    """Build a branch-length-scaled tree pruned to rendered members.

    Args:
        statistic: Group summary containing hierarchical and legacy tree identifiers.
        rendered_members: Exact bounded members displayed in the report.
        medoid: Sampled-medoid metadata for role annotation.
        nodes_by_tree_id: Normalised resolved-tree nodes keyed by tree identifier.
        edges_by_tree_id: Normalised resolved-tree edges keyed by tree identifier.
        aliases_by_member_species: OrthoFinder internal aliases by member and species.
        species_palette: Deterministic species colour mapping.

    Returns:
        JSON-safe rectangular phylogram payload or an explicit unavailable state.
    """

    candidate_tree_ids = list(
        dict.fromkeys(
            str(value)
            for value in (
                statistic.get("legacy_orthogroup_id", ""),
                statistic.get("group_id", ""),
            )
            if value
        )
    )
    tree_id = next(
        (candidate for candidate in candidate_tree_ids if nodes_by_tree_id.get(candidate)),
        "",
    )
    if not tree_id:
        return {
            "status": "UNAVAILABLE_NO_NORMALISED_RESOLVED_TREE",
            "reason": "No checksum-verified resolved gene tree was available for this group.",
            "candidateTreeIds": candidate_tree_ids,
        }
    tree_nodes = list(nodes_by_tree_id[tree_id])
    tree_edges = list(edges_by_tree_id.get(tree_id, ()))
    node_by_id = {str(row.get("node_id", "")): row for row in tree_nodes}

    member_species = {
        str(row.get("member_id", "")): str(row.get("species_label", ""))
        for row in rendered_members
    }
    alias_members: dict[str, set[str]] = defaultdict(set)
    for member_id, species in member_species.items():
        alias_members[member_id].add(member_id)
        alias_members[f"{species}_{member_id}"].add(member_id)
        for alias in aliases_by_member_species.get((member_id, species), set()):
            if alias:
                alias_members[alias].add(member_id)
    ambiguous_aliases = sorted(
        alias for alias, members in alias_members.items() if len(members) > 1
    )
    leaf_member: dict[str, str] = {}
    member_leaf: dict[str, str] = {}
    duplicated_members: set[str] = set()
    for node_id, row in node_by_id.items():
        if not _report_bool(row.get("is_leaf", False)):
            continue
        alias = str(row.get("node_name", ""))
        members = alias_members.get(alias, set())
        if len(members) != 1:
            continue
        member_id = next(iter(members))
        if member_id in member_leaf:
            duplicated_members.add(member_id)
            continue
        leaf_member[node_id] = member_id
        member_leaf[member_id] = node_id
    if duplicated_members:
        return {
            "status": "UNAVAILABLE_AMBIGUOUS_TREE_LEAVES",
            "reason": (
                "Multiple tree leaves resolved to the same rendered member: "
                + ", ".join(sorted(duplicated_members)[:10])
            ),
            "treeId": tree_id,
        }
    if len(leaf_member) < 2:
        return {
            "status": "UNAVAILABLE_INSUFFICIENT_RESOLVED_LEAVES",
            "reason": (
                f"Resolved {len(leaf_member):,} of {len(member_species):,} rendered "
                "members to unique leaves; at least two are required."
            ),
            "treeId": tree_id,
            "ambiguousAliases": ambiguous_aliases,
        }

    parent_by_node: dict[str, str] = {}
    branch_by_child: dict[str, float] = {}
    ordered_children: dict[str, list[str]] = defaultdict(list)
    for edge in tree_edges:
        parent = str(edge.get("parent_node_id", ""))
        child = str(edge.get("child_node_id", ""))
        if parent not in node_by_id or child not in node_by_id:
            continue
        parent_by_node[child] = parent
        ordered_children[parent].append(child)
        branch_by_child[child] = _report_float(edge.get("branch_length", ""))
    if not parent_by_node:
        for node_id, row in node_by_id.items():
            parent = str(row.get("parent_node_id", ""))
            if parent and parent in node_by_id:
                parent_by_node[node_id] = parent
                ordered_children[parent].append(node_id)
                branch_by_child[node_id] = _report_float(row.get("branch_length", ""))

    included = set(leaf_member)
    for leaf_id in tuple(leaf_member):
        current = leaf_id
        seen = {current}
        while current in parent_by_node:
            current = parent_by_node[current]
            if current in seen:
                return {
                    "status": "UNAVAILABLE_CYCLIC_TREE",
                    "reason": f"Resolved gene tree {tree_id} contains a parent cycle.",
                    "treeId": tree_id,
                }
            included.add(current)
            seen.add(current)
    roots = sorted(node_id for node_id in included if node_id not in parent_by_node)
    if len(roots) != 1:
        return {
            "status": "UNAVAILABLE_DISCONNECTED_TREE",
            "reason": (
                f"The pruned tree requires one root; {len(roots):,} roots were found."
            ),
            "treeId": tree_id,
        }
    root = roots[0]
    children = {
        node_id: [child for child in ordered_children.get(node_id, ()) if child in included]
        for node_id in included
    }
    traversal: list[str] = []

    def visit(node_id: str) -> None:
        traversal.append(node_id)
        for child in children[node_id]:
            visit(child)

    visit(root)
    if set(traversal) != included:
        return {
            "status": "UNAVAILABLE_DISCONNECTED_TREE",
            "reason": "Not every pruned node was reachable from the resolved root.",
            "treeId": tree_id,
        }
    cumulative = {root: 0.0}
    for node_id in traversal:
        for child in children[node_id]:
            cumulative[child] = cumulative[node_id] + branch_by_child.get(child, 0.0)
    member_order = [leaf_member[node_id] for node_id in traversal if node_id in leaf_member]
    y_by_node = {
        member_leaf[member_id]: float(index)
        for index, member_id in enumerate(member_order)
    }
    for node_id in reversed(traversal):
        child_values = [y_by_node[child] for child in children[node_id] if child in y_by_node]
        if child_values:
            y_by_node[node_id] = (min(child_values) + max(child_values)) / 2.0
    maximum_root_distance = max(cumulative.values(), default=0.0)
    if maximum_root_distance <= 0:
        return {
            "status": "UNAVAILABLE_NO_POSITIVE_BRANCH_LENGTHS",
            "reason": "The pruned resolved tree contains no positive branch lengths.",
            "treeId": tree_id,
        }
    medoid_id = str(medoid.get("member_id", ""))
    unresolved = sorted(set(member_species).difference(member_order))
    output_nodes = []
    for node_id in traversal:
        row = node_by_id[node_id]
        member_id = leaf_member.get(node_id, "")
        species = member_species.get(member_id, "")
        output_nodes.append(
            {
                "id": node_id,
                "parentId": parent_by_node.get(node_id, ""),
                "x": cumulative[node_id],
                "y": y_by_node[node_id],
                "isLeaf": bool(member_id),
                "memberId": member_id,
                "label": member_id or str(row.get("node_name", "")),
                "species": species,
                "colour": species_palette.get(species, "#4b5563"),
                "isMedoid": bool(member_id and member_id == medoid_id),
                "branchLength": branch_by_child.get(node_id, 0.0),
                "confidence": row.get("confidence", ""),
            }
        )
    output_edges = [
        {
            "parentId": parent_by_node[node_id],
            "childId": node_id,
            "branchLength": branch_by_child.get(node_id, 0.0),
        }
        for node_id in traversal
        if node_id in parent_by_node
    ]
    return {
        "status": (
            "COMPLETE_PRUNED_PHYLOGRAM"
            if not unresolved
            else "PARTIAL_PRUNED_PHYLOGRAM"
        ),
        "method": "RESOLVED_GENE_TREE_BRANCH_LENGTH",
        "treeId": tree_id,
        "requestedMemberCount": len(member_species),
        "displayedLeafCount": len(member_order),
        "maximumRootDistance": maximum_root_distance,
        "unresolvedMembers": unresolved,
        "ambiguousAliases": ambiguous_aliases,
        "memberOrder": member_order,
        "nodes": output_nodes,
        "edges": output_edges,
    }


def _report_bool(value: Any) -> bool:
    """Return a strict boolean interpretation of a report-table value."""

    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _report_float(value: Any) -> float:
    """Return a finite float or zero for an unavailable branch length."""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _select_members(
    *, members: Sequence[Mapping[str, Any]], group_key: str, max_members: int
) -> list[Mapping[str, Any]]:
    """Select deterministic unique members for one browser network.

    Args:
        members: Candidate membership rows.
        group_key: Collision-safe run/group key.
        max_members: Maximum rendered members.

    Returns:
        Deterministically selected rows.
    """

    unique: dict[str, Mapping[str, Any]] = {}
    for row in members:
        unique.setdefault(str(row["member_id"]), row)
    ranked = sorted(
        unique.values(),
        key=lambda row: hashlib.sha256(
            f"{group_key}\0{row['member_id']}".encode("utf-8")
        ).hexdigest(),
    )
    return sorted(ranked[:max_members], key=lambda row: str(row["member_id"]))


def _group_key(row: Mapping[str, Any]) -> str:
    """Return a collision-safe group key shared by report tables.

    Args:
        row: Record containing group type, node and identifier.

    Returns:
        Pipe-delimited key.
    """

    return "|".join(
        (
            str(row.get("group_type", "")),
            str(row.get("hierarchy_node", "")),
            str(row.get("group_id", "")),
        )
    )


def _group_label(row: Mapping[str, Any]) -> str:
    """Return a compact human-readable group label.

    Args:
        row: Group record.

    Returns:
        Type, optional node and group identifier.
    """

    node = str(row.get("hierarchy_node", ""))
    parts = [str(row.get("group_type", ""))]
    if node:
        parts.append(node)
    parts.append(str(row.get("group_id", "")))
    return " · ".join(parts)


def _species_palette(*, species_labels: Iterable[str]) -> dict[str, str]:
    """Return deterministic species colours with exact collision avoidance.

    Colours are derived from the full species label rather than its position in
    the current run, so expanding an OrthoFinder analysis does not normally
    recolour species that were already present. Exact CSS-colour collisions are
    resolved deterministically across the supplied label set.

    Args:
        species_labels: Iterable of exact species labels.

    Returns:
        Mapping from every distinct species label to its CSS HSL colour.
    """

    palette: dict[str, str] = {}
    used: set[str] = set()
    for species in sorted(set(species_labels)):
        attempt = 0
        while True:
            colour = _species_colour(species=species, attempt=attempt)
            if colour not in used:
                palette[species] = colour
                used.add(colour)
                break
            attempt += 1
    return palette


def _species_colour(*, species: str, attempt: int = 0) -> str:
    """Return a deterministic, legible HSL colour for a species.

    Args:
        species: Exact species label.
        attempt: Deterministic collision-resolution attempt.

    Returns:
        CSS HSL colour.
    """

    digest = hashlib.sha256(f"{species}\0{attempt}".encode("utf-8")).digest()
    hue = int.from_bytes(digest[:4], "big") / (2**32) * 360
    saturation = 58 + digest[4] % 19
    lightness = 42 + digest[5] % 17
    return f"hsl({hue:.1f},{saturation}%,{lightness}%)"


def _safe_script_json(value: Mapping[str, Any]) -> str:
    """Serialise JSON without permitting an embedded script terminator.

    Args:
        value: JSON-safe report payload.

    Returns:
        Compact safe JSON text.
    """

    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")


def _load_vis_network_assets() -> tuple[str, str]:
    """Load vis-network JavaScript and CSS bundled by the pyvis dependency.

    Returns:
        Minified JavaScript and stylesheet text.

    Raises:
        PublicationError: If installed pyvis assets are incomplete.
    """

    import pyvis

    root = Path(pyvis.__file__).resolve().parent / "templates" / "lib" / "vis-9.1.2"
    javascript = root / "vis-network.min.js"
    stylesheet_candidates = (root / "vis-network.css", root / "vis-network.min.css")
    stylesheet = next((path for path in stylesheet_candidates if path.is_file()), None)
    if not javascript.is_file() or stylesheet is None:
        raise PublicationError(
            "The installed pyvis package does not contain the expected offline vis-network assets."
        )
    return (
        javascript.read_text(encoding="utf-8"),
        stylesheet.read_text(encoding="utf-8"),
    )
