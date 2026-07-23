"""Atomic structural-alignment and three-dimensional pocket workflow."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import statistics
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from e3structalign import __version__
from e3structalign.errors import InputValidationError, StructuralAlignmentError
from e3structalign.io_utils import (
    atomic_write_json,
    close_logger,
    configure_logging,
    output_inventory,
    read_records,
    require_columns,
    resolve_input_file,
    safe_filename,
    sha256_file,
    utc_now,
    write_table,
    write_tsv,
)
from e3structalign.models import (
    ResidueLocator,
    SelectedPocket,
    StructureAsset,
)
from e3structalign.structure_io import (
    parse_ca_atoms,
    pocket_coordinates,
    pocket_geometry,
    transform_coordinates,
)
from e3structalign.usalign import run_usalign, tool_version

LOGGER = logging.getLogger("e3structalign")

ALIGNMENT_SCHEMA = (
    ("cluster_id", "VARCHAR"),
    ("primary_group_type", "VARCHAR"),
    ("primary_group_id", "VARCHAR"),
    ("reference_accession", "VARCHAR"),
    ("mobile_accession", "VARCHAR"),
    ("reference_species", "VARCHAR"),
    ("mobile_species", "VARCHAR"),
    ("reference_model_path", "VARCHAR"),
    ("mobile_model_path", "VARCHAR"),
    ("reference_model_sha256", "VARCHAR"),
    ("mobile_model_sha256", "VARCHAR"),
    ("alignment_tool", "VARCHAR"),
    ("status", "VARCHAR"),
    ("tool_version", "VARCHAR"),
    ("aligned_length", "BIGINT"),
    ("rmsd_angstrom", "DOUBLE"),
    ("sequence_identity", "DOUBLE"),
    ("tm_score_mobile_normalised", "DOUBLE"),
    ("tm_score_reference_normalised", "DOUBLE"),
    ("minimum_tm_score", "DOUBLE"),
    ("matrix_relative_path", "VARCHAR"),
    ("stdout_relative_path", "VARCHAR"),
)

POCKET_COMPARISON_SCHEMA = (
    ("cluster_id", "VARCHAR"),
    ("primary_group_type", "VARCHAR"),
    ("primary_group_id", "VARCHAR"),
    ("reference_accession", "VARCHAR"),
    ("mobile_accession", "VARCHAR"),
    ("reference_species", "VARCHAR"),
    ("mobile_species", "VARCHAR"),
    ("alignment_tool", "VARCHAR"),
    ("reference_pocket_number", "BIGINT"),
    ("mobile_pocket_number", "BIGINT"),
    ("reference_pocket_ca_count", "BIGINT"),
    ("mobile_pocket_ca_count", "BIGINT"),
    ("distance_threshold_angstrom", "DOUBLE"),
    ("centroid_distance_angstrom", "DOUBLE"),
    ("reference_fraction_within_threshold", "DOUBLE"),
    ("mobile_fraction_within_threshold", "DOUBLE"),
    ("symmetric_overlap_fraction", "DOUBLE"),
    ("mean_bidirectional_nearest_distance_angstrom", "DOUBLE"),
    ("minimum_tm_score", "DOUBLE"),
    ("global_tm_pass", "BOOLEAN"),
    ("pocket_centroid_pass", "BOOLEAN"),
    ("pocket_overlap_pass", "BOOLEAN"),
    ("same_pocket_supported", "BOOLEAN"),
    ("three_dimensional_pocket_score", "DOUBLE"),
    ("status", "VARCHAR"),
    ("reason", "VARCHAR"),
)

GROUP_SUMMARY_SCHEMA = (
    ("cluster_id", "VARCHAR"),
    ("primary_group_type", "VARCHAR"),
    ("primary_group_id", "VARCHAR"),
    ("reference_accession", "VARCHAR"),
    ("alignment_tools", "VARCHAR"),
    ("alignment_tool_count", "BIGINT"),
    ("selected_accession_count", "BIGINT"),
    ("model_available_accession_count", "BIGINT"),
    ("aligned_accession_count", "BIGINT"),
    ("supported_accession_count", "BIGINT"),
    ("aligned_species_count", "BIGINT"),
    ("supported_species_count", "BIGINT"),
    ("group_support_fraction", "DOUBLE"),
    ("pairwise_tool_agreement_fraction", "DOUBLE"),
    ("mean_minimum_tm_score", "DOUBLE"),
    ("mean_pocket_overlap_fraction", "DOUBLE"),
    ("median_centroid_distance_angstrom", "DOUBLE"),
    ("three_dimensional_pocket_score", "DOUBLE"),
    ("alignment_status", "VARCHAR"),
    ("supported_accessions", "VARCHAR"),
    ("supported_species", "VARCHAR"),
    ("interpretation", "VARCHAR"),
)


@dataclass(frozen=True)
class AlignmentSettings:
    """Validated runtime thresholds and executable settings."""

    usalign_executable: str = "USalign"
    tmalign_executable: str = "TMalign"
    run_usalign: bool = True
    run_tmalign: bool = True
    threads: int = 4
    distance_threshold_angstrom: float = 4.0
    maximum_centroid_distance_angstrom: float = 8.0
    minimum_pocket_overlap_fraction: float = 0.5
    minimum_global_tm_score: float = 0.5
    minimum_group_support_fraction: float = 0.75

    def validate(self) -> None:
        """Validate all settings before any output is created."""
        if not self.run_usalign and not self.run_tmalign:
            raise InputValidationError("At least one structural aligner must be enabled")
        if self.run_usalign and not self.usalign_executable.strip():
            raise InputValidationError("US-align executable must be non-empty")
        if self.run_tmalign and not self.tmalign_executable.strip():
            raise InputValidationError("TM-align executable must be non-empty")
        if self.threads < 1:
            raise InputValidationError("threads must be a positive integer")
        for label, value in (
            ("distance_threshold_angstrom", self.distance_threshold_angstrom),
            (
                "maximum_centroid_distance_angstrom",
                self.maximum_centroid_distance_angstrom,
            ),
        ):
            if value <= 0:
                raise InputValidationError(f"{label} must be greater than zero")
        for label, value in (
            ("minimum_pocket_overlap_fraction", self.minimum_pocket_overlap_fraction),
            ("minimum_global_tm_score", self.minimum_global_tm_score),
            ("minimum_group_support_fraction", self.minimum_group_support_fraction),
        ):
            if not 0.0 <= value <= 1.0:
                raise InputValidationError(f"{label} must be between zero and one")


def _text(value: Any) -> str:
    """Return a stripped string for a nullable table value."""
    return "" if value is None else str(value).strip()


def _optional_float(value: Any) -> float | None:
    """Return a finite-looking float or ``None`` for an empty table value."""
    text = _text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise InputValidationError(f"Expected numeric value, observed {value!r}") from exc


def _integer(value: Any, label: str) -> int:
    """Return an integer table value with field-specific context."""
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise InputValidationError(f"{label} must be an integer: {value!r}") from exc


def _boolean(value: Any) -> bool:
    """Parse common Boolean representations from TSV or Parquet."""
    if isinstance(value, bool):
        return value
    normalised = _text(value).lower()
    if normalised in {"true", "1", "yes"}:
        return True
    if normalised in {"false", "0", "no", ""}:
        return False
    raise InputValidationError(f"Expected Boolean value, observed {value!r}")


def parse_selected_pockets(records: Sequence[Mapping[str, Any]]) -> list[SelectedPocket]:
    """Validate and normalise selected-pocket records."""
    require_columns(
        records,
        (
            "cluster_id",
            "primary_group_type",
            "primary_group_id",
            "candidate_accession",
            "species_column",
            "pocket_number",
        ),
        "selected pockets",
    )
    parsed: list[SelectedPocket] = []
    seen: set[tuple[str, str]] = set()
    for row_number, record in enumerate(records, start=2):
        cluster_id = _text(record.get("cluster_id"))
        group_id = _text(record.get("primary_group_id"))
        accession = _text(record.get("candidate_accession"))
        if not cluster_id or not group_id or not accession:
            raise InputValidationError(
                f"Selected-pocket row {row_number} has an empty group or accession identifier"
            )
        key = (cluster_id, accession)
        if key in seen:
            raise InputValidationError(
                f"Duplicate selected pocket for cluster/accession: {cluster_id}/{accession}"
            )
        seen.add(key)
        parsed.append(
            SelectedPocket(
                cluster_id=cluster_id,
                primary_group_type=_text(record.get("primary_group_type")),
                primary_group_id=group_id,
                accession=accession,
                species=_text(record.get("species_column")),
                pocket_number=_integer(record.get("pocket_number"), "pocket_number"),
                druggability_score=_optional_float(record.get("druggability_score")),
                mapping_fraction=_optional_float(record.get("mapping_fraction")),
                pocket_plddt_fraction=_optional_float(
                    record.get("conservative_fraction_plddt_ge_70")
                ),
                predictor_agreement=_boolean(record.get("predictor_agreement")),
                structural_evidence_status=_text(
                    record.get("structural_evidence_status")
                ),
            )
        )
    return parsed


def resolve_structure_assets(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, StructureAsset]:
    """Resolve one existing, checksum-validated model per accession."""
    require_columns(records, ("accession",), "structure asset manifest")
    candidates: dict[str, list[tuple[int, Path, str]]] = {}
    path_fields = ("path", "model_path", "source_path")
    for record in records:
        accession = _text(record.get("accession"))
        if not accession:
            continue
        for field_priority, field in enumerate(path_fields):
            raw_path = _text(record.get(field))
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = path.resolve()
            else:
                path = path.resolve()
            if path.suffix.lower() not in {".pdb", ".cif", ".mmcif"} or not path.is_file():
                continue
            expected_sha256 = _text(record.get("sha256")).lower()
            observed_sha256 = sha256_file(path)
            if expected_sha256 and expected_sha256 != observed_sha256:
                raise InputValidationError(
                    f"Structure checksum mismatch for {accession}: {path}"
                )
            candidates.setdefault(accession, []).append(
                (field_priority, path, observed_sha256)
            )
    assets: dict[str, StructureAsset] = {}
    for accession, options in candidates.items():
        unique = sorted(set(options), key=lambda item: (item[0], str(item[1])))
        chosen = unique[0]
        assets[accession] = StructureAsset(
            accession=accession,
            path=chosen[1],
            sha256=chosen[2],
        )
    return assets


def parse_pocket_locators(
    records: Sequence[Mapping[str, Any]],
    selected: Sequence[SelectedPocket],
) -> dict[str, tuple[ResidueLocator, ...]]:
    """Return mapped residue locators for each accession's selected pocket."""
    require_columns(
        records,
        ("accession", "pocket_number", "mapping_status"),
        "pocket residue mappings",
    )
    selected_numbers = {
        pocket.accession: pocket.pocket_number for pocket in selected
    }
    locators: dict[str, list[ResidueLocator]] = {}
    for record in records:
        accession = _text(record.get("accession"))
        if accession not in selected_numbers:
            continue
        if _integer(record.get("pocket_number"), "pocket_number") != selected_numbers[accession]:
            continue
        if _text(record.get("mapping_status")).upper() != "MAPPED":
            continue
        locator = ResidueLocator(
            label_chain=_text(
                record.get("model_label_chain") or record.get("label_chain")
            ),
            label_seq_id=_text(
                record.get("model_label_seq_id") or record.get("label_seq_id")
            ),
            auth_chain=_text(
                record.get("model_auth_chain") or record.get("auth_chain")
            ),
            auth_seq_id=_text(
                record.get("model_auth_seq_id") or record.get("auth_seq_id")
            ),
            insertion_code=_text(
                record.get("model_insertion_code") or record.get("insertion_code")
            ),
        )
        if not locator.label_seq_id and not locator.auth_seq_id:
            continue
        if locator not in locators.setdefault(accession, []):
            locators[accession].append(locator)
    return {
        accession: tuple(accession_locators)
        for accession, accession_locators in locators.items()
    }


