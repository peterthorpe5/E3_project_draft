"""Explicit candidate-panel preparation and validation.

The chemistry workflow never interprets a numerical rank cut-off as human
approval.  This module creates a reviewable expanded-screen manifest or
validates a project-lead-approved manifest before any pharmacophore analysis.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from e3chemistry.errors import InputValidationError
from e3chemistry.io_utils import (
    read_records,
    require_columns,
    sha256_file,
    utc_now,
    write_json,
    write_records,
    write_tsv,
)
from e3chemistry.models import ChemistryConfig, StructureAsset
from e3chemistry.structures import resolve_structure_assets

CANDIDATE_MANIFEST_FIELDS = (
    "panel_order",
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "cluster_id",
    "candidate_accession",
    "species_column",
    "pocket_number",
    "structure_sha256",
    "decision_basis",
    "decided_by",
    "decided_at_utc",
    "rationale",
    "selection_mapping_fraction",
    "selection_pocket_plddt_fraction",
    "selection_druggability_score",
    "selection_mapped_residue_count",
    "eligible_pocket_count",
)

EXCLUSION_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "cluster_id",
    "exclusion_reason",
    "conflicting_candidate_pockets",
    "retained_evolutionary_group_keys",
)

POCKET_SELECTION_AUDIT_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "cluster_id",
    "candidate_accession",
    "species_column",
    "pocket_number",
    "selection_rank_within_group",
    "structure_available",
    "mapped_residue_count",
    "has_mapped_residues",
    "mapping_fraction",
    "pocket_plddt_fraction",
    "druggability_score",
    "passes_mapping_floor",
    "passes_plddt_floor",
    "selection_eligible",
    "target_already_assigned",
    "selected_for_manifest",
    "selection_status",
    "retained_evolutionary_group_key",
)

UNIVERSE_AUDIT_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "lead_cluster_id",
    "candidate_pocket_count",
    "eligible_pocket_count",
    "selected_for_manifest",
    "selected_candidate_accession",
    "selected_pocket_number",
    "assessment_status",
    "assessment_reason",
)

DECISION_BASES = frozenset(
    {"EXPANDED_COMPUTATIONAL_SCREEN", "PROJECT_LEAD_APPROVED"}
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CandidatePreparation:
    """Complete candidate-panel preparation result."""

    manifest: list[dict[str, Any]]
    exclusions: list[dict[str, Any]]
    pocket_audit: list[dict[str, Any]]
    universe_audit: list[dict[str, Any]]


def _text(value: Any) -> str:
    """Return stripped text for one possibly missing value."""
    return "" if value is None else str(value).strip()


def _integer(value: Any, label: str) -> int:
    """Parse a positive integer without accepting booleans or truncation."""
    try:
        result = int(_text(value))
    except (TypeError, ValueError) as exc:
        raise InputValidationError(f"{label} must be an integer: {value!r}") from exc
    if result < 1:
        raise InputValidationError(f"{label} must be a positive integer")
    return result


def _float(value: Any, *, default: float = 0.0) -> float:
    """Parse a finite floating-point value with a conservative default."""
    if value is None or _text(value) == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InputValidationError(f"Expected a numeric value: {value!r}") from exc
    if result != result or result in {float("inf"), float("-inf")}:
        raise InputValidationError(f"Expected a finite numeric value: {value!r}")
    return result


def _group_key(record: Mapping[str, Any]) -> tuple[str, str]:
    """Return the primary group type and identifier."""
    return (_text(record.get("primary_group_type")), _text(record.get("primary_group_id")))


def _target_key(record: Mapping[str, Any]) -> tuple[str, int]:
    """Return the normalised candidate accession and pocket identifier."""
    return (
        _text(record.get("candidate_accession")).upper(),
        _integer(record.get("pocket_number"), "pocket_number"),
    )


def _validate_utc(value: str, label: str) -> None:
    """Require a timezone-aware UTC ISO-8601 timestamp."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise InputValidationError(f"{label} must include the UTC timezone")


