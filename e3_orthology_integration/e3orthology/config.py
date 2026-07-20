"""Configuration loading, merging and validation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigurationError

DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "name": "ARIA plant E3 orthology integration",
        "orthofinder_run_id": "orthofinder2_results_feb26_2026",
    },
    "input": {
        "results_directory_name": "Results_Feb26",
        "candidate_cluster_column": "representative_id",
        "candidate_accession_column": "matched_seed_ids_calculated",
        "representative_original_id_column": "representative_original_id",
        "representative_entry_column": "representative_entry",
        "expected_species_count": 60,
        "require_sqlite_regression": True,
    },
    "identifiers": {
        "candidate_delimiter": ";",
        "fail_on_parsed_accession_ambiguity": True,
        "fail_on_unvalidated_candidate_membership": True,
        "minimum_uniprot_parse_fraction": 0.99,
    },
    "regression": {
        "accession": "Q9SA03",
        "expected_raw_identifier": "sp|Q9SA03|FB27_ARATH",
        "expected_orthogroup": "OG0001686",
        "expected_hierarchical_orthogroup": "N0.HOG0002084",
    },
    "execution": {
        "checksum_inputs": True,
        "parquet_block_size_bytes": 67_108_864,
        "threads": 1,
    },
    "output": {
        "write_tsv": True,
        "write_parquet": True,
    },
}

_REQUIRED_SECTIONS = {
    "project",
    "input",
    "identifiers",
    "regression",
    "execution",
    "output",
}


def deep_merge(*, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge mappings without modifying either input.

    Args:
        base: Baseline configuration.
        override: Higher-priority values.

    Returns:
        New recursively merged configuration.
    """

    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(base=merged[key], override=value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_config(*, path: Path | None) -> dict[str, Any]:
    """Load YAML overrides and return validated effective configuration.

    Args:
        path: Optional YAML configuration file.

    Returns:
        Validated configuration including defaults.

    Raises:
        ConfigurationError: If YAML or configuration values are invalid.
    """

    overrides: dict[str, Any] = {}
    if path is not None:
        config_path = Path(path).expanduser().resolve()
        if not config_path.is_file():
            raise ConfigurationError(f"Configuration file does not exist: {config_path}")
        try:
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise ConfigurationError(f"Invalid YAML configuration: {error}") from error
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise ConfigurationError("Configuration root must be a YAML mapping.")
        overrides = loaded
    config = deep_merge(base=DEFAULT_CONFIG, override=overrides)
    validate_config(config=config)
    return config


def validate_config(*, config: dict[str, Any]) -> None:
    """Validate configuration types and scientific thresholds.

    Args:
        config: Effective configuration mapping.

    Raises:
        ConfigurationError: If a required section or value is invalid.
    """

    missing = sorted(_REQUIRED_SECTIONS - set(config))
    if missing:
        raise ConfigurationError("Missing configuration sections: " + ", ".join(missing))
    expected_species = config["input"].get("expected_species_count")
    if isinstance(expected_species, bool) or not isinstance(expected_species, int):
        raise ConfigurationError("input.expected_species_count must be an integer.")
    if expected_species <= 0:
        raise ConfigurationError("input.expected_species_count must be positive.")
    parse_fraction = config["identifiers"].get("minimum_uniprot_parse_fraction")
    if isinstance(parse_fraction, bool) or not isinstance(parse_fraction, (int, float)):
        raise ConfigurationError("identifiers.minimum_uniprot_parse_fraction must be numeric.")
    if not 0.0 <= float(parse_fraction) <= 1.0:
        raise ConfigurationError(
            "identifiers.minimum_uniprot_parse_fraction must be between zero and one."
        )
    block_size = config["execution"].get("parquet_block_size_bytes")
    if isinstance(block_size, bool) or not isinstance(block_size, int) or block_size <= 0:
        raise ConfigurationError("execution.parquet_block_size_bytes must be positive.")
    threads = config["execution"].get("threads")
    if isinstance(threads, bool) or not isinstance(threads, int) or threads <= 0:
        raise ConfigurationError("execution.threads must be a positive integer.")
    for section, key in (
        ("project", "orthofinder_run_id"),
        ("input", "results_directory_name"),
        ("input", "candidate_cluster_column"),
        ("input", "candidate_accession_column"),
        ("regression", "accession"),
        ("regression", "expected_raw_identifier"),
        ("regression", "expected_orthogroup"),
        ("regression", "expected_hierarchical_orthogroup"),
    ):
        value = config[section].get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"{section}.{key} must be a non-empty string.")
    for section, key in (
        ("input", "require_sqlite_regression"),
        ("identifiers", "fail_on_parsed_accession_ambiguity"),
        ("identifiers", "fail_on_unvalidated_candidate_membership"),
        ("execution", "checksum_inputs"),
        ("output", "write_tsv"),
        ("output", "write_parquet"),
    ):
        if not isinstance(config[section].get(key), bool):
            raise ConfigurationError(f"{section}.{key} must be Boolean.")


def resolve_project_path(*, project_root: Path, value: str | Path) -> Path:
    """Resolve an absolute path or a path relative to the project root.

    Args:
        project_root: Project root used for relative paths.
        value: Absolute or relative path.

    Returns:
        Absolute normalised path without requiring it to exist.
    """

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = Path(project_root).expanduser() / candidate
    return candidate.resolve()
