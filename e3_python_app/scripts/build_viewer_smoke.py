"""Generate synthetic offline protein viewer documents for browser smoke tests."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Sequence

import duckdb

from e3app.pocket_review import add_terminal_trimming_controls
from e3app.research.review_highlights import add_review_highlights
from e3app.research.viewers import viewer_document
from e3app.research.species_tree import species_display_tree


def write_review_fixtures(*, output: Path) -> None:
    """Write group and pair HTML with the saved review canvas contract.

    Args:
        output: Directory for the two offline fixture documents.
    """
    names = {"Q": "GLN", "W": "TRP", "F": "PHE", "A": "ALA", "G": "GLY"}
    sequence = "QWFAAGQWFAA"
    proteins = [
        {"accession": name, "species": species, "atoms": [
            {"x": index * 2, "y": offset + math.sin(index) * 3, "z": math.cos(index),
             "resi": index, "resn": names[residue], "chain": "A", "plddt": 82,
             "pocket": index == 2,
             "pockets": [{"selection_rank": 1}] if index == 2 else []}
            for index, residue in enumerate(sequence, start=1)
        ]}
        for name, species, offset in (("P12345", "Plant_a", 0), ("Q12345", "Plant_b", 6))
    ]
    group_id = "N0.HOG1"
    group = {
        "group_key": {"primary_group_id": group_id}, "proteins": proteins,
        "alignment": {"records": [
            {"accession": row["accession"], "species": row["species"], "sequence": sequence}
            for row in proteins
        ]},
    }
    common = """
    const canvas=document.getElementById("viewer"),ctx=canvas.getContext("2d");
    let projected=[];
    function draw() {
      ctx.clearRect(0,0,canvas.width,canvas.height);
      projected=[];
      render();
    }
    function project(atom,kind,index) {
      return {x:40+atom.x*10,y:70+atom.y*10,z:atom.z,atom,kind,index};
    }
    function dots(records,kind,colour) {
      const points=records.map((atom,index)=>project(atom,kind,index));
      ctx.fillStyle=colour;
      for (const point of points) {
        ctx.beginPath();ctx.arc(point.x,point.y,3,0,2*Math.PI);ctx.fill();
      }
      projected.push(...points);
    }
    """
    group_js = """
    const data=JSON.parse(document.getElementById("reviewData").textContent);
    const proteinSelect=document.getElementById("proteinSelect");
    const palette={1:"#2de2a6"};
    function selectedRank(){return 1;}
    function currentProtein(){return data.proteins.find(p=>p.accession===proteinSelect.value);}
    function render(){
      const atoms=currentProtein().atoms;
      dots(atoms,"protein","#62aef5");
      dots(atoms.filter(atom=>atom.pockets.length),"protein",palette[1]);
    }
    proteinSelect.addEventListener("change",()=>draw());
    """
    pair_js = """
    const data=JSON.parse(document.getElementById("alignmentData").textContent);
    const colours={reference:"#4ea5ff",mobile:"#ff9d3d",referencePocket:"#21e6c1",
      mobilePocket:"#ff4fa3"};
    function allVisible(){return [...data.reference,...data.mobile];}
    function trace(records,kind,colour,show){if(show)dots(records,kind,colour);}
    function pockets(records,kind,colour,show){
      if(show&&document.getElementById("showPocket").checked){
        dots(records.filter(atom=>atom.pocket),kind,colour);
      }
    }
    function render(){
      for(const [role,check] of [["reference","showReference"],["mobile","showMobile"]]){
        const show=document.getElementById(check).checked;
        trace(data[role],role,colours[role],show);
        pockets(data[role],role,colours[role+"Pocket"],show);
      }
    }
    """
    header = (
        '<html><head></head><body><main class="viewer-layout"><canvas id="viewer" '
        'width="450" height="240" style="background:#07121d"></canvas><aside>'
    )
    group_document = (
        header + '<select id="proteinSelect"><option>P12345</option>'
        '<option>Q12345</option></select>'
        '</aside></main><script id="reviewData" type="application/json">'
        + json.dumps(group) + f"</script><script>{common}{group_js}draw()</script></body></html>"
    )
    pair = {
        "reference": proteins[0]["atoms"], "mobile": proteins[1]["atoms"],
        "metadata": {"reference": "P12345", "mobile": "Q12345"},
    }
    pair_document = (
        header + "".join(f'<input id="{name}" type="checkbox" checked>'
                         for name in ("showReference", "showMobile", "showPocket"))
        + '</aside></main><script id="alignmentData" type="application/json">'
        + json.dumps(pair) + f"</script><script>{common}{pair_js}draw()</script></body></html>"
    )
    with duckdb.connect(config={"threads": 1}) as connection:
        connection.execute(
            "CREATE TABLE domain_hits AS SELECT 'P12345' AS member_accession, "
            "'Plant_a' AS species_column, ? AS primary_group_id, ? AS protein_length, "
            "2 AS location_start, 4 AS location_end, 'PF00001' AS entry_accession, "
            "'Fixture domain' AS entry_name", [group_id, len(sequence)],
        )
        for name, document in (("review-group", group_document), ("review-pair", pair_document)):
            paired = name == "review-pair"
            (output / f"{name}.html").write_text(add_review_highlights(
                document=add_terminal_trimming_controls(document), group_id=group_id,
                connection=connection, group_document=group_document if paired else None,
                pair_members={"reference": ("P12345", "Plant_a"),
                              "mobile": ("Q12345", "Plant_b")} if paired else None,
            ), encoding="utf-8")


def main(*, argv: Sequence[str] | None = None) -> int:
    """Write bounded synthetic documents for each bundled viewer.

    Args:
        argv: Optional named command arguments.

    Returns:
        Zero after all viewer documents have been generated.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args(argv).output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "msa": ">query\nACDEFGHIKLMNPQRSTVWY\n>member\nACDEFGHIKLMNPQRSTVWF\n",
        "tree": "(query:0.1,member:0.2);",
        "sequence": "ACDEFGHIKLMNPQRSTVWY",
        "features": [
            {
                "accession": "SYNTHETIC_DOMAIN",
                "locations": [{"fragments": [{"start": 2, "end": 10}]}],
            }
        ],
    }
    for viewer in ("alignment", "jbrowse", "nightingale"):
        (output / f"{viewer}.html").write_text(
            viewer_document(viewer=viewer, payload=payload), encoding="utf-8"
        )
    (output / "nightingale-recorded.html").write_text(
        viewer_document(viewer="nightingale", payload={
            **payload, "sequence": "", "length": 100,
            "coordinate_scope": "Recorded annotation coordinates; amino-acid sequence not verified",
        }), encoding="utf-8",
    )
    (output / "nightingale-linked.html").write_text(
        viewer_document(viewer="nightingale", payload={
            **payload,
            "coordinate_scope": "Verified sequence axis", "model_label": "Synthetic model",
            "sequence": "ACDEFGHIKLMNPQRSTACD",
            "features": [
                {**payload["features"][0], "provenance": "sequence_verified"},
                {
                    "accession": "RECORDED_DOMAIN", "description": "Historical fixture",
                    "provenance": "recorded_coordinates",
                    "locations": [{"fragments": [{"start": 4, "end": 7}]}] * 2,
                },
            ],
            "pockets": [
                {"number": 4, "rank": 1, "positions": [3, 5], "color": "#c24e00"},
                {"number": 2, "rank": 2, "positions": [6, 8, 12], "color": "#007d7c"},
            ],
            "model": [
                {"position": index, "residue": residue, "x": index * .8,
                 "y": (index % 4) * .7, "z": (index % 5) * .6,
                 "plddt": 64 + index if index != 10 else None}
                for index, residue in enumerate("ACDEFGHIKLMNPQRSTACD", start=1)
            ],
        }), encoding="utf-8",
    )
    species, _audit = species_display_tree(
        newick="(Human:1,Plant:1);", sequence_ids=["query", "member"],
        metadata={"query": {"species": "Human"}, "member": {"species": "Plant"}},
    )
    (output / "jbrowse-species.html").write_text(
        viewer_document(viewer="jbrowse", payload={**payload, "tree": species}), encoding="utf-8",
    )
    write_review_fixtures(output=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
