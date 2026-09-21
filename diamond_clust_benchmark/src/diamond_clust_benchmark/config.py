"""Validated configuration for reproducible DIAMOND benchmarks."""

from __future__ import annotations

import re
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

import yaml

from diamond_clust_benchmark.exceptions import ConfigurationError

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_MEMORY = re.compile(r"^[1-9]\d*(?:\.\d+)?[KMGTP]?$", re.IGNORECASE)
_RESERVED_ARGS = {
    "--db",
    "--database",
    "--out",
    "--threads",
    "--memory-limit",
    "--id",
    "--approx-id",
    "--mutual-cover",
    "--member-cover",
    "--evalue",
    "--tmpdir",
    "--header",
    "--comp-based-stats",
    "--masking",
    "--cluster-steps",
    "--no-reassign",
}


@dataclass(frozen=True)
class BenchmarkCase:
    """Describe one DIAMOND executable and clustering strategy.

    Attributes:
        case_id: Stable identifier used in output paths and tables.
        executable: DIAMOND executable name or absolute path.
        conda_environment: Optional Conda environment used via ``conda run``.
        expected_version: Exact DIAMOND version required for the case.
        command: ``deepclust`` or ``linclust``.
        identity_mode: ``exact`` or ``approximate``.
        identity_percent: Minimum clustering identity percentage.
        mutual_cover_percent: Minimum bidirectional coverage percentage.
        evalue: Clustering-stage e-value threshold.
        comp_based_stats: DIAMOND composition-statistics mode.
        masking: Symmetric masking mode.
        cluster_steps: Optional explicit cascaded clustering steps.
        no_reassign: Disable final representative reassignment when true.
        extra_args: Additional non-reserved DIAMOND arguments.
        run_realign: Time exact representative-member realignment.
        enabled: Include the case in the benchmark matrix.
    """

    case_id: str
    executable: str
    conda_environment: Optional[str]
    expected_version: str
    command: str
    identity_mode: str
    identity_percent: float
    mutual_cover_percent: float
    evalue: float
    comp_based_stats: int
    masking: Optional[str]
    cluster_steps: Tuple[str, ...]
    no_reassign: bool
    extra_args: Tuple[str, ...]
    run_realign: bool
    enabled: bool


@dataclass(frozen=True)
class BenchmarkConfiguration:
    """Complete validated benchmark configuration."""

    config_path: Path
    project_name: str
    input_fasta: Path
    expected_sequences: Optional[int]
    expected_residues: Optional[int]
    sentinel_ids_tsv: Optional[Path]
    output_root: Path
    scratch_root: Optional[Path]
    threads: int
    memory_limit: str
    sampling_interval_seconds: float
    repeats: int
    quality_repeat: int
    baseline_case_id: str
    decision_stage: str
    minimum_speedup_percent: float
    minimum_pairwise_f1: float
    minimum_sentinel_recall: float
    bootstrap_iterations: int
    cases: Tuple[BenchmarkCase, ...]

    @property
    def enabled_cases(self) -> Tuple[BenchmarkCase, ...]:
        """Return enabled cases in configured order."""

        return tuple(case for case in self.cases if case.enabled)

    def case_by_id(self, case_id: str) -> BenchmarkCase:
        """Resolve one enabled case by identifier.

        Args:
            case_id: Configured case identifier.

        Returns:
            Matching enabled benchmark case.

        Raises:
            ConfigurationError: If the identifier is absent or disabled.
        """

        for case in self.enabled_cases:
            if case.case_id == case_id:
                return case
        raise ConfigurationError(f"Unknown or disabled benchmark case: {case_id}")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    """Require and return a mapping value."""

    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{label} must be a mapping")
    return value


def _identifier(value: object, label: str) -> str:
    """Validate a filesystem-safe identifier."""

    text = str(value or "")
    if not _IDENTIFIER.fullmatch(text):
        raise ConfigurationError(
            f"{label} must contain only letters, digits, '.', '_' or '-'"
        )
    return text


