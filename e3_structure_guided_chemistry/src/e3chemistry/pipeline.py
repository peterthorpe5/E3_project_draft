"""End-to-end open-source structure-guided chemistry execution."""

from __future__ import annotations

import importlib.metadata
import logging
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from e3chemistry import __version__
from e3chemistry.config import load_config
from e3chemistry.errors import InputValidationError
from e3chemistry.fragments import (
    FRAGMENT_PROPERTY_FIELDS,
    FRAGMENT_RANKING_FIELDS,
    load_fragment_properties,
    rank_fragments,
)
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
from e3chemistry.pharmacophore import (
    FEATURE_FIELDS,
    GROUP_SUMMARY_FIELDS,
    build_feature_records,
    summarise_groups,
)
from e3chemistry.reporting import write_report
from e3chemistry.structures import (
    load_pocket_residues,
    mapped_residue_locators,
    resolve_structure_assets,
)

LOGGER = logging.getLogger("e3chemistry.pipeline")

TARGET_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "cluster_id",
    "candidate_accession",
    "species_column",
    "pocket_number",
    "druggability_score",
    "mapping_fraction",
    "pocket_plddt_fraction",
    "conserved_component_fraction",
    "mean_chemical_group_conservation",
    "structure_path",
    "structure_sha256",
    "mapped_residue_count",
    "target_status",
    "status_reason",
)

METHOD_STATUS_FIELDS = (
    "method",
    "executed",
    "status",
    "reason",
)

COMPONENT_LICENCE_FIELDS = (
    "component",
    "spdx_licence",
    "open_source_approved",
    "commercial_entitlement_required",
)

MILESTONE_COVERAGE_FIELDS = (
    "milestone_component",
    "status",
    "implementation",
    "limitation",
)

QC_FIELDS = (
    "selected_group_limit",
    "target_group_count",
    "resolved_structure_target_count",
    "pharmacophore_feature_count",
    "chemistry_ready_group_count",
    "fragment_library_record_count",
    "valid_rule_of_three_fragment_count",
    "fragment_ranking_count",
    "fmophore_executed",
    "francestor_executed",
    "restricted_licence_tools_used",
    "validation_status",
)


def _text(value: Any) -> str:
    """Return stripped text for one possibly missing value."""
    return "" if value is None else str(value).strip()


