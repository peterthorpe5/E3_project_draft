"""End-to-end open-source structure-guided chemistry execution."""

from __future__ import annotations

import importlib.metadata
import logging
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from e3chemistry import __version__
from e3chemistry.candidate_manifest import validate_candidate_manifest
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
    SENSITIVITY_FIELDS,
    build_feature_records,
    summarise_groups,
    threshold_sensitivity,
)
from e3chemistry.reporting import write_report
from e3chemistry.source_provenance import capture_source_provenance
from e3chemistry.structures import (
    load_pocket_residues,
    mapped_residue_locators,
    resolve_structure_assets,
)

LOGGER = logging.getLogger("e3chemistry.pipeline")

TARGET_FIELDS = (
    "panel_order",
    "decision_basis",
    "decided_by",
    "decided_at_utc",
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
    "mapping_quality_supported",
    "pocket_plddt_fraction",
    "pocket_confidence_supported",
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
    "candidate_panel_type",
    "candidate_manifest_included_count",
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
    candidate_manifest: Sequence[Mapping[str, Any]],
    group_ranking: Sequence[Mapping[str, Any]],
    selected_pockets: Sequence[Mapping[str, Any]],
    conservation: Sequence[Mapping[str, Any]],
    assets: Mapping[str, StructureAsset],
    mappings: Sequence[Mapping[str, Any]],
    config: ChemistryConfig,
) -> list[dict[str, Any]]:
    """Resolve exact manifest-approved group, accession and pocket identities."""
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
    ranking_by_key = {
        _text(row.get("evolutionary_group_key")): row for row in group_ranking
    }
    pockets_by_group: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for pocket in selected_pockets:
        pockets_by_group.setdefault(_group_key(pocket), []).append(pocket)
    panel = validate_candidate_manifest(
        records=candidate_manifest,
        maximum_candidate_groups=config.maximum_candidate_groups,
    )
    targets = []
    for manifest_row in panel:
        group_key = _text(manifest_row["evolutionary_group_key"])
        group = ranking_by_key.get(group_key)
        if group is None:
            raise InputValidationError(
                f"Candidate manifest group is absent from Stage 08 ranking: {group_key}"
            )
        key = _group_key(group)
        expected_identity = (
            _integer(group.get("evolutionary_group_rank"), "evolutionary_group_rank"),
            key[0],
            key[1],
        )
        observed_identity = (
            int(manifest_row["evolutionary_group_rank"]),
            _text(manifest_row["primary_group_type"]),
            _text(manifest_row["primary_group_id"]),
        )
        if observed_identity != expected_identity:
            raise InputValidationError(
                f"Candidate manifest identity conflicts with Stage 08 ranking: {group_key}"
            )
        conservation_row = conservation_by_group.get(key, {})
        accession = _text(manifest_row["candidate_accession"]).upper()
        pocket_number = int(manifest_row["pocket_number"])
        matching_pockets = [
            pocket
            for pocket in pockets_by_group.get(key, [])
            if _text(pocket.get("candidate_accession")).upper() == accession
            and _integer(pocket.get("pocket_number"), "pocket_number")
            == pocket_number
            and _text(pocket.get("cluster_id")) == _text(manifest_row["cluster_id"])
        ]
        if not matching_pockets:
            raise InputValidationError(
                "Candidate manifest target is absent from selected pockets: "
                f"{group_key}/{accession}/{pocket_number}"
            )
        pocket = matching_pockets[0]
        asset = assets.get(accession)
        if asset is None:
            raise InputValidationError(
                f"Candidate manifest accession has no validated structure: {accession}"
            )
        if asset.sha256 != _text(manifest_row["structure_sha256"]).lower():
            raise InputValidationError(
                f"Candidate manifest structure checksum conflicts for {accession}"
            )
        locators = mapped_residue_locators(
            records=mappings,
            accession=accession,
            pocket_number=pocket_number,
        )
        if not locators:
            raise InputValidationError(
                "Candidate manifest target has no mapped pocket residues: "
                f"{accession}/{pocket_number}"
            )
        species = _text(pocket.get("species_column"))
        if species != _text(manifest_row["species_column"]):
            raise InputValidationError(
                f"Candidate manifest species conflicts for {accession}/{pocket_number}"
            )
        druggability = _float(pocket.get("druggability_score"))
        mapping_fraction = _float(pocket.get("mapping_fraction"))
        plddt_fraction = _float(pocket.get("conservative_fraction_plddt_ge_70"))
        targets.append(
            {
                "panel_order": manifest_row["panel_order"],
                "decision_basis": manifest_row["decision_basis"],
                "decided_by": manifest_row["decided_by"],
                "decided_at_utc": manifest_row["decided_at_utc"],
                "evolutionary_group_rank": group["evolutionary_group_rank"],
                "evolutionary_group_key": group["evolutionary_group_key"],
                "primary_group_type": key[0],
                "primary_group_id": key[1],
                "cluster_id": manifest_row["cluster_id"],
                "candidate_accession": accession,
                "species_column": species,
                "pocket_number": pocket_number,
                "druggability_score": druggability,
                "mapping_fraction": mapping_fraction,
                "mapping_quality_supported": (
                    mapping_fraction >= config.minimum_mapping_fraction
                ),
                "pocket_plddt_fraction": plddt_fraction,
                "pocket_confidence_supported": (
                    plddt_fraction >= config.minimum_pocket_plddt_fraction
                ),
                "conserved_component_fraction": _float(
                    conservation_row.get("conserved_component_fraction")
                ),
                "mean_chemical_group_conservation": _float(
                    conservation_row.get("mean_chemical_group_conservation")
                ),
                "structure_path": str(asset.path),
                "structure_sha256": asset.sha256,
                "mapped_residue_count": len(locators),
                "target_status": "READY_FOR_FEATURE_EXTRACTION",
                "status_reason": (
                    "resolved exact candidate-manifest accession, pocket and structure"
                ),
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
                "public GPL-3.0 FMOPhore code exists, but a complete validated "
                "licence-compliant apo-target execution route was not used; no "
                "FMO or FP-score claim is made"
            ),
        },
        {
            "method": "FrAncestor",
            "executed": False,
            "status": "NOT_RUN",
            "reason": (
                "no verified publicly executable and licensed workflow was used; the package "
                "screens only a user-supplied open fragment table"
            ),
        },
        {
            "method": "AlphaFold3",
            "executed": False,
            "status": "NOT_RUN",
            "reason": (
                "the package consumes existing checksum-bound structures only; "
                "AlphaFold3 model-parameter terms are outside the strict SPDX "
                "open-source component policy"
            ),
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
            "milestone_component": "explicit_evolutionary_candidate_panel",
            "status": "IMPLEMENTED",
            "implementation": (
                "checksum-bound candidate manifest with exact group, accession, "
                "pocket and decision-basis provenance"
            ),
            "limitation": (
                "expanded computational screening is not project-lead approval and "
                "candidate-group status does not prove E3 function"
            ),
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
    candidate_manifest_path: Path,
    group_ranking_path: Path,
    selected_pockets_path: Path,
    pocket_residue_mappings_path: Path,
    pocket_conservation_summary_path: Path,
    structure_asset_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Run the complete open structure-guided chemistry workflow."""
    config = load_config(config_path)
    source_provenance = capture_source_provenance()
    if config.require_clean_tracked_source:
        if not source_provenance.get("available"):
            raise InputValidationError(
                "A clean tracked Git source is required but source provenance is unavailable"
            )
        if source_provenance.get("tracked_source_state") != "CLEAN":
            raise InputValidationError(
                "A clean tracked Git source is required but package source is dirty"
            )
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
        "candidate_manifest": candidate_manifest_path.expanduser().resolve(),
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
    candidate_manifest = read_records(inputs["candidate_manifest"])
    group_ranking = read_records(inputs["group_ranking"])
    selected_pockets = read_records(inputs["selected_pockets"])
    mappings = read_records(inputs["pocket_residue_mappings"])
    conservation = read_records(inputs["pocket_conservation_summary"])
    asset_records = read_records(inputs["structure_asset_manifest"])
    assets = resolve_structure_assets(asset_records)
    targets = select_chemistry_targets(
        candidate_manifest=candidate_manifest,
        group_ranking=group_ranking,
        selected_pockets=selected_pockets,
        conservation=conservation,
        assets=assets,
        mappings=mappings,
        config=config,
    )
    if not targets:  # defensive after candidate-manifest validation
        raise InputValidationError("Candidate manifest produced no chemistry targets")
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
    sensitivity_rows = threshold_sensitivity(
        group_summaries=group_summaries,
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
        tsv_path=tables / "threshold_sensitivity.tsv",
        parquet_path=tables / "threshold_sensitivity.parquet",
        records=sensitivity_rows,
        fieldnames=SENSITIVITY_FIELDS,
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
        "candidate_panel_type": targets[0]["decision_basis"],
        "candidate_manifest_included_count": len(candidate_manifest),
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
    candidate_manifest_copy = (
        destination / "provenance" / candidate_manifest_path.name
    )
    shutil.copy2(candidate_manifest_path, candidate_manifest_copy)
    output_files = sorted(
        path
        for path in destination.rglob("*")
        if path.is_file() and path.relative_to(destination).parts[0] != "logs"
    )
    manifest = {
        "schema_version": 2,
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
        "source_provenance": source_provenance,
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
