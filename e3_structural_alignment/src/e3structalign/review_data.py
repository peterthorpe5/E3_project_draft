"""Input discovery and validated data preparation for pocket-review reports."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from e3structalign.errors import InputValidationError
from e3structalign.io_utils import (
    read_records,
    require_columns,
    resolve_input_file,
    safe_filename,
    sha256_file,
)
from e3structalign.models import ResidueLocator, SelectedPocket
from e3structalign.pipeline import (
    parse_ranked_pocket_sequence_coordinates,
    parse_ranked_pockets,
    parse_selected_pockets,
    resolve_structure_assets,
)
from e3structalign.review_models import (
    ReviewInputOverrides,
    ReviewInputs,
    ReviewSettings,
)
from e3structalign.structure_io import parse_ca_atoms, pocket_atom_coordinates

LOGGER = logging.getLogger("e3structalign.review")

_RUN_FILE_CANDIDATES = {
    "shortlist": (
        "10_integrated_resource/final_results/"
        "top_computational_review_shortlist.parquet",
        "10_integrated_resource/final_results/"
        "top_computational_review_shortlist.tsv",
        "10_integrated_resource/final_results/"
        "top_50_computational_review_shortlist.parquet",
        "10_integrated_resource/final_results/"
        "top_50_computational_review_shortlist.tsv",
    ),
    "selected_pockets": (
        "09_ligandability/tables/selected_pockets.parquet",
        "09_ligandability/tables/selected_pockets.tsv",
    ),
    "ranked_pockets": (
        "09_ligandability/tables/ranked_member_pockets.parquet",
        "09_ligandability/tables/ranked_member_pockets.tsv",
    ),
    "ranked_pocket_sequence_coordinates": (
        "09_ligandability/tables/ranked_pocket_sequence_coordinates.parquet",
        "09_ligandability/tables/ranked_pocket_sequence_coordinates.tsv",
    ),
    "asset_manifest": (
        "09_ligandability/tables/reused_asset_manifest.parquet",
        "09_ligandability/tables/reused_asset_manifest.tsv",
    ),
    "structural_summary": (
        "09b_structural_alignment/structural_alignment/tables/"
        "structural_alignment_summary.parquet",
        "09b_structural_alignment/structural_alignment/tables/"
        "structural_alignment_summary.tsv",
    ),
    "sensitivity_group_summary": (
        "09b_structural_alignment/structural_alignment/tables/"
        "structural_pocket_sensitivity_group_summary.parquet",
        "09b_structural_alignment/structural_alignment/tables/"
        "structural_pocket_sensitivity_group_summary.tsv",
    ),
    "sensitivity_member_summary": (
        "09b_structural_alignment/structural_alignment/tables/"
        "structural_pocket_sensitivity_member_summary.parquet",
        "09b_structural_alignment/structural_alignment/tables/"
        "structural_pocket_sensitivity_member_summary.tsv",
    ),
}

_ALIGNMENT_ROOT_CANDIDATES = (
    "09_ligandability/alignments",
    "09_ligandability/generated_ligandability/alignments",
)


def group_key(record: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return the controlled cluster/type/group key for one table row."""
    cluster_id = str(
        record.get("cluster_id") or record.get("lead_cluster_id") or ""
    ).strip()
    group_type = str(record.get("primary_group_type") or "").strip()
    group_id = str(record.get("primary_group_id") or "").strip()
    if not cluster_id or not group_type or not group_id:
        raise InputValidationError(
            "A review record has an empty cluster, group type or group identifier"
        )
    return (cluster_id, group_type, group_id)


def review_rank(record: Mapping[str, Any]) -> int:
    """Return one validated positive final evolutionary rank."""
    value = record.get("final_evolutionary_rank")
    try:
        rank = int(value)
    except (TypeError, ValueError) as exc:
        raise InputValidationError(
            f"Invalid final_evolutionary_rank value: {value!r}"
        ) from exc
    if rank < 1:
        raise InputValidationError(
            f"final_evolutionary_rank must be positive: {rank}"
        )
    return rank


