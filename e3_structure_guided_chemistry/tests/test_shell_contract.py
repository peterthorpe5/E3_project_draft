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
    assert "--job-id-file PATH" in result.stdout

    prepare = package_root / "scripts" / "prepare_expanded_candidate_manifest.sh"
    prepare_result = subprocess.run(
        [str(prepare), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--maximum-rank INTEGER" in prepare_result.stdout
    assert "--decided-by TEXT" in prepare_result.stdout

    complete = (
        package_root / "scripts" / "run_dundee_expanded_top200_v0_2_1.sh"
    )
    complete_result = subprocess.run(
        [str(complete), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "complete checked Dundee v0.2.1" in complete_result.stdout
    assert "All project paths and Slurm settings have production defaults" in (
        complete_result.stdout
    )


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


def test_full_universe_validation_and_orchestration_are_separated(
    package_root: Path,
) -> None:
    """Heavy validation and login-node orchestration must remain separated."""
    scripts = package_root / "scripts"
    validation = (
        scripts / "validate_dundee_full_universe_v0_3_1.slurm.sh"
    ).read_text(encoding="utf-8")
    orchestration = (
        scripts / "run_dundee_full_universe_v0_3_0.sh"
    ).read_text(encoding="utf-8")

    assert "#SBATCH --time=02:00:00" in validation
    assert "#SBATCH --chdir=/gpfs/uod-scale-01/cluster" in validation
    assert "BASH_SOURCE" not in validation
    assert 'CHEMISTRY_ROOT="${REPOSITORY_ROOT}/e3_structure_guided_chemistry"' in (
        validation
    )
    assert 'WORKFLOW_ROOT="${REPOSITORY_ROOT}/e3_end_to_end_workflow"' in (
        validation
    )
    assert "if [[ -z \"${SLURM_JOB_ID:-}\" ]]" in validation
    assert "pip install --no-deps --editable" in validation
    assert 'bash "${package_root}/run_tests.sh"' in validation
    assert ".passed.tsv" in validation

    assert "if [[ -n \"${SLURM_JOB_ID:-}\" ]]" in orchestration
    assert "pip install" not in orchestration
    assert "run_tests.sh" not in orchestration
    assert "WORKFLOW_RECEIPT=" in orchestration
    assert "CHEMISTRY_RECEIPT=" in orchestration
    assert "validate_dundee_full_universe_v0_3_1.slurm.sh" in orchestration
