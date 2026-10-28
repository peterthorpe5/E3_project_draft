"""Auditable pocket-to-FASTA-to-alignment mappings and offline review pages."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from .core import WorkbenchError, inside
from .presentation import model_labels
from .viewers import json_for_html, sequence_position_columns


def pocket_alignment_data(
    *, root: Path, data: dict, aligned_records: dict[str, str], top_k: int = 10
) -> dict:
    """Map each model's ranked fpocket residues to a representative alignment.

    Args:
        root: Existing project directory.
        data: Loaded project evidence.
        aligned_records: Exact representative IDs and aligned sequences.
        top_k: Largest original review rank to retain, between one and 100.

    Returns:
        Display rows, residue-level audit annotations and mapping completeness.
    """
    labels = model_labels(identifiers=[m["sample_id"] for m in data["models"]])
    lengths = {len(sequence) for sequence in aligned_records.values()}
    if len(lengths) != 1 or not 1 <= top_k <= 100:
        raise WorkbenchError("Use an equal-length alignment and top_k in [1, 100]")
    for identifier, aligned in aligned_records.items():
        sequence = data["sequences"].get(identifier)
        if sequence is None or aligned.replace("-", "").replace(".", "") != sequence:
            raise WorkbenchError("Alignment does not preserve the project sequences")
    rows, annotations, represented = [], [], set()
    for model in data["models"]:
        identifier = model.get("sequence_id")
        if identifier not in aligned_records:
            continue
        represented.add(identifier)
        valid = model.get("mapping_status") not in {
            "no_exact_fasta_match",
            "ambiguous_identical_fasta_records",
        }
        residues = (
            json.loads(inside(root=root, relative=model["coordinates"]).read_text())
            if model.get("coordinates") and valid
            else []
        )
        by_key = {row["residue_key"]: row for row in residues}
        columns = sequence_position_columns(aligned=aligned_records[identifier])
        pocket_count, expected, mapped = 0, 0, 0
        for pocket in data["pockets"]:
            rank = pocket.get("review_rank") or pocket.get("rank")
            if (
                pocket["sample_id"] != model["sample_id"]
                or pocket["method"] != "fpocket"
                or not isinstance(rank, (int, float))
                or not 1 <= rank <= top_k
            ):
                continue
            pocket_count += 1
            keys = sorted(set(pocket.get("residues", [])))
            for key in keys:
                expected += 1
                residue = by_key.get(key, {})
                column = columns.get(residue.get("sequence_position"))
                mapped += int(column is not None)
                annotations.append(
                    {
                        "sample_id": model["sample_id"],
                        "sequence_id": identifier,
                        "pocket_id": pocket["pocket_id"],
                        "review_rank": rank,
                        "residue_key": key,
                        "sequence_position": residue.get("sequence_position"),
                        "alignment_column": column,
                        "author_chain": residue.get("author_chain"),
                        "author_residue_number": residue.get("author_residue_number"),
                        "insertion_code": residue.get("insertion_code", ""),
                        "amino_acid": residue.get("amino_acid"),
                        "plddt": residue.get("plddt"),
                        "confidence_status": pocket.get("confidence_status"),
                        "quality_screen_pass": pocket.get("quality_screen_pass"),
                        "near_cut_boundary": pocket.get("near_cut_boundary"),
                        "near_very_low_confidence": pocket.get(
                            "near_very_low_confidence"
                        ),
                        "druggability_score": pocket.get("druggability_score"),
                        "mapping_status": "mapped" if column else "unmapped",
                    }
                )
        rows.append(
            {
                "sample_id": model["sample_id"],
                "display_label": labels[model["sample_id"]],
                "scope_key": json.dumps(
                    [
                        identifier,
                        model.get("input_scope", "full_model"),
                        model.get("original_start"),
                        model.get("original_end"),
                    ]
                ),
                "sequence_id": identifier,
                "aligned": aligned_records[identifier],
                "pocket_count": pocket_count,
                "expected": expected,
                "mapped": mapped,
                "mapping_status": model.get("mapping_status", "unreported"),
            }
        )
    for identifier, aligned in aligned_records.items():
        if identifier not in represented:
            rows.append(
                {
                    "sample_id": "",
                    "sequence_id": identifier,
                    "aligned": aligned,
                    "pocket_count": 0,
                    "mapped": 0,
                    "expected": 0,
                    "mapping_status": "no_model",
                }
            )
    return {
        "rows": rows,
        "annotations": annotations,
        "alignment_length": next(iter(lengths)),
        "top_k": top_k,
        "has_preparation_screen": bool(data.get("quality_preparation")),
    }


def pocket_alignment_document(*, payload: dict) -> str:
    """Render a safe, self-contained pocket track and residue alignment page.

    Args:
        payload: Mapping returned by pocket_alignment_data.

    Returns:
        Offline HTML with original pocket ranks and explicit unmapped evidence.
    """
    template = (
        files("pocket_workbench")
        .joinpath("assets", "pocket_alignment.html")
        .read_text()
    )
    return template.replace("@@DATA@@", json_for_html(value=payload))