def _resolve_run_file(
    *,
    run_root: Path,
    label: str,
    override: Path | None,
) -> Path:
    """Resolve one explicit or preferred conventional run input file."""
    if override is not None:
        return resolve_input_file(override, label)
    for relative in _RUN_FILE_CANDIDATES[label]:
        candidate = run_root / relative
        if candidate.is_file():
            return resolve_input_file(candidate, label)
    expected = ", ".join(_RUN_FILE_CANDIDATES[label])
    raise InputValidationError(
        f"Could not find {label} below {run_root}. Expected one of: {expected}"
    )


def _resolve_alignment_root(
    *, run_root: Path, override: Path | None
) -> Path:
    """Resolve the published Stage 09 MAFFT alignment directory."""
    if override is not None:
        resolved = Path(override).expanduser().resolve()
        if not resolved.is_dir():
            raise InputValidationError(
                f"alignments_root is not a directory: {resolved}"
            )
        return resolved
    present = [
        run_root / relative
        for relative in _ALIGNMENT_ROOT_CANDIDATES
        if (run_root / relative).is_dir()
    ]
    if len(present) != 1:
        raise InputValidationError(
            "Expected exactly one Stage 09 alignment directory below "
            f"{run_root}; found {len(present)}"
        )
    return present[0].resolve()


def resolve_review_inputs(
    *,
    run_root: Path,
    overrides: ReviewInputOverrides,
) -> ReviewInputs:
    """Resolve all reporting authorities from one completed workflow run."""
    root = Path(run_root).expanduser().resolve()
    if not root.is_dir():
        raise InputValidationError(f"run_root is not a directory: {root}")
    paths = {
        label: _resolve_run_file(
            run_root=root,
            label=label,
            override=getattr(overrides, label),
        )
        for label in _RUN_FILE_CANDIDATES
    }
    return ReviewInputs(
        run_root=root,
        shortlist=paths["shortlist"],
        selected_pockets=paths["selected_pockets"],
        ranked_pockets=paths["ranked_pockets"],
        ranked_pocket_sequence_coordinates=(
            paths["ranked_pocket_sequence_coordinates"]
        ),
        asset_manifest=paths["asset_manifest"],
        alignments_root=_resolve_alignment_root(
            run_root=root,
            override=overrides.alignments_root,
        ),
        structural_summary=paths["structural_summary"],
        sensitivity_group_summary=paths["sensitivity_group_summary"],
        sensitivity_member_summary=paths["sensitivity_member_summary"],
    )


def read_fasta(path: Path) -> dict[str, str]:
    """Read a strict FASTA file into unique accession-keyed sequences."""
    source = resolve_input_file(path, "aligned FASTA")
    sequences: dict[str, str] = {}
    header: str | None = None
    chunks: list[str] = []
    with source.open("r", encoding="utf-8", errors="strict") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    _store_fasta_record(
                        sequences=sequences,
                        header=header,
                        chunks=chunks,
                        path=source,
                    )
                identifier = line[1:].split(maxsplit=1)
                header = identifier[0] if identifier else ""
                chunks = []
                if not header:
                    raise InputValidationError(
                        f"Empty FASTA identifier at {source}:{line_number}"
                    )
                continue
            if header is None:
                raise InputValidationError(
                    f"FASTA sequence precedes its identifier at {source}:{line_number}"
                )
            chunks.append(line)
    if header is not None:
        _store_fasta_record(
            sequences=sequences,
            header=header,
            chunks=chunks,
            path=source,
        )
    if not sequences:
        raise InputValidationError(f"Aligned FASTA contains no records: {source}")
    lengths = {len(sequence) for sequence in sequences.values()}
    if len(lengths) != 1:
        raise InputValidationError(
            f"Aligned FASTA records have unequal lengths: {source}"
        )
    return sequences


def _store_fasta_record(
    *,
    sequences: dict[str, str],
    header: str,
    chunks: Sequence[str],
    path: Path,
) -> None:
    """Validate and store one parsed aligned FASTA record."""
    sequence = "".join(chunks).upper()
    if not sequence:
        raise InputValidationError(f"FASTA record {header} is empty in {path}")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ-*?.")
    unexpected = sorted(set(sequence).difference(allowed))
    if unexpected:
        raise InputValidationError(
            f"FASTA record {header} contains unsupported symbols in {path}: "
            + "".join(unexpected)
        )
    if header in sequences:
        raise InputValidationError(f"Duplicate FASTA identifier {header} in {path}")
    sequences[header] = sequence


