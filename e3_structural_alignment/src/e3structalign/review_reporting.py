"""Self-contained HTML reporting for ranked top-group pocket review."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


def _text(value: Any) -> str:
    """Return one compact, escaped display value."""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.4g}"
    return html.escape(str(value))


def _status_class(value: Any) -> str:
    """Return a conservative CSS class for one evidence conclusion."""
    text = str(value or "").upper()
    if any(token in text for token in ("NOT_ASSESSED", "UNAVAILABLE", "INSUFFICIENT")):
        return "unknown"
    if any(token in text for token in ("NOT_SUPPORTED", "FAIL", "EXCLUDED")):
        return "not-supported"
    if any(token in text for token in ("SUPPORTED", "PASS", "HIGH_CONFIDENCE")):
        return "supported"
    return "neutral"


def _record_table(
    record: Mapping[str, Any],
    *,
    fields: Sequence[tuple[str, str]] | None = None,
) -> str:
    """Render one mapping as a two-column HTML evidence table."""
    selected = fields or tuple((key, key.replace("_", " ").title()) for key in record)
    rows = []
    for key, label in selected:
        if key not in record:
            continue
        value = record[key]
        rows.append(
            "<tr>"
            f"<th>{html.escape(label)}</th>"
            f'<td><span class="badge {_status_class(value)}">{_text(value)}</span></td>'
            "</tr>"
        )
    return '<table class="evidence"><tbody>' + "".join(rows) + "</tbody></table>"


def _pocket_table(payload: Mapping[str, Any]) -> str:
    """Render every retained member pocket in deterministic report order."""
    rows = []
    for protein in payload["proteins"]:
        for pocket in protein["pockets"]:
            rows.append(
                "<tr>"
                f"<td>{_text(protein['accession'])}</td>"
                f"<td>{_text(protein['species'])}</td>"
                f"<td>{_text(pocket['selection_rank'])}</td>"
                f"<td>{_text(pocket['pocket_number'])}</td>"
                f"<td>{_text(pocket['druggability_score'])}</td>"
                f"<td>{_text(pocket['mapping_fraction'])}</td>"
                f"<td>{_text(pocket['pocket_plddt_fraction'])}</td>"
                f"<td>{_text(pocket['predictor_agreement'])}</td>"
                f"<td>{_text(pocket['structural_evidence_status'])}</td>"
                "</tr>"
            )
    return (
        '<div class="table-scroll"><table class="wide"><thead><tr>'
        "<th>Accession</th><th>Species</th><th>Pocket rank</th><th>Pocket number</th>"
        "<th>Druggability</th><th>Mapping fraction</th><th>pLDDT fraction</th>"
        "<th>Predictor agreement</th><th>Evidence status</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _records_table(records: Sequence[Mapping[str, Any]]) -> str:
    """Render a sequence of mappings as one scrollable wide table."""
    if not records:
        return '<p class="note">No member-level records were available.</p>'
    fields = sorted({str(key) for record in records for key in record})
    header = "".join(
        f"<th>{html.escape(field.replace('_', ' ').title())}</th>"
        for field in fields
    )
    rows = "".join(
        "<tr>"
        + "".join(f"<td>{_text(record.get(field))}</td>" for field in fields)
        + "</tr>"
        for record in records
    )
    return (
        '<div class="table-scroll"><table class="wide"><thead><tr>'
        + header
        + "</tr></thead><tbody>"
        + rows
        + "</tbody></table></div>"
    )


def _json_payload(payload: Mapping[str, Any]) -> str:
    """Serialise browser data without permitting a script-closing token."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).replace(
        "</", "<\\/"
    )


