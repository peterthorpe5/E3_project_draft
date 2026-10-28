"""Self-contained third-party structure, alignment and tree viewer pages."""

from __future__ import annotations

import hashlib
import html
import json
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from .core import WorkbenchError, inside
from .presentation import model_label, model_labels


def model_viewer_records(*, root: Path, model: dict, pockets: list[dict]) -> dict:
    """Load one model's portable viewer metadata using bounded project paths.

    Args:
        root: Open project directory.
        model: Imported model record.
        pockets: Project pocket evidence, including other models if desired.

    Returns:
        Coordinate-residue map and method-specific pockets for this model.
    """
    residues = (
        json.loads(inside(root=root, relative=model["coordinates"]).read_text())
        if model.get("coordinates")
        else []
    )
    return {
        "short_label": model_label(identifier=model["sample_id"]),
        "input_scope": model.get("input_scope", "full_model"),
        "residues": residues,
        "pockets": [p for p in pockets if p["sample_id"] == model["sample_id"]],
        "confidence": model.get("confidence", "plddt"),
    }


def json_for_html(*, value: object) -> str:
    """Encode data in an inert JSON script, including hostile sequence IDs safely.

    Args:
        value: JSON-compatible viewer input.

    Returns:
        Finite JSON with HTML delimiters escaped.
    """
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


@lru_cache(maxsize=5)
def viewer_asset(*, name: str) -> str:
    """Read a bundled third-party asset after verifying its pinned checksum.

    Args:
        name: Supported asset filename.

    Returns:
        Verified UTF-8 asset text.
    """
    root = files("pocket_workbench").joinpath("assets")
    hashes = json.loads(root.joinpath("checksums.json").read_text())
    if name not in hashes or "/" in name or "\\" in name:
        raise WorkbenchError("Unknown viewer asset")
    content = root.joinpath(name).read_bytes()
    if hashlib.sha256(content).hexdigest() != hashes[name]:
        raise WorkbenchError("Viewer checksum differs; reinstall the workbench")
    return content.decode("utf-8")


def alignment_document(*, msa: str, tree: str = "", viewer: str = "jbrowse") -> str:
    """Build a locally bundled AV2 or JBrowse MSA/tree page.

    Args:
        msa: Aligned FASTA.
        tree: Matching Newick, or an empty string.
        viewer: jbrowse or alignment.

    Returns:
        Complete offline-capable HTML.
    """
    if viewer not in {"jbrowse", "alignment"} or len(msa) > 5_000_000:
        raise WorkbenchError(
            "Choose a supported viewer with at most 5 million alignment characters"
        )
    script = re.sub(
        r"</script", r"<\\/script", viewer_asset(name=f"{viewer}.js"), flags=re.I
    )
    css = viewer_asset(name="alignment.css") if viewer == "alignment" else ""
    bootstrap = (
        """
    const d=JSON.parse(document.getElementById('protein-data').textContent);
    try {
      window.proteinMSA=window.ReactMSAView.mount(document.getElementById('viewer'),
        {msa:d.msa,tree:d.tree||undefined,height:660,colorScheme:'clustal'});
      document.getElementById('status').textContent='JBrowse MSA · alignment and tree';
    } catch(e) {
      document.getElementById('status').textContent='Viewer error: '+e.message;
    }
    """
        if viewer == "jbrowse"
        else ""
    )
    return (
        '<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
        "<title>Protein alignment viewer</title><style>"
        + css
        + "body{margin:0;background:white;font:14px"
        " system-ui;color:#17384d}#status{padding:10px}"
        "#viewer{height:660px;position:relative;width:100%}"
        "</style></head><body><div"
        ' id="status" role="status">Loading local viewer…</div><div'
        ' id="viewer"></div><script id="protein-data" type="application/json">'
        + json_for_html(value={"msa": msa, "tree": tree})
        + "</script><script>"
        + script
        + "</script><script>"
        + bootstrap
        + "</script></body></html>"
    )


def structure_document(
    *,
    reference_pdb: str,
    mobile_pdb: str = "",
    reference_label: str,
    mobile_label: str = "",
    match: dict | None = None,
    summary: str = "",
    reference_metadata: dict | None = None,
    mobile_metadata: dict | None = None,
) -> str:
    """Render a complete offline 3Dmol overlay with pocket and confidence controls.

    Args:
        reference_pdb: Prepared reference PDB text.
        mobile_pdb: Already-transformed all-atom mobile PDB text.
        reference_label: Exact reference identifier.
        mobile_label: Exact mobile identifier.
        match: Optional selected pocket-pair record.
        summary: Plain-language fit/method explanation.
        reference_metadata: Optional residue maps, confidence type and pockets.
        mobile_metadata: Equivalent metadata for the transformed mobile.

    Returns:
        Portable HTML containing local third-party code and model coordinates.
    """
    if len(reference_pdb) + len(mobile_pdb) > 30_000_000:
        raise WorkbenchError("Selected structures exceed the 30 MB viewer bound")
    payload = {
        "reference": reference_pdb,
        "mobile": mobile_pdb,
        "reference_label": reference_label,
        "mobile_label": mobile_label,
        "match": match or {},
        "models": [
            dict(
                label=label,
                pdb=pdb,
                initial_pocket=(match or {}).get(f"{role}_pocket"),
                initial_residues=(match or {}).get(f"{role}_residues", []),
                **(metadata or {}),
            )
            for role, label, pdb, metadata in [
                ("reference", reference_label, reference_pdb, reference_metadata),
                ("mobile", mobile_label, mobile_pdb, mobile_metadata),
            ]
            if pdb
        ],
    }
    labels = model_labels(identifiers=[m["label"] for m in payload["models"]])
    for model in payload["models"]:
        model["short_label"] = labels[model["label"]]
    library = re.sub(
        r"</script", r"<\\/script", viewer_asset(name="3Dmol-min.js"), flags=re.I
    )
    template = (
        files("pocket_workbench")
        .joinpath("assets", "structure_template.html")
        .read_text()
    )
    return (
        template.replace("@@SUMMARY@@", html.escape(summary))
        .replace("@@DATA@@", json_for_html(value=payload))
        .replace("@@LIBRARY@@", library)
    )


def sequence_position_columns(*, aligned: str) -> dict[int, int]:
    """Map one-based ungapped sequence positions to one-based MSA columns.

    Args:
        aligned: One aligned protein row.

    Returns:
        Sequence-position to alignment-column mapping.
    """
    result = {}
    position = 0
    for column, letter in enumerate(aligned, start=1):
        if letter not in {"-", "."}:
            position += 1
            result[position] = column
    return result
