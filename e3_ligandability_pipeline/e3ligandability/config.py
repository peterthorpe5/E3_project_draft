"""Configuration loading and validation for the ligandability workflow."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "name": "ARIA plant E3 ligandability",
        "run_label": "run",
    },
    "input": {
        "accession_column": "accession",
    },
    "alphafold": {
        "api_base_url": "https://alphafold.ebi.ac.uk/api/prediction",
        "request_timeout_seconds": 60,
        "retry_total": 8,
        "retry_backoff_seconds": 2.0,
        "download_pae": True,
        "download_msa": False,
        "download_plddt_json": True,
        "reuse_valid_files": True,
        "query_api_for_local_models": True,
    },
    "external_tools": {
        "run_fpocket_p2rank": True,
        "fpocket_executable": "fpocket",
        "p2rank_executable": "prank",
        "p2rank_model": "rescore_2024",
        "p2rank_threads": 8,
        "p2rank_keep_fpocket_output": True,
        "p2rank_version_arguments": ["-v"],
        "fpocket_version_arguments": ["--version"],
        "required_p2rank_version_prefix": "2.5.1",
        "required_fpocket_version_prefix": "",
        "command_timeout_seconds": 7200,
    },
    "quality": {
        "model_confident_threshold": 70.0,
        "model_very_high_threshold": 90.0,
        "minimum_fraction_residues_ge_70": 0.50,
        "minimum_pocket_mapping_fraction": 0.95,
        "api_fraction_tolerance": 0.01,
        "api_mean_plddt_tolerance": 0.25,
    },
    "execution": {
        "continue_on_accession_error": True,
        "fail_run_if_any_accession_failed": True,
        "checksum_algorithm": "sha256",
    },
    "output": {
        "write_tsv": True,
        "write_parquet": True,
        "write_duckdb": True,
    },
}

_REQUIRED_SECTIONS = {
    "project",
    "input",
    "alphafold",
    "external_tools",
    "quality",
    "execution",
    "output",
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge configuration dictionaries.

    Args:
        base: Baseline configuration dictionary.
        override: User-supplied values that take precedence.

    Returns:
        A new merged dictionary. Neither input is modified.
    """

    result = deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_config(path: Path | None) -> dict[str, Any]:
    """Load YAML configuration and apply documented defaults.

    Args:
        path: Optional YAML file. When omitted, defaults are returned.

    Returns:
        Validated merged configuration.

    Raises:
        FileNotFoundError: If a requested configuration file is absent.
        ValueError: If YAML content is not a mapping or values are invalid.
    """

    if path is None:
        config = deepcopy(DEFAULT_CONFIG)
    else:
        config_path = Path(path).expanduser().resolve()
        if not config_path.is_file():
            raise FileNotFoundError(
                f"Configuration file does not exist: {config_path}"
            )
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise ValueError("Configuration root must be a YAML mapping.")
        config = deep_merge(DEFAULT_CONFIG, loaded)

    validate_config(config)
    return config


def _require_positive_number(value: Any, field_name: str) -> float:
    """Validate a positive numeric configuration value.

    Args:
        value: Candidate value.
        field_name: Human-readable configuration field name.

    Returns:
        The value converted to float.

    Raises:
        ValueError: If the value is not numeric and strictly positive.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric.")
    numeric = float(value)
    if numeric <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return numeric


def _require_fraction(value: Any, field_name: str) -> float:
    """Validate a numeric value constrained to the closed interval [0, 1].

    Args:
        value: Candidate value.
        field_name: Human-readable configuration field name.

    Returns:
        The value converted to float.

    Raises:
        ValueError: If the value is not a valid fraction.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric.")
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1.")
    return numeric


def _require_positive_integer(value: Any, field_name: str) -> int:
    """Validate a strictly positive integer configuration value.

    Args:
        value: Candidate value.
        field_name: Human-readable configuration field name.

    Returns:
        Validated integer.

    Raises:
        ValueError: If the value is not a strictly positive integer.
    """

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _require_boolean(value: Any, field_name: str) -> bool:
    """Validate a Boolean configuration field without truthy coercion.

    Args:
        value: Candidate value.
        field_name: Human-readable configuration field name.

    Returns:
        Validated Boolean.

    Raises:
        ValueError: If the value is not exactly ``True`` or ``False``.
    """

    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be Boolean.")
    return value


def _require_nonempty_string(value: Any, field_name: str) -> str:
    """Validate a non-empty string configuration field.

    Args:
        value: Candidate value.
        field_name: Human-readable configuration field name.

    Returns:
        Stripped string.

    Raises:
        ValueError: If the value is not a non-empty string.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _require_percentage(value: Any, field_name: str) -> float:
    """Validate a pLDDT-like percentage in the closed interval [0, 100].

    Args:
        value: Candidate value.
        field_name: Human-readable configuration field name.

    Returns:
        Validated floating-point percentage.

    Raises:
        ValueError: If the value is not numeric or outside [0, 100].
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric.")
    numeric = float(value)
    if not 0.0 <= numeric <= 100.0:
        raise ValueError(f"{field_name} must be between 0 and 100.")
    return numeric