_GROUP_STYLE = """
:root{--ink:#14212b;--muted:#52616d;--blue:#0b5f8a;--navy:#0a2638;--line:#d6e0e6;
--paper:#fff;--wash:#f2f6f8;--rank1:#2de2a6;--rank2:#ef5da8;--rank3:#ffb547;
--rank4:#7b8cff;--rank5:#f07167}
*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);
font-family:Calibri,"Segoe UI",system-ui,sans-serif}
header{background:linear-gradient(120deg,#0a2638,#0b5f8a);
color:#fff;padding:1.4rem clamp(1rem,4vw,3rem)}header a{color:#cceeff}h1{margin:.35rem 0 .25rem;
font-size:clamp(1.5rem,3vw,2.5rem)}h2{margin-top:0}main{max-width:1500px;margin:auto;padding:1rem}
.notice{background:#fff8dc;border-left:6px solid #e6a700;padding:.9rem 1rem;margin:1rem 0}
.grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(300px,.7fr);gap:1rem}
.card{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:1rem;
min-width:0;
box-shadow:0 2px 10px #15394f10;margin-bottom:1rem}.viewer-layout{display:grid;
grid-template-columns:minmax(0,1fr) 330px;gap:1rem}#viewer{width:100%;height:68vh;min-height:500px;
background:#06131c;border-radius:8px;cursor:grab}
#viewer:active{cursor:grabbing}.controls label{display:block;
margin:.55rem 0}.controls select,.controls button{width:100%;padding:.48rem;margin-top:.2rem}
.button-row{display:grid;grid-template-columns:1fr 1fr;gap:.5rem}.legend{display:grid;gap:.35rem;
font-size:.9rem}.swatch{display:inline-block;width:.85rem;height:.85rem;border-radius:50%;
margin-right:.4rem;vertical-align:-.08rem}.rank1{background:var(--rank1)}.rank2{background:var(--rank2)}
.rank3{background:var(--rank3)}.rank4{background:var(--rank4)}.rank5{background:var(--rank5)}
.trace{background:#62aef5}.note{color:var(--muted);font-size:.9rem}.badge{display:inline-block;
border-radius:999px;padding:.13rem .5rem;background:#e9eef2;max-width:100%;
overflow-wrap:anywhere;white-space:normal}
.supported{background:#d9f8ea;color:#075c3d}
.not-supported{background:#ffe0e0;color:#8b1c1c}.unknown{background:#f1ead5;color:#6f5814}
.neutral{background:#e9eef2;color:#34434e}table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{border:1px solid var(--line);padding:.42rem;text-align:left;vertical-align:top;
overflow-wrap:anywhere}
th{background:#edf4f7}
.evidence th{width:46%}.table-scroll{overflow:auto}.wide{min-width:1050px}
.alignment-shell{overflow:auto;background:#07141c;color:#dfeaf0;border-radius:8px;padding:.8rem;
max-height:70vh}
.alignment-row{display:grid;grid-template-columns:210px max-content;gap:.7rem;
align-items:start;margin:.18rem 0}
.alignment-label{position:sticky;left:0;background:#07141c;z-index:2;
white-space:nowrap;color:#a8c7d8}.sequence{font-family:"SFMono-Regular",Consolas,monospace;
white-space:pre;letter-spacing:.02rem}.aa{display:inline-block;min-width:.66rem;text-align:center}
.aa.p1{background:var(--rank1);color:#032d23;font-weight:700}.aa.p2{background:var(--rank2);
color:#2a0717;font-weight:700}.aa.p3{background:var(--rank3);color:#3d2400;font-weight:700}
.aa.p4{background:var(--rank4);color:#fff;font-weight:700}.aa.p5{background:var(--rank5);
color:#fff;font-weight:700}.aa.gap{color:#50616c}.ruler{color:#78909d}.metric{font-size:1.4rem;
font-weight:700;color:var(--blue)}details summary{cursor:pointer;font-weight:700;margin:.3rem 0}
.track-row{display:grid;grid-template-columns:210px minmax(500px,1fr);gap:.7rem;
align-items:center;margin:.55rem 0}.track-label{white-space:nowrap}.track-line{height:1.2rem;
position:relative;background:#dce7ed;border-radius:999px;border:1px solid #b5c8d2}
.track-marker{position:absolute;top:50%;width:.75rem;height:.75rem;border:2px solid white;
border-radius:50%;transform:translate(-50%,-50%);box-shadow:0 0 0 1px #21313b}
.track-row.selected{background:#eaf5fa;border-radius:6px;padding:.3rem}
@media(max-width:1050px){.grid,.viewer-layout{grid-template-columns:1fr}#viewer{height:60vh}}
"""