def validate_candidate_manifest(
    *,
    records: Sequence[Mapping[str, Any]],
    maximum_candidate_groups: int,
) -> list[dict[str, Any]]:
    """Validate and deterministically order an explicit candidate manifest.

    Args:
        records: Candidate-manifest rows.
        maximum_candidate_groups: Defensive configured panel-size limit.

    Returns:
        Normalised manifest rows ordered by ``panel_order``.

    Raises:
        InputValidationError: If required identity, provenance or uniqueness
            constraints are violated.
    """
    require_columns(
        records=records,
        required=CANDIDATE_MANIFEST_FIELDS[:14],
        label="candidate manifest",
    )
    if len(records) > maximum_candidate_groups:
        raise InputValidationError(
            "Candidate manifest contains "
            f"{len(records)} rows but maximum_candidate_groups is "
            f"{maximum_candidate_groups}"
        )
    normalised: list[dict[str, Any]] = []
    observed_orders: set[int] = set()
    observed_groups: set[str] = set()
    observed_targets: set[tuple[str, int]] = set()
    observed_bases: set[str] = set()
    for row_number, record in enumerate(records, start=2):
        panel_order = _integer(record.get("panel_order"), f"row {row_number} panel_order")
        rank = _integer(
            record.get("evolutionary_group_rank"),
            f"row {row_number} evolutionary_group_rank",
        )
        group_key = _text(record.get("evolutionary_group_key"))
        group_type = _text(record.get("primary_group_type"))
        group_id = _text(record.get("primary_group_id"))
        cluster_id = _text(record.get("cluster_id"))
        accession = _text(record.get("candidate_accession")).upper()
        species = _text(record.get("species_column"))
        pocket_number = _integer(
            record.get("pocket_number"), f"row {row_number} pocket_number"
        )
        structure_sha256 = _text(record.get("structure_sha256")).lower()
        basis = _text(record.get("decision_basis")).upper()
        decided_by = _text(record.get("decided_by"))
        decided_at = _text(record.get("decided_at_utc"))
        rationale = _text(record.get("rationale"))
        required_text = {
            "evolutionary_group_key": group_key,
            "primary_group_type": group_type,
            "primary_group_id": group_id,
            "cluster_id": cluster_id,
            "candidate_accession": accession,
            "species_column": species,
            "decided_by": decided_by,
            "decided_at_utc": decided_at,
            "rationale": rationale,
        }
        empty = [name for name, value in required_text.items() if not value]
        if empty:
            raise InputValidationError(
                f"Candidate manifest row {row_number} has empty fields: "
                + ", ".join(empty)
            )
        if basis not in DECISION_BASES:
            raise InputValidationError(
                f"Candidate manifest row {row_number} has unsupported decision_basis: "
                f"{basis!r}"
            )
        if not SHA256_PATTERN.fullmatch(structure_sha256):
            raise InputValidationError(
                f"Candidate manifest row {row_number} has an invalid structure_sha256"
            )
        _validate_utc(decided_at, f"candidate manifest row {row_number} decided_at_utc")
        target_key = (accession, pocket_number)
        if panel_order in observed_orders:
            raise InputValidationError(f"Duplicate candidate panel_order: {panel_order}")
        if group_key in observed_groups:
            raise InputValidationError(f"Duplicate candidate evolutionary group: {group_key}")
        if target_key in observed_targets:
            raise InputValidationError(
                f"Duplicate candidate accession/pocket: {accession}/{pocket_number}"
            )
        observed_orders.add(panel_order)
        observed_groups.add(group_key)
        observed_targets.add(target_key)
        observed_bases.add(basis)
        normalised.append(
            {
                **dict(record),
                "panel_order": panel_order,
                "evolutionary_group_rank": rank,
                "evolutionary_group_key": group_key,
                "primary_group_type": group_type,
                "primary_group_id": group_id,
                "cluster_id": cluster_id,
                "candidate_accession": accession,
                "species_column": species,
                "pocket_number": pocket_number,
                "structure_sha256": structure_sha256,
                "decision_basis": basis,
                "decided_by": decided_by,
                "decided_at_utc": decided_at,
                "rationale": rationale,
            }
        )
    expected_orders = set(range(1, len(normalised) + 1))
    if observed_orders != expected_orders:
        raise InputValidationError(
            "Candidate manifest panel_order values must be consecutive from 1"
        )
    if len(observed_bases) != 1:
        raise InputValidationError(
            "Candidate manifest must use one consistent decision_basis"
        )
    return sorted(normalised, key=lambda row: int(row["panel_order"]))


def _mapped_pocket_counts(
    mappings: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, int], int]:
    """Return mapped-residue counts for accession/pocket keys."""
    require_columns(
        records=mappings,
        required=("accession", "pocket_number", "mapping_status"),
        label="pocket residue mappings",
    )
    counts: dict[tuple[str, int], int] = defaultdict(int)
    for record in mappings:
        if _text(record.get("mapping_status")).upper() != "MAPPED":
            continue
        accession = _text(record.get("accession")).upper()
        if not accession:
            continue
        pocket_number = _integer(record.get("pocket_number"), "pocket_number")
        counts[(accession, pocket_number)] += 1
    return dict(counts)