def _reference_sort_key(pocket: SelectedPocket) -> tuple[Any, ...]:
    """Return a deterministic best-evidence-first reference sort key."""
    return (
        not pocket.structural_evidence_status.startswith("SELECTED_HIGH_CONFIDENCE"),
        not pocket.predictor_agreement,
        -(pocket.mapping_fraction if pocket.mapping_fraction is not None else -1.0),
        -(pocket.pocket_plddt_fraction if pocket.pocket_plddt_fraction is not None else -1.0),
        -(pocket.druggability_score if pocket.druggability_score is not None else -1.0),
        pocket.accession,
    )


def _three_dimensional_score(
    *,
    minimum_tm_score: float,
    overlap_fraction: float,
    centroid_distance_angstrom: float,
    maximum_centroid_distance_angstrom: float,
) -> float:
    """Return a bounded transparent score for one superposed pocket pair."""
    global_component = max(0.0, min(1.0, minimum_tm_score))
    overlap_component = max(0.0, min(1.0, overlap_fraction))
    centroid_component = max(
        0.0,
        1.0
        - min(
            centroid_distance_angstrom / maximum_centroid_distance_angstrom,
            1.0,
        ),
    )
    return (
        0.40 * global_component
        + 0.40 * overlap_component
        + 0.20 * centroid_component
    )


