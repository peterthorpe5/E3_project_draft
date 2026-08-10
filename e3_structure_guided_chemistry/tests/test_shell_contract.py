"""Contracts for the user-facing chemistry shell launchers."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_slurm_launcher_help_and_open_defaults(package_root: Path) -> None:
    """The standalone launcher must document the Barton open-source route."""
    launcher = (
        package_root
        / "scripts"
        / "submit_e3_structure_guided_chemistry_slurm.sh"
    )

    result = subprocess.run(
        [str(launcher), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--run-root PATH" in result.stdout
    assert "default: barton" in result.stdout
    assert "--config PATH" in result.stdout
    assert "--candidate-manifest PATH" in result.stdout

    prepare = package_root / "scripts" / "prepare_expanded_candidate_manifest.sh"
    prepare_result = subprocess.run(
        [str(prepare), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--maximum-rank INTEGER" in prepare_result.stdout
    assert "--decided-by TEXT" in prepare_result.stdout


def test_shells_do_not_embed_python(package_root: Path) -> None:
    """Shells must delegate package logic to the installed Python command."""
    shells = [
        package_root / "run_e3_structure_guided_chemistry.sh",
        package_root / "run_tests.sh",
        *sorted((package_root / "scripts").glob("*.sh")),
    ]

    for shell in shells:
        source = shell.read_text(encoding="utf-8")
        assert "python -c" not in source
        assert "python <<" not in source
        assert "python - <<" not in source
