"""Tests for command parsing and JSON CLI responses."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from e3workflow.cli import (
    build_parser,
    main,
    plan_command,
    render_plan,
    validate_command,
    validate_stage_range,
)
from e3workflow.errors import WorkflowError


def test_parser_plan_and_validate(synthetic_config: Path) -> None:
    """All read-only commands expose complete machine-readable state."""

    assert build_parser().parse_args(["plan", "--config", str(synthetic_config)]).command == "plan"
    with pytest.raises(SystemExit, match="0"):
        build_parser().parse_args(["--version"])
    assert plan_command(synthetic_config)["production_eligible"] is False
    assert "Independent branches" in render_plan(plan_command(synthetic_config))
    assert "HTML reports" in render_plan(plan_command(synthetic_config))
    assert validate_command(synthetic_config)["proteomes"] == 2
    parsed = build_parser().parse_args(
        ["record-invocation", "--config", str(synthetic_config), "--", "snakemake", "--cores", "4"]
    )
    assert parsed.workflow_argv[-3:] == ["snakemake", "--cores", "4"]
    assert main(["plan", "--config", str(synthetic_config)]) == 0
    assert main(["plan", "--config", str(synthetic_config), "--human"]) == 0
    assert main(["validate", "--config", str(synthetic_config)]) == 0
    assert validate_stage_range("04_orthofinder", "05_orthology")["status"] == "valid"
    assert validate_stage_range("05_orthology", "05_orthology")["status"] == "valid"
    with pytest.raises(WorkflowError, match="not a prerequisite"):
        validate_stage_range("02_discovery", "05_orthology")
    assert (
        main(
            [
                "validate-range",
                "--start-at",
                "04_orthofinder",
                "--stop-after",
                "05_orthology",
            ]
        )
        == 0
    )


def test_cli_stage_and_error(synthetic_config: Path, tmp_path: Path) -> None:
    """The stage command runs and expected errors return status two."""

    assert main(["control", "--config", str(synthetic_config)]) == 0
    assert (
        main(
            [
                "run-stage",
                "--config",
                str(synthetic_config),
                "--stage",
                "00_inputs",
                "--verbose",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "stage-target",
                "--config",
                str(synthetic_config),
                "--stage",
                "00_inputs",
            ]
        )
        == 0
    )
    assert main(["validate", "--config", str(tmp_path / "missing")]) == 2
    assert (
        main(
            [
                "record-invocation",
                "--config",
                str(synthetic_config),
                "--",
                "snakemake",
                "--cores",
                "4",
            ]
        )
        == 0
    )


def test_validate_skips_inputs_for_disabled_branches(synthetic_config: Path) -> None:
    """A bounded OrthoFinder run does not require future seed or shortlist authorities."""
    raw = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    raw["run"]["mode"] = "production"
    for stage_name, stage in raw["stages"].items():
        stage["enabled"] = stage_name in {"00_inputs", "01_prepared_proteomes", "04_orthofinder"}
        stage["required"] = stage["enabled"]
        stage.pop("command", None)
        if not stage["enabled"]:
            stage["expected_outputs"] = []
    raw["stages"]["01_prepared_proteomes"]["expected_outputs"] = ["prepared_proteomes.tsv"]
    raw["stages"]["04_orthofinder"].update(
        command=["orthofinder", "-f", "{run_root}/01_prepared_proteomes/proteomes"],
        expected_outputs=["Results/Log.txt"],
    )
    raw["inputs"]["seeds_manifest"] = "does_not_exist_seeds.tsv"
    raw["inputs"]["shortlist_manifest"] = "does_not_exist_shortlist.tsv"
    synthetic_config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    result = validate_command(synthetic_config)
    assert result["controlled_inputs"] == ["proteomes"]
    assert result["seeds"] == 0
    assert result["shortlist_rows"] == 0