def _resolve_path(
    value: object,
    base: Path,
    label: str,
    required: bool = True,
) -> Optional[Path]:
    """Resolve an optional configuration path relative to its YAML file."""

    if value is None or value == "":
        if required:
            raise ConfigurationError(f"{label} is required")
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _positive_int(value: object, label: str) -> int:
    """Parse a strictly positive integer without accepting booleans."""

    if isinstance(value, bool):
        raise ConfigurationError(f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(
            f"{label} must be a positive integer"
        ) from error
    if parsed < 1:
        raise ConfigurationError(f"{label} must be a positive integer")
    return parsed


def _optional_count(value: object, label: str) -> Optional[int]:
    """Parse an optional positive expected count."""

    if value is None or value == "":
        return None
    return _positive_int(value, label)


def _percentage(value: object, label: str, allow_zero: bool = False) -> float:
    """Parse a percentage constrained to zero-to-one-hundred."""

    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"{label} must be numeric") from error
    minimum = 0.0 if allow_zero else 0.0 + 1e-12
    if not math.isfinite(parsed) or parsed < minimum or parsed > 100.0:
        boundary = "[0, 100]" if allow_zero else "(0, 100]"
        raise ConfigurationError(f"{label} must be in {boundary}")
    return parsed


def _boolean(value: object, label: str) -> bool:
    """Require a YAML boolean instead of accepting truthy strings."""

    if not isinstance(value, bool):
        raise ConfigurationError(f"{label} must be true or false")
    return value


def _string_tuple(value: object, label: str) -> Tuple[str, ...]:
    """Convert a YAML list of scalar tokens to an immutable tuple."""

    if value is None or value == "":
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ConfigurationError(f"{label} must be a list")
    tokens = tuple(str(item) for item in value)
    if any(
        not token or any(character.isspace() for character in token)
        for token in tokens
    ):
        raise ConfigurationError(f"{label} entries must be non-empty tokens")
    return tokens


def _parse_case(
    raw_value: object,
    index: int,
    base: Path,
) -> BenchmarkCase:
    """Parse and validate one benchmark case mapping."""

    raw = _mapping(raw_value, f"benchmark.cases[{index}]")
    case_id = _identifier(raw.get("case_id"), f"benchmark.cases[{index}].case_id")
    command = str(raw.get("command", "deepclust"))
    if command not in {"deepclust", "linclust"}:
        raise ConfigurationError(f"{case_id}: command must be deepclust or linclust")
    identity_mode = str(raw.get("identity_mode", "exact"))
    if identity_mode not in {"exact", "approximate"}:
        raise ConfigurationError(
            f"{case_id}: identity_mode must be exact or approximate"
        )
    expected_version = str(raw.get("expected_version", ""))
    if not _VERSION.fullmatch(expected_version):
        raise ConfigurationError(
            f"{case_id}: expected_version must use major.minor.patch"
        )
    comp_based_stats = int(raw.get("comp_based_stats", 0))
    if not 0 <= comp_based_stats <= 6:
        raise ConfigurationError(f"{case_id}: comp_based_stats must be 0 to 6")
    if identity_mode == "exact" and comp_based_stats not in {0, 1}:
        raise ConfigurationError(
            f"{case_id}: exact identity requires comp_based_stats 0 or 1"
        )
    masking_value = raw.get("masking", "tantan")
    masking = None if masking_value in {None, ""} else str(masking_value)
    if masking not in {None, "none", "tantan"}:
        raise ConfigurationError(
            f"{case_id}: masking must be tantan, none or null"
        )
    extra_args = _string_tuple(raw.get("extra_args", []), f"{case_id}.extra_args")
    conflicts = sorted(
        token
        for token in extra_args
        if token in _RESERVED_ARGS
        or any(token.startswith(f"{option}=") for option in _RESERVED_ARGS)
    )
    if conflicts:
        raise ConfigurationError(
            f"{case_id}: extra_args cannot override managed options: "
            + ", ".join(conflicts)
        )
    conda_value = raw.get("conda_environment")
    conda_environment = None
    if conda_value is not None and conda_value != "":
        conda_environment = _identifier(
            conda_value,
            "conda_environment",
        )
    executable = str(raw.get("executable", "diamond")).strip()
    if not executable:
        raise ConfigurationError(f"{case_id}: executable cannot be empty")
    if "/" in executable:
        executable_path = Path(executable).expanduser()
        if not executable_path.is_absolute():
            executable_path = base / executable_path
        executable = str(executable_path.resolve())
    try:
        evalue = float(raw.get("evalue", 0.1))
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"{case_id}: evalue must be numeric") from error
    if not math.isfinite(evalue) or evalue <= 0:
        raise ConfigurationError(f"{case_id}: evalue must be positive")
    return BenchmarkCase(
        case_id=case_id,
        executable=executable,
        conda_environment=conda_environment,
        expected_version=expected_version,
        command=command,
        identity_mode=identity_mode,
        identity_percent=_percentage(
            raw.get("identity_percent", 50),
            f"{case_id}.identity_percent",
        ),
        mutual_cover_percent=_percentage(
            raw.get("mutual_cover_percent", 50),
            f"{case_id}.mutual_cover_percent",
        ),
        evalue=evalue,
        comp_based_stats=comp_based_stats,
        masking=masking,
        cluster_steps=_string_tuple(
            raw.get("cluster_steps", []),
            f"{case_id}.cluster_steps",
        ),
        no_reassign=_boolean(
            raw.get("no_reassign", False),
            f"{case_id}.no_reassign",
        ),
        extra_args=extra_args,
        run_realign=_boolean(
            raw.get("run_realign", True),
            f"{case_id}.run_realign",
        ),
        enabled=_boolean(
            raw.get("enabled", True),
            f"{case_id}.enabled",
        ),
    )