def _reference_rows(
    *,
    pocket: SelectedPocket,
    asset: StructureAsset,
    coordinate_count: int,
    alignment_tool: str,
    version: str,
    settings: AlignmentSettings,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return explicit self-reference alignment and pocket records."""
    alignment = {
        "cluster_id": pocket.cluster_id,
        "primary_group_type": pocket.primary_group_type,
        "primary_group_id": pocket.primary_group_id,
        "reference_accession": pocket.accession,
        "mobile_accession": pocket.accession,
        "reference_species": pocket.species,
        "mobile_species": pocket.species,
        "reference_model_path": str(asset.path),
        "mobile_model_path": str(asset.path),
        "reference_model_sha256": asset.sha256,
        "mobile_model_sha256": asset.sha256,
        "alignment_tool": alignment_tool,
        "status": "REFERENCE",
        "tool_version": version,
        "aligned_length": None,
        "rmsd_angstrom": 0.0,
        "sequence_identity": 1.0,
        "tm_score_mobile_normalised": 1.0,
        "tm_score_reference_normalised": 1.0,
        "minimum_tm_score": 1.0,
        "matrix_relative_path": "",
        "stdout_relative_path": "",
    }
    comparison = {
        "cluster_id": pocket.cluster_id,
        "primary_group_type": pocket.primary_group_type,
        "primary_group_id": pocket.primary_group_id,
        "reference_accession": pocket.accession,
        "mobile_accession": pocket.accession,
        "reference_species": pocket.species,
        "mobile_species": pocket.species,
        "alignment_tool": alignment_tool,
        "reference_pocket_number": pocket.pocket_number,
        "mobile_pocket_number": pocket.pocket_number,
        "reference_pocket_ca_count": coordinate_count,
        "mobile_pocket_ca_count": coordinate_count,
        "distance_threshold_angstrom": settings.distance_threshold_angstrom,
        "centroid_distance_angstrom": 0.0,
        "reference_fraction_within_threshold": 1.0,
        "mobile_fraction_within_threshold": 1.0,
        "symmetric_overlap_fraction": 1.0,
        "mean_bidirectional_nearest_distance_angstrom": 0.0,
        "minimum_tm_score": 1.0,
        "global_tm_pass": True,
        "pocket_centroid_pass": True,
        "pocket_overlap_pass": True,
        "same_pocket_supported": True,
        "three_dimensional_pocket_score": 1.0,
        "status": "REFERENCE_POCKET",
        "reason": "reference pocket defines the comparison coordinate frame",
    }
    return alignment, comparison


def _align_pair(
    *,
    reference: SelectedPocket,
    mobile: SelectedPocket,
    assets: Mapping[str, StructureAsset],
    coordinates: Mapping[str, Sequence[tuple[float, float, float]]],
    raw_root: Path,
    output_root: Path,
    alignment_tool: str,
    executable: str,
    version: str,
    settings: AlignmentSettings,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one mobile-to-reference superposition and pocket comparison."""
    reference_asset = assets[reference.accession]
    mobile_asset = assets[mobile.accession]
    group_slug = safe_filename(
        f"{reference.cluster_id}__{reference.primary_group_id}"
    )
    pair_slug = safe_filename(f"{reference.accession}__{mobile.accession}")
    tool_slug = safe_filename(alignment_tool.lower())
    pair_root = raw_root / tool_slug / group_slug
    matrix_path = pair_root / f"{pair_slug}.matrix.txt"
    stdout_path = pair_root / f"{pair_slug}.stdout.txt"
    result = run_usalign(
        executable=executable,
        mobile_path=mobile_asset.path,
        reference_path=reference_asset.path,
        matrix_path=matrix_path,
        stdout_path=stdout_path,
        version=version,
        tool_name=alignment_tool,
    )
    minimum_tm_score = min(
        result.tm_score_mobile_normalised,
        result.tm_score_reference_normalised,
    )
    transformed_mobile = transform_coordinates(
        coordinates=coordinates[mobile.accession],
        transform=result.transform,
    )
    geometry = pocket_geometry(
        reference_coordinates=coordinates[reference.accession],
        transformed_mobile_coordinates=transformed_mobile,
        distance_threshold_angstrom=settings.distance_threshold_angstrom,
    )
    global_tm_pass = minimum_tm_score >= settings.minimum_global_tm_score
    centroid_pass = (
        geometry["centroid_distance_angstrom"]
        <= settings.maximum_centroid_distance_angstrom
    )
    overlap_pass = (
        geometry["symmetric_overlap_fraction"]
        >= settings.minimum_pocket_overlap_fraction
    )
    supported = global_tm_pass and centroid_pass and overlap_pass
    score = _three_dimensional_score(
        minimum_tm_score=minimum_tm_score,
        overlap_fraction=geometry["symmetric_overlap_fraction"],
        centroid_distance_angstrom=geometry["centroid_distance_angstrom"],
        maximum_centroid_distance_angstrom=settings.maximum_centroid_distance_angstrom,
    )
    alignment = {
        "cluster_id": reference.cluster_id,
        "primary_group_type": reference.primary_group_type,
        "primary_group_id": reference.primary_group_id,
        "reference_accession": reference.accession,
        "mobile_accession": mobile.accession,
        "reference_species": reference.species,
        "mobile_species": mobile.species,
        "reference_model_path": str(reference_asset.path),
        "mobile_model_path": str(mobile_asset.path),
        "reference_model_sha256": reference_asset.sha256,
        "mobile_model_sha256": mobile_asset.sha256,
        "alignment_tool": alignment_tool,
        "status": "COMPLETE",
        "tool_version": result.version,
        "aligned_length": result.aligned_length,
        "rmsd_angstrom": result.rmsd_angstrom,
        "sequence_identity": result.sequence_identity,
        "tm_score_mobile_normalised": result.tm_score_mobile_normalised,
        "tm_score_reference_normalised": result.tm_score_reference_normalised,
        "minimum_tm_score": minimum_tm_score,
        "matrix_relative_path": str(matrix_path.relative_to(output_root)),
        "stdout_relative_path": str(stdout_path.relative_to(output_root)),
    }
    comparison = {
        "cluster_id": reference.cluster_id,
        "primary_group_type": reference.primary_group_type,
        "primary_group_id": reference.primary_group_id,
        "reference_accession": reference.accession,
        "mobile_accession": mobile.accession,
        "reference_species": reference.species,
        "mobile_species": mobile.species,
        "alignment_tool": alignment_tool,
        "reference_pocket_number": reference.pocket_number,
        "mobile_pocket_number": mobile.pocket_number,
        "reference_pocket_ca_count": len(coordinates[reference.accession]),
        "mobile_pocket_ca_count": len(coordinates[mobile.accession]),
        "distance_threshold_angstrom": settings.distance_threshold_angstrom,
        **geometry,
        "minimum_tm_score": minimum_tm_score,
        "global_tm_pass": global_tm_pass,
        "pocket_centroid_pass": centroid_pass,
        "pocket_overlap_pass": overlap_pass,
        "same_pocket_supported": supported,
        "three_dimensional_pocket_score": score,
        "status": "ASSESSED",
        "reason": (
            "global superposition and pocket geometry pass configured thresholds"
            if supported
            else "one or more global-superposition or pocket-geometry thresholds failed"
        ),
    }
    return alignment, comparison


def _group_summary(
    *,
    records: Sequence[SelectedPocket],
    reference: SelectedPocket | None,
    eligible: Sequence[SelectedPocket],
    comparisons: Sequence[Mapping[str, Any]],
    alignment_tools: Sequence[str],
    settings: AlignmentSettings,
) -> dict[str, Any]:
    """Aggregate pairwise comparisons into one group-level evidence record."""
    first = records[0]
    assessed = [
        row for row in comparisons if row.get("status") == "ASSESSED"
    ]
    by_mobile: dict[str, list[Mapping[str, Any]]] = {}
    for row in assessed:
        by_mobile.setdefault(str(row["mobile_accession"]), []).append(row)
    supported_mobile = {
        accession
        for accession, rows in by_mobile.items()
        if len(rows) == len(alignment_tools)
        and all(bool(row["same_pocket_supported"]) for row in rows)
    }
    agreement_values = [
        float(len({bool(row["same_pocket_supported"]) for row in rows}) == 1)
        for rows in by_mobile.values()
        if len(rows) == len(alignment_tools)
    ]
    supported_accessions = (
        ({reference.accession} if reference is not None else set())
        | supported_mobile
    )
    record_by_accession = {record.accession: record for record in records}
    supported_species = {
        record_by_accession[accession].species
        for accession in supported_accessions
        if record_by_accession[accession].species
    }
    eligible_species = {record.species for record in eligible if record.species}
    support_fraction = (
        len(supported_accessions) / len(eligible) if eligible else 0.0
    )
    minimum_tm_scores = [float(row["minimum_tm_score"]) for row in assessed]
    overlaps = [float(row["symmetric_overlap_fraction"]) for row in assessed]
    centroid_distances = [
        float(row["centroid_distance_angstrom"]) for row in assessed
    ]
    scores = [
        float(row["three_dimensional_pocket_score"]) for row in assessed
    ]
    if len(eligible) < 2:
        status = "INSUFFICIENT_STRUCTURES"
    elif support_fraction >= settings.minimum_group_support_fraction:
        status = "CONSERVED_3D_POCKET_SUPPORTED"
    else:
        status = "THREE_DIMENSIONAL_POCKET_NOT_SUPPORTED"
    return {
        "cluster_id": first.cluster_id,
        "primary_group_type": first.primary_group_type,
        "primary_group_id": first.primary_group_id,
        "reference_accession": reference.accession if reference is not None else "",
        "alignment_tools": ";".join(alignment_tools),
        "alignment_tool_count": len(alignment_tools),
        "selected_accession_count": len(records),
        "model_available_accession_count": len(eligible),
        "aligned_accession_count": len(eligible),
        "supported_accession_count": len(supported_accessions),
        "aligned_species_count": len(eligible_species),
        "supported_species_count": len(supported_species),
        "group_support_fraction": support_fraction,
        "pairwise_tool_agreement_fraction": (
            statistics.mean(agreement_values) if agreement_values else None
        ),
        "mean_minimum_tm_score": (
            statistics.mean(minimum_tm_scores) if minimum_tm_scores else 0.0
        ),
        "mean_pocket_overlap_fraction": (
            statistics.mean(overlaps) if overlaps else 0.0
        ),
        "median_centroid_distance_angstrom": (
            statistics.median(centroid_distances)
            if centroid_distances
            else None
        ),
        "three_dimensional_pocket_score": (
            statistics.mean(scores) if scores else 0.0
        ),
        "alignment_status": status,
        "supported_accessions": ";".join(sorted(supported_accessions)),
        "supported_species": ";".join(sorted(supported_species)),
        "interpretation": (
            "all enabled structural aligners must support each member; global superposition "
            "is followed by selected-pocket C-alpha geometry; computational evidence only"
        ),
    }


def run_analysis(
    *,
    selected: Sequence[SelectedPocket],
    assets: Mapping[str, StructureAsset],
    locators: Mapping[str, Sequence[ResidueLocator]],
    output_root: Path,
    settings: AlignmentSettings,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, str],
]:
    """Execute all deterministic reference-to-member alignments."""
    tools: list[tuple[str, str]] = []
    if settings.run_usalign:
        tools.append(("US-align", settings.usalign_executable))
    if settings.run_tmalign:
        tools.append(("TM-align", settings.tmalign_executable))
    versions = {
        name: tool_version(executable, tool_name=name)
        for name, executable in tools
    }
    atoms: dict[str, Any] = {}
    coordinates: dict[str, Sequence[tuple[float, float, float]]] = {}
    for pocket in selected:
        asset = assets.get(pocket.accession)
        accession_locators = locators.get(pocket.accession, ())
        if asset is None or not accession_locators:
            continue
        atoms[pocket.accession] = parse_ca_atoms(asset.path)
        accession_coordinates = pocket_coordinates(
            atoms=atoms[pocket.accession],
            locators=accession_locators,
        )
        if accession_coordinates:
            coordinates[pocket.accession] = accession_coordinates
    grouped: dict[tuple[str, str, str], list[SelectedPocket]] = {}
    for pocket in selected:
        key = (
            pocket.cluster_id,
            pocket.primary_group_type,
            pocket.primary_group_id,
        )
        grouped.setdefault(key, []).append(pocket)
    alignments: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    group_context: list[
        tuple[list[SelectedPocket], SelectedPocket | None, list[SelectedPocket]]
    ] = []
    tasks: list[tuple[SelectedPocket, SelectedPocket, str, str]] = []
    for records in grouped.values():
        records.sort(key=lambda item: item.accession)
        eligible = [
            record
            for record in records
            if record.accession in assets and record.accession in coordinates
        ]
        reference = min(eligible, key=_reference_sort_key) if eligible else None
        group_context.append((records, reference, eligible))
        if reference is None:
            continue
        for alignment_tool, _executable in tools:
            reference_alignment, reference_comparison = _reference_rows(
                pocket=reference,
                asset=assets[reference.accession],
                coordinate_count=len(coordinates[reference.accession]),
                alignment_tool=alignment_tool,
                version=versions[alignment_tool],
                settings=settings,
            )
            alignments.append(reference_alignment)
            comparisons.append(reference_comparison)
        tasks.extend(
            (reference, mobile, alignment_tool, executable)
            for mobile in eligible
            if mobile.accession != reference.accession
            for alignment_tool, executable in tools
        )
    raw_root = output_root / "raw"
    with ThreadPoolExecutor(max_workers=settings.threads) as executor:
        future_to_pair = {
            executor.submit(
                _align_pair,
                reference=reference,
                mobile=mobile,
                assets=assets,
                coordinates=coordinates,
                raw_root=raw_root,
                output_root=output_root,
                alignment_tool=alignment_tool,
                executable=executable,
                version=versions[alignment_tool],
                settings=settings,
            ): (reference.accession, mobile.accession)
            for reference, mobile, alignment_tool, executable in tasks
        }
        for future in as_completed(future_to_pair):
            pair = future_to_pair[future]
            try:
                alignment, comparison = future.result()
            except BaseException as exc:
                raise StructuralAlignmentError(
                    f"Structural alignment failed for {pair[0]} versus {pair[1]}: {exc}"
                ) from exc
            alignments.append(alignment)
            comparisons.append(comparison)
    alignments.sort(
        key=lambda row: (
            str(row["cluster_id"]),
            str(row["reference_accession"]),
            str(row["mobile_accession"]),
            str(row["alignment_tool"]),
        )
    )
    comparisons.sort(
        key=lambda row: (
            str(row["cluster_id"]),
            str(row["reference_accession"]),
            str(row["mobile_accession"]),
            str(row["alignment_tool"]),
        )
    )
    summaries = []
    for records, reference, eligible in group_context:
        group_comparisons = [
            row
            for row in comparisons
            if row["cluster_id"] == records[0].cluster_id
            and row["primary_group_id"] == records[0].primary_group_id
        ]
        summaries.append(
            _group_summary(
                records=records,
                reference=reference,
                eligible=eligible,
                comparisons=group_comparisons,
                alignment_tools=[name for name, _executable in tools],
                settings=settings,
            )
        )
    summaries.sort(
        key=lambda row: (str(row["cluster_id"]), str(row["primary_group_id"]))
    )
    return alignments, comparisons, summaries, versions


