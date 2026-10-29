"""Portable external-tool directory generated only from saved project evidence."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from .core import WorkbenchError
from .external_tools import (
    EMERALD_URL,
    RESIDUE_COLUMNS,
    RESOURCES,
    external_records,
    pocket_tables,
    record_sequence,
    table_tsv,
)
from .viewers import json_for_html, viewer_asset


def external_review_document(
    *,
    data: dict,
    model_files: dict[str, str],
    residue_files: dict[str, str],
    group_files: list[dict],
    fits: list[dict],
) -> str:
    """Render an offline selection page with working downloads and public links.

    Args:
        data: Loaded project; no original coordinate paths are exposed as URLs.
        model_files: Model ID to relative saved-PDB download path.
        residue_files: Model ID to relative prepared-numbering residue TSV.
        group_files: Explicit group names and relative compatibility-ZIP paths.
        fits: Complete saved-fit descriptions with reference/mobile download paths.

    Returns:
        Self-contained HTML. Internet is used only after following an external link.
    """
    rows = []
    for record in external_records(data=data):
        row = {
            k: record.get(k)
            for k in (
                "record_id",
                "label",
                "sample_id",
                "sequence_id",
                "kind",
                "input_scope",
                "canonical_accession",
                "public_links",
            )
        }
        row.update(
            model_href=model_files.get(record["sample_id"]),
            residue_href=residue_files.get(record["sample_id"]),
        )
        for scope in ("model_input", "representative_fasta"):
            try:
                sequence, source = record_sequence(record=record, scope=scope)
                row[scope] = {"sequence": sequence, "source": source}
            except WorkbenchError as error:
                row[scope] = {"sequence": None, "reason": str(error)}
        rows.append(row)
    payload = {
        "title": data["title"],
        "records": rows,
        "resources": RESOURCES,
        "groups": group_files,
        "fits": fits,
        "emerald_url": EMERALD_URL,
    }
    return viewer_asset(name="external_links.html").replace(
        "@@DATA@@", json_for_html(value=payload)
    )


def export_external_review(
    *,
    root: Path,
    data: dict,
    output: Path,
    group_files: list[dict],
    fits: list[dict],
) -> Path:
    """Write exact local-model pocket downloads and an offline external-tools hub.

    Args:
        root: Finished resource, read without modification.
        data: Loaded project evidence.
        output: New external/ directory inside a new review, outside the resource.
        group_files: Already-created group ZIP link descriptions.
        fits: Already-exported saved alignment descriptions and coordinate paths.

    Returns:
        New index.html path.

    Raises:
        WorkbenchError: Output exists or overlaps the original resource.
    """
    root, output = root.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise WorkbenchError(
            "Choose a new external-review directory outside the resource"
        )
    output.mkdir(parents=True)
    (output / "pockets").mkdir()
    models, residues = {}, {}
    for index, model in enumerate(data["models"]):
        identifier = model["sample_id"]
        if model.get("prepared_model"):
            models[identifier] = "../models/" + quote(identifier, safe="") + ".pdb"
        tables = pocket_tables(root=root, data=data, model_ids=[identifier])
        filename = f"model_{index}_pocket_residues.tsv"
        (output / "pockets" / filename).write_bytes(
            table_tsv(rows=tables["residues"], columns=RESIDUE_COLUMNS)
        )
        residues[identifier] = "pockets/" + filename
    links = [
        {
            "record_id": r["record_id"],
            "sequence_id": r["sequence_id"],
            "input_scope": r["input_scope"],
            "canonical_accession": r["canonical_accession"],
            "accession_basis": r["accession_basis"],
            "molstar_url": r["public_links"]["molstar"],
            "alphafold_url": r["public_links"]["alphafold"],
            "saved_model": models.get(r["sample_id"]),
            "pocket_residues": residues.get(r["sample_id"]),
        }
        for r in external_records(data=data)
    ]
    (output / "public_links.tsv").write_bytes(
        table_tsv(
            rows=links,
            columns=list(links[0]) if links else ("record_id", "canonical_accession"),
        )
    )
    path = output / "index.html"
    path.write_text(
        external_review_document(
            data=data,
            model_files=models,
            residue_files=residues,
            group_files=group_files,
            fits=fits,
        ),
        encoding="utf-8",
    )
    return path