def alignment_position_map(sequence: str) -> dict[int, int]:
    """Map one-based ungapped positions to zero-based alignment columns."""
    mapping: dict[int, int] = {}
    residue_position = 0
    for alignment_column, character in enumerate(sequence):
        if character in {"-", "."}:
            continue
        residue_position += 1
        mapping[residue_position] = alignment_column
    return mapping


def alignment_path(
    *,
    alignments_root: Path,
    key: tuple[str, str, str],
) -> Path:
    """Return the conventional aligned FASTA path for one group."""
    group_slug = safe_filename(f"{key[0]}__{key[2]}")
    return alignments_root / group_slug / "aligned.fasta"


def _reference_sort_key(pocket: SelectedPocket) -> tuple[Any, ...]:
    """Return the structural package's deterministic reference ordering."""
    return (
        not pocket.structural_evidence_status.startswith(
            "SELECTED_HIGH_CONFIDENCE"
        ),
        not pocket.predictor_agreement,
        -(pocket.mapping_fraction if pocket.mapping_fraction is not None else -1.0),
        -(
            pocket.pocket_plddt_fraction
            if pocket.pocket_plddt_fraction is not None
            else -1.0
        ),
        -(
            pocket.druggability_score
            if pocket.druggability_score is not None
            else -1.0
        ),
        pocket.accession,
    )


def choose_reference(
    *,
    summary: Mapping[str, Any] | None,
    selected: Sequence[SelectedPocket],
) -> tuple[str, str]:
    """Choose the authoritative reference, with a documented safe fallback."""
    reported = str((summary or {}).get("reference_accession") or "").strip()
    accessions = {pocket.accession for pocket in selected}
    if reported:
        if reported not in accessions:
            raise InputValidationError(
                f"Structural summary reference {reported} is absent from selected pockets"
            )
        return reported, "STRUCTURAL_ALIGNMENT_SUMMARY"
    if not selected:
        raise InputValidationError("Cannot choose a reference without selected pockets")
    inferred = min(selected, key=_reference_sort_key).accession
    return inferred, "INFERRED_FROM_SELECTED_POCKET_EVIDENCE"


