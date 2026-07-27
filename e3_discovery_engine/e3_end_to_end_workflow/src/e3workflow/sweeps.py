"""Immutable parameter-sweep configuration generation and result comparison."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from e3workflow.config import load_config
from e3workflow.errors import ConfigurationError
from e3workflow.io_utils import atomic_write_json, sha256_file, write_tsv

SWEEP_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")
ALLOWED_SWEEP_PREFIXES = ("analysis.", "tools.")
COMPARISON_FIELDS = (
    "run_name",
    "parameter_set_sha256",
    "parameters_json",
    "cluster_id",
    "candidate_accessions",
    "final_rank",
    "recommendation_status",
    "final_score",
    "grant_aligned_prestructure_pass",
    "grant_aligned_final_pass",
    "profile_name",
)


@dataclass(frozen=True)
class SweepParameter:
    """One validated dotted configuration path and its candidate values."""

    path: str
    values: tuple[str | int | float | bool, ...]


@dataclass(frozen=True)
class SweepSpec:
    """A validated parameter-sweep definition."""

    source_path: Path
    name: str
    base_config: Path
    strategy: str
    include_baseline: bool
    maximum_runs: int
    parameters: tuple[SweepParameter, ...]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    """Validate a mapping-like YAML section."""
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a YAML mapping")
    return value


def _non_empty_string(value: Any, label: str) -> str:
    """Validate a non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{label} must be a non-empty string")
    return value.strip()


def _positive_integer(value: Any, label: str) -> int:
    """Validate a positive integer."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigurationError(f"{label} must be a positive integer")
    return value


def _scalar(value: Any, label: str) -> str | int | float | bool:
    """Validate a scalar value suitable for a master configuration."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and any(character in value for character in "\t\r\n"):
        raise ConfigurationError(f"{label} must not contain tabs or line breaks")
    if isinstance(value, float) and not math.isfinite(value):
        raise ConfigurationError(f"{label} must be finite")
    if isinstance(value, (str, int, float)) and not (
        isinstance(value, str) and not value.strip()
    ):
        return value
    raise ConfigurationError(
        f"{label} must be one non-empty string, integer, number or boolean"
    )


def _parameter_path(value: Any, label: str) -> str:
    """Validate a sweepable dotted path."""
    path = _non_empty_string(value, label)
    if not path.startswith(ALLOWED_SWEEP_PREFIXES):
        raise ConfigurationError(
            f"{label} must begin with analysis. or tools.; observed {path}"
        )
    parts = path.split(".")
    if any(SWEEP_KEY.fullmatch(part) is None for part in parts):
        raise ConfigurationError(
            f"{label} contains an unsafe path segment; use lower-case letters, numbers "
            "and underscores"
        )
    return path


def load_sweep_spec(path: Path) -> SweepSpec:
    """Load and validate a parameter-sweep YAML file.

    Args:
        path: Sweep specification path.

    Returns:
        Immutable sweep specification.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ConfigurationError(f"Sweep configuration does not exist: {source}")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read sweep configuration {source}: {exc}") from exc
    root = _mapping(raw, "sweep configuration")
    if root.get("schema_version") != 1:
        raise ConfigurationError("sweep schema_version must be the integer 1")
    name = _non_empty_string(root.get("name"), "name")
    safe_name = SAFE_NAME.sub("_", name).strip("_")
    if not safe_name or safe_name != name:
        raise ConfigurationError(
            "name must contain only letters, numbers, underscores and hyphens"
        )
    base_value = _non_empty_string(root.get("base_config"), "base_config")
    base_config = Path(base_value).expanduser()
    if not base_config.is_absolute():
        base_config = source.parent / base_config
    base_config = base_config.resolve()
    load_config(base_config)
    strategy = _non_empty_string(root.get("strategy", "cartesian"), "strategy")
    if strategy not in {"cartesian", "one_at_a_time"}:
        raise ConfigurationError("strategy must be cartesian or one_at_a_time")
    include_baseline = root.get("include_baseline", True)
    if not isinstance(include_baseline, bool):
        raise ConfigurationError("include_baseline must be a boolean")
    maximum_runs = _positive_integer(root.get("maximum_runs", 25), "maximum_runs")
    if maximum_runs > 500:
        raise ConfigurationError("maximum_runs cannot exceed 500")
    raw_parameters = root.get("parameters")
    if not isinstance(raw_parameters, list) or not raw_parameters:
        raise ConfigurationError("parameters must be a non-empty YAML list")
    parameters = []
    seen_paths: set[str] = set()
    for index, raw_parameter in enumerate(raw_parameters, start=1):
        item = _mapping(raw_parameter, f"parameters[{index}]")
        parameter_path = _parameter_path(
            item.get("path"),
            f"parameters[{index}].path",
        )
        if parameter_path in seen_paths:
            raise ConfigurationError(f"Duplicate sweep parameter path: {parameter_path}")
        seen_paths.add(parameter_path)
        raw_values = item.get("values")
        if not isinstance(raw_values, list) or not raw_values:
            raise ConfigurationError(
                f"parameters[{index}].values must be a non-empty YAML list"
            )
        values = tuple(
            _scalar(value, f"parameters[{index}].values") for value in raw_values
        )
        if len({_canonical(value) for value in values}) != len(values):
            raise ConfigurationError(f"Duplicate values for sweep parameter {parameter_path}")
        parameters.append(SweepParameter(path=parameter_path, values=values))
    unknown = set(root).difference(
        {
            "schema_version",
            "name",
            "base_config",
            "strategy",
            "include_baseline",
            "maximum_runs",
            "parameters",
        }
    )
    if unknown:
        raise ConfigurationError(
            f"Unknown sweep settings: {', '.join(sorted(unknown))}"
        )
    return SweepSpec(
        source_path=source,
        name=name,
        base_config=base_config,
        strategy=strategy,
        include_baseline=include_baseline,
        maximum_runs=maximum_runs,
        parameters=tuple(parameters),
    )


def _canonical(value: Any) -> str:
    """Return deterministic compact JSON for a value."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _read_nested(root: Mapping[str, Any], dotted_path: str) -> Any:
    """Read an existing dotted mapping path and fail on a typo."""
    current: Any = root
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ConfigurationError(
                f"Sweep parameter path is absent from the base configuration: {dotted_path}"
            )
        current = current[part]
    return current


