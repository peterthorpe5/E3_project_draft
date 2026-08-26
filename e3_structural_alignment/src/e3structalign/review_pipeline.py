"""Atomic pipeline for ranked pocket-review HTML report generation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from e3structalign import __version__
from e3structalign.errors import StructuralAlignmentError
from e3structalign.io_utils import (
    atomic_write_json,
    close_logger,
    configure_logging,
    output_inventory,
    read_records,
    require_columns,
    safe_filename,
    sha256_file,
    utc_now,
    write_tsv,
)
from e3structalign.review_data import (
    input_digest,
    load_report_payloads,
    resolve_review_inputs,
)
from e3structalign.review_models import ReviewInputOverrides, ReviewSettings
from e3structalign.review_models import ReviewInputs
from e3structalign.review_reporting import (
    group_page_name,
    render_evidence_matrix,
    render_group_page,
    render_index,
    write_html,
)

LOGGER = logging.getLogger("e3structalign.review")


def _embedded_source_inventory(
    payloads: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return model and alignment checksums embedded into each ranked page."""
    return [
        {
            "review_rank": payload["review_rank"],
            "alignment_sha256": payload["alignment"].get("source_sha256", ""),
            "models": [
                {
                    "accession": protein["accession"],
                    "sha256": protein.get("model_sha256", ""),
                }
                for protein in payload["proteins"]
            ],
        }
        for payload in payloads
    ]


