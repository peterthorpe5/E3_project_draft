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
    """Load a YAML configuration file as a dictionary.

    Args:
        path: Path to the UTF-8 YAML file.

    Returns:
        The top-level YAML mapping as a mutable dictionary.

    Raises:
        FileNotFoundError: If ``path`` is not an existing file.
        yaml.YAMLError: If the YAML syntax is invalid.
        ConfigurationError: If the YAML root is not a mapping.
    """

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Configuration file does not exist: {source}")
    with source.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ConfigurationError("The configuration root must be a mapping")
    return data


def _require_mapping(config: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Retrieve a required configuration section and verify its type.

    Args:
        config: Parent configuration mapping.
        key: Section name to retrieve.

    Returns:
        The requested nested mapping.

    Raises:
        ConfigurationError: If the section is absent or is not a mapping.
    """
    value = config.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"Configuration section '{key}' must be a mapping")
    return value


def _require_positive_number(section: Mapping[str, Any], key: str) -> float:
    """Retrieve a required positive numeric configuration value.

    Args:
        section: Configuration section containing the value.
        key: Name of the numeric setting.

    Returns:
        The validated setting converted to ``float``.

    Raises:
        ConfigurationError: If the value is absent, non-numeric or not
            positive.
    """
    value = section.get(key)
    if not isinstance(value, (int, float)) or value <= 0:
        raise ConfigurationError(f"'{key}' must be a positive number")
    return float(value)


def validate_config(config: Mapping[str, Any]) -> None:
    """Validate the complete workflow configuration without modifying it.

    Validation covers required sections, input/output settings, DIAMOND
    identity and matrix compatibility, strict thresholds, resource controls,
    benchmark repeats and sequence-identifier policy.

    Args:
        config: Parsed workflow configuration mapping.

    Returns:
        None.

    Raises:
        ConfigurationError: If a required value is missing, has the wrong type,
            falls outside its valid range or conflicts with another setting.
    """

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
    path_alias_root = diamond.get("path_alias_root")
    if path_alias_root is not None:
        alias_text = str(path_alias_root)
        if not alias_text.strip():
            raise ConfigurationError(
                "diamond.path_alias_root must be omitted or a non-empty path"
            )
        if any(character.isspace() for character in alias_text):
            raise ConfigurationError(
                "diamond.path_alias_root must not contain whitespace"
            )
    tmpdir = diamond.get("tmpdir")
    if tmpdir is not None and not str(tmpdir).strip():
        raise ConfigurationError(
            "diamond.tmpdir must be omitted or a non-empty path"
        )
    comp_based_stats = diamond.get("comp_based_stats", 0)
    if (
        not isinstance(comp_based_stats, int)
        or not 0 <= comp_based_stats <= 6
    ):
        raise ConfigurationError(
            "diamond.comp_based_stats must be an integer from 0 to 6"
        )
    if identity_mode == "exact" and comp_based_stats not in {0, 1}:
        raise ConfigurationError(
            "diamond.identity_mode 'exact' requires traceback and therefore "
            "diamond.comp_based_stats must be 0 or 1"
        )

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
    """Resolve configured workflow paths relative to the configuration file.

    The input mapping is deep-copied. Only recognised path fields are expanded
    and resolved, so the caller's configuration object is not modified.

    Args:
        config: Validated workflow configuration mapping.
        config_path: Location of the YAML file used as the relative-path base.

    Returns:
        A deep-copied dictionary containing absolute resolved path strings.
    """

    resolved = deepcopy(dict(config))
    base = Path(config_path).resolve().parent

    path_fields = [
        ("inputs", "samples_tsv"),
        ("inputs", "e3_seed_table"),
        ("outputs", "root"),
    ]
    if resolved.get("diamond", {}).get("tmpdir") is not None:
        path_fields.append(("diamond", "tmpdir"))
    if resolved.get("diamond", {}).get("path_alias_root") is not None:
        path_fields.append(("diamond", "path_alias_root"))
    for section, key in path_fields:
        raw = Path(str(resolved[section][key])).expanduser()
        if not raw.is_absolute():
            raw = base / raw
        resolved[section][key] = str(raw.resolve())

    return resolved


def load_config(path: Path) -> Dict[str, Any]:
    """Load, validate and path-resolve a workflow YAML configuration.

    Args:
        path: Path to the workflow configuration file.

    Returns:
        A validated configuration dictionary with absolute workflow paths.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        yaml.YAMLError: If the YAML syntax is invalid.
        ConfigurationError: If configuration values fail validation.
    """

    raw = load_yaml(path)
    validate_config(raw)
    return resolve_paths(raw, Path(path))
