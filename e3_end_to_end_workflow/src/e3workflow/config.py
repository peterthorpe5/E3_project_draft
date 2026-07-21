"""Validated workflow configuration and stable stage ordering."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from e3workflow.errors import ConfigurationError

STAGE_NAMES = (
    "00_inputs",
    "01_prepared_proteomes",
    "02_discovery",
    "03_candidate_evidence",
    "04_orthofinder",
    "05_orthology",
    "06_domains",
    "07_expression",
    "08_shortlist_gate",
    "09_ligandability",
    "10_integrated_resource",
    "11_app_ready",
)
INTERNAL_PRODUCTION_STAGES = frozenset({"00_inputs", "08_shortlist_gate", "11_app_ready"})


@dataclass(frozen=True)
class StageConfig:
    """Execution contract for one named stage."""

    name: str
    enabled: bool
    required: bool
    command: tuple[str, ...]
    expected_outputs: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowConfig:
    """Fully resolved top-level workflow configuration."""

    source_path: Path
    project_root: Path
    output_root: Path
    run_name: str
    mode: str
    proteomes_manifest: Path
    seeds_manifest: Path
    shortlist_manifest: Path
    stages: tuple[StageConfig, ...]
    digest: str

    @property
    def run_root(self) -> Path:
        """Return the isolated root for this run."""
        return self.output_root / self.run_name

    def stage(self, name: str) -> StageConfig:
        """Return a configured stage by its stable name."""
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise ConfigurationError(f"Unknown stage: {name}")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    """Validate and return one mapping-like configuration section."""
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a YAML mapping")
    return value


def _resolve_path(value: Any, base: Path, label: str) -> Path:
    """Resolve a required path relative to the configuration directory."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{label} must be a non-empty path string")
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _strings(value: Any, label: str) -> tuple[str, ...]:
    """Validate a YAML sequence containing only non-empty strings."""
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ConfigurationError(f"{label} must be a list of non-empty strings")
    return tuple(value)


def load_config(path: Path) -> WorkflowConfig:
    """Load, validate, and resolve one workflow YAML file.

    Args:
        path: YAML configuration path.

    Returns:
        Immutable resolved configuration.
    """
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {source}")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read configuration {source}: {exc}") from exc
    root = _mapping(raw, "configuration")
    if root.get("schema_version") != 1:
        raise ConfigurationError("schema_version must be the integer 1")
    run = _mapping(root.get("run"), "run")
    inputs = _mapping(root.get("inputs"), "inputs")
    mode = run.get("mode")
    if mode not in {"synthetic", "production"}:
        raise ConfigurationError("run.mode must be 'synthetic' or 'production'")
    run_name = run.get("name")
    if not isinstance(run_name, str) or not run_name or "/" in run_name or run_name in {".", ".."}:
        raise ConfigurationError("run.name must be a safe, non-empty directory name")
    base = source.parent
    project_root = _resolve_path(run.get("project_root"), base, "run.project_root")
    output_root = _resolve_path(run.get("output_root"), base, "run.output_root")
    raw_stages = _mapping(root.get("stages"), "stages")
    unknown = set(raw_stages).difference(STAGE_NAMES)
    if unknown:
        raise ConfigurationError(f"Unknown stage configuration: {', '.join(sorted(unknown))}")
    stages = []
    for name in STAGE_NAMES:
        item = _mapping(raw_stages.get(name, {}), f"stages.{name}")
        enabled = item.get("enabled", True)
        required = item.get("required", True)
        if not isinstance(enabled, bool) or not isinstance(required, bool):
            raise ConfigurationError(f"enabled and required must be booleans for {name}")
        command = _strings(item.get("command"), f"stages.{name}.command")
        expected = _strings(item.get("expected_outputs"), f"stages.{name}.expected_outputs")
        if required and not enabled:
            raise ConfigurationError(f"Required stage cannot be disabled: {name}")
        missing_production_command = (
            mode == "production"
            and enabled
            and not command
            and name not in INTERNAL_PRODUCTION_STAGES
        )
        if missing_production_command:
            raise ConfigurationError(f"Production stage requires an argv command: {name}")
        for relative in expected:
            candidate = Path(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise ConfigurationError(f"Unsafe expected output for {name}: {relative}")
        stages.append(StageConfig(name, enabled, required, command, expected))
    canonical = json.dumps(root, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return WorkflowConfig(
        source_path=source,
        project_root=project_root,
        output_root=output_root,
        run_name=run_name,
        mode=mode,
        proteomes_manifest=_resolve_path(
            inputs.get("proteomes_manifest"), base, "inputs.proteomes_manifest"
        ),
        seeds_manifest=_resolve_path(inputs.get("seeds_manifest"), base, "inputs.seeds_manifest"),
        shortlist_manifest=_resolve_path(
            inputs.get("shortlist_manifest"), base, "inputs.shortlist_manifest"
        ),
        stages=tuple(stages),
        digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def previous_stage(name: str) -> str | None:
    """Return the immediately preceding stage, if one exists."""
    try:
        index = STAGE_NAMES.index(name)
    except ValueError as exc:
        raise ConfigurationError(f"Unknown stage: {name}") from exc
    return None if index == 0 else STAGE_NAMES[index - 1]