def _record_value(record: Mapping[str, Any], key: str) -> Any:
    """Return a JSON-safe representation of one tabular value."""
    value = record.get(key)
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def json_safe_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a stable JSON-safe copy of one table record."""
    return {
        str(key): _record_value(record, str(key))
        for key in sorted(record)
    }


def _pocket_payload(pocket: SelectedPocket) -> dict[str, Any]:
    """Return one ranked pocket as a browser-safe record."""
    return {
        "pocket_number": pocket.pocket_number,
        "selection_rank": pocket.selection_rank,
        "druggability_score": pocket.druggability_score,
        "mapping_fraction": pocket.mapping_fraction,
        "pocket_plddt_fraction": pocket.pocket_plddt_fraction,
        "predictor_agreement": pocket.predictor_agreement,
        "structural_evidence_status": pocket.structural_evidence_status,
    }


def _atom_payload(
    *,
    atoms: Sequence[Any],
    pocket_atoms: Mapping[tuple[float, float, float], list[dict[str, int]]],
) -> list[dict[str, Any]]:
    """Return compact C-alpha trace records with ranked-pocket annotations."""
    return [
        {
            "x": round(atom.x, 4),
            "y": round(atom.y, 4),
            "z": round(atom.z, 4),
            "chain": atom.label_chain or atom.auth_chain,
            "resi": atom.label_seq_id or atom.auth_seq_id,
            "resn": atom.residue_name,
            "pockets": pocket_atoms.get(atom.coordinate, []),
        }
        for atom in atoms
    ]


def _protein_payload(
    *,
    pocket_records: Sequence[SelectedPocket],
    coordinate_index: Mapping[tuple[str, int], Sequence[Any]],
    asset: Any | None,
    reference_accession: str,
) -> dict[str, Any]:
    """Build one protein's trace, pocket and evidence payload."""
    first = pocket_records[0]
    pockets = sorted(
        pocket_records,
        key=lambda pocket: (pocket.selection_rank, pocket.pocket_number),
    )
    if asset is None:
        return {
            "accession": first.accession,
            "species": first.species,
            "is_reference": first.accession == reference_accession,
            "model_status": "MODEL_UNAVAILABLE",
            "atoms": [],
            "pockets": [_pocket_payload(pocket) for pocket in pockets],
        }
    atoms = parse_ca_atoms(asset.path)
    annotated: dict[tuple[float, float, float], list[dict[str, int]]] = defaultdict(list)
    for pocket in pockets:
        locators = [
            coordinate.locator
            for coordinate in coordinate_index.get(
                (pocket.accession, pocket.pocket_number),
                (),
            )
        ]
        for _, atom in pocket_atom_coordinates(atoms, locators):
            annotation = {
                "pocket_number": pocket.pocket_number,
                "selection_rank": pocket.selection_rank,
            }
            if annotation not in annotated[atom.coordinate]:
                annotated[atom.coordinate].append(annotation)
    for values in annotated.values():
        values.sort(key=lambda item: (item["selection_rank"], item["pocket_number"]))
    return {
        "accession": first.accession,
        "species": first.species,
        "is_reference": first.accession == reference_accession,
        "model_status": "MODEL_AVAILABLE",
        "model_sha256": asset.sha256,
        "atom_count": len(atoms),
        "mapped_pocket_atom_count": len(annotated),
        "atoms": _atom_payload(atoms=atoms, pocket_atoms=annotated),
        "pockets": [_pocket_payload(pocket) for pocket in pockets],
    }


def _alignment_payload(
    *,
    sequences: Mapping[str, str],
    proteins: Sequence[Mapping[str, Any]],
    coordinate_index: Mapping[tuple[str, int], Sequence[Any]],
    ranked_by_accession: Mapping[str, Sequence[SelectedPocket]],
) -> dict[str, Any]:
    """Build aligned sequences with exact top-k pocket-column annotations."""
    protein_index = {
        str(protein["accession"]): protein for protein in proteins
    }
    reference_accession = next(
        (
            str(protein["accession"])
            for protein in proteins
            if protein["is_reference"]
        ),
        "",
    )
    all_records = [
        {
            "accession": accession,
            "species": (
                protein_index[accession]["species"]
                if accession in protein_index
                else ""
            ),
            "is_reference": accession == reference_accession,
            "has_ranked_pocket_evidence": accession in protein_index,
            "sequence": sequence,
        }
        for accession, sequence in sequences.items()
    ]
    all_records.sort(
        key=lambda record: (
            not record["is_reference"],
            not bool(record["species"]),
            record["species"],
            record["accession"],
        )
    )
    records = []
    for accession, sequence in sequences.items():
        position_map = alignment_position_map(sequence)
        annotations: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for pocket in ranked_by_accession.get(accession, ()):
            for coordinate in coordinate_index.get(
                (accession, pocket.pocket_number),
                (),
            ):
                if (
                    coordinate.sequence_coordinate_status != "MAPPED_EXACT"
                    or coordinate.fasta_position is None
                ):
                    continue
                column = position_map.get(coordinate.fasta_position)
                if column is None:
                    raise InputValidationError(
                        f"Pocket FASTA position {coordinate.fasta_position} exceeds "
                        f"the aligned sequence for {accession}"
                    )
                observed = sequence[column]
                if (
                    coordinate.fasta_residue
                    and observed not in {"X", "?"}
                    and observed != coordinate.fasta_residue
                ):
                    raise InputValidationError(
                        f"Aligned residue identity disagrees for {accession} at "
                        f"FASTA position {coordinate.fasta_position}"
                    )
                annotation = {
                    "column": column,
                    "fasta_position": coordinate.fasta_position,
                    "fasta_residue": coordinate.fasta_residue,
                    "pocket_number": pocket.pocket_number,
                    "selection_rank": pocket.selection_rank,
                    "structure_label_chain": coordinate.locator.label_chain,
                    "structure_label_seq_id": coordinate.locator.label_seq_id,
                    "structure_auth_chain": coordinate.locator.auth_chain,
                    "structure_auth_seq_id": coordinate.locator.auth_seq_id,
                    "structure_insertion_code": coordinate.locator.insertion_code,
                    "structure_residue_name": coordinate.structure_residue_name,
                }
                if annotation not in annotations[column]:
                    annotations[column].append(annotation)
        ordered_annotations = [
            annotation
            for column in sorted(annotations)
            for annotation in sorted(
                annotations[column],
                key=lambda item: (
                    item["selection_rank"],
                    item["pocket_number"],
                ),
            )
        ]
        records.append(
            {
                "accession": accession,
                "species": (
                    protein_index[accession]["species"]
                    if accession in protein_index
                    else ""
                ),
                "is_reference": accession == reference_accession,
                "has_ranked_pocket_evidence": accession in protein_index,
                "sequence": sequence,
                "pocket_annotations": ordered_annotations,
            }
        )
    records.sort(
        key=lambda record: (
            not record["is_reference"],
            not bool(record["species"]),
            record["species"],
            record["accession"],
        )
    )
    alignment_length = len(next(iter(sequences.values()))) if sequences else 0
    return {
        "status": "AVAILABLE" if records else "UNAVAILABLE",
        "alignment_length": alignment_length,
        "sequence_count": len(records),
        "all_sequence_count": len(all_records),
        "all_records": all_records,
        "records": records,
    }