def load_config(path: Path, check_paths: bool = True) -> BenchmarkConfiguration:
    """Load and validate a YAML benchmark configuration.

    Args:
        path: YAML configuration path.
        check_paths: Require input files to exist when true.

    Returns:
        Immutable validated configuration.

    Raises:
        ConfigurationError: If the YAML or any configured value is invalid.
    """

    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {config_path}")
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigurationError(f"Invalid YAML in {config_path}: {error}") from error
    root = _mapping(loaded, "configuration")
    project = _mapping(root.get("project"), "project")
    inputs = _mapping(root.get("inputs"), "inputs")
    outputs = _mapping(root.get("outputs"), "outputs")
    resources = _mapping(root.get("resources"), "resources")
    benchmark = _mapping(root.get("benchmark"), "benchmark")
    base = config_path.parent
    input_fasta = _resolve_path(inputs.get("fasta"), base, "inputs.fasta")
    sentinel_ids = _resolve_path(
        inputs.get("sentinel_ids_tsv"),
        base,
        "inputs.sentinel_ids_tsv",
        required=False,
    )
    output_root = _resolve_path(outputs.get("root"), base, "outputs.root")
    scratch_value = outputs.get("scratch_root")
    scratch_root = None
    if scratch_value not in {None, "", "auto"}:
        scratch_root = _resolve_path(
            scratch_value,
            base,
            "outputs.scratch_root",
        )
    raw_cases = benchmark.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ConfigurationError("benchmark.cases must be a non-empty list")
    cases = tuple(
        _parse_case(value, index, base)
        for index, value in enumerate(raw_cases)
    )
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ConfigurationError("benchmark case identifiers must be unique")
    enabled_ids = {case.case_id for case in cases if case.enabled}
    baseline = str(benchmark.get("baseline_case_id", ""))
    if baseline not in enabled_ids:
        raise ConfigurationError("baseline_case_id must identify an enabled case")
    repeats = _positive_int(benchmark.get("repeats", 3), "benchmark.repeats")
    quality_repeat = _positive_int(
        benchmark.get("quality_repeat", 1),
        "benchmark.quality_repeat",
    )
    if quality_repeat > repeats:
        raise ConfigurationError("quality_repeat cannot exceed repeats")
    decision_stage = str(benchmark.get("decision_stage", "pairwise_pipeline"))
    if decision_stage not in {"cluster", "pairwise_pipeline", "total_pipeline"}:
        raise ConfigurationError(
            "decision_stage must be cluster, pairwise_pipeline or total_pipeline"
        )
    memory_limit = str(resources.get("diamond_memory_limit", "220G"))
    if not _MEMORY.fullmatch(memory_limit):
        raise ConfigurationError("resources.diamond_memory_limit is invalid")
    sampling_interval = float(resources.get("sampling_interval_seconds", 0.2))
    if not 0.05 <= sampling_interval <= 60.0:
        raise ConfigurationError(
            "resources.sampling_interval_seconds must be from 0.05 to 60"
        )
    bootstrap_iterations = _positive_int(
        benchmark.get("bootstrap_iterations", 10000),
        "benchmark.bootstrap_iterations",
    )
    configuration = BenchmarkConfiguration(
        config_path=config_path,
        project_name=_identifier(project.get("name"), "project.name"),
        input_fasta=input_fasta,
        expected_sequences=_optional_count(
            inputs.get("expected_sequences"),
            "inputs.expected_sequences",
        ),
        expected_residues=_optional_count(
            inputs.get("expected_residues"),
            "inputs.expected_residues",
        ),
        sentinel_ids_tsv=sentinel_ids,
        output_root=output_root,
        scratch_root=scratch_root,
        threads=_positive_int(resources.get("threads", 32), "resources.threads"),
        memory_limit=memory_limit,
        sampling_interval_seconds=sampling_interval,
        repeats=repeats,
        quality_repeat=quality_repeat,
        baseline_case_id=baseline,
        decision_stage=decision_stage,
        minimum_speedup_percent=_percentage(
            benchmark.get("minimum_speedup_percent", 10),
            "benchmark.minimum_speedup_percent",
            allow_zero=True,
        ),
        minimum_pairwise_f1=float(benchmark.get("minimum_pairwise_f1", 0.99)),
        minimum_sentinel_recall=float(
            benchmark.get("minimum_sentinel_recall", 0.99)
        ),
        bootstrap_iterations=bootstrap_iterations,
        cases=cases,
    )
    for label, value in (
        ("minimum_pairwise_f1", configuration.minimum_pairwise_f1),
        ("minimum_sentinel_recall", configuration.minimum_sentinel_recall),
    ):
        if not 0.0 <= value <= 1.0:
            raise ConfigurationError(f"benchmark.{label} must be in [0, 1]")
    if check_paths:
        for label, candidate in (
            ("inputs.fasta", configuration.input_fasta),
            ("inputs.sentinel_ids_tsv", configuration.sentinel_ids_tsv),
        ):
            if candidate is not None and not candidate.is_file():
                raise ConfigurationError(f"{label} does not exist: {candidate}")
    return configuration