def _complete_digest(
    *,
    base_digest: str,
    payloads: Sequence[Mapping[str, Any]],
    viewer_rows: Sequence[Mapping[str, Any]],
) -> str:
    """Bind the run digest to model and alignment checksums used in pages."""
    public_viewers = [
        {
            field: value
            for field, value in row.items()
            if field != "viewer_source_path"
        }
        for row in viewer_rows
    ]
    sources = {
        "review_sources": _embedded_source_inventory(payloads),
        "structural_viewers": public_viewers,
    }
    encoded = json.dumps(sources, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    digest = hashlib.sha256()
    digest.update(base_digest.encode("ascii"))
    digest.update(encoded)
    return digest.hexdigest()


def _structural_viewer_rows(
    *,
    inputs: ReviewInputs,
    payloads: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve and checksum every selected pairwise superposition page."""
    alignments = read_records(inputs.structural_alignments)
    comparisons = read_records(inputs.structural_pocket_comparisons)
    required = (
        "cluster_id",
        "primary_group_type",
        "primary_group_id",
        "reference_accession",
        "mobile_accession",
        "reference_species",
        "mobile_species",
        "alignment_tool",
        "interactive_view_relative_path",
    )
    require_columns(alignments, required, "structural alignments")
    comparison_index = {
        (
            str(row.get("cluster_id") or ""),
            str(row.get("primary_group_type") or ""),
            str(row.get("primary_group_id") or ""),
            str(row.get("reference_accession") or ""),
            str(row.get("mobile_accession") or ""),
            str(row.get("alignment_tool") or ""),
        ): row
        for row in comparisons
        if str(row.get("status") or "") == "ASSESSED"
    }
    payload_index = {
        (
            str(payload["group_key"]["cluster_id"]),
            str(payload["group_key"]["primary_group_type"]),
            str(payload["group_key"]["primary_group_id"]),
        ): payload
        for payload in payloads
    }
    rows: list[dict[str, Any]] = []
    for alignment in alignments:
        key = (
            str(alignment.get("cluster_id") or ""),
            str(alignment.get("primary_group_type") or ""),
            str(alignment.get("primary_group_id") or ""),
        )
        payload = payload_index.get(key)
        relative_text = str(
            alignment.get("interactive_view_relative_path") or ""
        ).strip()
        if payload is None or not relative_text:
            continue
        relative = Path(relative_text)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or relative.parts[0] != "interactive"
        ):
            raise StructuralAlignmentError(
                f"Unsafe structural viewer path: {relative_text!r}"
            )
        group_slug = (
            f"{key[1]}:{key[2]}".replace(":", "__").replace("/", "_")
        )
        interactive_root = inputs.structural_interactive_root.resolve()
        relative_suffix = Path(*relative.parts[1:])
        source_candidates = (
            interactive_root / relative_suffix,
            interactive_root / "groups" / group_slug / relative_suffix,
        )
        present_sources = [
            candidate.resolve()
            for candidate in source_candidates
            if candidate.resolve().is_file()
            and interactive_root in candidate.resolve().parents
        ]
        if len(present_sources) != 1:
            raise StructuralAlignmentError(
                "Expected exactly one structural viewer for the alignment row; "
                f"found {len(present_sources)} for {relative_text!r}"
            )
        source = present_sources[0]
        pair_key = (
            *key,
            str(alignment["reference_accession"]),
            str(alignment["mobile_accession"]),
            str(alignment["alignment_tool"]),
        )
        comparison = comparison_index.get(pair_key, {})
        destination = (
            Path("structural_alignment")
            / "groups"
            / group_slug
            / Path(*relative.parts[1:])
        )
        rows.append(
            {
                "review_rank": int(payload["review_rank"]),
                "primary_group_type": key[1],
                "primary_group_id": key[2],
                "lead_cluster_id": key[0],
                "reference_accession": alignment["reference_accession"],
                "mobile_accession": alignment["mobile_accession"],
                "reference_species": alignment["reference_species"],
                "mobile_species": alignment["mobile_species"],
                "alignment_tool": alignment["alignment_tool"],
                "minimum_tm_score": alignment.get("minimum_tm_score"),
                "rmsd_angstrom": alignment.get("rmsd_angstrom"),
                "centroid_distance_angstrom": comparison.get(
                    "centroid_distance_angstrom"
                ),
                "symmetric_pocket_overlap_fraction": comparison.get(
                    "symmetric_overlap_fraction"
                ),
                "structural_residue_match_fraction": comparison.get(
                    "structural_residue_match_fraction"
                ),
                "structural_chemical_group_conservation": comparison.get(
                    "structural_chemical_group_conservation"
                ),
                "same_pocket_position_supported": comparison.get(
                    "same_pocket_position_supported"
                ),
                "pocket_structure_conserved": comparison.get(
                    "pocket_structure_conserved"
                ),
                "interactive_view_html": destination.as_posix(),
                "viewer_source_path": str(source),
                "viewer_source_sha256": sha256_file(source),
            }
        )
    rows.sort(
        key=lambda row: (
            int(row["review_rank"]),
            str(row["mobile_species"]),
            str(row["mobile_accession"]),
            str(row["alignment_tool"]),
        )
    )
    if not rows:
        raise StructuralAlignmentError(
            "No pairwise structural viewer pages were resolved for the selected "
            "review groups"
        )
    return rows


def _validate_existing_output(output_dir: Path, run_digest: str) -> bool:
    """Return whether an existing report is a checksum-valid resume target."""
    manifest_path = output_dir / "provenance" / "run_manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("status") != "complete" or payload.get("run_digest") != run_digest:
        return False
    outputs = payload.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        return False
    for record in outputs:
        if not isinstance(record, dict):
            return False
        relative = Path(str(record.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            return False
        path = output_dir / relative
        if (
            not path.is_file()
            or path.stat().st_size != record.get("size_bytes")
            or sha256_file(path) != record.get("sha256")
        ):
            return False
    return True


def _review_index_rows(
    payloads: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return compact human-readable report navigation rows."""
    rows = []
    for payload in payloads:
        ranking = payload["ranking"]
        key = payload["group_key"]
        rows.append(
            {
                "review_rank": payload["review_rank"],
                "primary_group_type": key["primary_group_type"],
                "primary_group_id": key["primary_group_id"],
                "lead_cluster_id": key["cluster_id"],
                "reference_accession": payload["reference_accession"],
                "protein_count": len(payload["proteins"]),
                "alignment_sequence_count": payload["alignment"]["sequence_count"],
                "conservation_status": ranking.get("conservation_status", ""),
                "strict_three_dimensional_position_status": ranking.get(
                    "three_dimensional_position_status",
                    "",
                ),
                "strict_three_dimensional_alignment_status": ranking.get(
                    "three_dimensional_alignment_status",
                    "",
                ),
                "sensitivity_position_alignment_status": ranking.get(
                    "sensitivity_position_alignment_status",
                    "",
                ),
                "sensitivity_alignment_status": ranking.get(
                    "sensitivity_alignment_status",
                    "",
                ),
                "group_review_html": f"groups/{group_page_name(payload)}",
            }
        )
    return rows


def _decision_rows(
    payloads: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return a blank, rank-preserving expert-review worksheet."""
    return [
        {
            "review_rank": payload["review_rank"],
            "primary_group_type": payload["group_key"]["primary_group_type"],
            "primary_group_id": payload["group_key"]["primary_group_id"],
            "lead_cluster_id": payload["group_key"]["cluster_id"],
            "reviewer": "",
            "decision": "",
            "final_priority": "",
            "rationale": "",
            "review_date": "",
        }
        for payload in payloads
    ]


def _evidence_matrix_rows(
    payloads: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return a rank-preserving strict and sensitivity evidence matrix."""
    fields = (
        "grant_aligned_prestructure_pass",
        "conservation_status",
        "three_dimensional_position_status",
        "three_dimensional_alignment_status",
        "sensitivity_position_alignment_status",
        "sensitivity_alignment_status",
        "grant_aligned_final_pass",
    )
    rows = []
    for payload in payloads:
        ranking = payload["ranking"]
        row = {
            "review_rank": payload["review_rank"],
            "primary_group_type": payload["group_key"]["primary_group_type"],
            "primary_group_id": payload["group_key"]["primary_group_id"],
            "lead_cluster_id": payload["group_key"]["cluster_id"],
        }
        row.update({field: ranking.get(field, "") for field in fields})
        rows.append(row)
    return rows


def _pocket_residue_rows(
    payloads: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return every exact pocket-to-FASTA-to-alignment residue mapping."""
    rows = []
    for payload in payloads:
        key = payload["group_key"]
        for record in payload["alignment"]["records"]:
            for annotation in record["pocket_annotations"]:
                rows.append(
                    {
                        "review_rank": payload["review_rank"],
                        "primary_group_type": key["primary_group_type"],
                        "primary_group_id": key["primary_group_id"],
                        "lead_cluster_id": key["cluster_id"],
                        "candidate_accession": record["accession"],
                        "species_column": record["species"],
                        "is_reference": record["is_reference"],
                        "selection_rank": annotation["selection_rank"],
                        "pocket_number": annotation["pocket_number"],
                        "alignment_column": annotation["column"] + 1,
                        "fasta_position": annotation["fasta_position"],
                        "fasta_residue": annotation["fasta_residue"],
                        "structure_label_chain": annotation[
                            "structure_label_chain"
                        ],
                        "structure_label_seq_id": annotation[
                            "structure_label_seq_id"
                        ],
                        "structure_auth_chain": annotation[
                            "structure_auth_chain"
                        ],
                        "structure_auth_seq_id": annotation[
                            "structure_auth_seq_id"
                        ],
                        "structure_insertion_code": annotation[
                            "structure_insertion_code"
                        ],
                        "structure_residue_name": annotation[
                            "structure_residue_name"
                        ],
                    }
                )
    rows.sort(
        key=lambda row: (
            row["review_rank"],
            not row["is_reference"],
            row["species_column"],
            row["candidate_accession"],
            row["selection_rank"],
            row["fasta_position"],
        )
    )
    return rows


def _model_inventory_rows(
    payloads: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return every displayed protein model and its embedded evidence status."""
    rows = []
    for payload in payloads:
        key = payload["group_key"]
        for protein in payload["proteins"]:
            rows.append(
                {
                    "review_rank": payload["review_rank"],
                    "primary_group_type": key["primary_group_type"],
                    "primary_group_id": key["primary_group_id"],
                    "lead_cluster_id": key["cluster_id"],
                    "candidate_accession": protein["accession"],
                    "species_column": protein["species"],
                    "is_reference": protein["is_reference"],
                    "model_status": protein["model_status"],
                    "model_sha256": protein.get("model_sha256", ""),
                    "ca_atom_count": protein.get("atom_count", 0),
                    "mapped_pocket_ca_count": protein.get(
                        "mapped_pocket_atom_count",
                        0,
                    ),
                    "retained_pocket_count": len(protein["pockets"]),
                }
            )
    return rows


def _sequence_rows(
    payloads: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return every sequence in the published alignments for reviewed groups."""
    rows: list[dict[str, Any]] = []
    observed_identifiers: set[str] = set()
    for payload in payloads:
        key = payload["group_key"]
        source_sha256 = payload["alignment"].get("source_sha256", "")
        for record in payload["alignment"].get("all_records", ()):
            aligned_sequence = str(record["sequence"]).upper()
            amino_acid_sequence = aligned_sequence.replace("-", "").replace(".", "")
            if not amino_acid_sequence:
                raise StructuralAlignmentError(
                    "Prioritised-group alignment contains an all-gap sequence: "
                    f"{record['accession']}"
                )
            fasta_identifier = safe_filename(
                "rank_"
                f"{int(payload['review_rank']):03d}__"
                f"{key['primary_group_type']}__"
                f"{key['primary_group_id']}__"
                f"{key['cluster_id']}__"
                f"{record['accession']}"
            )
            if fasta_identifier in observed_identifiers:
                raise StructuralAlignmentError(
                    "Prioritised-group FASTA identifier is not unique after "
                    f"normalisation: {fasta_identifier}"
                )
            observed_identifiers.add(fasta_identifier)
            rows.append(
                {
                    "review_rank": payload["review_rank"],
                    "primary_group_type": key["primary_group_type"],
                    "primary_group_id": key["primary_group_id"],
                    "lead_cluster_id": key["cluster_id"],
                    "fasta_identifier": fasta_identifier,
                    "candidate_accession": record["accession"],
                    "species_column": record.get("species", ""),
                    "is_reference": record.get("is_reference", False),
                    "has_ranked_pocket_evidence": record.get(
                        "has_ranked_pocket_evidence",
                        False,
                    ),
                    "sequence_length": len(amino_acid_sequence),
                    "amino_acid_sequence": amino_acid_sequence,
                    "alignment_length": len(aligned_sequence),
                    "aligned_sequence": aligned_sequence,
                    "alignment_source_sha256": source_sha256,
                }
            )
    rows.sort(
        key=lambda row: (
            row["review_rank"],
            not row["is_reference"],
            not bool(row["species_column"]),
            row["species_column"],
            row["candidate_accession"],
        )
    )
    return rows


def _write_sequence_fasta(
    *,
    path: Path,
    records: Sequence[Mapping[str, Any]],
    line_width: int = 80,
) -> None:
    """Write a deterministic, atomically published protein FASTA file.

    Args:
        path: Destination FASTA path.
        records: Sequence-export records containing identifiers and sequences.
        line_width: Maximum residues per sequence line.

    Raises:
        StructuralAlignmentError: If no records are available or the line width
            is invalid.
    """
    if not records:
        raise StructuralAlignmentError(
            "No prioritised-group sequences were available for FASTA export"
        )
    if line_width < 1:
        raise StructuralAlignmentError("FASTA line width must be positive")
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial.{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            for record in records:
                identifier = str(record["fasta_identifier"])
                sequence = str(record["amino_acid_sequence"])
                handle.write(f">{identifier}\n")
                for start in range(0, len(sequence), line_width):
                    handle.write(f"{sequence[start:start + line_width]}\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise StructuralAlignmentError(
            f"Could not publish prioritised-group FASTA {destination}: {exc}"
        ) from exc


def _supplementary_sequence_rows(
    *, inputs: ReviewInputs, payloads: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Return validated exact sequences supplied outside pocket assessment.

    The optional table is used by human-inclusive extensions to keep sequence
    evidence visible when an AlphaFold model or acceptable pocket is absent.
    It is not folded into the pocket-aligned sequence table because those rows
    have no defensible pocket coordinates to annotate.
    """
    source = inputs.supplementary_group_sequences
    if source is None:
        return []
    rows = read_records(source)
    required = (
        "review_rank",
        "cluster_id",
        "primary_group_type",
        "primary_group_id",
        "species_column",
        "accession",
        "sequence_length",
        "sequence_sha256",
        "protein_sequence",
    )
    require_columns(rows, required, "supplementary group sequences")
    valid_keys = {
        (
            int(payload["review_rank"]),
            str(payload["group_key"]["cluster_id"]),
            str(payload["group_key"]["primary_group_type"]),
            str(payload["group_key"]["primary_group_id"]),
        )
        for payload in payloads
    }
    published: list[dict[str, Any]] = []
    observed: set[tuple[int, str, str, str, str]] = set()
    for row in rows:
        try:
            rank = int(row["review_rank"])
            expected_length = int(row["sequence_length"])
        except (TypeError, ValueError) as exc:
            raise StructuralAlignmentError(
                "Supplementary sequence ranks and lengths must be integers"
            ) from exc
        cluster_id = str(row["cluster_id"]).strip()
        group_type = str(row["primary_group_type"]).strip()
        group_id = str(row["primary_group_id"]).strip()
        accession = str(row["accession"]).strip()
        species = str(row["species_column"]).strip()
        sequence = str(row["protein_sequence"]).strip().upper()
        digest = str(row["sequence_sha256"]).strip().lower()
        group_key = (rank, cluster_id, group_type, group_id)
        member_key = (*group_key, accession)
        if group_key not in valid_keys:
            continue
        if not accession or not species or not sequence:
            raise StructuralAlignmentError(
                "Supplementary sequence rows require accession, species and sequence"
            )
        if any(not (residue.isalpha() or residue in {"*", "-"}) for residue in sequence):
            raise StructuralAlignmentError(
                f"Supplementary sequence contains invalid residues: {accession}"
            )
        ungapped = sequence.replace("-", "")
        if len(ungapped) != expected_length:
            raise StructuralAlignmentError(
                f"Supplementary sequence length mismatch for {accession}"
            )
        if hashlib.sha256(ungapped.encode("ascii")).hexdigest() != digest:
            raise StructuralAlignmentError(
                f"Supplementary sequence checksum mismatch for {accession}"
            )
        if member_key in observed:
            raise StructuralAlignmentError(
                f"Duplicate supplementary sequence for {accession} in {group_id}"
            )
        observed.add(member_key)
        published.append(
            {
                "review_rank": rank,
                "primary_group_type": group_type,
                "primary_group_id": group_id,
                "lead_cluster_id": cluster_id,
                "fasta_identifier": (
                    f"rank_{rank:03d}__{safe_filename(group_type)}__"
                    f"{safe_filename(group_id)}__{safe_filename(accession)}"
                ),
                "candidate_accession": accession,
                "species_column": species,
                "sequence_length": expected_length,
                "sequence_sha256": digest,
                "amino_acid_sequence": ungapped,
                "structural_assessment_note": (
                    "Exact HOG-member sequence inventory; inclusion does not imply "
                    "that an AlphaFold model or qualifying pocket was available"
                ),
            }
        )
    published.sort(
        key=lambda row: (
            int(row["review_rank"]),
            str(row["species_column"]),
            str(row["candidate_accession"]),
        )
    )
    return published


def _validation(
    payloads: Sequence[Mapping[str, Any]],
    settings: ReviewSettings,
    viewer_rows: Sequence[Mapping[str, Any]],
    supplementary_sequence_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return the explicit report-generation quality-control summary."""
    return {
        "status": "PASS",
        "requested_review_limit": settings.review_limit,
        "reported_group_count": len(payloads),
        "group_page_count": len(payloads),
        "protein_count": sum(len(payload["proteins"]) for payload in payloads),
        "model_available_protein_count": sum(
            protein["model_status"] == "MODEL_AVAILABLE"
            for payload in payloads
            for protein in payload["proteins"]
        ),
        "alignment_available_group_count": sum(
            payload["alignment"]["status"] == "AVAILABLE" for payload in payloads
        ),
        "sequence_export_group_count": sum(
            bool(payload["alignment"].get("all_records")) for payload in payloads
        ),
        "sequence_export_record_count": len(_sequence_rows(payloads)),
        "exact_pocket_residue_annotation_count": len(
            _pocket_residue_rows(payloads)
        ),
        "strict_reference_group_count": sum(
            payload["reference_source"] == "STRUCTURAL_ALIGNMENT_SUMMARY"
            for payload in payloads
        ),
        "inferred_reference_group_count": sum(
            payload["reference_source"]
            == "INFERRED_FROM_SELECTED_POCKET_EVIDENCE"
            for payload in payloads
        ),
        "structural_superposition_viewer_count": len(viewer_rows),
        "structural_superposition_group_count": len(
            {int(row["review_rank"]) for row in viewer_rows}
        ),
        "supplementary_sequence_record_count": len(
            supplementary_sequence_rows
        ),
        "supplementary_sequence_group_count": len(
            {
                int(row["review_rank"])
                for row in supplementary_sequence_rows
            }
        ),
        "interpretation": (
            "HTML pages visualise existing rank-one and top-k evidence without "
            "recalculating candidate order or scientific decisions"
        ),
    }


def _publish_report(
    *,
    staging: Path,
    payloads: Sequence[Mapping[str, Any]],
    viewer_rows: Sequence[Mapping[str, Any]],
    supplementary_sequence_rows: Sequence[Mapping[str, Any]],
) -> None:
    """Write the complete report tree into a private staging directory."""
    write_html(staging / "index.html", render_index(payloads))
    write_html(
        staging / "evidence_matrix.html",
        render_evidence_matrix(payloads),
    )
    for payload in payloads:
        write_html(
            staging / "groups" / group_page_name(payload),
            render_group_page(payload),
        )
    index_rows = _review_index_rows(payloads)
    index_fields = tuple(index_rows[0])
    write_tsv(
        staging / "tables" / "review_report_index.tsv",
        index_rows,
        index_fields,
    )
    decision_rows = _decision_rows(payloads)
    write_tsv(
        staging / "review_decisions_template.tsv",
        decision_rows,
        tuple(decision_rows[0]),
    )
    evidence_rows = _evidence_matrix_rows(payloads)
    write_tsv(
        staging / "tables" / "top_group_evidence_matrix.tsv",
        evidence_rows,
        tuple(evidence_rows[0]),
    )
    residue_rows = _pocket_residue_rows(payloads)
    residue_fields = (
        "review_rank",
        "primary_group_type",
        "primary_group_id",
        "lead_cluster_id",
        "candidate_accession",
        "species_column",
        "is_reference",
        "selection_rank",
        "pocket_number",
        "alignment_column",
        "fasta_position",
        "fasta_residue",
        "structure_label_chain",
        "structure_label_seq_id",
        "structure_auth_chain",
        "structure_auth_seq_id",
        "structure_insertion_code",
        "structure_residue_name",
    )
    write_tsv(
        staging / "tables" / "pocket_residue_annotations.tsv",
        residue_rows,
        residue_fields,
    )
    model_rows = _model_inventory_rows(payloads)
    write_tsv(
        staging / "tables" / "protein_model_inventory.tsv",
        model_rows,
        tuple(model_rows[0]),
    )
    sequence_rows = _sequence_rows(payloads)
    sequence_fields = (
        "review_rank",
        "primary_group_type",
        "primary_group_id",
        "lead_cluster_id",
        "fasta_identifier",
        "candidate_accession",
        "species_column",
        "is_reference",
        "has_ranked_pocket_evidence",
        "sequence_length",
        "amino_acid_sequence",
        "alignment_length",
        "aligned_sequence",
        "alignment_source_sha256",
    )
    write_tsv(
        staging / "tables" / "prioritised_group_sequences.tsv",
        sequence_rows,
        sequence_fields,
    )
    _write_sequence_fasta(
        path=staging / "sequences" / "prioritised_group_sequences.fasta",
        records=sequence_rows,
    )
    if supplementary_sequence_rows:
        write_tsv(
            staging / "tables" / "supplementary_group_sequences.tsv",
            supplementary_sequence_rows,
            tuple(supplementary_sequence_rows[0]),
        )
        _write_sequence_fasta(
            path=staging / "sequences" / "supplementary_group_sequences.fasta",
            records=supplementary_sequence_rows,
        )
    public_viewer_rows = [
        {
            field: value
            for field, value in row.items()
            if field != "viewer_source_path"
        }
        for row in viewer_rows
    ]
    public_viewer_fields = tuple(public_viewer_rows[0])
    write_tsv(
        staging / "tables" / "structural_alignment_viewers.tsv",
        public_viewer_rows,
        public_viewer_fields,
    )
    for row in viewer_rows:
        source = Path(str(row["viewer_source_path"]))
        destination = staging / str(row["interactive_view_html"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if sha256_file(destination) != str(row["viewer_source_sha256"]):
            raise StructuralAlignmentError(
                f"Copied structural viewer checksum changed: {destination}"
            )


def build_review_report(
    *,
    run_root: Path,
    output_dir: Path,
    settings: ReviewSettings,
    overrides: ReviewInputOverrides,
    resume: bool,
    force: bool,
    verbose: bool,
) -> Path:
    """Build the complete top-group review report through atomic publication.

    Args:
        run_root: Completed end-to-end workflow run root.
        output_dir: New report directory.
        settings: Bounded report settings.
        overrides: Optional explicit input authorities.
        resume: Reuse only a checksum-valid matching completed report.
        force: Supersede an existing report before rebuilding.
        verbose: Emit debug messages to the console as well as the log.

    Returns:
        Published run-manifest path.

    Raises:
        StructuralAlignmentError: If inputs, outputs or publication are invalid.
    """
    if resume and force:
        raise StructuralAlignmentError("resume and force are mutually exclusive")
    settings.validate()
    inputs = resolve_review_inputs(run_root=run_root, overrides=overrides)
    base_digest, input_inventory = input_digest(inputs=inputs, settings=settings)
    payloads = load_report_payloads(inputs=inputs, settings=settings)
    viewer_rows = _structural_viewer_rows(inputs=inputs, payloads=payloads)
    supplementary_sequence_rows = _supplementary_sequence_rows(
        inputs=inputs,
        payloads=payloads,
    )
    run_digest = _complete_digest(
        base_digest=base_digest,
        payloads=payloads,
        viewer_rows=viewer_rows,
    )
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        if resume and _validate_existing_output(destination, run_digest):
            return destination / "provenance" / "run_manifest.json"
        if not force:
            raise StructuralAlignmentError(
                "Output directory already exists but is not a valid matching resume "
                f"target: {destination}"
            )
        superseded = destination.with_name(
            f"{destination.name}.superseded.{uuid.uuid4().hex}"
        )
        destination.replace(superseded)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(
        f".{destination.name}.staging.{uuid.uuid4().hex}"
    )
    staging.mkdir()
    logger = configure_logging(staging / "logs" / "pocket_review.log", verbose)
    started = utc_now()
    failed = destination.with_name(
        f".{destination.name}.failed.{uuid.uuid4().hex}"
    )
    try:
        LOGGER.info("E3 structural package version: %s", __version__)
        LOGGER.info("Run root: %s", inputs.run_root)
        LOGGER.info(
            "Building %d ranked group pages with top-%d pockets",
            len(payloads),
            settings.member_pocket_top_k,
        )
        for label, record in input_inventory.items():
            LOGGER.debug(
                "Input %s: %s (%d bytes; SHA-256 %s)",
                label,
                record["path"],
                record["size_bytes"],
                record["sha256"],
            )
        _publish_report(
            staging=staging,
            payloads=payloads,
            viewer_rows=viewer_rows,
            supplementary_sequence_rows=supplementary_sequence_rows,
        )
        validation = _validation(
            payloads,
            settings,
            viewer_rows,
            supplementary_sequence_rows,
        )
        write_tsv(
            staging / "qc" / "pocket_review_validation.tsv",
            [validation],
            tuple(validation),
        )
        close_logger(logger)
        outputs = output_inventory(
            staging,
            excluded_names=frozenset({"run_manifest.json"}),
        )
        manifest = {
            "status": "complete",
            "package_version": __version__,
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "run_digest": run_digest,
            "run_root": str(inputs.run_root),
            "settings": {
                "review_limit": settings.review_limit,
                "member_pocket_top_k": settings.member_pocket_top_k,
            },
            "inputs": input_inventory,
            "embedded_sources": _embedded_source_inventory(payloads),
            "validation": validation,
            "outputs": outputs,
        }
        atomic_write_json(staging / "provenance" / "run_manifest.json", manifest)
        os.replace(staging, destination)
        return destination / "provenance" / "run_manifest.json"
    except BaseException:
        close_logger(logger)
        if staging.exists():
            staging.replace(failed)
        raise