def input_digest(
    *,
    inputs: ReviewInputs,
    settings: ReviewSettings,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Return a checksum-bound report-build digest and input inventory."""
    inventory = {
        label: {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for label, path in inputs.file_inputs().items()
    }
    payload = {
        "inputs": inventory,
        "run_root": str(inputs.run_root),
        "alignments_root": str(inputs.alignments_root),
        "settings": {
            "review_limit": settings.review_limit,
            "member_pocket_top_k": settings.member_pocket_top_k,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest(), inventory


def load_report_payloads(
    *,
    inputs: ReviewInputs,
    settings: ReviewSettings,
) -> list[dict[str, Any]]:
    """Load, join and validate all ranked group report payloads."""
    shortlist = read_records(inputs.shortlist)
    require_columns(
        shortlist,
        (
            "final_evolutionary_rank",
            "lead_cluster_id",
            "primary_group_type",
            "primary_group_id",
        ),
        "top review shortlist",
    )
    ranked_shortlist = shortlist[: settings.review_limit]
    if not ranked_shortlist:
        raise InputValidationError("Top review shortlist contains no rows")
    observed_ranks = [review_rank(record) for record in ranked_shortlist]
    if observed_ranks != sorted(observed_ranks) or len(set(observed_ranks)) != len(
        observed_ranks
    ):
        raise InputValidationError(
            "Top review shortlist is not uniquely ordered by final_evolutionary_rank"
        )
    selected = parse_selected_pockets(read_records(inputs.selected_pockets))
    ranked = parse_ranked_pockets(
        read_records(inputs.ranked_pockets),
        maximum_rank=settings.member_pocket_top_k,
    )
    coordinate_index = parse_ranked_pocket_sequence_coordinates(
        read_records(inputs.ranked_pocket_sequence_coordinates),
        ranked=ranked,
    )
    assets = resolve_structure_assets(read_records(inputs.asset_manifest))
    structural_rows = read_records(inputs.structural_summary)
    sensitivity_group_rows = read_records(inputs.sensitivity_group_summary)
    sensitivity_member_rows = read_records(inputs.sensitivity_member_summary)
    by_key_selected: dict[tuple[str, str, str], list[SelectedPocket]] = defaultdict(list)
    by_key_ranked: dict[tuple[str, str, str], list[SelectedPocket]] = defaultdict(list)
    for pocket in selected:
        by_key_selected[
            (pocket.cluster_id, pocket.primary_group_type, pocket.primary_group_id)
        ].append(pocket)
    for pocket in ranked:
        by_key_ranked[
            (pocket.cluster_id, pocket.primary_group_type, pocket.primary_group_id)
        ].append(pocket)
    structural_by_key = _unique_rows_by_key(
        rows=structural_rows,
        label="structural summary",
    )
    sensitivity_group_by_key = _unique_rows_by_key(
        rows=sensitivity_group_rows,
        label="sensitivity group summary",
    )
    sensitivity_members_by_key = _rows_by_key(sensitivity_member_rows)
    payloads = []
    for rank_row in ranked_shortlist:
        key = group_key(rank_row)
        group_selected = by_key_selected.get(key, [])
        group_ranked = by_key_ranked.get(key, [])
        if not group_selected or not group_ranked:
            raise InputValidationError(
                f"Ranked review group has no Stage 09 pockets: {key}"
            )
        summary = structural_by_key.get(key)
        reference, reference_source = choose_reference(
            summary=summary,
            selected=group_selected,
        )
        ranked_by_accession: dict[str, list[SelectedPocket]] = defaultdict(list)
        for pocket in group_ranked:
            ranked_by_accession[pocket.accession].append(pocket)
        proteins = [
            _protein_payload(
                pocket_records=sorted(
                    pockets,
                    key=lambda pocket: (
                        pocket.selection_rank,
                        pocket.pocket_number,
                    ),
                ),
                coordinate_index=coordinate_index,
                asset=assets.get(accession),
                reference_accession=reference,
            )
            for accession, pockets in sorted(ranked_by_accession.items())
        ]
        proteins.sort(
            key=lambda protein: (
                not protein["is_reference"],
                protein["species"],
                protein["accession"],
            )
        )
        aligned_path = alignment_path(
            alignments_root=inputs.alignments_root,
            key=key,
        )
        if aligned_path.is_file():
            sequences = read_fasta(aligned_path)
            alignment = _alignment_payload(
                sequences=sequences,
                proteins=proteins,
                coordinate_index=coordinate_index,
                ranked_by_accession=ranked_by_accession,
            )
            alignment["source_sha256"] = sha256_file(aligned_path)
        else:
            LOGGER.warning("No MAFFT alignment for %s", key)
            alignment = {
                "status": "UNAVAILABLE",
                "reason": "No published Stage 09 aligned.fasta was available",
                "alignment_length": 0,
                "sequence_count": 0,
                "all_sequence_count": 0,
                "all_records": [],
                "records": [],
            }
        payloads.append(
            {
                "review_rank": review_rank(rank_row),
                "group_key": {
                    "cluster_id": key[0],
                    "primary_group_type": key[1],
                    "primary_group_id": key[2],
                },
                "reference_accession": reference,
                "reference_source": reference_source,
                "ranking": json_safe_record(rank_row),
                "structural_summary": (
                    json_safe_record(summary) if summary is not None else {}
                ),
                "sensitivity_group_summary": (
                    json_safe_record(sensitivity_group_by_key[key])
                    if key in sensitivity_group_by_key
                    else {}
                ),
                "sensitivity_member_summary": [
                    json_safe_record(row)
                    for row in sensitivity_members_by_key.get(key, [])
                ],
                "proteins": proteins,
                "alignment": alignment,
            }
        )
    return payloads


def _unique_rows_by_key(
    *,
    rows: Sequence[Mapping[str, Any]],
    label: str,
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    """Index a group table while rejecting duplicate decision rows."""
    indexed: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = group_key(row)
        if key in indexed:
            raise InputValidationError(f"{label} contains duplicate group key: {key}")
        indexed[key] = row
    return indexed


def _rows_by_key(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str], list[Mapping[str, Any]]]:
    """Index a one-to-many group table deterministically."""
    indexed: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        indexed[group_key(row)].append(row)
    for values in indexed.values():
        values.sort(
            key=lambda row: (
                str(row.get("mobile_species") or row.get("species_column") or ""),
                str(row.get("mobile_accession") or row.get("candidate_accession") or ""),
            )
        )
    return indexed
