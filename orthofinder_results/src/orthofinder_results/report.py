"""Offline interactive HTML reporting for OrthoFinder result resources."""

from __future__ import annotations

import hashlib
import html
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import PublicationError
from .io_utils import atomic_write_text


def build_interactive_report(
    *,
    output_path: Path,
    run_metadata: Mapping[str, Any],
    group_statistics: Sequence[Mapping[str, Any]],
    memberships: Sequence[Mapping[str, Any]],
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
        memberships: Bounded member rows for network-rendered groups.
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
    vis_javascript, vis_stylesheet = _load_vis_network_assets()
    networks = _build_network_payload(
        group_statistics=group_statistics,
        memberships=memberships,
        distances=distances,
        distance_statistics=distance_statistics,
        max_groups=max_network_groups,
        max_members=max_network_members,
        nearest_neighbours=nearest_neighbours,
    )
    payload = {
        "run": dict(run_metadata),
        "groupStatistics": [dict(row) for row in group_statistics],
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
    .controls {{ display:flex; flex-wrap:wrap; gap:.65rem; align-items:end; }}
    label {{ display:flex; flex-direction:column; gap:.25rem; color:var(--muted);
      font-size:.8rem; }}
    select,input,button {{ font:inherit; padding:.48rem .58rem; border:1px solid #aeb7ca;
      border-radius:6px; background:white; color:var(--ink); }}
    button {{ cursor:pointer; background:#eef2ff; border-color:#9dafef; }}
    #network {{ height:620px; border:1px solid var(--line); border-radius:8px;
      margin-top:.8rem; background:#fff; }}
    .network-grid {{ display:grid; grid-template-columns:minmax(0,3fr) minmax(260px,1fr);
      gap:1rem; }}
    .detail {{ border-left:1px solid var(--line); padding-left:1rem; overflow-wrap:anywhere; }}
    .detail dl {{ display:grid; grid-template-columns:auto 1fr; gap:.35rem .65rem; }}
    .detail dt {{ font-weight:700; }} .detail dd {{ margin:0; }}
    .notice {{ color:var(--warn); background:#fff7e8; border:1px solid #eed09e;
      padding:.65rem; border-radius:7px; margin:.7rem 0; }}
    .histogram {{ display:flex; align-items:flex-end; gap:3px; height:130px;
      border-bottom:1px solid #9aa4b7; padding-top:.5rem; }}
    .bar {{ flex:1; min-width:4px; background:#5577d5; border-radius:3px 3px 0 0; }}
    .scroll {{ overflow:auto; max-height:500px; border:1px solid var(--line); }}
    table {{ width:100%; border-collapse:collapse; font-size:.82rem; }}
    th,td {{ padding:.42rem .5rem; text-align:left; border-bottom:1px solid #e6e9f1;
      white-space:nowrap; }}
    th {{ position:sticky; top:0; background:#edf1f8; z-index:2; }}
    tr:hover td {{ background:#f5f7fd; }}
    .pager {{ display:flex; gap:.5rem; align-items:center; margin-top:.6rem; }}
    .small {{ color:var(--muted); font-size:.78rem; }}
    @media (max-width:900px) {{ .network-grid {{ grid-template-columns:1fr; }}
      .detail {{ border-left:0; padding-left:0; }} #network {{ height:480px; }} }}
  </style>
  <script>{vis_javascript}</script>
</head>
<body>
<header><h1>OrthoFinder results interrogation</h1><p>Run {title} · offline interactive report</p></header>
<main>
  <section class="cards" id="run-cards"></section>
  <section class="panel">
    <h2>Interactive cluster view</h2>
    <div class="controls">
      <label>Group<select id="group-select"></select></label>
      <label>Find member<input id="member-search" type="search" placeholder="Exact or partial ID"></label>
      <button id="fit-network" type="button">Fit network</button>
    </div>
    <div id="network-notice" class="notice"></div>
    <div class="network-grid">
      <div id="network"></div>
      <aside class="detail">
        <h2>Selected member</h2><div id="node-detail" class="small">Click a node to inspect it.</div>
        <h2>Distance distribution</h2><div id="distance-summary" class="small"></div>
        <div id="histogram" class="histogram" aria-label="Distance histogram"></div>
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
      placeholder="Group, node, type or species"></label></div>
    <div class="scroll"><table><thead><tr><th>Type</th><th>Node</th><th>Group</th>
      <th>Members</th><th>Species</th><th>Max copies/species</th><th>Mean copies/species</th></tr></thead>
      <tbody id="statistics-table"></tbody></table></div>
    <div class="pager"><button id="previous-page" type="button">Previous</button>
      <span id="page-status" class="small"></span><button id="next-page" type="button">Next</button></div>
  </section>
  <p class="small">This report is an exploratory, bounded visualisation. The checksum-bound TSV,
    Parquet and DuckDB resources are the complete analytical authorities.</p>
</main>
<script id="orthofinder-results-data" type="application/json">{payload_json}</script>
<script>
"use strict";
const DATA=JSON.parse(document.getElementById("orthofinder-results-data").textContent);
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
const groupSelect=document.getElementById("group-select");
Object.keys(DATA.networks).sort().forEach(key=>{{const option=document.createElement("option");
  option.value=key;option.textContent=DATA.networks[key].label;groupSelect.appendChild(option);}});
let network=null;let nodes=null;let edges=null;
function renderNetwork(){{
  const entry=DATA.networks[groupSelect.value];
  if(!entry){{document.getElementById("network-notice").textContent="No network groups were embedded.";return;}}
  nodes=new vis.DataSet(entry.nodes);edges=new vis.DataSet(entry.edges);
  network=new vis.Network(document.getElementById("network"),{{nodes,edges}},{{
    autoResize:true,interaction:{{hover:true,navigationButtons:true,multiselect:true}},
    physics:{{solver:"forceAtlas2Based",stabilization:{{iterations:250}}}},
    edges:{{smooth:false,color:{{inherit:false}},font:{{size:9,align:"middle"}}}},
    nodes:{{shape:"dot",size:15,font:{{size:11}}}}
  }});
  network.on("click",params=>{{if(!params.nodes.length)return;const node=nodes.get(params.nodes[0]);
    document.getElementById("node-detail").innerHTML=`<dl><dt>ID</dt><dd>${{escapeHtml(node.label)}}</dd>`+
      `<dt>Species</dt><dd>${{escapeHtml(node.species||"")}}</dd><dt>Group</dt><dd>${{escapeHtml(entry.label)}}</dd></dl>`;}});
  document.getElementById("network-notice").textContent=entry.notice;
  renderMembers(entry);renderHistogram(entry);
}}
function renderMembers(entry){{document.getElementById("member-table").innerHTML=entry.members.map(row=>
  `<tr><td>${{escapeHtml(row.member_id)}}</td><td>${{escapeHtml(row.species_label)}}</td><td>${{escapeHtml(entry.label)}}</td></tr>`).join("");}}
function renderHistogram(entry){{const values=entry.distanceValues.map(Number).filter(Number.isFinite);
  const target=document.getElementById("histogram"),summary=document.getElementById("distance-summary");
  target.innerHTML="";if(!values.length){{summary.textContent="No pairwise distances were available for this rendered group.";return;}}
  const min=Math.min(...values),max=Math.max(...values),bins=20,counts=Array(bins).fill(0),width=(max-min)||1;
  values.forEach(value=>{{const index=Math.min(bins-1,Math.floor((value-min)/width*bins));counts[index]++;}});
  const peak=Math.max(...counts,1);counts.forEach((count,index)=>{{const bar=document.createElement("div");bar.className="bar";
    bar.style.height=`${{100*count/peak}}%`;bar.title=`Bin ${{index+1}}: ${{count}} pairs`;target.appendChild(bar);}});
  const s=entry.distanceSummary||{{}};summary.textContent=`${{s.distance_method||"Distance"}} · n=${{number(values.length)}} pairs · `+
    `mean=${{fixed(s.mean_distance)}} · median=${{fixed(s.median_distance)}} · range=${{fixed(min)}}–${{fixed(max)}} · ${{s.computation_status||""}}`;}}
groupSelect.addEventListener("change",renderNetwork);
document.getElementById("fit-network").addEventListener("click",()=>network&&network.fit());
document.getElementById("member-search").addEventListener("input",event=>{{if(!network||!nodes)return;
  const term=event.target.value.toLowerCase();if(!term)return;const matches=nodes.get().filter(node=>
    String(node.label).toLowerCase().includes(term)&&!node.isGroup).map(node=>node.id);if(matches.length){{network.selectNodes(matches);network.focus(matches[0],{{scale:1.5}});}}}});
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
renderStats();renderNetwork();
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
    payload: dict[str, Any] = {}
    for statistic in ordered_statistics:
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
        nodes = [
            {
                "id": str(row["member_id"]),
                "label": str(row["member_id"]),
                "title": html.escape(
                    f"{row['member_id']} | {row.get('species_label', '')}", quote=True
                ),
                "species": str(row.get("species_label", "")),
                "color": _species_colour(species=str(row.get("species_label", ""))),
                "isGroup": False,
            }
            for row in rendered_members
        ]
        if group_distances:
            edges = _nearest_neighbour_edges(
                distance_rows=group_distances,
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
                {"from": centre, "to": member_id, "color": "#c8cedb", "dashes": True}
                for member_id in sorted(rendered_ids)
            ]
        notice = (
            f"Rendered {len(rendered_members):,} of {len(available_members):,} supplied members; "
            f"analytical group size is {int(statistic.get('member_count', 0)):,}. "
            f"Edges retain up to {nearest_neighbours} nearest neighbours per rendered member."
        )
        payload[key] = {
            "label": _group_label(statistic),
            "nodes": nodes,
            "edges": edges,
            "members": [dict(row) for row in rendered_members],
            "distanceValues": [float(row["distance"]) for row in group_distances],
            "distanceSummary": summary_by_key.get(key),
            "notice": notice,
        }
    return payload


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

    neighbours: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for row in distance_rows:
        left, right = str(row["member_a"]), str(row["member_b"])
        distance = float(row["distance"])
        neighbours[left].append((distance, right))
        neighbours[right].append((distance, left))
    retained: set[tuple[str, str]] = set()
    distance_lookup: dict[tuple[str, str], float] = {}
    for member, candidates in neighbours.items():
        for distance, neighbour in sorted(candidates)[:nearest_neighbours]:
            edge = tuple(sorted((member, neighbour)))
            retained.add(edge)
            distance_lookup[edge] = distance
    edges = []
    for left, right in sorted(retained):
        distance = distance_lookup[(left, right)]
        edges.append(
            {
                "from": left,
                "to": right,
                "color": "#7786a8",
                "value": max(0.2, 1.2 - distance),
                "title": f"distance={distance:.6g}",
            }
        )
    return edges


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


def _species_colour(*, species: str) -> str:
    """Return a deterministic, legible HSL colour for a species.

    Args:
        species: Exact species label.

    Returns:
        CSS HSL colour.
    """

    digest = hashlib.sha256(species.encode("utf-8")).hexdigest()
    hue = int(digest[:8], 16) % 360
    return f"hsl({hue},62%,52%)"


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
