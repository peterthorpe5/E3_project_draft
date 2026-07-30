"""Tests for pocket-review shell entry points and Slurm limits."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_direct_wrapper_reports_version() -> None:
    """The source-tree wrapper exposes the package release version."""
    result = subprocess.run(
        [str(PACKAGE_ROOT / "run_e3_pocket_review.sh"), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "e3-pocket-review 0.3.0"


def test_submitter_help_and_five_day_limit(tmp_path: Path) -> None:
    """Slurm submitter documents names and rejects durations above five days."""
    script = PACKAGE_ROOT / "scripts" / "submit_e3_pocket_review_slurm.sh"
    help_result = subprocess.run(
        [str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0
    assert "--partition" in help_result.stdout
    assert "default: barton" in help_result.stdout
    invalid = subprocess.run(
        [
            str(script),
            "--run-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "report"),
            "--walltime",
            "5-00:00:01",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert invalid.returncode == 2
    assert "no longer than five days" in invalid.stderr


def test_submitter_accepts_exact_five_days_and_barton_defaults(
    tmp_path: Path,
) -> None:
    """An exact five-day request reaches sbatch with required barton defaults."""
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    capture = tmp_path / "sbatch_arguments.txt"
    sbatch = binary_dir / "sbatch"
    sbatch.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"${SBATCH_CAPTURE}\"\n"
        "printf '12345\\n'\n",
        encoding="utf-8",
    )
    sbatch.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{binary_dir}:{environment['PATH']}"
    environment["SBATCH_CAPTURE"] = str(capture)
    result = subprocess.run(
        [
            str(PACKAGE_ROOT / "scripts" / "submit_e3_pocket_review_slurm.sh"),
            "--run-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "report"),
            "--walltime",
            "5-00:00:00",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0
    arguments = capture.read_text(encoding="utf-8")
    assert "--account=barton" in arguments
    assert "--partition=barton" in arguments
    assert "--time=5-00:00:00" in arguments


def test_worker_rejects_unknown_option() -> None:
    """Slurm worker fails before execution for an unknown option."""
    result = subprocess.run(
        [
            str(PACKAGE_ROOT / "scripts" / "slurm_e3_pocket_review_job.sh"),
            "--unknown",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "unknown worker option" in result.stderr
