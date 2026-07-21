"""Tests for workflow configuration validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from e3workflow.config import STAGE_NAMES, load_config, previous_stage
from e3workflow.errors import ConfigurationError


def test_load_valid_config_and_lookup(synthetic_config: Path) -> None:
    """Valid configuration resolves paths, stages and a stable digest."""

    config = load_config(synthetic_config)
    assert config.mode == "synthetic"
    assert config.stage("00_inputs").required
    assert config.run_root.name == "synthetic_e2e_v0_2_0"
    assert len(config.digest) == 64
    assert previous_stage("00_inputs") is None
    assert previous_stage("01_prepared_proteomes") == "00_inputs"
    with pytest.raises(ConfigurationError):
        config.stage("missing")
    with pytest.raises(ConfigurationError):
        previous_stage("missing")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(schema_version=2), "schema_version"),
        (lambda data: data["run"].update(mode="invalid"), "run.mode"),
        (lambda data: data["run"].update(name="../bad"), "run.name"),
        (lambda data: data["run"].update(project_root=""), "project_root"),
        (lambda data: data.update(stages={"unknown": {}}), "Unknown stage"),
        (lambda data: data.update(stages={"00_inputs": []}), "must be a YAML mapping"),
        (
            lambda data: data["stages"]["02_discovery"].update(enabled="yes"),
            "must be booleans",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(command="tool"),
            "list of non-empty strings",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(
                enabled=False, required=True
            ),
            "Required stage",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(
                expected_outputs=["../escape"]
            ),
            "Unsafe expected output",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(
                expected_outputs=["/absolute"]
            ),
            "Unsafe expected output",
        ),
    ],
)
def test_invalid_configuration_branches(
    synthetic_config: Path, mutation: object, message: str
) -> None:
    """Malformed configuration is rejected with actionable context."""

    data = yaml.safe_load(synthetic_config.read_text())
    mutation(data)
    synthetic_config.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        load_config(synthetic_config)


def test_missing_and_non_mapping_config(tmp_path: Path) -> None:
    """Missing, invalid YAML and non-mapping roots fail closed."""

    with pytest.raises(ConfigurationError):
        load_config(tmp_path / "missing.yaml")
    for index, text in enumerate(("[", "[]")):
        path = tmp_path / f"bad{index}.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ConfigurationError):
            load_config(path)


def test_production_requires_external_commands(synthetic_config: Path) -> None:
    """Scientific production stages cannot silently use synthetic handlers."""

    data = yaml.safe_load(synthetic_config.read_text())
    data["run"]["mode"] = "production"
    synthetic_config.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=STAGE_NAMES[1]):
        load_config(synthetic_config)