_GROUP_SCRIPT = r"""
"use strict";
const data=JSON.parse(document.getElementById("reviewData").textContent);
const canvas=document.getElementById("viewer"),ctx=canvas.getContext("2d");
const proteinSelect=document.getElementById("proteinSelect");
const pocketSelect=document.getElementById("pocketSelect");
const palette={1:"#2de2a6",2:"#ef5da8",3:"#ffb547",4:"#7b8cff",5:"#f07167"};
let rx=-0.28,ry=0.45,zoom=1,drag=false,moved=false,lastX=0,lastY=0,projected=[];
function formatMetric(value){if(value===null||value===undefined)return"NA";
return typeof value==="number"?Number(value.toPrecision(4)).toString():String(value);}
function currentProtein(){
return data.proteins.find(p=>p.accession===proteinSelect.value)||data.proteins[0];}
function selectedRank(){return Number(pocketSelect.value);}
function visibleAnnotations(atom){const rank=selectedRank();
return atom.pockets.filter(p=>!rank||p.selection_rank===rank);}
function resize(){const r=canvas.getBoundingClientRect();
canvas.width=Math.max(500,r.width*devicePixelRatio);
canvas.height=Math.max(400,r.height*devicePixelRatio);draw();}
function rotate(p){let x=p.x,y=p.y,z=p.z;const cy=Math.cos(ry),sy=Math.sin(ry);
const x1=x*cy+z*sy,z1=-x*sy+z*cy;const cx=Math.cos(rx),sx=Math.sin(rx);
return{x:x1,y:y*cx-z1*sx,z:y*sx+z1*cx};}
function scaleInfo(atoms){const pts=atoms.map(rotate);
let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
for(const p of pts){minX=Math.min(minX,p.x);maxX=Math.max(maxX,p.x);minY=Math.min(minY,p.y);
maxY=Math.max(maxY,p.y);}const w=maxX-minX||1,h=maxY-minY||1;
return{scale:Math.min(canvas.width/(w*1.18),canvas.height/(h*1.18))*zoom,
cx:(minX+maxX)/2,cy:(minY+maxY)/2};}
function project(atom,index,s){const p=rotate(atom);return{x:canvas.width/2+(p.x-s.cx)*s.scale,
y:canvas.height/2-(p.y-s.cy)*s.scale,z:p.z,atom,index};}
function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);projected=[];
const protein=currentProtein();
document.getElementById("modelStatus").textContent=protein.model_status;
if(!protein.atoms.length){ctx.fillStyle="#d4e7f2";
ctx.font=`${18*devicePixelRatio}px sans-serif`;
ctx.fillText("No structure model is available for this member.",
30*devicePixelRatio,50*devicePixelRatio);return;}
const s=scaleInfo(protein.atoms),points=protein.atoms.map((a,i)=>project(a,i,s));
ctx.strokeStyle="#62aef5";ctx.lineWidth=2.2*devicePixelRatio;ctx.globalAlpha=.72;
ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));
ctx.stroke();ctx.globalAlpha=1;for(const p of points){ctx.fillStyle="#62aef5";
ctx.beginPath();ctx.arc(p.x,p.y,1.8*devicePixelRatio,0,Math.PI*2);ctx.fill();}
const pocketPoints=points.filter(p=>visibleAnnotations(p.atom).length);
pocketPoints.sort((a,b)=>a.z-b.z);
for(const p of pocketPoints){const ann=visibleAnnotations(p.atom);
const rank=Math.min(...ann.map(a=>a.selection_rank));
ctx.fillStyle=palette[rank]||"#fff";ctx.strokeStyle="#fff";
ctx.lineWidth=1.1*devicePixelRatio;ctx.beginPath();
ctx.arc(p.x,p.y,6.8*devicePixelRatio,0,Math.PI*2);
ctx.fill();ctx.stroke();}projected=points;}
function updateProtein(){const protein=currentProtein();pocketSelect.replaceChildren();
const all=document.createElement("option");all.value="0";
all.textContent="All retained pockets";pocketSelect.appendChild(all);
for(const pocket of protein.pockets){const option=document.createElement("option");
option.value=String(pocket.selection_rank);
option.textContent=`Rank ${pocket.selection_rank} · pocket ${pocket.pocket_number}`;
pocketSelect.appendChild(option);}document.getElementById("proteinMeta").textContent=
`${protein.accession} · ${protein.species}${protein.is_reference?" · reference":""}`;
document.getElementById("pocketMeta").textContent=protein.pockets.map(p=>
`rank ${p.selection_rank}: pocket ${p.pocket_number}, `+
`druggability ${formatMetric(p.druggability_score)}`).join(" | ");
renderAlignment();renderPocketTracks();draw();}
function renderAlignment(){const shell=document.getElementById("alignment");
shell.replaceChildren();if(data.alignment.status!=="AVAILABLE"){
shell.textContent=data.alignment.reason||"Alignment unavailable";return;}
const rank=selectedRank();for(const record of data.alignment.records){
const row=document.createElement("div");row.className="alignment-row";
const label=document.createElement("div");label.className="alignment-label";
label.textContent=`${record.is_reference?"★ ":""}${record.accession} · ${record.species}`;
const sequence=document.createElement("div");sequence.className="sequence";
const annotations=new Map();for(const ann of record.pocket_annotations){
if(rank&&ann.selection_rank!==rank)continue;
if(!annotations.has(ann.column))annotations.set(ann.column,[]);
annotations.get(ann.column).push(ann);}
for(let i=0;i<record.sequence.length;i++){const span=document.createElement("span");
const residue=record.sequence[i];
span.className="aa"+((residue==="-"||residue===".")?" gap":"");span.textContent=residue;
const anns=annotations.get(i)||[];if(anns.length){
const minRank=Math.min(...anns.map(a=>a.selection_rank));
span.classList.add(`p${minRank}`);span.title=anns.map(a=>
`alignment ${i+1}; FASTA ${a.fasta_position}; pocket ${a.pocket_number}; `+
`rank ${a.selection_rank}`).join("\n");}
sequence.appendChild(span);}row.append(label,sequence);shell.appendChild(row);}}
function renderPocketTracks(){const shell=document.getElementById("pocketTracks");
shell.replaceChildren();if(data.alignment.status!=="AVAILABLE"){
shell.textContent="No published alignment was available for position tracks.";return;}
const rank=selectedRank();for(const record of data.alignment.records){
const row=document.createElement("div");row.className="track-row";
if(record.accession===proteinSelect.value)row.classList.add("selected");
const label=document.createElement("div");label.className="track-label";
label.textContent=`${record.is_reference?"★ ":""}${record.accession} · ${record.species}`;
const line=document.createElement("div");line.className="track-line";
for(const ann of record.pocket_annotations){if(rank&&ann.selection_rank!==rank)continue;
const marker=document.createElement("span");marker.className="track-marker";
marker.style.left=`${100*(ann.column+1)/data.alignment.alignment_length}%`;
marker.style.background=palette[ann.selection_rank]||"#fff";
marker.title=`alignment ${ann.column+1}; FASTA ${ann.fasta_position}; `+
`pocket ${ann.pocket_number}; rank ${ann.selection_rank}`;
line.appendChild(marker);}row.append(label,line);shell.appendChild(row);}}
for(const protein of data.proteins){const option=document.createElement("option");
option.value=protein.accession;
option.textContent=`${protein.is_reference?"★ ":""}${protein.accession} · ${protein.species}`;
proteinSelect.appendChild(option);}proteinSelect.value=data.reference_accession;
proteinSelect.addEventListener("change",updateProtein);
pocketSelect.addEventListener("change",()=>{renderAlignment();renderPocketTracks();draw();});
canvas.addEventListener("pointerdown",e=>{drag=true;moved=false;
lastX=e.clientX;lastY=e.clientY;
canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener("pointermove",e=>{if(!drag)return;
const dx=e.clientX-lastX,dy=e.clientY-lastY;if(Math.abs(dx)+Math.abs(dy)>2)moved=true;
ry+=dx*.01;rx+=dy*.01;lastX=e.clientX;lastY=e.clientY;draw();});
canvas.addEventListener("pointerup",()=>{drag=false;});
canvas.addEventListener("wheel",e=>{e.preventDefault();
zoom*=e.deltaY<0?1.12:.89;zoom=Math.max(.15,Math.min(8,zoom));draw();},{passive:false});
canvas.addEventListener("click",e=>{if(moved)return;const r=canvas.getBoundingClientRect();
const x=(e.clientX-r.left)*devicePixelRatio;
const y=(e.clientY-r.top)*devicePixelRatio;let best=null,dist=Infinity;
for(const p of projected){const d=Math.hypot(p.x-x,p.y-y);if(d<dist){best=p;dist=d;}}
if(best&&dist<15*devicePixelRatio){const anns=visibleAnnotations(best.atom);
document.getElementById("picked").textContent=
`${best.atom.resn} chain ${best.atom.chain||"?"} residue ${best.atom.resi||"?"}`+
`${anns.length?" · "+anns.map(a=>
`pocket ${a.pocket_number} rank ${a.selection_rank}`).join(", "):""}`;}});
document.getElementById("reset").onclick=()=>{rx=-.28;ry=.45;zoom=1;draw();};
document.getElementById("fit").onclick=()=>{zoom=1;draw();};
window.addEventListener("resize",resize);updateProtein();resize();
"""


