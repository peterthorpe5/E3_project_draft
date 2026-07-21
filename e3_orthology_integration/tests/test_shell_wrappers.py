"""Integration tests for the local and Slurm shell wrappers."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class ShellWrapperTests(unittest.TestCase):
    """Exercise external log placement and informative Slurm submission output."""

    def test_runner_places_default_wrapper_log_under_run_root(self) -> None:
        """The local wrapper creates no runtime log inside the software directory."""

        package_root = Path(__file__).resolve().parents[1]
        repository_log_root = package_root / "logs"
        repository_logs_before = (
            set(repository_log_root.rglob("*")) if repository_log_root.exists() else set()
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            run_root = root / "external_analysis" / "fixture_run"
            fake_conda = fake_bin / "conda"
            fake_conda.write_text(
                "#!/usr/bin/env bash\n"
                "set -Eeuo pipefail\n"
                "if [[ \"${1:-}\" == \"run\" ]]; then\n"
                "    for argument in \"$@\"; do\n"
                "        if [[ \"${argument}\" == \"--print-run-root\" ]]; then\n"
                "            printf '%s\\n' \"${FAKE_RUN_ROOT}\"\n"
                "            exit 0\n"
                "        fi\n"
                "    done\n"
                "    printf 'fake pipeline completed\\n'\n"
                "    exit 0\n"
                "fi\n"
                "if [[ \"${1:-}\" == \"env\" && \"${2:-}\" == \"list\" ]]; then\n"
                "    printf 'e3_orthology /fake/e3_orthology\\n'\n"
                "    exit 0\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            fake_conda.chmod(0o755)
            environment = {
                **os.environ,
                "FAKE_RUN_ROOT": str(run_root),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            }
            completed = subprocess.run(
                args=[
                    str(package_root / "run_e3_orthology_integration.sh"),
                    "--conda-env",
                    "e3_orthology",
                    "--dry-run",
                ],
                cwd=package_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            wrapper_logs = list((run_root / "logs").glob("wrapper_*.log"))
            self.assertEqual(len(wrapper_logs), 1)
            self.assertIn(f"Run directory: {run_root}", wrapper_logs[0].read_text())
            repository_logs_after = (
                set(repository_log_root.rglob("*")) if repository_log_root.exists() else set()
            )
            self.assertEqual(repository_logs_after, repository_logs_before)

    def test_submitter_uses_run_root_and_reports_job_details(self) -> None:
        """Slurm logs live with the run and submission reports actionable paths."""

        package_root = Path(__file__).resolve().parents[1]
        repository_log_root = package_root / "slurm_logs"
        repository_logs_before = (
            set(repository_log_root.rglob("*")) if repository_log_root.exists() else set()
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            run_root = root / "external_analysis" / "fixture_run"
            sbatch_arguments = root / "sbatch_arguments.txt"
            fake_conda = fake_bin / "conda"
            fake_conda.write_text(
                "#!/usr/bin/env bash\n"
                "set -Eeuo pipefail\n"
                "if [[ \"${1:-}\" == \"run\" ]]; then\n"
                "    for argument in \"$@\"; do\n"
                "        if [[ \"${argument}\" == \"--print-run-root\" ]]; then\n"
                "            printf '%s\\n' \"${FAKE_RUN_ROOT}\"\n"
                "            exit 0\n"
                "        fi\n"
                "    done\n"
                "fi\n"
                "exit 2\n",
                encoding="utf-8",
            )
            fake_conda.chmod(0o755)
            fake_sbatch = fake_bin / "sbatch"
            fake_sbatch.write_text(
                "#!/usr/bin/env bash\n"
                "set -Eeuo pipefail\n"
                "printf '%s\\n' \"$@\" > \"${FAKE_SBATCH_ARGUMENTS}\"\n"
                "printf '4242;test-cluster\\n'\n",
                encoding="utf-8",
            )
            fake_sbatch.chmod(0o755)
            environment = {
                **os.environ,
                "FAKE_RUN_ROOT": str(run_root),
                "FAKE_SBATCH_ARGUMENTS": str(sbatch_arguments),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            }
            completed = subprocess.run(
                args=[
                    str(package_root / "submit_e3_orthology_integration.sh"),
                    "--account",
                    "barton",
                    "--partition",
                    "general",
                    "--",
                    "--conda-env",
                    "e3_orthology",
                    "--resume",
                ],
                cwd=package_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Submitted batch job 4242", completed.stdout)
            self.assertIn(f"Run directory: {run_root}", completed.stdout)
            self.assertIn("Monitor: squeue --job 4242", completed.stdout)
            recorded = sbatch_arguments.read_text(encoding="utf-8")
            self.assertIn("--parsable", recorded)
            self.assertIn(f"--output={run_root}/slurm_logs/%x_%j.out", recorded)
            self.assertIn(f"--error={run_root}/slurm_logs/%x_%j.err", recorded)
            repository_logs_after = (
                set(repository_log_root.rglob("*")) if repository_log_root.exists() else set()
            )
            self.assertEqual(repository_logs_after, repository_logs_before)

    def test_submitter_rejects_walltime_above_three_days(self) -> None:
        """A request beyond the Dundee Slurm limit fails before submission."""

        package_root = Path(__file__).resolve().parents[1]
        excessive_time = subprocess.run(
            args=[
                str(package_root / "submit_e3_orthology_integration.sh"),
                "--time",
                "72:00:01",
                "--",
                "--conda-env",
                "e3_orthology",
            ],
            cwd=package_root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(excessive_time.returncode, 2)
        self.assertIn("exceeds the cluster maximum", excessive_time.stderr)


if __name__ == "__main__":
    unittest.main()
