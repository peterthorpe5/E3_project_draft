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
            sbatch_environment = root / "sbatch_environment.txt"
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
                "printf '%s\\n' \"${SLURM_CPUS_PER_TASK-unset}\" > "
                "\"${FAKE_SBATCH_ENVIRONMENT}\"\n"
                "printf '4242;test-cluster\\n'\n",
                encoding="utf-8",
            )
            fake_sbatch.chmod(0o755)
            environment = {
                **os.environ,
                "FAKE_RUN_ROOT": str(run_root),
                "FAKE_SBATCH_ARGUMENTS": str(sbatch_arguments),
                "FAKE_SBATCH_ENVIRONMENT": str(sbatch_environment),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "SLURM_CPUS_PER_TASK": "9",
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
            self.assertIn("--cpus-per-task=4", recorded)
            self.assertIn("--export=ALL,E3_REQUESTED_CPUS=4", recorded)
            self.assertIn(f"--output={run_root}/slurm_logs/%x_%j.out", recorded)
            self.assertIn(f"--error={run_root}/slurm_logs/%x_%j.err", recorded)
            self.assertEqual(sbatch_environment.read_text(encoding="utf-8").strip(), "unset")
            submitted_arguments = recorded.splitlines()
            batch_script_index = submitted_arguments.index(
                str(package_root / "slurm" / "e3_orthology_integration.sbatch")
            )
            self.assertEqual(
                submitted_arguments[batch_script_index + 1],
                str(package_root / "run_e3_orthology_integration.sh"),
            )
            self.assertIn("--conda-env", submitted_arguments[batch_script_index + 2:])
            threads_index = submitted_arguments.index("--threads")
            self.assertEqual(submitted_arguments[threads_index + 1], "4")
            repository_logs_after = (
                set(repository_log_root.rglob("*")) if repository_log_root.exists() else set()
            )
            self.assertEqual(repository_logs_after, repository_logs_before)

    def test_batch_script_uses_supplied_absolute_runner_from_spool_copy(self) -> None:
        """The Slurm script must not resolve the runner relative to its spool copy."""

        package_root = Path(__file__).resolve().parents[1]
        batch_script = package_root / "slurm" / "e3_orthology_integration.sbatch"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spool_directory = root / "var" / "spool" / "slurmd" / "job4242"
            spool_directory.mkdir(parents=True)
            spool_copy = spool_directory / "slurm_script"
            spool_copy.write_bytes(batch_script.read_bytes())
            spool_copy.chmod(0o755)
            runner = root / "shared" / "run_e3_orthology_integration.sh"
            runner.parent.mkdir()
            captured_arguments = root / "runner_arguments.txt"
            runner.write_text(
                "#!/usr/bin/env bash\n"
                "set -Eeuo pipefail\n"
                "printf '%s\\n' \"$@\" > \"${FAKE_RUNNER_ARGUMENTS}\"\n",
                encoding="utf-8",
            )
            runner.chmod(0o755)
            environment = {
                **os.environ,
                "FAKE_RUNNER_ARGUMENTS": str(captured_arguments),
                "E3_REQUESTED_CPUS": "4",
                "SLURM_JOB_ID": "4242",
                "SLURM_CPUS_PER_TASK": "4",
            }
            completed = subprocess.run(
                args=[
                    str(spool_copy),
                    str(runner),
                    "--conda-env",
                    "e3_orthology",
                    "--resume",
                ],
                cwd=spool_directory,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(f"Pipeline runner: {runner}", completed.stdout)
            self.assertIn("Requested and allocated CPUs per task: 4", completed.stdout)
            self.assertEqual(
                captured_arguments.read_text(encoding="utf-8").splitlines(),
                ["--conda-env", "e3_orthology", "--resume"],
            )

    def test_batch_script_rejects_missing_runner_argument(self) -> None:
        """A malformed direct batch submission fails with an actionable error."""

        package_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            args=[str(package_root / "slurm" / "e3_orthology_integration.sbatch")],
            cwd=package_root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("absolute pipeline runner path was not supplied", completed.stderr)

    def test_batch_script_rejects_cpu_mismatch(self) -> None:
        """The compute-node guard rejects stale or inconsistent CPU metadata."""

        package_root = Path(__file__).resolve().parents[1]
        runner = package_root / "run_e3_orthology_integration.sh"
        environment = {
            **os.environ,
            "E3_REQUESTED_CPUS": "4",
            "SLURM_CPUS_PER_TASK": "9",
        }
        completed = subprocess.run(
            args=[
                str(package_root / "slurm" / "e3_orthology_integration.sbatch"),
                str(runner),
            ],
            cwd=package_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("requested 4 but allocated 9", completed.stderr)

    def test_submitter_rejects_mismatched_pipeline_threads(self) -> None:
        """Scheduler CPUs and pipeline threads cannot silently diverge."""

        package_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            args=[
                str(package_root / "submit_e3_orthology_integration.sh"),
                "--cpus-per-task",
                "4",
                "--",
                "--conda-env",
                "e3_orthology",
                "--threads",
                "2",
            ],
            cwd=package_root,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("must equal pipeline --threads", completed.stderr)

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
