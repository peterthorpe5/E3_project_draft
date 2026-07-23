"""Tests for the application launcher."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import Mock, patch

from e3app.cli import build_parser, main, streamlit_command
from e3app.errors import AppError


def test_parser_and_streamlit_argv(resource_db: Path) -> None:
    """Launcher arguments remain a shell-safe sequence."""

    args = build_parser().parse_args(
        ["--resource-duckdb", str(resource_db), "--host", "127.0.0.1", "--port", "9000"]
    )
    command = streamlit_command(args)
    assert command[1:4] == ["-m", "streamlit", "run"]
    assert "9000" in command
    args.port = 0
    try:
        streamlit_command(args)
    except AppError as exc:
        assert "port" in str(exc)
    else:
        raise AssertionError("invalid port was accepted")


def test_validate_only_and_missing(
    resource_db: Path,
    master_parquet: Path,
    run_results_dir: Path,
    tmp_path: Path,
) -> None:
    """Validation-only succeeds and missing inputs return status two."""

    assert main(["--resource-duckdb", str(resource_db), "--validate-only"]) == 0
    assert main(["--resource-parquet", str(master_parquet), "--validate-only"]) == 0
    assert main(["--resource-run-dir", str(run_results_dir), "--validate-only"]) == 0
    assert main(["--resource-duckdb", str(tmp_path / "missing"), "--validate-only"]) == 2


def test_launcher_subprocess(resource_db: Path) -> None:
    """Validated launch configuration is passed through the environment."""

    completed = Mock(returncode=7)
    with patch("e3app.cli.subprocess.run", return_value=completed) as run:
        assert (
            main(
                [
                    "--resource-duckdb",
                    str(resource_db),
                    "--expression-duckdb",
                    str(resource_db),
                    "--headless",
                ]
            )
            == 7
        )
    assert run.call_args.kwargs["env"]["E3_RESOURCE_DUCKDB"] == str(resource_db)
    assert run.call_args.kwargs["env"]["E3_EXPRESSION_DUCKDB"] == str(resource_db)
    assert "E3_RESOURCE_PARQUET" not in run.call_args.kwargs["env"]


def test_bad_host(resource_db: Path) -> None:
    """Whitespace in a bind host is rejected."""

    args = argparse.Namespace(host="bad host", port=8501, headless=False)
    try:
        streamlit_command(args)
    except AppError as exc:
        assert "host" in str(exc)
    else:
        raise AssertionError("invalid host was accepted")


def test_missing_application_module(resource_db: Path) -> None:
    """A broken installation reports the missing Streamlit module path."""

    args = build_parser().parse_args(["--resource-duckdb", str(resource_db)])
    with patch("e3app.cli.find_spec", return_value=None):
        try:
            streamlit_command(args)
        except AppError as exc:
            assert "locate" in str(exc)
        else:
            raise AssertionError("missing application module was accepted")
