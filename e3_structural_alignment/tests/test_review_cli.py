"""Tests for the named-option pocket-review command line."""

from __future__ import annotations

import json
import argparse
from pathlib import Path

import pytest

from e3structalign.review_cli import build_parser, main, positive_integer


def test_review_cli_builds_report(
    review_run: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI reports the published manifest and index as JSON."""
    status = main(
        [
            "--run-root",
            str(review_run["run_root"]),
            "--output-dir",
            str(review_run["output"]),
            "--review-limit",
            "1",
            "--member-pocket-top-k",
            "2",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert status == 0
    assert payload["status"] == "complete"
    assert Path(payload["index_html"]).is_file()


def test_review_cli_converts_controlled_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing run inputs return status two with a concise diagnostic."""
    status = main(
        [
            "--run-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "output"),
        ]
    )
    captured = capsys.readouterr()
    assert status == 2
    assert "ERROR:" in captured.err


def test_review_cli_parser_rejects_non_positive_values() -> None:
    """Shared positive-integer validation applies to visual report limits."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--run-root",
                "/run",
                "--output-dir",
                "/output",
                "--review-limit",
                "0",
            ]
        )
    with pytest.raises(argparse.ArgumentTypeError):
        positive_integer("not-an-integer")
