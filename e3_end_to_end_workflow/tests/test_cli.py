"""Tests for command parsing and JSON CLI responses."""

from __future__ import annotations

from pathlib import Path

from e3workflow.cli import build_parser, main, plan_command, validate_command


def test_parser_plan_and_validate(synthetic_config: Path) -> None:
    """All read-only commands expose complete machine-readable state."""

    assert build_parser().parse_args(["plan", "--config", str(synthetic_config)]).command == "plan"
    assert plan_command(synthetic_config)["production_eligible"] is False
    assert validate_command(synthetic_config)["proteomes"] == 2
    assert main(["plan", "--config", str(synthetic_config)]) == 0
    assert main(["validate", "--config", str(synthetic_config)]) == 0


def test_cli_stage_and_error(synthetic_config: Path, tmp_path: Path) -> None:
    """The stage command runs and expected errors return status two."""

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
    assert main(["validate", "--config", str(tmp_path / "missing")]) == 2
