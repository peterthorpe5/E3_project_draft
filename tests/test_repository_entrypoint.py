"""Tests for the repository-root E3 workflow entry point."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


class RepositoryEntrypointTests(unittest.TestCase):
    """Exercise the user-facing repository launcher."""

    @classmethod
    def setUpClass(cls) -> None:
        """Resolve the repository and launcher paths once."""

        cls.repository_root = Path(__file__).resolve().parents[1]
        cls.launcher = cls.repository_root / "run_e3_pipeline.sh"
        cls.fresh_launcher = cls.repository_root / "run_e3_pipeline_fresh.sh"

    def test_version_is_reported(self) -> None:
        """The root launcher must expose a stable release version."""

        result = subprocess.run(
            [str(self.launcher), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "E3 project launcher 0.9.3")

    def test_help_documents_all_execution_modes(self) -> None:
        """The help text must explain cluster, local and legacy modes."""

        result = subprocess.run(
            [str(self.launcher), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--mode MODE", result.stdout)
        self.assertIn("slurm", result.stdout)
        self.assertIn("local", result.stdout)
        self.assertIn("login-detached", result.stdout)
        self.assertIn("--start-at STAGE", result.stdout)

    def test_configuration_is_mandatory(self) -> None:
        """A production-capable root launch must never select inputs implicitly."""

        result = subprocess.run(
            [str(self.launcher), "--mode", "local"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--config is required", result.stderr)

    def test_unknown_mode_fails_closed(self) -> None:
        """An unrecognised execution mode must not fall back silently."""

        configuration = (
            self.repository_root
            / "e3_end_to_end_workflow"
            / "config"
            / "synthetic.yaml"
        )
        result = subprocess.run(
            [
                str(self.launcher),
                "--config",
                str(configuration),
                "--mode",
                "not-a-real-mode",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--mode must be", result.stderr)

    def test_profile_cannot_conflict_with_root_mode(self) -> None:
        """Repository mode must remain the single execution-profile selector."""

        configuration = (
            self.repository_root
            / "e3_end_to_end_workflow"
            / "config"
            / "synthetic.yaml"
        )
        result = subprocess.run(
            [
                str(self.launcher),
                "--config",
                str(configuration),
                "--mode",
                "local",
                "--profile",
                "slurm",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("use --mode", result.stderr)

    def test_shell_contains_no_embedded_python(self) -> None:
        """The shell entry point must delegate all Python work."""

        for launcher in (self.launcher, self.fresh_launcher):
            shell = launcher.read_text(encoding="utf-8")
            self.assertNotIn("python -c", shell)
            self.assertNotIn("python <<", shell)
            self.assertNotIn("python - <<", shell)

    def test_pytest_launchers_are_package_scoped(self) -> None:
        """Pytest launchers must not collect sibling packages accidentally."""

        package_names = (
            "e3_end_to_end_workflow",
            "e3_python_app",
            "e3_structural_alignment",
        )
        for package_name in package_names:
            script = (
                self.repository_root / package_name / "run_tests.sh"
            ).read_text(encoding="utf-8")
            self.assertIn("unset PYTEST_ADDOPTS", script, package_name)
            self.assertRegex(
                script,
                r"pytest[^\n]*\"\$\{SCRIPT_DIR\}/tests\"",
                package_name,
            )

    def test_fresh_launcher_reports_version_and_limits_jobs(self) -> None:
        """The clean-room launcher must expose its release and enforce the ten-job cap."""
        version = subprocess.run(
            [str(self.fresh_launcher), "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            version.stdout.strip(),
            "E3 fresh pipeline launcher 0.9.3",
        )
        configuration = (
            self.repository_root
            / "e3_end_to_end_workflow"
            / "config"
            / "production.cluster.template.yaml"
        )
        result = subprocess.run(
            [
                str(self.fresh_launcher),
                "--config",
                str(configuration),
                "--max-jobs",
                "11",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("between 1 and 10", result.stderr)

    def test_fresh_help_explains_durable_slurm_submission(self) -> None:
        """The clean-room help must state that logout is safe."""
        result = subprocess.run(
            [str(self.fresh_launcher), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("safe after logout", result.stdout)
        self.assertIn("--max-jobs INTEGER", result.stdout)
        self.assertIn("--resume", result.stdout)


if __name__ == "__main__":
    unittest.main()
