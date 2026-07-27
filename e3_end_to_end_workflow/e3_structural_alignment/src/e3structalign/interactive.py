"""Portable interactive C-alpha structure and pocket alignment browser."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from e3structalign.models import AtomCoordinate, Transform


def _atom_payload(
    atoms: Sequence[AtomCoordinate],
    *,
    transform: Transform | None,
    pocket_coordinates: set[tuple[float, float, float]],
) -> list[dict[str, Any]]:
    """Return compact browser records for a C-alpha trace."""
    payload = []
    for atom in atoms:
        coordinate = (
            transform.apply(atom.coordinate) if transform is not None else atom.coordinate
        )
        payload.append(
            {
                "x": round(coordinate[0], 4),
                "y": round(coordinate[1], 4),
                "z": round(coordinate[2], 4),
                "chain": atom.label_chain or atom.auth_chain,
                "resi": atom.label_seq_id or atom.auth_seq_id,
                "resn": atom.residue_name,
                "pocket": atom.coordinate in pocket_coordinates,
            }
        )
    return payload


def render_pair_viewer(
    *,
    title: str,
    reference_accession: str,
    mobile_accession: str,
    alignment_tool: str,
    reference_atoms: Sequence[AtomCoordinate],
    mobile_atoms: Sequence[AtomCoordinate],
    reference_pocket_coordinates: set[tuple[float, float, float]],
    mobile_pocket_coordinates: set[tuple[float, float, float]],
    transform: Transform,
    metrics: Mapping[str, Any],
) -> str:
    """Render a standalone rotatable C-alpha/pocket viewer."""
    data = {
        "reference": _atom_payload(
            reference_atoms,
            transform=None,
            pocket_coordinates=reference_pocket_coordinates,
        ),
        "mobile": _atom_payload(
            mobile_atoms,
            transform=transform,
            pocket_coordinates=mobile_pocket_coordinates,
        ),
        "metadata": {
            "reference": reference_accession,
            "mobile": mobile_accession,
            "tool": alignment_tool,
        },
    }
    encoded = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    metric_rows = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>"
        for label, value in metrics.items()
    )
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;color:#18212b;background:#f3f6f8}}
header{{padding:1rem 1.3rem;background:#173f5f;color:white}}
main{{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:1rem;padding:1rem}}
#viewer{{width:100%;height:72vh;background:#07121d;border-radius:10px;cursor:grab}}
#viewer:active{{cursor:grabbing}} aside{{background:white;padding:1rem;border-radius:10px}}
button,label{{margin:.25rem}} table{{border-collapse:collapse;width:100%;font-size:.88rem}}
th,td{{border:1px solid #d6dee5;padding:.4rem;text-align:left}}
.legend span{{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:.3rem}}
.ref{{background:#4ea5ff}} .mob{{background:#ff9d3d}}
.refp{{background:#21e6c1}} .mobp{{background:#ff4fa3}}
.note{{font-size:.88rem;color:#52606d}} @media(max-width:900px){{main{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>{html.escape(title)}</h1></header>
<main><section><canvas id="viewer"></canvas></section><aside>
<h2>Controls</h2>
<p><button id="reset">Reset view</button><button id="fit">Fit</button></p>
<label><input type="checkbox" id="showReference" checked> Reference trace</label><br>
<label><input type="checkbox" id="showMobile" checked> Member trace</label><br>
<label><input type="checkbox" id="showPocket" checked> Pocket residues</label>
<p class="note">Drag to rotate. Use the mouse wheel to zoom. Click a residue to show its
chain, structure position and residue name.</p>
<div class="legend">
<p><span class="ref"></span>Reference trace <span class="mob"></span>Member trace</p>
<p><span class="refp"></span>Reference pocket <span class="mobp"></span>Member pocket</p>
</div>
<h2>Selected residue</h2><p id="picked">None</p>
<h2>Pair evidence</h2><table>{metric_rows}</table>
<p class="note">The viewer shows Cα traces, not atoms or molecular surfaces. The member
coordinates have been transformed into the reference frame using the recorded
{html.escape(alignment_tool)} matrix.</p>
</aside></main>
<script id="alignmentData" type="application/json">{encoded}</script>
<script>
"use strict";
const data=JSON.parse(document.getElementById("alignmentData").textContent);
const canvas=document.getElementById("viewer"),ctx=canvas.getContext("2d");
let rx=-0.2,ry=0.4,zoom=1,drag=false,lastX=0,lastY=0,projected=[];
const colours={{reference:"#4ea5ff",mobile:"#ff9d3d",referencePocket:"#21e6c1",
mobilePocket:"#ff4fa3"}};
function resize(){{const r=canvas.getBoundingClientRect();
canvas.width=Math.max(400,r.width*devicePixelRatio);
canvas.height=Math.max(400,r.height*devicePixelRatio);draw();}}
function rotate(p){{let x=p.x,y=p.y,z=p.z;const cy=Math.cos(ry),sy=Math.sin(ry);
const x1=x*cy+z*sy,z1=-x*sy+z*cy;const cx=Math.cos(rx),sx=Math.sin(rx);
return {{x:x1,y:y*cx-z1*sx,z:y*sx+z1*cx}};}}
function allVisible(){{return [...data.reference,...data.mobile];}}
function bounds(){{const pts=allVisible().map(rotate);
let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
for(const p of pts){{minX=Math.min(minX,p.x);maxX=Math.max(maxX,p.x);
minY=Math.min(minY,p.y);maxY=Math.max(maxY,p.y);}}
return {{minX,maxX,minY,maxY}};}}
function scaleInfo(){{const b=bounds(),w=b.maxX-b.minX||1,h=b.maxY-b.minY||1;
return {{scale:Math.min(canvas.width/(w*1.25),canvas.height/(h*1.25))*zoom,
cx:(b.minX+b.maxX)/2,cy:(b.minY+b.maxY)/2}};}}
function project(atom,kind,index){{const p=rotate(atom),s=scaleInfo();
return {{x:canvas.width/2+(p.x-s.cx)*s.scale,y:canvas.height/2-(p.y-s.cy)*s.scale,
z:p.z,atom,kind,index}};}}
function trace(records,kind,colour,show){{if(!show)return;
const pts=records.map((a,i)=>project(a,kind,i));
ctx.strokeStyle=colour;ctx.lineWidth=2*devicePixelRatio;ctx.globalAlpha=.72;ctx.beginPath();
pts.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.stroke();ctx.globalAlpha=1;
for(const p of pts){{ctx.fillStyle=colour;ctx.beginPath();
ctx.arc(p.x,p.y,2.1*devicePixelRatio,0,Math.PI*2);ctx.fill();}}
projected.push(...pts);}}
function pockets(records,kind,colour,showStructure){{
if(!showStructure||!document.getElementById("showPocket").checked)return;
for(let i=0;i<records.length;i++){{const a=records[i];if(!a.pocket)continue;
const p=project(a,kind,i);
ctx.fillStyle=colour;ctx.strokeStyle="#ffffff";ctx.lineWidth=1.2*devicePixelRatio;ctx.beginPath();
ctx.arc(p.x,p.y,7*devicePixelRatio,0,Math.PI*2);ctx.fill();ctx.stroke();projected.push(p);}}}}
function draw(){{if(!canvas.width)return;ctx.clearRect(0,0,canvas.width,canvas.height);
projected=[];const sr=document.getElementById("showReference").checked;
const sm=document.getElementById("showMobile").checked;
trace(data.reference,"reference",colours.reference,sr);trace(data.mobile,"mobile",colours.mobile,sm);
pockets(data.reference,"reference",colours.referencePocket,sr);
pockets(data.mobile,"mobile",colours.mobilePocket,sm);}}
canvas.addEventListener("pointerdown",e=>{{drag=true;lastX=e.clientX;lastY=e.clientY;
canvas.setPointerCapture(e.pointerId);}});
canvas.addEventListener("pointermove",e=>{{if(!drag)return;ry+=(e.clientX-lastX)*.01;rx+=(e.clientY-lastY)*.01;
lastX=e.clientX;lastY=e.clientY;draw();}});canvas.addEventListener("pointerup",()=>drag=false);
canvas.addEventListener("wheel",e=>{{e.preventDefault();zoom*=e.deltaY<0?1.12:.89;
zoom=Math.max(.15,Math.min(8,zoom));draw();}},
{{passive:false}});
canvas.addEventListener("click",e=>{{if(drag)return;const r=canvas.getBoundingClientRect();
const x=(e.clientX-r.left)*devicePixelRatio,y=(e.clientY-r.top)*devicePixelRatio;
let best=null,dist=Infinity;for(const p of projected){{const d=Math.hypot(p.x-x,p.y-y);
if(d<dist){{best=p;dist=d;}}}}
if(best&&dist<15*devicePixelRatio){{document.getElementById("picked").textContent=
`${{best.kind}}: ${{best.atom.resn}} chain ${{best.atom.chain||"?"}} `+
`residue ${{best.atom.resi||"?"}}${{best.atom.pocket?" (pocket)":""}}`;}}}});
document.getElementById("reset").onclick=()=>{{rx=-.2;ry=.4;zoom=1;draw();}};
document.getElementById("fit").onclick=()=>{{zoom=1;draw();}};
for(const id of ["showReference","showMobile","showPocket"])
document.getElementById(id).onchange=draw;
window.addEventListener("resize",resize);resize();
</script></body></html>"""