def _write_nested(root: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Replace an existing dotted mapping path."""
    current: Any = root
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ConfigurationError(
                f"Sweep parameter path is absent from the base configuration: {dotted_path}"
            )
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise ConfigurationError(
            f"Sweep parameter path is absent from the base configuration: {dotted_path}"
        )
    current[parts[-1]] = value


def _parameter_sets(
    *,
    base: Mapping[str, Any],
    spec: SweepSpec,
) -> list[dict[str, str | int | float | bool]]:
    """Return deterministic, de-duplicated parameter combinations."""
    for parameter in spec.parameters:
        _read_nested(base, parameter.path)
    records: list[dict[str, str | int | float | bool]] = []
    if spec.include_baseline:
        records.append({})
    if spec.strategy == "cartesian":
        for values in itertools.product(*(parameter.values for parameter in spec.parameters)):
            records.append(
                {
                    parameter.path: value
                    for parameter, value in zip(spec.parameters, values)
                }
            )
    else:
        for parameter in spec.parameters:
            records.extend({parameter.path: value} for value in parameter.values)
    unique: list[dict[str, str | int | float | bool]] = []
    observed: set[str] = set()
    for record in records:
        key = _canonical(record)
        if key not in observed:
            observed.add(key)
            unique.append(record)
    if len(unique) > spec.maximum_runs:
        raise ConfigurationError(
            f"Sweep expands to {len(unique)} runs, exceeding maximum_runs={spec.maximum_runs}"
        )
    return unique


def _atomic_write_yaml(path: Path, payload: Mapping[str, Any]) -> None:
    """Write YAML atomically without reordering its documented sections."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(
        yaml.safe_dump(dict(payload), sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_run_name(base_name: str, sweep_name: str, run_index: int) -> str:
    """Return a bounded, filesystem-safe run name."""
    suffix = f"__{sweep_name}__r{run_index:03d}"
    maximum_base_length = max(1, 180 - len(suffix))
    return f"{base_name[:maximum_base_length]}{suffix}"


def prepare_sweep(
    *,
    sweep_config: Path,
    output_dir: Path,
    force: bool = False,
) -> dict[str, Any]:
    """Generate immutable workflow configurations and a TSV sweep manifest.

    Args:
        sweep_config: Validated sweep specification.
        output_dir: Destination for generated YAML files and the manifest.
        force: Replace same-named generated files, while retaining unrelated files.

    Returns:
        Machine-readable generation summary.
    """
    spec = load_sweep_spec(sweep_config)
    try:
        base_raw = yaml.safe_load(spec.base_config.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Could not read base configuration: {exc}") from exc
    base = dict(_mapping(base_raw, "base configuration"))
    base_workflow = load_config(spec.base_config)
    combinations = _parameter_sets(base=base, spec=spec)
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "sweep_runs.tsv"
    if manifest_path.exists() and not force:
        raise ConfigurationError(
            f"Sweep manifest already exists; use --force to replace generated files: "
            f"{manifest_path}"
        )
    rows = []
    for run_index, parameters in enumerate(combinations, start=1):
        run_payload = json.loads(json.dumps(base))
        for dotted_path, value in parameters.items():
            _write_nested(run_payload, dotted_path, value)
        run_name = _safe_run_name(base_workflow.run_name, spec.name, run_index)
        run_payload["schema_version"] = 2
        run_payload["path_base"] = str(spec.base_config.parent)
        run_payload["run"]["name"] = run_name
        parameter_json = _canonical(parameters)
        parameter_digest = hashlib.sha256(parameter_json.encode("utf-8")).hexdigest()
        run_payload["sweep"] = {
            "name": spec.name,
            "run_index": run_index,
            "strategy": spec.strategy,
            "base_configuration": str(spec.base_config),
            "parameter_set_sha256": parameter_digest,
            "parameters": parameters,
        }
        config_path = destination / f"run_{run_index:03d}.yaml"
        if config_path.exists() and not force:
            raise ConfigurationError(
                f"Generated configuration already exists; use --force: {config_path}"
            )
        _atomic_write_yaml(config_path, run_payload)
        generated = load_config(config_path)
        rows.append(
            {
                "run_index": run_index,
                "run_name": run_name,
                "baseline": str(not parameters).lower(),
                "config_path": config_path,
                "config_sha256": sha256_file(config_path),
                "parameter_set_sha256": parameter_digest,
                "parameters_json": parameter_json,
                "run_root": generated.run_root,
            }
        )
    write_tsv(
        manifest_path,
        rows,
        (
            "run_index",
            "run_name",
            "baseline",
            "config_path",
            "config_sha256",
            "parameter_set_sha256",
            "parameters_json",
            "run_root",
        ),
    )
    summary = {
        "status": "complete",
        "sweep_name": spec.name,
        "strategy": spec.strategy,
        "run_count": len(rows),
        "manifest": str(manifest_path),
        "output_directory": str(destination),
    }
    atomic_write_json(destination / "sweep_generation_manifest.json", summary)
    return summary


def _read_tsv(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 TSV file with a required header."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ConfigurationError(f"TSV file does not exist: {source}")
    try:
        with source.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if not reader.fieldnames:
                raise ConfigurationError(f"TSV file has no header: {source}")
            return [dict(row) for row in reader]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ConfigurationError(f"Could not read TSV file {source}: {exc}") from exc


def _as_float(value: str, label: str) -> float:
    """Parse a finite numeric comparison value."""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{label} must be numeric; observed {value!r}") from exc
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        raise ConfigurationError(f"{label} must be finite")
    return parsed


def _as_int(value: str, label: str) -> int:
    """Parse a positive integer comparison value."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{label} must be an integer; observed {value!r}") from exc
    if parsed < 1:
        raise ConfigurationError(f"{label} must be positive")
    return parsed


def _candidate_summary(
    records: Iterable[dict[str, Any]],
    completed_run_count: int,
) -> list[dict[str, Any]]:
    """Summarise candidate stability across completed sweep runs."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["cluster_id"]), []).append(record)
    summaries = []
    for cluster_id in sorted(grouped):
        candidates = grouped[cluster_id]
        ranks = [int(record["final_rank"]) for record in candidates]
        scores = [float(record["final_score"]) for record in candidates]
        statuses = sorted({str(record["recommendation_status"]) for record in candidates})
        summaries.append(
            {
                "cluster_id": cluster_id,
                "candidate_accessions": candidates[0]["candidate_accessions"],
                "completed_sweep_runs": completed_run_count,
                "runs_present": len(candidates),
                "priority_recommendation_runs": sum(
                    record["recommendation_status"] == "PRIORITY_RECOMMENDATION"
                    for record in candidates
                ),
                "stringent_pass_runs": sum(
                    str(record["grant_aligned_final_pass"]).lower() == "true"
                    for record in candidates
                ),
                "minimum_final_rank": min(ranks),
                "maximum_final_rank": max(ranks),
                "minimum_final_score": min(scores),
                "maximum_final_score": max(scores),
                "recommendation_statuses": "|".join(statuses),
            }
        )
    return summaries


def compare_sweep(
    *,
    manifest: Path,
    output_dir: Path,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    """Compare final candidate rankings across generated sweep runs.

    Args:
        manifest: ``sweep_runs.tsv`` produced by :func:`prepare_sweep`.
        output_dir: Destination for tab-separated comparison tables.
        allow_incomplete: Publish available results instead of failing on missing runs.

    Returns:
        Machine-readable comparison summary.
    """
    sweep_rows = _read_tsv(manifest)
    if not sweep_rows:
        raise ConfigurationError("Sweep manifest contains no runs")
    required = {
        "run_name",
        "config_path",
        "config_sha256",
        "parameter_set_sha256",
        "parameters_json",
        "run_root",
    }
    missing_columns = required.difference(sweep_rows[0])
    if missing_columns:
        raise ConfigurationError(
            f"Sweep manifest is missing columns: {', '.join(sorted(missing_columns))}"
        )
    statuses = []
    comparisons: list[dict[str, Any]] = []
    missing_runs = []
    for sweep_row in sweep_rows:
        config_path = Path(sweep_row["config_path"]).expanduser().resolve()
        if not config_path.is_file() or sha256_file(config_path) != sweep_row["config_sha256"]:
            raise ConfigurationError(
                f"Generated sweep configuration is missing or changed: {config_path}"
            )
        final_table = (
            Path(sweep_row["run_root"]).expanduser().resolve()
            / "10_integrated_resource"
            / "tables"
            / "final_candidate_prioritisation.tsv"
        )
        if not final_table.is_file():
            missing_runs.append(sweep_row["run_name"])
            statuses.append(
                {
                    "run_name": sweep_row["run_name"],
                    "status": "MISSING",
                    "config_path": config_path,
                    "final_table": final_table,
                    "candidate_count": 0,
                    "priority_recommendation_count": 0,
                }
            )
            continue
        final_rows = _read_tsv(final_table)
        final_required = set(COMPARISON_FIELDS).difference(
            {"run_name", "parameter_set_sha256", "parameters_json"}
        )
        missing_final_columns = final_required.difference(final_rows[0] if final_rows else {})
        if missing_final_columns:
            raise ConfigurationError(
                f"Final table is missing comparison columns: "
                f"{', '.join(sorted(missing_final_columns))}"
            )
        for final_row in final_rows:
            comparison = {
                "run_name": sweep_row["run_name"],
                "parameter_set_sha256": sweep_row["parameter_set_sha256"],
                "parameters_json": sweep_row["parameters_json"],
                "cluster_id": final_row["cluster_id"],
                "candidate_accessions": final_row["candidate_accessions"],
                "final_rank": _as_int(
                    final_row["final_rank"],
                    f"{sweep_row['run_name']}.final_rank",
                ),
                "recommendation_status": final_row["recommendation_status"],
                "final_score": _as_float(
                    final_row["final_score"],
                    f"{sweep_row['run_name']}.final_score",
                ),
                "grant_aligned_prestructure_pass": final_row[
                    "grant_aligned_prestructure_pass"
                ],
                "grant_aligned_final_pass": final_row["grant_aligned_final_pass"],
                "profile_name": final_row["profile_name"],
            }
            comparisons.append(comparison)
        statuses.append(
            {
                "run_name": sweep_row["run_name"],
                "status": "COMPLETE",
                "config_path": config_path,
                "final_table": final_table,
                "candidate_count": len(final_rows),
                "priority_recommendation_count": sum(
                    row["recommendation_status"] == "PRIORITY_RECOMMENDATION"
                    for row in final_rows
                ),
            }
        )
    if missing_runs and not allow_incomplete:
        raise ConfigurationError(
            "Sweep runs are incomplete: " + ", ".join(sorted(missing_runs))
        )
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    write_tsv(
        destination / "sweep_run_status.tsv",
        statuses,
        (
            "run_name",
            "status",
            "config_path",
            "final_table",
            "candidate_count",
            "priority_recommendation_count",
        ),
    )
    write_tsv(
        destination / "sweep_candidate_sensitivity.tsv",
        comparisons,
        COMPARISON_FIELDS,
    )
    completed_run_count = sum(record["status"] == "COMPLETE" for record in statuses)
    candidate_summaries = _candidate_summary(comparisons, completed_run_count)
    write_tsv(
        destination / "sweep_candidate_summary.tsv",
        candidate_summaries,
        (
            "cluster_id",
            "candidate_accessions",
            "completed_sweep_runs",
            "runs_present",
            "priority_recommendation_runs",
            "stringent_pass_runs",
            "minimum_final_rank",
            "maximum_final_rank",
            "minimum_final_score",
            "maximum_final_score",
            "recommendation_statuses",
        ),
    )
    summary = {
        "status": "complete" if not missing_runs else "partial",
        "configured_run_count": len(sweep_rows),
        "completed_run_count": completed_run_count,
        "missing_run_count": len(missing_runs),
        "candidate_count": len(candidate_summaries),
        "output_directory": str(destination),
    }
    atomic_write_json(destination / "sweep_comparison_manifest.json", summary)
    return summary