def _run_digest(
    *,
    input_paths: Mapping[str, Path],
    settings: AlignmentSettings,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Return the reproducibility digest and input inventory."""
    inputs = {
        label: {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for label, path in sorted(input_paths.items())
    }
    canonical = json.dumps(
        {"inputs": inputs, "settings": asdict(settings), "package_version": __version__},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest(), inputs


def validate_existing_output(output_dir: Path, run_digest: str) -> bool:
    """Return whether an existing output is complete and unchanged."""
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
        relative = Path(str(record.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            return False
        path = output_dir / relative
        if not path.is_file() or path.stat().st_size != record.get("size_bytes"):
            return False
        if sha256_file(path) != record.get("sha256"):
            return False
    return True


def run_pipeline(
    *,
    selected_pockets_path: Path,
    pocket_residue_mappings_path: Path,
    asset_manifest_path: Path,
    output_dir: Path,
    settings: AlignmentSettings,
    resume: bool,
    force: bool,
    verbose: bool,
) -> Path:
    """Run the complete workflow through atomic publication."""
    settings.validate()
    input_paths = {
        "selected_pockets": resolve_input_file(
            selected_pockets_path, "selected pockets"
        ),
        "pocket_residue_mappings": resolve_input_file(
            pocket_residue_mappings_path, "pocket residue mappings"
        ),
        "asset_manifest": resolve_input_file(
            asset_manifest_path, "structure asset manifest"
        ),
    }
    run_digest, input_inventory = _run_digest(
        input_paths=input_paths,
        settings=settings,
    )
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        if resume and validate_existing_output(destination, run_digest):
            return destination / "provenance" / "run_manifest.json"
        if not force:
            raise StructuralAlignmentError(
                "Output directory already exists but is not a valid matching resume target: "
                f"{destination}"
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
    logger = configure_logging(staging / "logs" / "pipeline.log", verbose)
    started = utc_now()
    try:
        LOGGER.info("Structural-alignment package version: %s", __version__)
        LOGGER.info("Output staging directory: %s", staging)
        for label, details in input_inventory.items():
            LOGGER.info(
                "Input %s: %s (%s bytes; SHA-256 %s)",
                label,
                details["path"],
                details["size_bytes"],
                details["sha256"],
            )
        selected = parse_selected_pockets(
            read_records(input_paths["selected_pockets"])
        )
        assets = resolve_structure_assets(
            read_records(input_paths["asset_manifest"])
        )
        locators = parse_pocket_locators(
            read_records(input_paths["pocket_residue_mappings"]),
            selected=selected,
        )
        LOGGER.info(
            "Selected pockets=%d; resolved models=%d; mapped-pocket accessions=%d",
            len(selected),
            len(assets),
            len(locators),
        )
        alignments, comparisons, summaries, versions = run_analysis(
            selected=selected,
            assets=assets,
            locators=locators,
            output_root=staging,
            settings=settings,
        )
        write_table(
            tsv_path=staging / "tables" / "structural_alignments.tsv",
            parquet_path=staging / "tables" / "structural_alignments.parquet",
            records=alignments,
            schema=ALIGNMENT_SCHEMA,
        )
        write_table(
            tsv_path=staging / "tables" / "pocket_comparisons.tsv",
            parquet_path=staging / "tables" / "pocket_comparisons.parquet",
            records=comparisons,
            schema=POCKET_COMPARISON_SCHEMA,
        )
        write_table(
            tsv_path=staging / "tables" / "structural_alignment_summary.tsv",
            parquet_path=staging / "tables" / "structural_alignment_summary.parquet",
            records=summaries,
            schema=GROUP_SUMMARY_SCHEMA,
        )
        validation = {
            "selected_accession_count": len(selected),
            "resolved_model_count": len(assets),
            "group_count": len(summaries),
            "pairwise_alignment_count": sum(
                row["status"] == "COMPLETE" for row in alignments
            ),
            "supported_group_count": sum(
                row["alignment_status"] == "CONSERVED_3D_POCKET_SUPPORTED"
                for row in summaries
            ),
            "insufficient_structure_group_count": sum(
                row["alignment_status"] == "INSUFFICIENT_STRUCTURES"
                for row in summaries
            ),
            "alignment_tools": list(versions),
            "alignment_tool_versions": versions,
            "status": "PASS",
            "interpretation": (
                "three-dimensional pocket equivalence is computational evidence and does not "
                "establish compound binding"
            ),
        }
        write_tsv(
            staging / "qc" / "structural_alignment_validation.tsv",
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
            "settings": asdict(settings),
            "inputs": input_inventory,
            "validation": validation,
            "outputs": outputs,
        }
        atomic_write_json(staging / "provenance" / "run_manifest.json", manifest)
        os.replace(staging, destination)
        return destination / "provenance" / "run_manifest.json"
    except BaseException:
        close_logger(logger)
        failed = destination.with_name(
            f"{destination.name}.failed.{uuid.uuid4().hex}"
        )
        if staging.exists():
            shutil.move(str(staging), str(failed))
        raise