def _quality_sort_key(
    record: Mapping[str, Any],
    *,
    mapped_residue_count: int,
) -> tuple[Any, ...]:
    """Return a ligandability-first key after eligibility floors pass."""
    mapping = _float(record.get("mapping_fraction"))
    confidence = _float(record.get("conservative_fraction_plddt_ge_70"))
    druggability = _float(record.get("druggability_score"))
    return (
        -druggability,
        -confidence,
        -mapping,
        -mapped_residue_count,
        _text(record.get("candidate_accession")).upper(),
        _integer(record.get("pocket_number"), "pocket_number"),
        _text(record.get("cluster_id")),
    )


def _candidate_preparation(
    *,
    config: ChemistryConfig,
    group_ranking: Sequence[Mapping[str, Any]],
    selected_pockets: Sequence[Mapping[str, Any]],
    mappings: Sequence[Mapping[str, Any]],
    assets: Mapping[str, StructureAsset],
    maximum_rank: int | None,
    decision_basis: str,
    decided_by: str,
    rationale: str,
    decided_at_utc: str | None = None,
) -> CandidatePreparation:
    """Prepare a full panel, exclusion log and pocket/universe audits."""
    if maximum_rank is not None and maximum_rank < 1:
        raise InputValidationError("maximum_rank must be a positive integer or null")
    basis = decision_basis.strip().upper()
    if basis not in DECISION_BASES:
        raise InputValidationError(f"Unsupported decision_basis: {basis!r}")
    decided_by = decided_by.strip()
    rationale = rationale.strip()
    if not decided_by or not rationale:
        raise InputValidationError("decided_by and rationale must not be empty")
    timestamp = decided_at_utc or utc_now()
    _validate_utc(timestamp, "decided_at_utc")
    require_columns(
        records=group_ranking,
        required=(
            "evolutionary_group_rank",
            "evolutionary_group_key",
            "primary_group_type",
            "primary_group_id",
            "lead_cluster_id",
        ),
        label="evolutionary-group ranking",
    )
    require_columns(
        records=selected_pockets,
        required=(
            "primary_group_type",
            "primary_group_id",
            "cluster_id",
            "candidate_accession",
            "species_column",
            "pocket_number",
        ),
        label="selected pockets",
    )
    mapped_counts = _mapped_pocket_counts(mappings)
    pockets_by_group: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for pocket in selected_pockets:
        pockets_by_group[_group_key(pocket)].append(pocket)
    ranked_groups = sorted(
        (
            row
            for row in group_ranking
            if maximum_rank is None
            or _integer(row.get("evolutionary_group_rank"), "evolutionary_group_rank")
            <= maximum_rank
        ),
        key=lambda row: (
            _integer(row.get("evolutionary_group_rank"), "evolutionary_group_rank"),
            _text(row.get("evolutionary_group_key")),
        ),
    )
    if len(ranked_groups) > config.maximum_candidate_groups:
        raise InputValidationError(
            "Ranked candidate universe contains "
            f"{len(ranked_groups)} groups but maximum_candidate_groups is "
            f"{config.maximum_candidate_groups}"
        )
    manifest: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    pocket_audit: list[dict[str, Any]] = []
    universe_audit: list[dict[str, Any]] = []
    assigned_targets: dict[tuple[str, int], str] = {}
    for group in ranked_groups:
        key = _group_key(group)
        group_key = _text(group.get("evolutionary_group_key"))
        candidates: list[dict[str, Any]] = []
        for pocket in pockets_by_group.get(key, []):
            accession = _text(pocket.get("candidate_accession")).upper()
            pocket_number = _integer(pocket.get("pocket_number"), "pocket_number")
            target_key = (accession, pocket_number)
            mapped_count = mapped_counts.get(target_key, 0)
            mapping = _float(pocket.get("mapping_fraction"))
            confidence = _float(
                pocket.get("conservative_fraction_plddt_ge_70")
            )
            candidate = {
                "record": pocket,
                "accession": accession,
                "pocket_number": pocket_number,
                "target_key": target_key,
                "mapped_count": mapped_count,
                "structure_available": accession in assets,
                "passes_mapping": mapping >= config.minimum_mapping_fraction,
                "passes_plddt": (
                    confidence >= config.minimum_pocket_plddt_fraction
                ),
            }
            candidate["eligible"] = bool(
                candidate["structure_available"]
                and mapped_count > 0
                and candidate["passes_mapping"]
                and candidate["passes_plddt"]
            )
            candidates.append(candidate)
        eligible = [candidate for candidate in candidates if candidate["eligible"]]
        eligible.sort(
            key=lambda candidate: _quality_sort_key(
                candidate["record"],
                mapped_residue_count=int(candidate["mapped_count"]),
            )
        )
        available = [
            candidate
            for candidate in eligible
            if candidate["target_key"] not in assigned_targets
        ]
        selected = available[0] if available else None
        if selected is None:
            if not candidates:
                exclusion_reason = "NO_POCKET_EVIDENCE_IN_SOURCE_RUN"
            elif not eligible:
                exclusion_reason = "NO_POCKET_PASSING_MAPPING_AND_PLDDT_FLOORS"
            else:
                exclusion_reason = "ALL_ELIGIBLE_CANDIDATE_POCKETS_ALREADY_ASSIGNED"
            conflicting_targets = sorted(
                candidate["target_key"]
                for candidate in eligible
                if candidate["target_key"] in assigned_targets
            )
            exclusions.append(
                {
                    "evolutionary_group_rank": group["evolutionary_group_rank"],
                    "evolutionary_group_key": group["evolutionary_group_key"],
                    "primary_group_type": key[0],
                    "primary_group_id": key[1],
                    "cluster_id": group["lead_cluster_id"],
                    "exclusion_reason": exclusion_reason,
                    "conflicting_candidate_pockets": ";".join(
                        f"{accession}/{pocket_number}"
                        for accession, pocket_number in conflicting_targets
                    ),
                    "retained_evolutionary_group_keys": ";".join(
                        sorted(
                            {
                                assigned_targets[target]
                                for target in conflicting_targets
                            }
                        )
                    ),
                }
            )
        else:
            pocket = selected["record"]
            accession = str(selected["accession"])
            target_key = selected["target_key"]
            assigned_targets[target_key] = group_key
            manifest.append(
                {
                    "panel_order": len(manifest) + 1,
                    "evolutionary_group_rank": group["evolutionary_group_rank"],
                    "evolutionary_group_key": group["evolutionary_group_key"],
                    "primary_group_type": key[0],
                    "primary_group_id": key[1],
                    "cluster_id": _text(pocket.get("cluster_id")),
                    "candidate_accession": accession,
                    "species_column": _text(pocket.get("species_column")),
                    "pocket_number": selected["pocket_number"],
                    "structure_sha256": assets[accession].sha256,
                    "decision_basis": basis,
                    "decided_by": decided_by,
                    "decided_at_utc": timestamp,
                    "rationale": rationale,
                    "selection_mapping_fraction": _float(
                        pocket.get("mapping_fraction")
                    ),
                    "selection_pocket_plddt_fraction": _float(
                        pocket.get("conservative_fraction_plddt_ge_70")
                    ),
                    "selection_druggability_score": _float(
                        pocket.get("druggability_score")
                    ),
                    "selection_mapped_residue_count": selected["mapped_count"],
                    "eligible_pocket_count": len(eligible),
                }
            )
        selection_ranks = {
            id(candidate): rank
            for rank, candidate in enumerate(eligible, start=1)
        }
        for candidate in candidates:
            pocket = candidate["record"]
            target_key = candidate["target_key"]
            was_selected = candidate is selected
            retained_group = assigned_targets.get(target_key, "")
            if was_selected:
                status = "SELECTED_MOST_DRUGGABLE_ELIGIBLE_POCKET"
            elif not candidate["structure_available"]:
                status = "STRUCTURE_UNAVAILABLE"
            elif int(candidate["mapped_count"]) == 0:
                status = "NO_MAPPED_RESIDUES"
            elif not candidate["passes_mapping"]:
                status = "BELOW_MAPPING_FLOOR"
            elif not candidate["passes_plddt"]:
                status = "BELOW_PLDDT_FLOOR"
            elif target_key in assigned_targets:
                status = "ELIGIBLE_TARGET_ASSIGNED_TO_EARLIER_GROUP"
            else:
                status = "ELIGIBLE_NOT_SELECTED_LOWER_DRUGGABILITY"
            pocket_audit.append(
                {
                    "evolutionary_group_rank": group["evolutionary_group_rank"],
                    "evolutionary_group_key": group["evolutionary_group_key"],
                    "primary_group_type": key[0],
                    "primary_group_id": key[1],
                    "cluster_id": _text(pocket.get("cluster_id")),
                    "candidate_accession": candidate["accession"],
                    "species_column": _text(pocket.get("species_column")),
                    "pocket_number": candidate["pocket_number"],
                    "selection_rank_within_group": selection_ranks.get(
                        id(candidate), ""
                    ),
                    "structure_available": candidate["structure_available"],
                    "mapped_residue_count": candidate["mapped_count"],
                    "has_mapped_residues": int(candidate["mapped_count"]) > 0,
                    "mapping_fraction": _float(pocket.get("mapping_fraction")),
                    "pocket_plddt_fraction": _float(
                        pocket.get("conservative_fraction_plddt_ge_70")
                    ),
                    "druggability_score": _float(
                        pocket.get("druggability_score")
                    ),
                    "passes_mapping_floor": candidate["passes_mapping"],
                    "passes_plddt_floor": candidate["passes_plddt"],
                    "selection_eligible": candidate["eligible"],
                    "target_already_assigned": (
                        bool(retained_group) and not was_selected
                    ),
                    "selected_for_manifest": was_selected,
                    "selection_status": status,
                    "retained_evolutionary_group_key": retained_group,
                }
            )
        universe_audit.append(
            {
                "evolutionary_group_rank": group["evolutionary_group_rank"],
                "evolutionary_group_key": group["evolutionary_group_key"],
                "primary_group_type": key[0],
                "primary_group_id": key[1],
                "lead_cluster_id": group["lead_cluster_id"],
                "candidate_pocket_count": len(candidates),
                "eligible_pocket_count": len(eligible),
                "selected_for_manifest": selected is not None,
                "selected_candidate_accession": (
                    selected["accession"] if selected is not None else ""
                ),
                "selected_pocket_number": (
                    selected["pocket_number"] if selected is not None else ""
                ),
                "assessment_status": (
                    "INCLUDED" if selected is not None else "NOT_INCLUDED"
                ),
                "assessment_reason": (
                    "MOST_DRUGGABLE_POCKET_AFTER_MAPPING_AND_PLDDT_FLOORS"
                    if selected is not None
                    else exclusion_reason
                ),
            }
        )
    validated = validate_candidate_manifest(
        records=manifest,
        maximum_candidate_groups=config.maximum_candidate_groups,
    )
    return CandidatePreparation(
        manifest=validated,
        exclusions=exclusions,
        pocket_audit=pocket_audit,
        universe_audit=universe_audit,
    )