def _integer(value: Any, label: str) -> int:
    """Parse one integer or raise a controlled input error."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise InputValidationError(f"{label} must be an integer: {value!r}") from exc


def _float(value: Any, default: float = 0.0) -> float:
    """Return one finite numeric value with a conservative default."""
    if value is None or _text(value) == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InputValidationError(f"Expected a numeric value, observed {value!r}") from exc
    if result != result or result in {float("inf"), float("-inf")}:
        raise InputValidationError(f"Expected a finite numeric value, observed {value!r}")
    return result


def _group_key(record: Mapping[str, Any]) -> tuple[str, str]:
    """Return one primary evolutionary-group key."""
    return (_text(record.get("primary_group_type")), _text(record.get("primary_group_id")))


def select_chemistry_targets(
    *,
    group_ranking: Sequence[Mapping[str, Any]],
    selected_pockets: Sequence[Mapping[str, Any]],
    conservation: Sequence[Mapping[str, Any]],
    assets: Mapping[str, StructureAsset],
    mappings: Sequence[Mapping[str, Any]],
    config: ChemistryConfig,
) -> list[dict[str, Any]]:
    """Select one best checksum-bound pocket structure per evolutionary group."""
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
            "candidate_accession",
            "pocket_number",
        ),
        label="selected pockets",
    )
    require_columns(
        records=conservation,
        required=(
            "primary_group_type",
            "primary_group_id",
            "conserved_component_fraction",
            "mean_chemical_group_conservation",
        ),
        label="pocket conservation summary",
    )
    conservation_by_group = {_group_key(row): row for row in conservation}
    pockets_by_group: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for pocket in selected_pockets:
        pockets_by_group.setdefault(_group_key(pocket), []).append(pocket)
    targets = []
    selected_groups = sorted(
        (
            row
            for row in group_ranking
            if _integer(row["evolutionary_group_rank"], "evolutionary_group_rank")
            <= config.group_limit
        ),
        key=lambda row: (
            _integer(row["evolutionary_group_rank"], "evolutionary_group_rank"),
            _text(row["evolutionary_group_key"]),
        ),
    )
    for group in selected_groups:
        key = _group_key(group)
        conservation_row = conservation_by_group.get(key, {})
        candidates = []
        for pocket in pockets_by_group.get(key, []):
            accession = _text(pocket.get("candidate_accession")).upper()
            asset = assets.get(accession)
            if asset is None:
                continue
            pocket_number = _integer(pocket.get("pocket_number"), "pocket_number")
            locators = mapped_residue_locators(
                records=mappings,
                accession=accession,
                pocket_number=pocket_number,
            )
            if not locators:
                continue
            candidates.append((pocket, asset, locators))
        candidates.sort(
            key=lambda item: (
                -_float(item[0].get("druggability_score")),
                -_float(item[0].get("conservative_fraction_plddt_ge_70")),
                -_float(item[0].get("mapping_fraction")),
                _text(item[0].get("candidate_accession")),
                _integer(item[0].get("pocket_number"), "pocket_number"),
            )
        )
        if candidates:
            pocket, asset, locators = candidates[0]
            status = "READY_FOR_FEATURE_EXTRACTION"
            reason = "selected best mapped pocket with a checksum-validated structure"
            accession = _text(pocket.get("candidate_accession")).upper()
            pocket_number = _integer(pocket.get("pocket_number"), "pocket_number")
            species = _text(pocket.get("species_column"))
            druggability = _float(pocket.get("druggability_score"))
            mapping_fraction = _float(pocket.get("mapping_fraction"))
            plddt_fraction = _float(
                pocket.get("conservative_fraction_plddt_ge_70")
            )
            structure_path = str(asset.path)
            structure_sha256 = asset.sha256
            mapped_count = len(locators)
        else:
            status = "NO_CHECKSUM_BOUND_MAPPED_POCKET_STRUCTURE"
            reason = "no selected pocket had both mapped residues and a validated structure asset"
            accession = ""
            pocket_number = ""
            species = ""
            druggability = ""
            mapping_fraction = ""
            plddt_fraction = ""
            structure_path = ""
            structure_sha256 = ""
            mapped_count = 0
        targets.append(
            {
                "evolutionary_group_rank": group["evolutionary_group_rank"],
                "evolutionary_group_key": group["evolutionary_group_key"],
                "primary_group_type": key[0],
                "primary_group_id": key[1],
                "cluster_id": group["lead_cluster_id"],
                "candidate_accession": accession,
                "species_column": species,
                "pocket_number": pocket_number,
                "druggability_score": druggability,
                "mapping_fraction": mapping_fraction,
                "pocket_plddt_fraction": plddt_fraction,
                "conserved_component_fraction": _float(
                    conservation_row.get("conserved_component_fraction")
                ),
                "mean_chemical_group_conservation": _float(
                    conservation_row.get("mean_chemical_group_conservation")
                ),
                "structure_path": structure_path,
                "structure_sha256": structure_sha256,
                "mapped_residue_count": mapped_count,
                "target_status": status,
                "status_reason": reason,
            }
        )
    return targets


def _method_status(config: ChemistryConfig) -> list[dict[str, Any]]:
    """Return explicit executed/not-executed method declarations."""
    return [
        {
            "method": "FMOPhore",
            "executed": False,
            "status": "NOT_RUN",
            "reason": (
                "a complete independently reproducible open-source execution route "
                "was not used; no FMO or FP-score claim is made"
            ),
        },
        {
            "method": "FrAncestor",
            "executed": False,
            "status": "NOT_RUN",
            "reason": (
                "no verified open-source executable workflow was used; the package "
                "screens only a user-supplied open fragment table"
            ),
        },
        {
            "method": "AlphaFold3",
            "executed": False,
            "status": "NOT_RUN",
            "reason": "the package consumes existing checksum-bound structures only",
        },
        {
            "method": config.method_name,
            "executed": True,
            "status": "EXECUTED",
            "reason": (
                "open residue-derived three-dimensional pharmacophore hypotheses "
                "and optional RDKit fragment compatibility"
            ),
        },
    ]


def _milestone_coverage(config: ChemistryConfig) -> list[dict[str, Any]]:
    """Return an explicit mapping from the grant text to executed work."""
    fragment_status = (
        "EXECUTED_OPEN_ALTERNATIVE"
        if config.fragment_screening_mode == "open_fragment_screen"
        else "PREPARED_NOT_SCREENED"
    )
    return [
        {
            "milestone_component": "ten_evolutionary_candidate_groups",
            "status": "IMPLEMENTED",
            "implementation": "top ten distinct Stage 08 evolutionary groups by default",
            "limitation": "candidate-group status does not prove E3 function",
        },
        {
            "milestone_component": "evolutionarily_stable_regions",
            "status": "IMPLEMENTED",
            "implementation": (
                "Stage 09 conserved-component and chemical-group conservation gates"
            ),
            "limitation": "computational conservation in predicted pockets only",
        },
        {
            "milestone_component": "unique_regions",
            "status": "IMPLEMENTED_OPEN_ALTERNATIVE",
            "implementation": (
                "feature chemistry and rotation-invariant feature-pair distance comparison"
            ),
            "limitation": "uniqueness is relative to the selected candidate-group panel",
        },
        {
            "milestone_component": "structure_prediction_refinement",
            "status": "EXISTING_STRUCTURES_CONSUMED",
            "implementation": "checksum-bound Stage 09 structures and mapped pocket residues",
            "limitation": "AlphaFold3 was not run or refined by this package",
        },
        {
            "milestone_component": "ligandable_surface_identification",
            "status": "EXISTING_POCKETS_CONSUMED",
            "implementation": "Stage 09 selected predicted pockets",
            "limitation": "FMOPhore was not run and no FMO energy is reported",
        },
        {
            "milestone_component": "pharmacophore_identification",
            "status": "IMPLEMENTED_OPEN_ALTERNATIVE",
            "implementation": "residue-derived three-dimensional feature hypotheses",
            "limitation": "not FMOPhore, docking, affinity or binding evidence",
        },
        {
            "milestone_component": "fragment_prioritisation",
            "status": fragment_status,
            "implementation": (
                "optional RDKit rule-of-three and 2D feature compatibility ranking"
            ),
            "limitation": "FrAncestor was not run; no experimental screen is claimed",
        },
    ]


def _package_versions() -> dict[str, str]:
    """Return installed versions without failing on optional metadata gaps."""
    versions = {"e3-structure-guided-chemistry": __version__}
    for distribution in ("duckdb", "gemmi", "rdkit"):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = "unavailable"
    return versions


def run_pipeline(
    *,
    config_path: Path,
    group_ranking_path: Path,
    selected_pockets_path: Path,
    pocket_residue_mappings_path: Path,
    pocket_conservation_summary_path: Path,
    structure_asset_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Run the complete open structure-guided chemistry workflow."""
    config = load_config(config_path)
    destination = output_dir.expanduser().resolve()
    if destination.is_file():
        raise InputValidationError(f"Output directory is a file: {destination}")
    if destination.exists():
        existing_scientific_outputs = [
            path for path in destination.iterdir() if path.name != "logs"
        ]
        if existing_scientific_outputs:
            raise InputValidationError(f"Output directory is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    inputs = {
        "config": config.source_path,
        "group_ranking": group_ranking_path.expanduser().resolve(),
        "selected_pockets": selected_pockets_path.expanduser().resolve(),
        "pocket_residue_mappings": pocket_residue_mappings_path.expanduser().resolve(),
        "pocket_conservation_summary": (
            pocket_conservation_summary_path.expanduser().resolve()
        ),
        "structure_asset_manifest": structure_asset_manifest_path.expanduser().resolve(),
    }
    if config.fragment_library is not None:
        inputs["fragment_library"] = config.fragment_library
    for label, path in inputs.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise InputValidationError(f"{label} input is missing or empty: {path}")
    LOGGER.info("Reading controlled chemistry inputs")
    group_ranking = read_records(inputs["group_ranking"])
    selected_pockets = read_records(inputs["selected_pockets"])
    mappings = read_records(inputs["pocket_residue_mappings"])
    conservation = read_records(inputs["pocket_conservation_summary"])
    asset_records = read_records(inputs["structure_asset_manifest"])
    assets = resolve_structure_assets(asset_records)
    targets = select_chemistry_targets(
        group_ranking=group_ranking,
        selected_pockets=selected_pockets,
        conservation=conservation,
        assets=assets,
        mappings=mappings,
        config=config,
    )
    if not targets:
        raise InputValidationError(
            "No evolutionary groups were available within the configured group limit"
        )
    features = []
    for target in targets:
        if target["target_status"] != "READY_FOR_FEATURE_EXTRACTION":
            continue
        accession = str(target["candidate_accession"])
        pocket_number = int(target["pocket_number"])
        locators = mapped_residue_locators(
            records=mappings,
            accession=accession,
            pocket_number=pocket_number,
        )
        try:
            residues = load_pocket_residues(
                asset=assets[accession],
                pocket_number=pocket_number,
                locators=locators,
            )
        except InputValidationError as exc:
            target["target_status"] = "STRUCTURE_RESIDUE_RESOLUTION_FAILED"
            target["status_reason"] = str(exc)
            LOGGER.warning("Could not extract %s: %s", accession, exc)
            continue
        extracted = build_feature_records(
            target=target,
            residues=residues,
            config=config,
        )
        if not extracted:
            target["target_status"] = "NO_PHARMACOPHORE_FEATURES"
            target["status_reason"] = "mapped residues yielded no supported feature types"
            continue
        target["target_status"] = "FEATURES_EXTRACTED"
        target["status_reason"] = f"extracted {len(extracted)} residue-derived features"
        features.extend(extracted)
    group_summaries = summarise_groups(
        targets=targets,
        features=features,
        config=config,
    )
    fragment_properties: list[dict[str, Any]] = []
    fragment_rankings: list[dict[str, Any]] = []
    if config.fragment_screening_mode == "open_fragment_screen":
        if config.fragment_library is None:  # defensive after configuration validation
            raise InputValidationError("Open fragment screening has no fragment library")
        fragment_properties = load_fragment_properties(config.fragment_library)
        fragment_rankings = rank_fragments(
            group_summaries=group_summaries,
            features=features,
            fragments=fragment_properties,
            config=config,
        )
    tables = destination / "tables"
    write_records(
        tsv_path=tables / "chemistry_target_manifest.tsv",
        parquet_path=tables / "chemistry_target_manifest.parquet",
        records=targets,
        fieldnames=TARGET_FIELDS,
    )
    write_records(
        tsv_path=tables / "pocket_pharmacophore_features.tsv",
        parquet_path=tables / "pocket_pharmacophore_features.parquet",
        records=features,
        fieldnames=FEATURE_FIELDS,
    )
    write_records(
        tsv_path=tables / "group_pharmacophore_summary.tsv",
        parquet_path=tables / "group_pharmacophore_summary.parquet",
        records=group_summaries,
        fieldnames=GROUP_SUMMARY_FIELDS,
    )
    write_records(
        tsv_path=tables / "fragment_properties.tsv",
        parquet_path=tables / "fragment_properties.parquet",
        records=fragment_properties,
        fieldnames=FRAGMENT_PROPERTY_FIELDS,
    )
    write_records(
        tsv_path=tables / "fragment_pharmacophore_ranking.tsv",
        parquet_path=tables / "fragment_pharmacophore_ranking.parquet",
        records=fragment_rankings,
        fieldnames=FRAGMENT_RANKING_FIELDS,
    )
    method_status = _method_status(config)
    write_tsv(
        path=destination / "METHOD_STATUS.tsv",
        records=method_status,
        fieldnames=METHOD_STATUS_FIELDS,
    )
    write_tsv(
        path=destination / "COMPONENT_LICENCES.tsv",
        records=[
            {
                "component": component.name,
                "spdx_licence": component.spdx,
                "open_source_approved": True,
                "commercial_entitlement_required": False,
            }
            for component in config.declared_components
        ],
        fieldnames=COMPONENT_LICENCE_FIELDS,
    )
    write_tsv(
        path=destination / "MILESTONE_COVERAGE.tsv",
        records=_milestone_coverage(config),
        fieldnames=MILESTONE_COVERAGE_FIELDS,
    )
    qc = {
        "selected_group_limit": config.group_limit,
        "target_group_count": len(targets),
        "resolved_structure_target_count": sum(
            row["target_status"] == "FEATURES_EXTRACTED" for row in targets
        ),
        "pharmacophore_feature_count": len(features),
        "chemistry_ready_group_count": sum(
            row["chemistry_handoff_status"]
            == "READY_FOR_OPEN_FRAGMENT_PRIORITISATION"
            for row in group_summaries
        ),
        "fragment_library_record_count": len(fragment_properties),
        "valid_rule_of_three_fragment_count": sum(
            row.get("fragment_status") == "READY" for row in fragment_properties
        ),
        "fragment_ranking_count": len(fragment_rankings),
        "fmophore_executed": False,
        "francestor_executed": False,
        "restricted_licence_tools_used": False,
        "validation_status": "PASS",
    }
    if targets and not features:
        qc["validation_status"] = "PASS_WITH_NO_RESOLVED_FEATURES"
    write_tsv(
        path=destination / "qc" / "computational_chemistry_validation.tsv",
        records=[qc],
        fieldnames=QC_FIELDS,
    )
    write_report(
        path=destination / "reports" / "structure_guided_chemistry_summary.html",
        config=config,
        targets=targets,
        group_summaries=group_summaries,
        fragment_rankings=fragment_rankings,
    )
    config_copy = destination / "provenance" / config.source_path.name
    config_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config.source_path, config_copy)
    output_files = sorted(
        path
        for path in destination.rglob("*")
        if path.is_file() and path.relative_to(destination).parts[0] != "logs"
    )
    manifest = {
        "schema_version": 1,
        "package_version": __version__,
        "method": config.method_name,
        "configuration_digest": config.digest,
        "created_at_utc": utc_now(),
        "licence_policy": {
            "allow_restricted_licence_tools": False,
            "declared_components": [
                {"name": component.name, "spdx": component.spdx}
                for component in config.declared_components
            ],
        },
        "method_status": method_status,
        "package_versions": _package_versions(),
        "inputs": {
            label: {"path": str(path), "sha256": sha256_file(path)}
            for label, path in sorted(inputs.items())
        },
        "counts": qc,
        "outputs": [
            {
                "path": str(path.relative_to(destination)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in output_files
        ],
    }
    manifest_path = destination / "provenance" / "run_manifest.json"
    write_json(path=manifest_path, payload=manifest)
    return {
        "status": "complete",
        "output_dir": str(destination),
        "target_group_count": len(targets),
        "pharmacophore_feature_count": len(features),
        "fragment_ranking_count": len(fragment_rankings),
        "manifest": str(manifest_path),
    }
