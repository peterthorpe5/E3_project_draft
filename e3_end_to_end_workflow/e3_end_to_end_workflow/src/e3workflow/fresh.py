"""Strict preflight checks for a complete clean-room production run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from e3workflow.config import WorkflowConfig, load_config
from e3workflow.errors import ConfigurationError

FRESH_EVIDENCE_MODES = {
    "00_inputs": frozenset({"validate"}),
    "01_prepared_proteomes": frozenset({"prepare"}),
    "02_discovery": frozenset({"generate"}),
    "03_candidate_evidence": frozenset({"generate"}),
    "04_orthofinder": frozenset({"generate"}),
    "05_orthology": frozenset({"derive"}),
    "06_domains": frozenset({"download", "generate"}),
    "07_expression": frozenset({"generate"}),
    "08_shortlist_gate": frozenset({"derive"}),
    "09_ligandability": frozenset({"generate"}),
    "09b_structural_alignment": frozenset({"generate"}),
    "10_integrated_resource": frozenset({"derive"}),
    "11_app_ready": frozenset({"derive"}),
}
COMMAND_REQUIRED = frozenset(
    {
        "02_discovery",
        "03_candidate_evidence",
        "04_orthofinder",
        "05_orthology",
        "07_expression",
        "09_ligandability",
        "09b_structural_alignment",
    }
)


def _contains_placeholder(value: Any) -> bool:
    """Return whether a nested value contains an unresolved template marker."""
    if isinstance(value, str):
        return "CHANGE_ME" in value
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_placeholder(item) for item in value)
    return False


def _validate_unused_reuse_resources(config: WorkflowConfig) -> None:
    """Reject previous-analysis authorities in a declared fresh run."""
    forbidden = {
        "candidate_evidence": config.resources.candidate_evidence,
        "candidate_evidence_manifest": config.resources.candidate_evidence_manifest,
        "orthofinder_archive": config.resources.orthofinder_archive,
        "expression_manifest": config.resources.expression_manifest,
        "ligandability_manifest": config.resources.ligandability_manifest,
        "domain_annotation_manifest": config.resources.domain_annotation_manifest,
    }
    supplied = sorted(name for name, path in forbidden.items() if path is not None)
    if supplied:
        raise ConfigurationError(
            "Fresh run must not supply reusable result authorities: "
            + ", ".join(supplied)
        )


def validate_fresh_config(
    *,
    config_path: Path,
    allow_existing_run: bool = False,
) -> dict[str, Any]:
    """Validate that a configuration will generate the complete workflow afresh.

    Args:
        config_path: Master workflow YAML.
        allow_existing_run: Permit the same run root for a checksum-validated resume.

    Returns:
        Machine-readable clean-room preflight summary.
    """
    config = load_config(config_path)
    if config.mode != "production":
        raise ConfigurationError("Fresh end-to-end execution requires run.mode: production")
    if config.schema_version < 2:
        raise ConfigurationError(
            "Fresh end-to-end execution requires schema_version: 2 and a central tools section"
        )
    if not config.tools:
        raise ConfigurationError("Fresh end-to-end execution requires a non-empty tools section")
    for stage_name, permitted_modes in FRESH_EVIDENCE_MODES.items():
        stage = config.stage(stage_name)
        if not stage.enabled:
            raise ConfigurationError(
                f"Fresh complete run requires stage {stage_name} to be enabled"
            )
        if stage.evidence_mode not in permitted_modes:
            raise ConfigurationError(
                f"Fresh complete run requires {stage_name}.evidence_mode to be one of "
                f"{', '.join(sorted(permitted_modes))}; observed {stage.evidence_mode}"
            )
        if stage_name in COMMAND_REQUIRED and not stage.command:
            raise ConfigurationError(
                f"Fresh complete run requires an external argv command for {stage_name}"
            )
        if _contains_placeholder(stage.command):
            raise ConfigurationError(
                f"Fresh complete run contains an unresolved CHANGE_ME marker in {stage_name}"
            )
    if _contains_placeholder(config.tool_records()):
        raise ConfigurationError(
            "Fresh complete run contains an unresolved CHANGE_ME marker in tools"
        )
    _validate_unused_reuse_resources(config)
    if config.run_root.exists() and any(config.run_root.iterdir()) and not allow_existing_run:
        raise ConfigurationError(
            f"Fresh run root is not empty: {config.run_root}. Use a new run.name, or use "
            "--resume only when continuing this exact checksum-bound run."
        )
    return {
        "status": "valid",
        "mode": config.mode,
        "configuration_schema_version": config.schema_version,
        "run_root": str(config.run_root),
        "stage_count": len(FRESH_EVIDENCE_MODES),
        "tool_count": len(config.tools),
        "maximum_stage_threads": max(stage.threads for stage in config.stages),
        "allow_existing_run": allow_existing_run,
    }
