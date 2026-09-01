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
    .network-support-grid {{ display:grid; grid-template-columns:repeat(3,minmax(240px,1fr));
      gap:1rem; margin-top:1rem; }}
    .detail {{ border-left:1px solid var(--line); padding-left:1rem; overflow-wrap:anywhere; }}
    .detail dl {{ display:grid; grid-template-columns:auto 1fr; gap:.35rem .65rem; }}
    .detail dt {{ font-weight:700; }} .detail dd {{ margin:0; }}
    .notice {{ color:var(--warn); background:#fff7e8; border:1px solid #eed09e;
      padding:.65rem; border-radius:7px; margin:.7rem 0; }}
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
    .chart {{ min-height:250px; }}
    .chart svg {{ width:100%; height:250px; display:block; overflow:visible; }}
    .chart .axis {{ stroke:#8993a8; stroke-width:1; }}
    .chart .grid {{ stroke:#e5e8ef; stroke-width:1; }}
    .chart text {{ fill:var(--muted); font-size:11px; }}
    .chart .plot-bar {{ fill:#5577d5; }}
    .chart .plot-point {{ fill:#d7633c; fill-opacity:.65; stroke:#8b3219; stroke-width:.45; }}
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
      .detail {{ border-left:0; padding-left:0; }} .network-canvas {{ height:480px; }} }}
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
      <article class="chart-card"><h3>Cluster-size distribution</h3>
        <div id="cluster-size-chart" class="chart" role="img" aria-label="Cluster-size histogram"></div>
        <p class="small">Log₂-sized bins retain the long tail of large clusters.</p></article>
      <article class="chart-card"><h3>Species-breadth distribution</h3>
        <div id="species-breadth-chart" class="chart" role="img" aria-label="Species-breadth histogram"></div>
        <p class="small">Number of represented species per cluster.</p></article>
      <article class="chart-card"><h3>Copy-number complexity</h3>
        <div id="copy-complexity-chart" class="chart" role="img" aria-label="Maximum copies per species histogram"></div>
        <p class="small">Maximum paralogue count observed in any one species.</p></article>
      <article class="chart-card"><h3>Cluster size versus species breadth</h3>
        <div id="size-breadth-chart" class="chart" role="img" aria-label="Cluster size versus species breadth scatter plot"></div>
        <p class="small">Up to 2,000 deterministic points; y-axis is log-scaled.</p></article>
      <article class="chart-card"><h3>Mean distance versus sampled cluster size</h3>
        <div id="distance-coverage-chart" class="chart" role="img" aria-label="Mean distance versus sampled cluster size scatter plot"></div>
        <p class="small">Available distance summaries only; hover points for exact status and method.</p></article>
      <article class="chart-card"><h3>Exact copy counts for displayed network groups</h3>
        <div id="species-heatmap" class="scroll heatmap"></div>
        <p class="small">Rows: HOGs · columns: species · cells: exact protein-copy counts.
          These are full counts for the bounded network groups, not sampled node counts.</p></article>
    </div>
  </section>
  <section class="panel">
    <h2>Within-HOG protein distance network</h2>
    <p class="small">Each selector entry is one HOG. Node fill colour denotes species;
      the gold star denotes the medoid of the displayed distance sample. The default
      PCoA layout approximates all displayed pairwise distances in two dimensions.</p>
    <div class="controls">
      <label>Group<select id="group-select"></select></label>
      <label>Find member<input id="member-search" type="search" placeholder="Exact or partial ID"></label>
      <label class="check"><input id="show-labels" type="checkbox">Show all labels</label>
      <label class="check"><input id="show-connectors" type="checkbox" checked>Show component connectors</label>
      <button id="fit-distance-network" type="button">Fit distance map</button>
      <button id="fit-topology-network" type="button">Fit topology</button>
    </div>
    <div id="network-notice" class="notice"></div>
    <div class="network-key">
      <span class="key-item"><span class="line-key"></span>Nearest-neighbour edge</span>
      <span class="key-item"><span class="line-key connector"></span>Layout-only component connector</span>
      <span class="key-item"><span class="medoid-key">★</span>Sample medoid</span>
      <span>PCoA spacing approximates all pairwise distances; projection quality is reported below.
        Force-directed spacing is exploratory only.</span>
    </div>
    <article class="network-section">
      <h3>1. Quantitative distance map (PCoA)</h3>
      <p class="small">Fixed node spacing is calculated from every displayed pairwise
        distance. It is a two-dimensional approximation; its quality metrics are shown explicitly.</p>
      <div id="distance-network-notice" class="notice"></div>
      <div id="distance-network" class="network-canvas"></div>
    </article>
    <article class="network-section">
      <h3>2. Force-directed neighbour topology</h3>
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
const number=v=>Number(v||0).toLocaleString();
const fixed=v=>Number(v||0).toFixed(4);
const cards=[
  ["Run",DATA.run.run_id],["OrthoFinder",DATA.run.orthofinder_version],
  ["Adapter",DATA.run.adapter_name],["Primary groups",DATA.run.primary_group_authority],
  ["Analytical groups",number(DATA.limits.totalGroupStatisticCount)],
  ["Analytical memberships",number(DATA.limits.totalMembershipCount)]
];
document.getElementById("run-cards").innerHTML=cards.map(([label,value])=>
  `<div class="card"><div class="label">${{escapeHtml(label)}}</div><div class="value">${{escapeHtml(value)}}</div></div>`).join("");
document.getElementById("statistics-notice").textContent=
  `Embedded ${{number(DATA.limits.embeddedGroupStatisticCount)}} of ${{number(DATA.limits.totalGroupStatisticCount)}} group summaries. `+
  `Complete rows remain in the analytical outputs.`;
const overviewLevel=document.getElementById("overview-level");
const levelRows=[...DATA.groupStatistics,...DATA.networkGroupStatistics];
const levelRecords=[...new Map(levelRows.map(row=>{{const key=`${{row.group_type}}|${{row.hierarchy_node}}`;
  return [key,{{key,type:row.group_type,node:row.hierarchy_node}}];}})).values()].sort((a,b)=>a.key.localeCompare(b.key));
levelRecords.forEach(level=>{{const option=document.createElement("option");option.value=level.key;
  option.textContent=level.node?`${{level.type}} · ${{level.node}}`:level.type;overviewLevel.appendChild(option);}});
const preferredLevel=levelRecords.find(level=>level.type===DATA.run.primary_group_authority&&level.node==="N0")||
  levelRecords.find(level=>level.type===DATA.run.primary_group_authority)||levelRecords[0];
if(preferredLevel)overviewLevel.value=preferredLevel.key;
function selectedOverviewRows(){{return DATA.groupStatistics.filter(row=>
  `${{row.group_type}}|${{row.hierarchy_node}}`===overviewLevel.value);}}
function plotMessage(target,message){{document.getElementById(target).innerHTML=`<p class="small">${{escapeHtml(message)}}</p>`;}}
function renderOverviewHistogram(targetId,rawValues,logBins,xTitle,yTitle){{const values=rawValues.map(Number).filter(value=>Number.isFinite(value)&&value>=0);
  if(!values.length){{plotMessage(targetId,"No values are available for this group level.");return;}}
  let counts=[],labels=[];
  if(logBins){{const maximum=Math.max(...values,1),last=Math.floor(Math.log2(maximum));counts=Array(last+1).fill(0);
    values.forEach(value=>counts[Math.floor(Math.log2(Math.max(1,value)))]++);
    labels=counts.map((_,index)=>index===0?"1":`${{2**index}}–${{2**(index+1)-1}}`);
  }}else{{const maximum=Math.max(...values,1),binCount=Math.min(20,Math.max(1,Math.ceil(Math.sqrt(values.length)))),width=Math.max(1,Math.ceil(maximum/binCount));
    counts=Array(Math.ceil(maximum/width)).fill(0);values.forEach(value=>counts[Math.min(counts.length-1,Math.floor(value/width))]++);
    labels=counts.map((_,index)=>`${{index*width}}–${{(index+1)*width-1}}`);}}
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
  const peak=Math.max(...counts.values(),1),head=species.map(label=>`<th class="rotate" title="${{escapeHtml(label)}}"><span>${{escapeHtml(label)}}</span></th>`).join("");
  const body=groups.map(group=>`<tr><th>${{escapeHtml(group)}}</th>`+species.map(label=>{{const value=counts.get(`${{group}}\u0000${{label}}`)||0;
    const alpha=value?(.16+.74*value/peak):0;return `<td class="copy" style="background:rgba(53,88,200,${{alpha}})" title="${{escapeHtml(group)}} · ${{escapeHtml(label)}} · copies=${{value}}">${{value||""}}</td>`;}}).join("")+"</tr>").join("");
  target.innerHTML=`<table><thead><tr><th>Group</th>${{head}}</tr></thead><tbody>${{body}}</tbody></table>`;}}
function renderOverview(){{const rows=selectedOverviewRows();document.getElementById("overview-notice").textContent=
  `Visualising ${{number(rows.length)}} embedded summaries for ${{overviewLevel.options[overviewLevel.selectedIndex]?.text||"this level"}}. `+
  `The analytical tables contain ${{number(DATA.limits.totalGroupStatisticCount)}} summaries across all levels.`;
  renderOverviewHistogram("cluster-size-chart",rows.map(row=>row.member_count),true,
    "Members per HOG (log₂ bins)","HOG count");
  renderOverviewHistogram("species-breadth-chart",rows.map(row=>row.species_count),false,
    "Species represented per HOG","HOG count");
  renderOverviewHistogram("copy-complexity-chart",rows.map(row=>row.max_copies_per_species),true,
    "Maximum copies in one species (log₂ bins)","HOG count");
  renderScatter("size-breadth-chart",rows,"species_count","member_count",true,
    ["group_id","species_count","member_count","max_copies_per_species"],
    "Species represented per HOG","Members per HOG (log₂ scale)");
  const distanceRows=DATA.distanceStatistics.filter(row=>`${{row.group_type}}|${{row.hierarchy_node}}`===overviewLevel.value&&
    row.computation_status!=="UNAVAILABLE"&&Number(row.distance_pair_count)>0);
  renderScatter("distance-coverage-chart",distanceRows,"sampled_member_count","mean_distance",false,
    ["group_id","distance_method","computation_status","member_identifier_resolution","mean_distance"],
    "Sampled members per HOG","Mean pairwise distance");
  renderHeatmap(rows);}}
overviewLevel.addEventListener("change",renderOverview);
const groupSelect=document.getElementById("group-select");
Object.keys(DATA.networks).sort().forEach(key=>{{const option=document.createElement("option");
  option.value=key;option.textContent=DATA.networks[key].label;groupSelect.appendChild(option);}});
const showLabels=document.getElementById("show-labels");
const showConnectors=document.getElementById("show-connectors");
const speciesFilter=document.getElementById("species-filter");
let distanceNetwork=null;let distanceNodes=null;let distanceEdges=null;
let topologyNetwork=null;let topologyNodes=null;let topologyEdges=null;
function hasDistanceProjection(entry){{return entry.distanceProjection?.status==="COMPLETE_DISTANCE_PCOA_2D";}}
function visibleNodeRecords(entry,projected){{
  return entry.nodes.map(node=>{{const record={{...node,label:node.isGroup?node.label:(showLabels.checked?node.memberLabel:"")}};
    if(projected&&!node.isGroup){{record.x=node.projectionX;record.y=node.projectionY;record.fixed={{x:true,y:true}};}}
    else record.fixed=false;return record;}});}}
function visibleEdgeRecords(entry){{return entry.edges.filter(edge=>
  showConnectors.checked||edge.edgeType!=="COMPONENT_CONNECTOR").map(edge=>({{...edge}}));}}
function bindNodeInspection(currentNetwork,currentNodes,entry){{currentNetwork.on("click",params=>{{
  if(!params.nodes.length)return;const node=currentNodes.get(params.nodes[0]);
  const representative=node.isMedoid?`<dt>Representative</dt><dd>Sample medoid; mean distance `+
    `${{fixed(entry.medoid.mean_distance)}} to ${{number(entry.medoid.comparison_count)}} displayed proteins</dd>`:"";
  document.getElementById("node-detail").innerHTML=`<dl><dt>ID</dt><dd>${{escapeHtml(node.memberLabel||node.label)}}</dd>`+
    `<dt>Species</dt><dd>${{escapeHtml(node.species||"")}}</dd><dt>Group</dt><dd>${{escapeHtml(entry.label)}}</dd>`+
    representative+`</dl>`;
}});}}
function renderNetwork(){{
  const entry=DATA.networks[groupSelect.value];
  if(!entry){{document.getElementById("network-notice").textContent="No network groups were embedded.";return;}}
  if(distanceNetwork)distanceNetwork.destroy();if(topologyNetwork)topologyNetwork.destroy();
  const distanceTarget=document.getElementById("distance-network");distanceTarget.textContent="";
  const edgeRecords=visibleEdgeRecords(entry);
  if(hasDistanceProjection(entry)){{
    distanceNodes=new vis.DataSet(visibleNodeRecords(entry,true));distanceEdges=new vis.DataSet(edgeRecords.map(edge=>({{...edge}})));
    distanceNetwork=new vis.Network(distanceTarget,{{nodes:distanceNodes,edges:distanceEdges}},{{
      autoResize:true,interaction:{{hover:true,navigationButtons:true,multiselect:true,dragNodes:false}},physics:false,
      edges:{{smooth:false,color:{{inherit:false}},font:{{size:9,align:"middle"}}}},
      nodes:{{shape:"dot",size:14,font:{{size:11}},borderWidthSelected:4}}
    }});bindNodeInspection(distanceNetwork,distanceNodes,entry);
  }}else{{distanceNetwork=null;distanceNodes=null;distanceEdges=null;
    distanceTarget.textContent="A quantitative distance map is unavailable for this HOG.";}}
  topologyNodes=new vis.DataSet(visibleNodeRecords(entry,false));topologyEdges=new vis.DataSet(edgeRecords.map(edge=>({{...edge}})));
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
  document.getElementById("distance-network-notice").textContent=hasDistanceProjection(entry)?
    `Uses all ${{number(projection.pair_count)}} pairwise distances. PCoA axis 1=${{(100*Number(projection.axis_1_positive_inertia_fraction||0)).toFixed(1)}}% `+
    `and axis 2=${{(100*Number(projection.axis_2_positive_inertia_fraction||0)).toFixed(1)}}% of positive inertia; `+
    `distance correlation=${{projection.distance_correlation==null?"not defined":fixed(projection.distance_correlation)}}; `+
    `normalised stress=${{fixed(projection.normalised_stress)}}; negative inertia=${{(100*Number(projection.negative_inertia_fraction||0)).toFixed(1)}}%.`:
    `Unavailable: ${{projection.reason||"complete distances were not available"}}`;
  document.getElementById("topology-network-notice").textContent=
    `Solid edges retain up to ${{number(DATA.limits.nearestNeighbours)}} nearest neighbours per protein. `+
    `Dashed component connectors can be hidden. Screen spacing is not quantitative.`;
  speciesFilter.value="";renderMembers(entry);renderDistanceHistogram(entry);renderSpeciesLegend(entry);
}}
function renderMembers(entry){{document.getElementById("member-table").innerHTML=entry.members.map(row=>
  `<tr><td>${{row.member_id===entry.medoid?.member_id?"★ ":""}}${{escapeHtml(row.member_id)}}</td>`+
  `<td>${{escapeHtml(row.species_label)}}</td><td>${{escapeHtml(entry.label)}}</td></tr>`).join("");}}
function renderSpeciesLegend(entry){{const term=speciesFilter.value.toLowerCase(),target=document.getElementById("species-legend");
  const records=(entry.speciesLegend||[]).filter(record=>record.species.toLowerCase().includes(term));
  target.innerHTML=records.map(record=>`<button type="button" class="legend-item" data-species="${{escapeHtml(record.species)}}" `+
    `title="Select displayed proteins from ${{escapeHtml(record.species)}}"><span class="legend-swatch" `+
    `style="background:${{record.colour}}"></span><span class="legend-label">${{escapeHtml(record.species)}} `+
    `(${{number(record.displayedMemberCount)}})</span></button>`).join("");
  target.querySelectorAll(".legend-item").forEach(item=>item.addEventListener("click",()=>{{
    [[distanceNetwork,distanceNodes],[topologyNetwork,topologyNodes]].forEach(([currentNetwork,currentNodes])=>{{
      if(!currentNetwork||!currentNodes)return;const matches=currentNodes.get().filter(node=>
        node.species===item.dataset.species).map(node=>node.id);
      if(matches.length){{currentNetwork.selectNodes(matches);currentNetwork.fit({{nodes:matches,animation:true}});}}
    }});
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
document.getElementById("fit-distance-network").addEventListener("click",()=>distanceNetwork&&distanceNetwork.fit());
document.getElementById("fit-topology-network").addEventListener("click",()=>topologyNetwork&&topologyNetwork.fit());
showLabels.addEventListener("change",()=>{{const entry=DATA.networks[groupSelect.value];
  if(distanceNodes)distanceNodes.update(visibleNodeRecords(entry,true).map(node=>({{id:node.id,label:node.label}})));
  if(topologyNodes)topologyNodes.update(visibleNodeRecords(entry,false).map(node=>({{id:node.id,label:node.label}})));}});
showConnectors.addEventListener("change",()=>{{const entry=DATA.networks[groupSelect.value];
  [distanceEdges,topologyEdges].forEach(currentEdges=>{{if(!currentEdges)return;
    currentEdges.clear();currentEdges.add(visibleEdgeRecords(entry));}});}});
speciesFilter.addEventListener("input",()=>{{const entry=DATA.networks[groupSelect.value];if(entry)renderSpeciesLegend(entry);}});
document.getElementById("member-search").addEventListener("input",event=>{{const term=event.target.value.toLowerCase();
  [[distanceNetwork,distanceNodes],[topologyNetwork,topologyNodes]].forEach(([currentNetwork,currentNodes])=>{{
    if(!currentNetwork||!currentNodes)return;if(!term){{currentNetwork.unselectAll();return;}}
    const matches=currentNodes.get().filter(node=>String(node.memberLabel||node.label).toLowerCase().includes(term)&&
      !node.isGroup).map(node=>node.id);
    if(matches.length){{currentNetwork.selectNodes(matches);currentNetwork.focus(matches[0],{{scale:1.5}});}}
  }});}});
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
        supplied_count = len(available_members)
        analytical_count = int(statistic.get("member_count", 0))
        notice = (
            f"This is one within-HOG network. Displayed {len(rendered_members):,} "
            f"of {supplied_count:,} supplied members; analytical HOG size is "
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
            "stress=%s.",
            network_index,
            len(ordered_statistics),
            key,
            len(rendered_members),
            len(species_counts),
            network_metrics["rawComponentCount"],
            network_metrics["connectorCount"],
            projection.get("status", "UNAVAILABLE"),
            projection.get("normalised_stress", ""),
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
    browser lays out the whole HOG together. Connector records are explicitly
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

    display_span = max(float(np.ptp(coordinates[:, 0])), float(np.ptp(coordinates[:, 1])))
    display_scale = 900.0 / display_span if display_span > 0 else 1.0
    positions = {
        member_id: (
            float(coordinates[index, 0] * display_scale),
            float(-coordinates[index, 1] * display_scale),
        )
        for index, member_id in enumerate(ordered_ids)
    }
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
    }
    return positions, metadata


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
