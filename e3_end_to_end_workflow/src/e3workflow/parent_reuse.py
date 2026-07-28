"""Checksum-validated import of immutable stages from a completed parent run."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from e3workflow.config import WorkflowConfig
from e3workflow.errors import StageError
from e3workflow.io_utils import sha256_file, write_tsv

STAGE08_DERIVED_OUTPUTS = frozenset(
    {
        "tables/evolutionary_candidate_group_ranking.parquet",
        "tables/evolutionary_candidate_group_ranking.tsv",
        "tables/evolutionary_group_cluster_contributors.parquet",
        "tables/evolutionary_group_cluster_contributors.tsv",
        "tables/structural_analysis_accessions.parquet",
        "tables/structural_analysis_accessions.tsv",
        "tables/structural_representative_selection_audit.parquet",
        "tables/structural_representative_selection_audit.tsv",
        "tables/ligandability_accessions.tsv",
    }
)


def _read_manifest(path: Path) -> dict[str, Any]:
    """Read one parent stage manifest and require a JSON mapping."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageError(f"Could not read parent stage manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StageError(f"Parent stage manifest is not a JSON object: {path}")
    return payload


def _output_inventory(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Index validated parent output records by relative path."""
    records = manifest.get("outputs")
    if not isinstance(records, list):
        raise StageError("Parent stage manifest lacks an output inventory")
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise StageError("Parent stage output inventory contains a non-mapping record")
        relative = str(record.get("path", ""))
        if not relative or relative in indexed:
            raise StageError("Parent stage output inventory has an empty or duplicate path")
        indexed[relative] = record
    return indexed


def _validate_parent_file(
    *,
    source: Path,
    relative_path: str,
    inventory: Mapping[str, Mapping[str, Any]],
) -> None:
    """Validate one parent file against its recorded size and checksum."""
    record = inventory.get(relative_path)
    if record is None:
        raise StageError(
            f"Parent stage manifest does not inventory required output: {relative_path}"
        )
    if not source.is_file():
        raise StageError(f"Parent stage output is missing: {source}")
    observed_size = source.stat().st_size
    try:
        expected_size = int(record["size_bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise StageError(
            f"Parent output inventory has an invalid size for {relative_path}"
        ) from exc
    if observed_size != expected_size:
        raise StageError(
            f"Parent output size changed for {relative_path}: "
            f"expected={expected_size}, observed={observed_size}"
        )
    expected_sha256 = str(record.get("sha256", ""))
    observed_sha256 = sha256_file(source)
    if not expected_sha256 or observed_sha256 != expected_sha256:
        raise StageError(
            f"Parent output checksum changed for {relative_path}: "
            f"expected={expected_sha256}, observed={observed_sha256}"
        )


def _link_or_copy(source: Path, destination: Path) -> str:
    """Hard-link one immutable parent file, falling back to a metadata copy."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
        return "hard_link"
    except OSError:
        shutil.copy2(source, destination)
        return "copied"


def import_parent_stage(
    *,
    config: WorkflowConfig,
    stage_name: str,
    stage_root: Path,
) -> None:
    """Import declared outputs from a completed immutable parent stage.

    Stage 08 receives a deliberate refinement step after import: the parent
    all-member structural expansion is retained separately and the current
    release derives one representative per target species and evolutionary
    candidate group.
    """
    parent_run_root = config.parent_run_root
    if parent_run_root is None:
        raise StageError("parent_reuse requires run.parent_run_root")
    parent_stage_root = parent_run_root / stage_name
    manifest_path = parent_stage_root / "stage_manifest.json"
    manifest = _read_manifest(manifest_path)
    if manifest.get("stage") != stage_name:
        raise StageError(
            f"Parent manifest stage mismatch: expected={stage_name}, "
            f"observed={manifest.get('stage')}"
        )
    if manifest.get("status") != "complete":
        raise StageError(
            f"Parent stage is not complete: {stage_name} status={manifest.get('status')}"
        )
    inventory = _output_inventory(manifest)
    imported_rows: list[dict[str, Any]] = []
    for relative_path in config.stage(stage_name).expected_outputs:
        if stage_name == "08_shortlist_gate" and relative_path in STAGE08_DERIVED_OUTPUTS:
            continue
        source_relative = relative_path
        destination_relative = relative_path
        if (
            stage_name == "08_shortlist_gate"
            and relative_path == "tables/structural_analysis_accessions_all_members.parquet"
        ):
            source_relative = "tables/structural_analysis_accessions.parquet"
        source = parent_stage_root / source_relative
        _validate_parent_file(
            source=source,
            relative_path=source_relative,
            inventory=inventory,
        )
        action = _link_or_copy(source, stage_root / destination_relative)
        imported_rows.append(
            {
                "stage": stage_name,
                "parent_run_root": parent_run_root,
                "parent_configuration_digest": manifest.get(
                    "configuration_digest",
                    "",
                ),
                "source_relative_path": source_relative,
                "published_relative_path": destination_relative,
                "size_bytes": source.stat().st_size,
                "sha256": sha256_file(source),
                "publication_action": action,
            }
        )
    if stage_name == "08_shortlist_gate":
        from e3workflow.prioritisation import derive_structural_representatives

        derive_structural_representatives(config=config, stage_root=stage_root)
    write_tsv(
        stage_root / "provenance" / "parent_stage_import.tsv",
        imported_rows,
        (
            "stage",
            "parent_run_root",
            "parent_configuration_digest",
            "source_relative_path",
            "published_relative_path",
            "size_bytes",
            "sha256",
            "publication_action",
        ),
    )
