"""Configuration loading and validation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping

import yaml

from e3_discovery.exceptions import ConfigurationError

_REQUIRED_TOP_LEVEL = (
    "project",
    "inputs",
    "outputs",
    "diamond",
    "thresholds",
    "resources",
)


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML mapping from disk."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Configuration file does not exist: {source}")
    with source.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ConfigurationError("The configuration root must be a mapping")
    return data


def _require_mapping(config: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = config.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"Configuration section '{key}' must be a mapping")
    return value


def _require_positive_number(section: Mapping[str, Any], key: str) -> float:
    value = section.get(key)
    if not isinstance(value, (int, float)) or value <= 0:
        raise ConfigurationError(f"'{key}' must be a positive number")
    return float(value)


def validate_config(config: Mapping[str, Any]) -> None:
    """Validate required settings and incompatible parameter combinations."""

    missing = [key for key in _REQUIRED_TOP_LEVEL if key not in config]
    if missing:
        raise ConfigurationError(
            "Missing top-level configuration sections: " + ", ".join(missing)
        )

    for key in _REQUIRED_TOP_LEVEL:
        _require_mapping(config, key)

    project = _require_mapping(config, "project")
    if not str(project.get("name", "")).strip():
        raise ConfigurationError("project.name must be a non-empty string")

    inputs = _require_mapping(config, "inputs")
    for key in ("samples_tsv", "e3_seed_table"):
        if not str(inputs.get(key, "")).strip():
            raise ConfigurationError(f"inputs.{key} must be set")

    outputs = _require_mapping(config, "outputs")
    if not str(outputs.get("root", "")).strip():
        raise ConfigurationError("outputs.root must be set")

    diamond = _require_mapping(config, "diamond")
    identity_mode = diamond.get("identity_mode")
    if identity_mode not in {"approximate", "exact"}:
        raise ConfigurationError(
            "diamond.identity_mode must be 'approximate' or 'exact'"
        )
    identity = _require_positive_number(diamond, "identity_percent")
    if identity > 100:
        raise ConfigurationError("diamond.identity_percent cannot exceed 100")
    cover = _require_positive_number(diamond, "mutual_cover_percent")
    if cover > 100:
        raise ConfigurationError(
            "diamond.mutual_cover_percent cannot exceed 100"
        )
    _require_positive_number(diamond, "clustering_evalue")
    if not str(diamond.get("memory_limit", "")).strip():
        raise ConfigurationError("diamond.memory_limit must be set")
    if not str(diamond.get("executable", "diamond")).strip():
        raise ConfigurationError("diamond.executable must be a non-empty string")
    if not isinstance(diamond.get("cluster_steps", []), list):
        raise ConfigurationError("diamond.cluster_steps must be a list")
    if not isinstance(diamond.get("extra_args", []), list):
        raise ConfigurationError("diamond.extra_args must be a list")

    thresholds = _require_mapping(config, "thresholds")
    for key in (
        "minimum_percent_identity",
        "minimum_representative_coverage",
        "minimum_member_coverage",
        "minimum_bitscore",
        "maximum_evalue",
    ):
        value = _require_positive_number(thresholds, key)
        if "coverage" in key or "identity" in key:
            if value > 100:
                raise ConfigurationError(f"thresholds.{key} cannot exceed 100")

    resources = _require_mapping(config, "resources")
    threads = resources.get("threads")
    if not isinstance(threads, int) or threads < 1:
        raise ConfigurationError("resources.threads must be a positive integer")
    batch_size = resources.get("parquet_batch_size")
    if not isinstance(batch_size, int) or batch_size < 1:
        raise ConfigurationError(
            "resources.parquet_batch_size must be a positive integer"
        )

    benchmarking = config.get("benchmarking", {})
    if not isinstance(benchmarking, Mapping):
        raise ConfigurationError(
            "Configuration section 'benchmarking' must be a mapping"
        )
    repeats = benchmarking.get("repeats", 1)
    if not isinstance(repeats, int) or repeats < 1:
        raise ConfigurationError("benchmarking.repeats must be a positive integer")

    identifier_mode = inputs.get("identifier_mode", "prefix_sample")
    if identifier_mode not in {"prefix_sample", "preserve"}:
        raise ConfigurationError(
            "inputs.identifier_mode must be 'prefix_sample' or 'preserve'"
        )


def resolve_paths(config: Mapping[str, Any], config_path: Path) -> Dict[str, Any]:
    """Return a deep copy with relative file paths resolved from the YAML file."""

    resolved = deepcopy(dict(config))
    base = Path(config_path).resolve().parent

    path_fields = (
        ("inputs", "samples_tsv"),
        ("inputs", "e3_seed_table"),
        ("outputs", "root"),
    )
    for section, key in path_fields:
        raw = Path(str(resolved[section][key])).expanduser()
        if not raw.is_absolute():
            raw = base / raw
        resolved[section][key] = str(raw.resolve())

    return resolved


def load_config(path: Path) -> Dict[str, Any]:
    """Load, validate, and resolve a workflow configuration file."""

    raw = load_yaml(path)
    validate_config(raw)
    return resolve_paths(raw, Path(path))