def configuration_to_dict(config: BenchmarkConfiguration) -> dict[str, object]:
    """Create a JSON-compatible representation of validated configuration.

    Args:
        config: Validated configuration object.

    Returns:
        Nested dictionary suitable for a provenance manifest.
    """

    return {
        "config_path": str(config.config_path),
        "project_name": config.project_name,
        "input_fasta": str(config.input_fasta),
        "expected_sequences": config.expected_sequences,
        "expected_residues": config.expected_residues,
        "sentinel_ids_tsv": (
            str(config.sentinel_ids_tsv) if config.sentinel_ids_tsv else None
        ),
        "output_root": str(config.output_root),
        "scratch_root": str(config.scratch_root) if config.scratch_root else None,
        "threads": config.threads,
        "memory_limit": config.memory_limit,
        "sampling_interval_seconds": config.sampling_interval_seconds,
        "repeats": config.repeats,
        "quality_repeat": config.quality_repeat,
        "baseline_case_id": config.baseline_case_id,
        "decision_stage": config.decision_stage,
        "minimum_speedup_percent": config.minimum_speedup_percent,
        "minimum_pairwise_f1": config.minimum_pairwise_f1,
        "minimum_sentinel_recall": config.minimum_sentinel_recall,
        "bootstrap_iterations": config.bootstrap_iterations,
        "cases": [case.__dict__ for case in config.enabled_cases],
    }