def write_pair_viewer(
    *,
    path: Path,
    title: str,
    reference_accession: str,
    mobile_accession: str,
    alignment_tool: str,
    reference_atoms: Sequence[AtomCoordinate],
    mobile_atoms: Sequence[AtomCoordinate],
    reference_pocket_coordinates: set[tuple[float, float, float]],
    mobile_pocket_coordinates: set[tuple[float, float, float]],
    transform: Transform,
    metrics: Mapping[str, Any],
) -> None:
    """Write one interactive pair viewer atomically."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.write_text(
        render_pair_viewer(
            title=title,
            reference_accession=reference_accession,
            mobile_accession=mobile_accession,
            alignment_tool=alignment_tool,
            reference_atoms=reference_atoms,
            mobile_atoms=mobile_atoms,
            reference_pocket_coordinates=reference_pocket_coordinates,
            mobile_pocket_coordinates=mobile_pocket_coordinates,
            transform=transform,
            metrics=metrics,
        ),
        encoding="utf-8",
    )
    temporary.replace(destination)


def write_browser_index(
    *,
    path: Path,
    alignments: Sequence[Mapping[str, Any]],
    summaries: Sequence[Mapping[str, Any]],
) -> None:
    """Write the interactive browser index linking all pair viewers."""
    summary_by_group = {
        (
            str(row["cluster_id"]),
            str(row["primary_group_type"]),
            str(row["primary_group_id"]),
        ): row
        for row in summaries
    }
    rows = []
    for alignment in alignments:
        viewer_path = str(alignment.get("interactive_view_relative_path") or "")
        if not viewer_path:
            continue
        viewer_link = (
            str(Path(viewer_path).relative_to("interactive"))
            if Path(viewer_path).parts
            and Path(viewer_path).parts[0] == "interactive"
            else viewer_path
        )
        key = (
            str(alignment["cluster_id"]),
            str(alignment["primary_group_type"]),
            str(alignment["primary_group_id"]),
        )
        summary = summary_by_group.get(key, {})
        rows.append(
            "<tr>"
            f"<td>{html.escape(key[0])}</td><td>{html.escape(key[2])}</td>"
            f"<td>{html.escape(str(alignment['reference_accession']))}</td>"
            f"<td>{html.escape(str(alignment['mobile_accession']))}</td>"
            f"<td>{html.escape(str(alignment['alignment_tool']))}</td>"
            f"<td>{html.escape(str(summary.get('position_alignment_status', '')))}</td>"
            f"<td>{html.escape(str(summary.get('alignment_status', '')))}</td>"
            f'<td><a href="{html.escape(viewer_link)}">Open 3D viewer</a></td></tr>'
        )
    report = f"""<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Structural alignment browser</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1250px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d7dee5;padding:.45rem;
text-align:left}}th{{background:#eaf1f5}}a{{color:#075c9c;font-weight:650}}</style></head>
<body><h1>Interactive structural alignment browser</h1>
<p>Select an aligned reference/member pair. Each standalone viewer contains the superposed
Cα traces and highlights both predicted pockets. No network connection is required.</p>
<table><thead><tr><th>Discovery cluster</th><th>OrthoFinder group</th><th>Reference</th>
<th>Member</th><th>Tool</th><th>Position conclusion</th><th>Conservation conclusion</th>
<th>Viewer</th></tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>"""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.write_text(report, encoding="utf-8")
    temporary.replace(destination)
