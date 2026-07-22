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

STAGE_DEPENDENCIES = {
    "00_inputs": (),
    "01_prepared_proteomes": ("00_inputs",),
    "02_discovery": ("01_prepared_proteomes",),
    "03_candidate_evidence": ("02_discovery",),
    "04_orthofinder": ("01_prepared_proteomes",),
    "05_orthology": ("04_orthofinder",),
    "06_domains": ("03_candidate_evidence",),
    "07_expression": ("00_inputs",),
    "08_shortlist_gate": (
        "03_candidate_evidence",
        "05_orthology",
        "06_domains",
        "07_expression",
    ),
    "09_ligandability": ("08_shortlist_gate",),
    "10_integrated_resource": (
        "03_candidate_evidence",
        "05_orthology",
        "06_domains",
        "07_expression",
        "09_ligandability",
    ),
    "11_app_ready": ("10_integrated_resource",),
}

STAGE_PURPOSES = {
    "00_inputs": (
        "Validate the controlled input manifests and their checksums.",
        "All later evidence must be traceable to an explicit, unchanged input set.",
    ),
    "01_prepared_proteomes": (
        "Prepare consistently named, validated proteomes for sequence analyses.",
        "Discovery and OrthoFinder must analyse the same complete species inputs.",
    ),
    "02_discovery": (
        "Build sequence-similarity clusters and identify clusters containing known E3 seeds.",
        "This expands the evidence set without claiming that every cluster member is an E3 ligase.",
    ),
    "03_candidate_evidence": (
        "Build the candidate-evidence resource from the validated Discovery Engine database.",
        "Downstream analyses need reconciled counts, identifiers and seed evidence per cluster.",
    ),
    "04_orthofinder": (
        "Run a fresh, isolated OrthoFinder analysis on the complete proteomes.",
        (
            "Run-specific orthogroups provide evidence distinct from DeepClust sequence clusters; "
            "OrthoFinder 2.5.5 is retained because its project-reviewed phylogeny was preferred."
        ),
    ),
    "05_orthology": (
        "Reconcile candidate identifiers with the fresh OrthoFinder outputs.",
        (
            "Orthogroup and predicted-orthologue evidence must be joined through validated "
            "identifiers."
        ),
    ),
    "06_domains": (
        "Collect protein-family and domain evidence for the candidate set.",
        "Domain architecture helps assess E3 plausibility independently of sequence clustering.",
    ),
    "07_expression": (
        "Build the expression evidence resource for the configured species and datasets.",
        "Expression context is supporting evidence and can be prepared independently of orthology.",
    ),
    "08_shortlist_gate": (
        "Validate and publish the explicitly approved shortlist.",
        "Expensive structural work must follow a recorded human review decision.",
    ),
    "09_ligandability": (
        "Run structure and pocket analyses for approved proteins.",
        "Ligandability evidence is meaningful only for the controlled shortlist.",
    ),
    "10_integrated_resource": (
        "Assemble validated evidence authorities into the release resource.",
        (
            "The application requires traceable joins across discovery, orthology, domains, "
            "expression and pockets."
        ),
    ),
    "11_app_ready": (
        "Publish the application hand-off and production-readiness statement.",
        "The viewer must open only a completed, validated integrated release.",
    ),
}


@dataclass(frozen=True)
class StageConfig:
    """Execution contract for one named stage."""

    name: str
    enabled: bool
    required: bool
    command: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    threads: int
    memory_mb: int
    runtime_minutes: int


@dataclass(frozen=True)
class BenchmarkConfig:
    """Validated resource-monitoring settings.

    Attributes:
        sample_interval_seconds: Delay between process-tree samples.
        collect_slurm_accounting: Whether the final aggregation should query ``sacct``.
    """

    sample_interval_seconds: float
    collect_slurm_accounting: bool


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
    benchmarking: BenchmarkConfig
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
    raw_benchmarking = _mapping(root.get("benchmarking", {}), "benchmarking")
    sample_interval = raw_benchmarking.get("sample_interval_seconds", 5.0)
    collect_slurm = raw_benchmarking.get("collect_slurm_accounting", True)
    if (
        not isinstance(sample_interval, (int, float))
        or isinstance(sample_interval, bool)
        or sample_interval <= 0
    ):
        raise ConfigurationError(
            "benchmarking.sample_interval_seconds must be a positive number"
        )
    if not isinstance(collect_slurm, bool):
        raise ConfigurationError("benchmarking.collect_slurm_accounting must be a boolean")
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
        threads = item.get("threads", 1)
        memory_mb = item.get("memory_mb", 8_000)
        runtime_minutes = item.get("runtime_minutes", 60)
        if required and not enabled:
            raise ConfigurationError(f"Required stage cannot be disabled: {name}")
        for value, label in (
            (threads, "threads"),
            (memory_mb, "memory_mb"),
            (runtime_minutes, "runtime_minutes"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ConfigurationError(f"stages.{name}.{label} must be a positive integer")
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
        stages.append(
            StageConfig(
                name,
                enabled,
                required,
                command,
                expected,
                threads,
                memory_mb,
                runtime_minutes,
            )
        )
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
        benchmarking=BenchmarkConfig(
            sample_interval_seconds=float(sample_interval),
            collect_slurm_accounting=collect_slurm,
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


def stage_dependencies(name: str) -> tuple[str, ...]:
    """Return the scientific prerequisites for a stage.

    Args:
        name: Stable stage identifier.

    Returns:
        Ordered prerequisite stage names.

    Raises:
        ConfigurationError: If the stage name is unknown.
    """
    try:
        return STAGE_DEPENDENCIES[name]
    except KeyError as exc:
        raise ConfigurationError(f"Unknown stage: {name}") from exc


def stage_purpose(name: str) -> tuple[str, str]:
    """Return the action and scientific rationale for a stage.

    Args:
        name: Stable stage identifier.

    Returns:
        Two strings containing what the stage does and why it is required.

    Raises:
        ConfigurationError: If the stage name is unknown.
    """
    try:
        return STAGE_PURPOSES[name]
    except KeyError as exc:
        raise ConfigurationError(f"Unknown stage: {name}") from exc


def stage_ancestors(name: str) -> tuple[str, ...]:
    """Return every direct and indirect prerequisite in stable stage order.

    Args:
        name: Stable stage identifier.

    Returns:
        De-duplicated prerequisite stage names.
    """
    discovered: set[str] = set()

    def visit(stage_name: str) -> None:
        """Recursively collect prerequisites for one known stage."""
        for dependency in stage_dependencies(stage_name):
            if dependency not in discovered:
                discovered.add(dependency)
                visit(dependency)

    visit(name)
    return tuple(stage_name for stage_name in STAGE_NAMES if stage_name in discovered)