def render_group_page(payload: Mapping[str, Any]) -> str:
    """Render one standalone evolutionary-group review page."""
    key = payload["group_key"]
    title = (
        f"Rank {payload['review_rank']}: "
        f"{key['primary_group_type']} {key['primary_group_id']}"
    )
    ranking_fields = (
        ("final_evolutionary_rank", "Final review rank"),
        ("prestructure_evolutionary_group_rank", "Pre-structure group rank"),
        ("grant_aligned_prediction_status", "Grant-aligned conclusion"),
        ("grant_aligned_prestructure_pass", "Strict pre-structure pass"),
        ("grant_aligned_base_pass", "Ligandability/conservation base pass"),
        ("grant_aligned_final_pass", "Strict final pass"),
        ("conservation_status", "Sequence pocket conservation"),
        ("three_dimensional_position_status", "Strict 3D position"),
        ("three_dimensional_alignment_status", "Strict 3D conservation"),
        ("sensitivity_position_alignment_status", "Top-k 3D position"),
        ("sensitivity_alignment_status", "Top-k 3D conservation"),
        ("final_score", "Integrated score"),
        ("prestructure_score", "Pre-structure score"),
    )
    structural_fields = (
        ("reference_accession", "Structural reference"),
        ("selected_accession_count", "Selected accessions"),
        ("model_available_accession_count", "Models available"),
        ("aligned_accession_count", "Aligned accessions"),
        ("position_supported_accession_count", "Position-supported accessions"),
        ("supported_accession_count", "Conservation-supported accessions"),
        ("group_position_support_fraction", "Strict position support"),
        ("group_support_fraction", "Strict conservation support"),
        ("mean_minimum_tm_score", "Mean minimum TM-score"),
        ("mean_pocket_overlap_fraction", "Mean pocket overlap"),
        ("median_centroid_distance_angstrom", "Median centroid distance (Å)"),
        ("position_alignment_status", "Strict position conclusion"),
        ("alignment_status", "Strict conservation conclusion"),
    )
    sensitivity_fields = (
        ("member_pocket_top_k", "Member-pocket top-k"),
        (
            "sensitivity_group_position_support_fraction",
            "Top-k position support",
        ),
        ("sensitivity_group_support_fraction", "Top-k conservation support"),
        ("position_rescued_accession_count", "Position-rescued accessions"),
        (
            "conservation_rescued_accession_count",
            "Conservation-rescued accessions",
        ),
        (
            "sensitivity_position_alignment_status",
            "Top-k position conclusion",
        ),
        ("sensitivity_alignment_status", "Top-k conservation conclusion"),
    )
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{_GROUP_STYLE}</style></head><body>
<header><a href="../index.html">← Ranked top-50 index</a>
<h1>{html.escape(title)}</h1>
<p>Lead DeepClust cluster {html.escape(str(key['cluster_id']))} · reference
{html.escape(str(payload['reference_accession']))}</p></header>
<main>
<div class="notice"><strong>Interpretation boundary.</strong> These are predicted pockets and
computational comparisons for expert review. A highlighted pocket does not establish compound
binding, E3 recruitment or complete PROTAC function. The top-k view is sensitivity evidence and
never replaces the immutable strict rank-one result.</div>
<section class="grid">
<div class="card"><h2>Ranked decision record</h2>
{_record_table(payload['ranking'], fields=ranking_fields)}
<details><summary>Show the complete authoritative ranking row</summary>
{_record_table(payload['ranking'])}</details></div>
<div class="card"><h2>Review scope</h2>
<p><span class="metric">{len(payload['proteins'])}</span><br>proteins represented</p>
<p><span class="metric">{payload['alignment']['sequence_count']}</span><br>aligned sequences</p>
<p><strong>Reference source:</strong> {_text(payload['reference_source'])}</p>
<p class="note">The final rank is inherited from the authoritative Stage 10 top-50 relation.
This report does not recalculate or reorder candidates.</p></div>
</section>
<section class="card"><h2>Interactive 3D pocket location</h2>
<div class="viewer-layout"><canvas id="viewer"></canvas><aside class="controls">
<label>Protein<select id="proteinSelect"></select></label>
<label>Pocket display<select id="pocketSelect"></select></label>
<div class="button-row"><button id="reset" type="button">Reset rotation</button>
<button id="fit" type="button">Fit structure</button></div>
<p id="proteinMeta"></p><p id="pocketMeta" class="note"></p>
<p><strong>Model:</strong> <span id="modelStatus"></span></p>
<p class="note">Drag to rotate; use the mouse wheel to zoom; click a residue for its label.
The view is a Cα trace with mapped pocket residues highlighted, not an atomistic surface or
docking result.</p><div class="legend">
<span><i class="swatch trace"></i>Protein Cα trace</span>
<span><i class="swatch rank1"></i>Strict rank-one pocket</span>
<span><i class="swatch rank2"></i>Alternative rank two</span>
<span><i class="swatch rank3"></i>Alternative rank three</span>
<span><i class="swatch rank4"></i>Alternative rank four</span>
<span><i class="swatch rank5"></i>Alternative rank five</span></div>
<h3>Selected residue</h3><p id="picked">None</p></aside></div></section>
<section class="card"><h2>Pocket-annotated MAFFT sequence alignment</h2>
<p>Exact one-based FASTA coordinates from Stage 09 are projected onto the published MAFFT
alignment. Choose a protein and pocket rank above to focus the highlights.</p>
<h3>Interactive linear pocket-position overview</h3>
<p class="note">Markers show pocket residues along the full alignment. Hover for exact
alignment, FASTA, pocket-number and rank details.</p>
<div class="table-scroll"><div id="pocketTracks"></div></div>
<h3>Residue-level alignment</h3>
<div id="alignment" class="alignment-shell"></div></section>
<section class="card"><h2>Retained pocket evidence</h2>{_pocket_table(payload)}</section>
<section class="card"><h2>Member-level top-k agreement and rescue audit</h2>
<p>These records show which member pocket number, if any, both structural aligners supported.
An alternative-pocket rescue remains sensitivity evidence and does not rewrite rank one.</p>
{_records_table(payload['sensitivity_member_summary'])}</section>
<section class="grid"><div class="card"><h2>Strict structural summary</h2>
{_record_table(payload['structural_summary'], fields=structural_fields)}
<details><summary>Complete strict summary</summary>
{_record_table(payload['structural_summary'])}</details></div>
<div class="card"><h2>Top-k sensitivity summary</h2>
{_record_table(payload['sensitivity_group_summary'], fields=sensitivity_fields)}
<details><summary>Complete sensitivity summary</summary>
{_record_table(payload['sensitivity_group_summary'])}</details></div></section>
</main>
<script id="reviewData" type="application/json">{_json_payload(payload)}</script>
<script>{_GROUP_SCRIPT}</script></body></html>"""


_INDEX_STYLE = """
body{font-family:Calibri,"Segoe UI",system-ui,sans-serif;margin:0;background:#f2f6f8;color:#14212b}
header{background:linear-gradient(120deg,#0a2638,#0b5f8a);color:white;
padding:2rem clamp(1rem,5vw,4rem)}
main{max-width:1500px;margin:auto;padding:1rem}.card{background:white;border:1px solid #d6e0e6;
border-radius:10px;padding:1rem;margin:1rem 0;box-shadow:0 2px 10px #15394f10}
.notice{background:#fff8dc;
border-left:6px solid #e6a700;padding:.9rem 1rem}input{width:100%;padding:.65rem;font-size:1rem;
margin:.5rem 0 1rem}table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{border:1px solid #d6e0e6;
padding:.45rem;text-align:left;vertical-align:top}th{background:#e7f0f4;position:sticky;top:0}
.scroll{overflow:auto;max-height:75vh}a{color:#075c9c;font-weight:700}.badge{display:inline-block;
border-radius:999px;padding:.13rem .48rem;background:#e9eef2}
.supported{background:#d9f8ea;color:#075c3d}
.not-supported{background:#ffe0e0;color:#8b1c1c}.unknown{background:#f1ead5;color:#6f5814}
.neutral{background:#e9eef2;color:#34434e}.small{color:#52616d;font-size:.9rem}
.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.8rem;
margin:1rem 0}.summary-card{background:white;border:1px solid #d6e0e6;border-radius:10px;
padding:1rem}.summary-value{font-size:1.8rem;font-weight:700;color:#0b5f8a}
.filter-grid{display:grid;grid-template-columns:minmax(240px,1fr) minmax(220px,.4fr);gap:.8rem}
select{width:100%;padding:.65rem;font-size:1rem;margin:.5rem 0 1rem}
"""


def render_index(payloads: Sequence[Mapping[str, Any]]) -> str:
    """Render the ranked index linking all group review pages."""
    rows = []
    for payload in payloads:
        key = payload["group_key"]
        ranking = payload["ranking"]
        slug = group_page_name(payload)
        searchable = " ".join(
            str(value)
            for value in (
                payload["review_rank"],
                key["cluster_id"],
                key["primary_group_type"],
                key["primary_group_id"],
                ranking.get("grant_aligned_prediction_status", ""),
                ranking.get("three_dimensional_alignment_status", ""),
                ranking.get("sensitivity_alignment_status", ""),
            )
        ).lower()
        rows.append(
            f'<tr data-search="{html.escape(searchable)}">'
            f"<td>{payload['review_rank']}</td>"
            f"<td>{_text(key['primary_group_type'])}<br>"
            f"{_text(key['primary_group_id'])}</td>"
            f"<td>{_text(key['cluster_id'])}</td>"
            f"<td>{_text(payload['reference_accession'])}</td>"
            f"<td>{len(payload['proteins'])}</td>"
            f"<td><span class=\"badge {_status_class(ranking.get('conservation_status'))}\">"
            f"{_text(ranking.get('conservation_status'))}</span></td>"
            "<td><span class=\"badge "
            f"{_status_class(ranking.get('three_dimensional_alignment_status'))}\">"
            f"{_text(ranking.get('three_dimensional_alignment_status'))}</span></td>"
            "<td><span class=\"badge "
            f"{_status_class(ranking.get('sensitivity_alignment_status'))}\">"
            f"{_text(ranking.get('sensitivity_alignment_status'))}</span></td>"
            f'<td><a href="groups/{html.escape(slug)}">Open review page</a></td></tr>'
        )
    protein_count = sum(len(payload["proteins"]) for payload in payloads)
    model_count = sum(
        protein["model_status"] == "MODEL_AVAILABLE"
        for payload in payloads
        for protein in payload["proteins"]
    )
    alignment_count = sum(
        payload["alignment"]["status"] == "AVAILABLE" for payload in payloads
    )
    return f"""<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ARIA E3 ranked pocket review</title><style>{_INDEX_STYLE}</style></head><body>
<header><h1>ARIA E3 ranked pocket review</h1>
<p>Authoritative best-to-worst top-{len(payloads)} manual-review set with predicted
pocket locations and pocket-annotated sequence alignments.</p>
<p><a href="evidence_matrix.html" style="color:#cceeff">Open the top-group evidence matrix</a>
</p></header><main>
<div class="notice"><strong>Scientific boundary.</strong> The strict rank-one conclusions remain
the primary result. Top-k pocket views are sensitivity evidence. Neither predicted pocket
location nor structural similarity establishes ligand binding or successful PROTAC activity.</div>
<section class="summary-grid">
<div class="summary-card"><span class="summary-value">{len(payloads)}</span><br>ranked groups</div>
<div class="summary-card"><span class="summary-value">{protein_count}</span><br>group proteins</div>
<div class="summary-card"><span class="summary-value">{model_count}</span><br>models available</div>
<div class="summary-card"><span class="summary-value">{alignment_count}</span>
<br>group alignments</div>
</section>
<section class="card"><h2>Review pages</h2>
<p class="small">The ordering is inherited unchanged from
<code>top_50_computational_review_shortlist</code>. Search filters the table but does not
reorder it.
Use <code>review_decisions_template.tsv</code> to record the project leads' final choices.</p>
<label for="filter">Filter by rank, group, cluster or conclusion</label>
<input id="filter" type="search" placeholder="Type to filter the ranked list">
<div class="scroll"><table><thead><tr><th>Rank</th><th>Evolutionary group</th>
<th>Lead cluster</th><th>Reference</th><th>Proteins</th><th>Sequence pocket</th>
<th>Strict 3D</th><th>Top-k 3D</th><th>Review</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section></main>
<script>"use strict";const input=document.getElementById("filter");
const rows=[...document.querySelectorAll("tbody tr")];input.addEventListener("input",()=>{{
const term=input.value.trim().toLowerCase();
for(const row of rows)row.hidden=!row.dataset.search.includes(term);}});
</script></body></html>"""


_MATRIX_FIELDS = (
    ("grant_aligned_prestructure_pass", "Strict pre-structure"),
    ("conservation_status", "Sequence pocket"),
    ("three_dimensional_position_status", "Strict 3D position"),
    ("three_dimensional_alignment_status", "Strict 3D conservation"),
    ("sensitivity_position_alignment_status", "Top-k 3D position"),
    ("sensitivity_alignment_status", "Top-k 3D conservation"),
    ("grant_aligned_final_pass", "Strict final"),
)


def render_evidence_matrix(payloads: Sequence[Mapping[str, Any]]) -> str:
    """Render a rank-preserving matrix of primary and sensitivity conclusions."""
    headers = "".join(f"<th>{html.escape(label)}</th>" for _, label in _MATRIX_FIELDS)
    rows = []
    for payload in payloads:
        key = payload["group_key"]
        ranking = payload["ranking"]
        strict_status = _status_class(
            ranking.get("three_dimensional_alignment_status")
        )
        sensitivity_status = _status_class(
            ranking.get("sensitivity_alignment_status")
        )
        searchable = " ".join(
            str(value)
            for value in (
                payload["review_rank"],
                key["primary_group_type"],
                key["primary_group_id"],
                *(
                    ranking.get(field, "")
                    for field, _ in _MATRIX_FIELDS
                ),
            )
        ).lower()
        cells = "".join(
            f'<td><span class="badge {_status_class(ranking.get(field))}">'
            f"{_text(ranking.get(field))}</span></td>"
            for field, _ in _MATRIX_FIELDS
        )
        rows.append(
            f'<tr data-search="{html.escape(searchable)}" '
            f'data-strict="{strict_status}" data-sensitivity="{sensitivity_status}">'
            f"<td>{payload['review_rank']}</td>"
            f"<td>{_text(key['primary_group_type'])}<br>{_text(key['primary_group_id'])}</td>"
            f"{cells}<td><a href=\"groups/{html.escape(group_page_name(payload))}\">"
            "Review</a></td></tr>"
        )
    return f"""<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ARIA E3 top-group evidence matrix</title><style>{_INDEX_STYLE}</style></head><body>
<header><p><a href="index.html" style="color:#cceeff">← Ranked review index</a></p>
<h1>Top-{len(payloads)} evidence matrix</h1>
<p>Strict rank-one conclusions and separate top-k sensitivity conclusions in the
authoritative Stage 10 order.</p></header><main>
<div class="notice">This matrix is a comparison aid, not a new score. Missing evidence is
not treated as biological failure, and top-k support does not rewrite the strict result.</div>
<section class="card"><div class="filter-grid">
<label>Filter rank, group or conclusion
<input id="matrixFilter" type="search" placeholder="Type to filter the matrix"></label>
<label>Structural filter<select id="matrixStatus">
<option value="all">All evidence states</option>
<option value="strict-supported">Strict 3D supported</option>
<option value="sensitivity-supported">Top-k 3D supported</option>
<option value="not-supported">Not supported</option>
<option value="unknown">Not assessed or insufficient</option>
</select></label></div>
<div class="scroll"><table><thead><tr><th>Rank</th>
<th>Evolutionary group</th>{headers}<th>Page</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section></main>
<script>"use strict";const query=document.getElementById("matrixFilter");
const status=document.getElementById("matrixStatus");
const matrixRows=[...document.querySelectorAll("tbody tr")];
function applyMatrixFilter(){{const term=query.value.trim().toLowerCase();
for(const row of matrixRows){{const textMatch=row.dataset.search.includes(term);
let statusMatch=true;if(status.value==="strict-supported")
statusMatch=row.dataset.strict==="supported";
else if(status.value==="sensitivity-supported")
statusMatch=row.dataset.sensitivity==="supported";
else if(status.value==="not-supported")
statusMatch=row.dataset.strict==="not-supported"||row.dataset.sensitivity==="not-supported";
else if(status.value==="unknown")
statusMatch=row.dataset.strict==="unknown"||row.dataset.sensitivity==="unknown";
row.hidden=!(textMatch&&statusMatch);}}}}
query.addEventListener("input",applyMatrixFilter);
status.addEventListener("change",applyMatrixFilter);</script></body></html>"""


def group_page_name(payload: Mapping[str, Any]) -> str:
    """Return one deterministic, rank-prefixed group-page filename."""
    key = payload["group_key"]
    raw = (
        f"rank_{int(payload['review_rank']):03d}__"
        f"{key['primary_group_type']}__{key['primary_group_id']}"
    )
    safe = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in raw
    )
    return (safe[:220].strip(".") or f"rank_{payload['review_rank']:03d}") + ".html"


def write_html(path: Path, content: str) -> None:
    """Write one UTF-8 HTML document through an atomic replacement."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial.{os.getpid()}")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(destination)