def validate_config(config: dict[str, Any]) -> None:
    """Validate required configuration sections and critical values.

    Args:
        config: Merged configuration dictionary.

    Raises:
        ValueError: If required sections or values are invalid.
    """

    missing_sections = sorted(_REQUIRED_SECTIONS.difference(config))
    if missing_sections:
        raise ValueError(
            "Missing configuration sections: " + ", ".join(missing_sections)
        )

    _require_nonempty_string(config["project"].get("name"), "project.name")
    _require_nonempty_string(
        config["project"].get("run_label"),
        "project.run_label",
    )
    _require_nonempty_string(
        config["input"].get("accession_column"),
        "input.accession_column",
    )

    api_url = config["alphafold"].get("api_base_url")
    if not isinstance(api_url, str) or not api_url.startswith(("http://", "https://")):
        raise ValueError("alphafold.api_base_url must be an HTTP(S) URL.")
    _require_positive_number(
        config["alphafold"].get("request_timeout_seconds"),
        "alphafold.request_timeout_seconds",
    )
    retry_total = config["alphafold"].get("retry_total")
    if isinstance(retry_total, bool) or not isinstance(retry_total, int):
        raise ValueError("alphafold.retry_total must be an integer.")
    if retry_total < 0:
        raise ValueError("alphafold.retry_total cannot be negative.")
    _require_positive_number(
        config["alphafold"].get("retry_backoff_seconds"),
        "alphafold.retry_backoff_seconds",
    )
    for field_name in (
        "download_pae",
        "download_msa",
        "download_plddt_json",
        "reuse_valid_files",
        "query_api_for_local_models",
    ):
        _require_boolean(
            config["alphafold"].get(field_name),
            f"alphafold.{field_name}",
        )

    run_tools = _require_boolean(
        config["external_tools"].get("run_fpocket_p2rank"),
        "external_tools.run_fpocket_p2rank",
    )
    for field_name in (
        "p2rank_version_arguments",
        "fpocket_version_arguments",
    ):
        version_arguments = config["external_tools"].get(field_name)
        if (
            not isinstance(version_arguments, list)
            or not version_arguments
            or not all(
                isinstance(argument, str) and argument
                for argument in version_arguments
            )
        ):
            raise ValueError(
                f"external_tools.{field_name} must be a non-empty list "
                "of non-empty strings."
            )
    if run_tools:
        for field_name in (
            "fpocket_executable",
            "p2rank_executable",
            "p2rank_model",
        ):
            _require_nonempty_string(
                config["external_tools"].get(field_name),
                f"external_tools.{field_name}",
            )
    _require_positive_integer(
        config["external_tools"].get("p2rank_threads"),
        "external_tools.p2rank_threads",
    )
    _require_boolean(
        config["external_tools"].get("p2rank_keep_fpocket_output"),
        "external_tools.p2rank_keep_fpocket_output",
    )
    _require_positive_number(
        config["external_tools"].get("command_timeout_seconds"),
        "external_tools.command_timeout_seconds",
    )

    confident = _require_percentage(
        config["quality"].get("model_confident_threshold"),
        "quality.model_confident_threshold",
    )
    very_high = _require_percentage(
        config["quality"].get("model_very_high_threshold"),
        "quality.model_very_high_threshold",
    )
    if very_high <= confident:
        raise ValueError(
            "quality.model_very_high_threshold must exceed "
            "quality.model_confident_threshold."
        )
    _require_fraction(
        config["quality"].get("minimum_fraction_residues_ge_70"),
        "quality.minimum_fraction_residues_ge_70",
    )
    _require_fraction(
        config["quality"].get("minimum_pocket_mapping_fraction"),
        "quality.minimum_pocket_mapping_fraction",
    )
    _require_fraction(
        config["quality"].get("api_fraction_tolerance"),
        "quality.api_fraction_tolerance",
    )
    _require_positive_number(
        config["quality"].get("api_mean_plddt_tolerance"),
        "quality.api_mean_plddt_tolerance",
    )

    for field_name in (
        "continue_on_accession_error",
        "fail_run_if_any_accession_failed",
    ):
        _require_boolean(
            config["execution"].get(field_name),
            f"execution.{field_name}",
        )
    checksum_algorithm = config["execution"].get("checksum_algorithm")
    if checksum_algorithm != "sha256":
        raise ValueError(
            "execution.checksum_algorithm currently supports only 'sha256'."
        )

    for field_name in ("write_tsv", "write_parquet", "write_duckdb"):
        _require_boolean(
            config["output"].get(field_name),
            f"output.{field_name}",
        )
    if not any(
        config["output"][field_name]
        for field_name in ("write_tsv", "write_parquet", "write_duckdb")
    ):
        raise ValueError("At least one output format must be enabled.")
    if config["output"]["write_duckdb"] and not config["output"]["write_parquet"]:
        raise ValueError(
            "output.write_parquet must be true when output.write_duckdb is true."
        )
