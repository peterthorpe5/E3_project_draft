"""Tests for the named-option CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from e3structalign.cli import build_parser, fraction, main, positive_float, positive_integer


def test_cli_runs(structural_inputs: dict[str, Path]) -> None:
    """The CLI forwards every required path and threshold."""
    status = main(
        [
            "run",
            "--selected-pockets",
            str(structural_inputs["selected"]),
            "--pocket-residue-mappings",
            str(structural_inputs["mappings"]),
            "--asset-manifest",
            str(structural_inputs["assets"]),
            "--output-dir",
            str(structural_inputs["output"]),
            "--usalign-executable",
            str(structural_inputs["executable"]),
            "--tmalign-executable",
            str(structural_inputs["tmalign"]),
            "--threads",
            "2",
        ]
    )
    assert status == 0


def test_cli_errors_and_numeric_types(tmp_path: Path) -> None:
    """Argument types and expected workflow failures return useful errors."""
    assert fraction("0.5") == 0.5
    assert positive_float("1.0") == 1.0
    assert positive_integer("2") == 2
    for parser, value in (
        (fraction, "2"),
        (positive_float, "0"),
        (positive_integer, "0"),
    ):
        with pytest.raises(Exception):
            parser(value)
    parsed = build_parser().parse_args(
        [
            "run",
            "--selected-pockets",
            str(tmp_path / "missing"),
            "--pocket-residue-mappings",
            str(tmp_path / "missing"),
            "--asset-manifest",
            str(tmp_path / "missing"),
            "--output-dir",
            str(tmp_path / "output"),
        ]
    )
    assert parsed.command == "run"
    assert (
        main(
            [
                "run",
                "--selected-pockets",
                str(tmp_path / "missing"),
                "--pocket-residue-mappings",
                str(tmp_path / "missing"),
                "--asset-manifest",
                str(tmp_path / "missing"),
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 2
    )