def prepare_candidate_manifest(
    *,
    config: ChemistryConfig,
    group_ranking: Sequence[Mapping[str, Any]],
    selected_pockets: Sequence[Mapping[str, Any]],
    mappings: Sequence[Mapping[str, Any]],
    assets: Mapping[str, StructureAsset],
    maximum_rank: int | None,
    decision_basis: str,
    decided_by: str,
    rationale: str,
    decided_at_utc: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Prepare a panel while retaining the established two-value API."""
    result = _candidate_preparation(
        config=config,
        group_ranking=group_ranking,
        selected_pockets=selected_pockets,
        mappings=mappings,
        assets=assets,
        maximum_rank=maximum_rank,
        decision_basis=decision_basis,
        decided_by=decided_by,
        rationale=rationale,
        decided_at_utc=decided_at_utc,
    )
    return result.manifest, result.exclusions


def prepare_candidate_manifest_files(
    *,
    config: ChemistryConfig,
    group_ranking_path: Path,
    selected_pockets_path: Path,
    pocket_residue_mappings_path: Path,
    structure_asset_manifest_path: Path,
    ranked_pockets_path: Path | None = None,
    output_dir: Path,
    maximum_rank: int | None,
    decision_basis: str,
    decided_by: str,
    rationale: str,
) -> dict[str, Any]:
    """Prepare candidate-panel files from controlled Stage 08/09 authorities."""
    destination = output_dir.expanduser().resolve()
    if destination.is_file():
        raise InputValidationError(
            f"Candidate-manifest output directory is a file: {destination}"
        )
    if destination.exists() and any(destination.iterdir()):
        raise InputValidationError(
            f"Candidate-manifest output directory is not empty: {destination}"
        )
    destination.mkdir(parents=True, exist_ok=True)
    input_paths = {
        "group_ranking": group_ranking_path.expanduser().resolve(),
        "selected_pockets": selected_pockets_path.expanduser().resolve(),
        "pocket_residue_mappings": pocket_residue_mappings_path.expanduser().resolve(),
        "structure_asset_manifest": structure_asset_manifest_path.expanduser().resolve(),
    }
    if ranked_pockets_path is not None:
        input_paths["ranked_pockets"] = ranked_pockets_path.expanduser().resolve()
    for label, path in input_paths.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise InputValidationError(f"{label} input is missing or empty: {path}")
    assets = resolve_structure_assets(read_records(input_paths["structure_asset_manifest"]))
    group_ranking = read_records(input_paths["group_ranking"])
    selected_pockets = read_records(input_paths["selected_pockets"])
    mappings = read_records(input_paths["pocket_residue_mappings"])
    preparation = _candidate_preparation(
        config=config,
        group_ranking=group_ranking,
        selected_pockets=selected_pockets,
        mappings=mappings,
        assets=assets,
        maximum_rank=maximum_rank,
        decision_basis=decision_basis,
        decided_by=decided_by,
        rationale=rationale,
    )
    manifest = preparation.manifest
    exclusions = preparation.exclusions
    manifest_path = destination / "candidate_manifest.tsv"
    exclusions_path = destination / "candidate_manifest_exclusions.tsv"
    write_tsv(
        path=manifest_path,
        records=manifest,
        fieldnames=CANDIDATE_MANIFEST_FIELDS,
    )
    write_tsv(
        path=exclusions_path,
        records=exclusions,
        fieldnames=EXCLUSION_FIELDS,
    )
    write_records(
        tsv_path=destination / "candidate_pocket_selection_audit.tsv",
        parquet_path=destination / "candidate_pocket_selection_audit.parquet",
        records=preparation.pocket_audit,
        fieldnames=POCKET_SELECTION_AUDIT_FIELDS,
    )
    write_records(
        tsv_path=destination / "candidate_universe_audit.tsv",
        parquet_path=destination / "candidate_universe_audit.parquet",
        records=preparation.universe_audit,
        fieldnames=UNIVERSE_AUDIT_FIELDS,
    )
    ranked_audit_paths: dict[str, str] = {}
    if "ranked_pockets" in input_paths:
        ranked_records = read_records(input_paths["ranked_pockets"])
        ranked_fields = sorted(
            {str(field) for record in ranked_records for field in record}
        )
        ranked_tsv = destination / "ranked_member_pocket_evidence.tsv"
        ranked_parquet = destination / "ranked_member_pocket_evidence.parquet"
        write_records(
            tsv_path=ranked_tsv,
            parquet_path=ranked_parquet,
            records=ranked_records,
            fieldnames=ranked_fields,
        )
        ranked_audit_paths = {
            "tsv": str(ranked_tsv),
            "parquet": str(ranked_parquet),
        }
    provenance = {
        "schema_version": 3,
        "created_at_utc": utc_now(),
        "decision_basis": manifest[0]["decision_basis"],
        "maximum_rank": maximum_rank,
        "all_ranked_groups_requested": maximum_rank is None,
        "included_group_count": len(manifest),
        "excluded_group_count": len(exclusions),
        "candidate_universe_group_count": len(preparation.universe_audit),
        "pocket_selection_audit_row_count": len(preparation.pocket_audit),
        "inputs": {
            label: {"path": str(path), "sha256": sha256_file(path)}
            for label, path in sorted(input_paths.items())
        },
        "candidate_manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
        },
        "exclusion_audit": {
            "path": str(exclusions_path),
            "sha256": sha256_file(exclusions_path),
        },
        "selection_policy": {
            "eligibility_floors": {
                "minimum_mapping_fraction": config.minimum_mapping_fraction,
                "minimum_pocket_plddt_fraction": (
                    config.minimum_pocket_plddt_fraction
                ),
                "requires_checksum_bound_structure": True,
                "requires_at_least_one_mapped_residue": True,
            },
            "eligible_pocket_order": (
                "druggability descending; pocket pLDDT descending; mapping "
                "descending; mapped-residue count descending; stable identifiers"
            ),
        },
        "ranked_member_pocket_evidence": ranked_audit_paths,
    }
    provenance_path = destination / "candidate_manifest_provenance.json"
    write_json(path=provenance_path, payload=provenance)
    return {
        "status": "complete",
        "output_dir": str(destination),
        "candidate_manifest": str(manifest_path),
        "included_group_count": len(manifest),
        "excluded_group_count": len(exclusions),
        "candidate_universe_group_count": len(preparation.universe_audit),
        "pocket_selection_audit_row_count": len(preparation.pocket_audit),
        "provenance": str(provenance_path),
    }
