"""Tests for scheduler-managed node-local scratch selection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _run_job_wrapper(
    *, tmp_path: Path, package_arguments: list[str]
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the Slurm job wrapper with a harmless fake Conda executable.

    Args:
        tmp_path: Isolated test directory.
        package_arguments: Arguments passed through to the package runner.

    Returns:
        Completed shell process and captured fake-Conda arguments.
    """

    package_root = Path(__file__).resolve().parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture = tmp_path / "conda_arguments.txt"
    fake_conda = fake_bin / "conda"
    fake_conda.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$@\" > \"$CAPTURE_FILE\"\n",
        encoding="utf-8",
    )
    fake_conda.chmod(0o755)
    node_temp = tmp_path / "node_tmp"
    node_temp.mkdir()
    environment = {
        **os.environ,
        "CAPTURE_FILE": str(capture),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SLURM_CPUS_PER_TASK": "8",
        "SLURM_JOB_ID": "12345",
        "TMPDIR": str(node_temp),
        "USER": "test_user",
    }
    completed = subprocess.run(
        [
            "bash",
            str(package_root / "slurm/orthofinder_results.sbatch"),
            str(package_root),
            "orthofinder_results",
            *package_arguments,
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )
    captured_arguments = capture.read_text(encoding="utf-8").splitlines()
    return completed, captured_arguments


def test_slurm_wrapper_injects_job_specific_node_local_work_dir(tmp_path: Path) -> None:
    """Slurm defaults to a private directory below the compute-node TMPDIR."""

    completed, arguments = _run_job_wrapper(tmp_path=tmp_path, package_arguments=["--version"])
    expected = tmp_path / "node_tmp/orthofinder_results_test_user_12345"
    assert completed.returncode == 0, completed.stderr
    assert f"Node-local work directory: {expected}" in completed.stdout
    work_index = arguments.index("--work-dir")
    assert arguments[work_index + 1] == str(expected)
    assert not expected.exists()


def test_slurm_wrapper_preserves_explicit_work_dir(tmp_path: Path) -> None:
    """A named work directory remains available for other cluster policies."""

    explicit = tmp_path / "explicit_work"
    completed, arguments = _run_job_wrapper(
        tmp_path=tmp_path,
        package_arguments=["--version", "--work-dir", str(explicit)],
    )
    assert completed.returncode == 0, completed.stderr
    assert "Using explicitly supplied work directory." in completed.stdout
    assert arguments.count("--work-dir") == 1
    assert arguments[arguments.index("--work-dir") + 1] == str(explicit)
