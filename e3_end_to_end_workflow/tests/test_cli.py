"""Tests for command parsing and JSON CLI responses."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    assert validate_command(synthetic_config)["proteomes"] == 2
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
