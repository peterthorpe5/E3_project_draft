"""Explicit pocket-to-model residue mapping and confidence calculations."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .models import PocketResidueRecord, ResidueRecord


def build_model_residue_indexes(
    residues: list[ResidueRecord],
) -> tuple[
    dict[tuple[str, int], ResidueRecord],
    dict[tuple[str, int, str], ResidueRecord],
]:
    """Build unique label-numbering and author-numbering residue indexes.

    Args:
        residues: Parsed model residues.

    Returns:
        Label and author residue indexes.

    Raises:
        ValueError: If duplicate model residue keys are encountered.
    """

    label_index: dict[tuple[str, int], ResidueRecord] = {}
    auth_index: dict[tuple[str, int, str], ResidueRecord] = {}
    for residue in residues:
        if residue.label_seq_id is not None:
            label_key = (residue.label_chain, residue.label_seq_id)
            if label_key in label_index:
                raise ValueError(f"Duplicate model label residue key: {label_key}")
            label_index[label_key] = residue
        if residue.auth_seq_id is not None:
            auth_key = (
                residue.auth_chain,
                residue.auth_seq_id,
                residue.insertion_code,
            )
            if auth_key in auth_index:
                raise ValueError(f"Duplicate model author residue key: {auth_key}")
            auth_index[auth_key] = residue
    return label_index, auth_index


def map_one_pocket_residue(
    pocket_residue: PocketResidueRecord,
    label_index: dict[tuple[str, int], ResidueRecord],
    auth_index: dict[tuple[str, int, str], ResidueRecord],
) -> dict[str, Any]:
    """Map one pocket residue to the source model without silent dropping.

    Label numbering is preferred when available. Author numbering is used as a
    checked fallback. If both methods match different residues, the mapping is
    reported as ambiguous rather than choosing one silently.

    Args:
        pocket_residue: Predicted pocket residue.
        label_index: Model index by label chain and sequence ID.
        auth_index: Model index by author chain, sequence ID and insertion code.

    Returns:
        Flat mapping record including status and model pLDDT.
    """

    label_match: ResidueRecord | None = None
    auth_match: ResidueRecord | None = None
    if pocket_residue.label_seq_id is not None:
        label_match = label_index.get(
            (pocket_residue.label_chain, pocket_residue.label_seq_id)
        )
    if pocket_residue.auth_seq_id is not None:
        auth_match = auth_index.get(
            (
                pocket_residue.auth_chain,
                pocket_residue.auth_seq_id,
                pocket_residue.insertion_code,
            )
        )

    status = "UNMAPPED"
    method = "none"
    model_residue: ResidueRecord | None = None
    if label_match is not None and auth_match is not None:
        if label_match == auth_match:
            status = "MAPPED"
            method = "label_and_auth_agree"
            model_residue = label_match
        else:
            status = "AMBIGUOUS"
            method = "label_auth_conflict"
    elif label_match is not None:
        status = "MAPPED"
        method = "label"
        model_residue = label_match
    elif auth_match is not None:
        status = "MAPPED"
        method = "auth"
        model_residue = auth_match

    record = pocket_residue.to_dict()
    record.update(
        {
            "mapping_status": status,
            "mapping_method": method,
            "model_label_chain": None,
            "model_label_seq_id": None,
            "model_auth_chain": None,
            "model_auth_seq_id": None,
            "model_insertion_code": None,
            "model_residue_name": None,
            "model_plddt": None,
        }
    )
    if model_residue is not None:
        record.update(
            {
                "model_label_chain": model_residue.label_chain,
                "model_label_seq_id": model_residue.label_seq_id,
                "model_auth_chain": model_residue.auth_chain,
                "model_auth_seq_id": model_residue.auth_seq_id,
                "model_insertion_code": model_residue.insertion_code,
                "model_residue_name": model_residue.residue_name,
                "model_plddt": model_residue.plddt,
            }
        )
    return record


def map_pocket_residues(
    pocket_residues: list[PocketResidueRecord],
    model_residues: list[ResidueRecord],
) -> list[dict[str, Any]]:
    """Map all pocket residues to model residues and retain every attempt.

    Args:
        pocket_residues: Predicted pocket residues.
        model_residues: Source model residues.

    Returns:
        Mapping records, including unmapped and ambiguous residues.
    """

    label_index, auth_index = build_model_residue_indexes(model_residues)
    return [
        map_one_pocket_residue(residue, label_index, auth_index)
        for residue in pocket_residues
    ]


def _residue_identifier(record: dict[str, Any]) -> str:
    """Create a readable residue identifier for QC reporting.

    Args:
        record: Pocket residue mapping record.

    Returns:
        Stable identifier string.
    """

    label = f"{record.get('label_chain', '')}_{record.get('label_seq_id', '')}"
    auth = (
        f"{record.get('auth_chain', '')}_{record.get('auth_seq_id', '')}"
        f"{record.get('insertion_code', '')}"
    )
    return f"label={label};auth={auth};res={record.get('residue_name', '')}"


def compute_pocket_quality(
    mapping_records: list[dict[str, Any]],
    confident_threshold: float = 70.0,
    very_high_threshold: float = 90.0,
    minimum_mapping_fraction: float = 0.95,
) -> list[dict[str, Any]]:
    """Calculate pocket pLDDT summaries with explicit mapping denominators.

    Both a mapped-residue fraction and a conservative predicted-residue
    fraction are reported. The conservative fraction uses every predicted
    pocket residue in the denominator, so unmapped residues cannot inflate the
    confidence estimate.

    Args:
        mapping_records: Pocket-to-model mapping records.
        confident_threshold: Confident pLDDT threshold.
        very_high_threshold: Very-high-confidence pLDDT threshold.
        minimum_mapping_fraction: Minimum acceptable residue mapping fraction.

    Returns:
        One quality record per accession and pocket.

    Raises:
        ValueError: If thresholds are invalid.
    """

    if not 0 <= confident_threshold < very_high_threshold <= 100:
        raise ValueError("Invalid pLDDT thresholds.")
    if not 0 <= minimum_mapping_fraction <= 1:
        raise ValueError("minimum_mapping_fraction must be between 0 and 1.")

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in mapping_records:
        grouped[(str(record["accession"]), int(record["pocket_number"]))].append(
            record
        )

    quality_records: list[dict[str, Any]] = []
    for (accession, pocket_number), records in sorted(grouped.items()):
        mapped = [record for record in records if record["mapping_status"] == "MAPPED"]
        ambiguous = [
            record for record in records if record["mapping_status"] == "AMBIGUOUS"
        ]
        unmapped = [
            record for record in records if record["mapping_status"] == "UNMAPPED"
        ]
        values = [float(record["model_plddt"]) for record in mapped]
        predicted_count = len(records)
        mapped_count = len(mapped)
        ge_confident = sum(value >= confident_threshold for value in values)
        ge_very_high = sum(value >= very_high_threshold for value in values)
        mapping_fraction = (
            mapped_count / predicted_count if predicted_count else 0.0
        )
        mapped_fraction_ge_70 = (
            ge_confident / mapped_count if mapped_count else None
        )
        mapped_fraction_ge_90 = (
            ge_very_high / mapped_count if mapped_count else None
        )
        conservative_fraction_ge_70 = (
            ge_confident / predicted_count if predicted_count else None
        )
        conservative_fraction_ge_90 = (
            ge_very_high / predicted_count if predicted_count else None
        )
        quality_records.append(
            {
                "accession": accession,
                "pocket_number": pocket_number,
                "predicted_pocket_residue_count": predicted_count,
                "mapped_pocket_residue_count": mapped_count,
                "ambiguous_pocket_residue_count": len(ambiguous),
                "unmapped_pocket_residue_count": len(unmapped),
                "mapping_fraction": mapping_fraction,
                "mapping_qc_pass": (
                    mapping_fraction >= minimum_mapping_fraction
                    and not ambiguous
                ),
                "mapped_num_plddt_ge_70": ge_confident,
                "mapped_num_plddt_ge_90": ge_very_high,
                "mapped_fraction_plddt_ge_70": mapped_fraction_ge_70,
                "mapped_fraction_plddt_ge_90": mapped_fraction_ge_90,
                "conservative_fraction_plddt_ge_70": (
                    conservative_fraction_ge_70
                ),
                "conservative_fraction_plddt_ge_90": (
                    conservative_fraction_ge_90
                ),
                "mapped_mean_plddt": (
                    sum(values) / mapped_count if mapped_count else None
                ),
                "mapped_minimum_plddt": min(values) if values else None,
                "mapped_maximum_plddt": max(values) if values else None,
                "unmapped_residue_identifiers_json": json.dumps(
                    [_residue_identifier(record) for record in unmapped],
                    sort_keys=True,
                ),
                "ambiguous_residue_identifiers_json": json.dumps(
                    [_residue_identifier(record) for record in ambiguous],
                    sort_keys=True,
                ),
            }
        )
    return quality_records


def join_fpocket_and_p2rank(
    fpocket_records: list[dict[str, Any]],
    p2rank_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join P2Rank rescoring fields to FPocket pockets by original rank.

    Args:
        fpocket_records: Parsed FPocket pocket records.
        p2rank_records: Parsed P2Rank predictions.

    Returns:
        FPocket records with nested P2Rank provenance fields flattened.

    Raises:
        ValueError: If multiple P2Rank rows map to one FPocket pocket.
    """

    p2rank_index: dict[tuple[str, int], dict[str, Any]] = {}
    for record in p2rank_records:
        pocket_number = record.get("fpocket_pocket_number")
        if pocket_number is None:
            continue
        key = (str(record["accession"]), int(pocket_number))
        if key in p2rank_index:
            raise ValueError(f"Multiple P2Rank rows map to FPocket pocket {key}")
        p2rank_index[key] = record

    joined: list[dict[str, Any]] = []
    for fpocket_record in fpocket_records:
        key = (
            str(fpocket_record["accession"]),
            int(fpocket_record["pocket_number"]),
        )
        output = dict(fpocket_record)
        p2rank_record = p2rank_index.get(key)
        output["p2rank_match_status"] = (
            "MATCHED" if p2rank_record is not None else "UNMATCHED"
        )
        if p2rank_record is not None:
            for field, value in p2rank_record.items():
                if field == "accession":
                    continue
                output[f"p2rank_{field}"] = value
        joined.append(output)
    return joined
