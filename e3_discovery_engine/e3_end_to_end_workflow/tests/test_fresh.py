"""Tests for strict complete fresh-run preflight validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from e3workflow.errors import ConfigurationError
from e3workflow.fresh import validate_fresh_config


def _fresh_config(package_root: Path, tmp_path: Path) -> Path:
    """Create a syntactically complete clean-room configuration."""
    source = package_root / "config" / "production.cluster.template.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    data["run"]["name"] = "fresh_test_run"
    data["run"]["project_root"] = str(package_root.parent)
    data["run"]["output_root"] = str(tmp_path / "runs")
    data["tools"]["discovery"]["executable"] = "/opt/e3/discovery-adapter"
    data["tools"]["candidate_evidence"]["executable"] = "/opt/e3/candidate-adapter"
    data["tools"]["orthology"]["executable"] = "/opt/e3/orthology-adapter"
    data["tools"]["expression"]["executable"] = "/opt/e3/expression-adapter"
    data["tools"]["ligandability"]["executable"] = "/opt/e3/ligandability-adapter"
    for tool in data["tools"].values():
        if tool.get("expected_version") == "CHANGE_ME_REVIEWED_VERSION":
            tool["expected_version"] = "1.0.0"
    path = tmp_path / "fresh.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_complete_fresh_configuration_is_accepted(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """A complete generation-only configuration passes clean-room preflight."""
    path = _fresh_config(package_root, tmp_path)
    result = validate_fresh_config(config_path=path)
    assert result["status"] == "valid"
    assert result["stage_count"] == 13
    assert result["maximum_stage_threads"] == 32
    assert result["tool_count"] == 7


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda data: data["run"].update(mode="synthetic"),
            "run.mode: production",
        ),
        (
            lambda data: data.update(schema_version=1),
            "schema_version: 2",
        ),
        (
            lambda data: data.update(tools={}),
            "non-empty tools",
        ),
        (
            lambda data: data["stages"]["09b_structural_alignment"].update(
                enabled=False,
                required=False,
                evidence_mode="disabled",
            ),
            "requires stage 09b_structural_alignment",
        ),
        (
            lambda data: data["stages"]["07_expression"].update(
                evidence_mode="reuse",
            ),
            "07_expression.evidence_mode",
        ),
        (
            lambda data: data["stages"]["04_orthofinder"].update(command=[]),
            "Fresh generation requires",
        ),
        (
            lambda data: data["tools"]["orthology"].update(
                executable="CHANGE_ME_ADAPTER",
            ),
            "unresolved CHANGE_ME",
        ),
        (
            lambda data: data["inputs"].update(
                expression_manifest="/previous/expression.tsv",
            ),
            "reusable result authorities",
        ),
    ],
)
def test_incomplete_fresh_configuration_is_rejected(
    package_root: Path,
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    """Every branch that could silently reuse or omit evidence fails closed."""
    path = _fresh_config(package_root, tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutation(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        validate_fresh_config(config_path=path)


def test_existing_fresh_run_requires_explicit_resume(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """An occupied run root is accepted only for an explicit exact-run resume."""
    path = _fresh_config(package_root, tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    run_root = Path(data["run"]["output_root"]) / data["run"]["name"]
    run_root.mkdir(parents=True)
    (run_root / "existing.txt").write_text("evidence", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="run root is not empty"):
        validate_fresh_config(config_path=path)
    result = validate_fresh_config(
        config_path=path,
        allow_existing_run=True,
    )
    assert result["allow_existing_run"] is True
