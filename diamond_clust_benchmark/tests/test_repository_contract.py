"""Package layout, configuration and shell-policy tests."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

import yaml

from tests.helpers import PACKAGE_ROOT


class RepositoryContractTests(unittest.TestCase):
    """Protect the reviewable package and production matrix contracts."""

    def test_required_documentation_and_workflow_files_exist(self) -> None:
        """Keep operator, grant and workflow entry points together."""

        required = [
            "README.md",
            "CHANGELOG.md",
            "Snakefile",
            "run_workflow.sh",
            "run_tests.sh",
            "docs/BENCHMARK_PROTOCOL.md",
            "docs/CLUSTER_RUNBOOK.md",
            "docs/GRANT_ALIGNMENT.md",
            "scripts/submit_benchmark_slurm.sh",
        ]
        for relative in required:
            with self.subTest(relative=relative):
                self.assertTrue((PACKAGE_ROOT / relative).is_file())

    def test_production_matrix_has_baseline_and_supported_comparisons(self) -> None:
        """Retain version, cascade, command and identity comparisons."""

        path = PACKAGE_ROOT / "config" / "full_onekp_cluster.template.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        benchmark = payload["benchmark"]
        cases = benchmark["cases"]
        self.assertEqual(benchmark["decision_stage"], "pairwise_pipeline")
        self.assertEqual(benchmark["minimum_speedup_percent"], 10)
        self.assertEqual(benchmark["repeats"], 3)
        self.assertIn("diamond_2_2_3_deepclust_exact", benchmark["baseline_case_id"])
        self.assertEqual({case["command"] for case in cases}, {"deepclust", "linclust"})
        self.assertEqual(
            {case["identity_mode"] for case in cases},
            {"exact", "approximate"},
        )
        self.assertEqual(
            {case["expected_version"] for case in cases},
            {"2.2.3", "2.2.8"},
        )

    def test_shell_launchers_are_executable_and_do_not_embed_python(self) -> None:
        """Require named Bash interfaces and separate Python modules."""

        scripts = [
            PACKAGE_ROOT / "run_workflow.sh",
            PACKAGE_ROOT / "run_tests.sh",
            PACKAGE_ROOT / "scripts" / "slurm_controller.sh",
            PACKAGE_ROOT / "scripts" / "submit_benchmark_slurm.sh",
        ]
        for path in scripts:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("#!/usr/bin/env bash"))
                self.assertNotIn("python <<", text)
                self.assertTrue(os.access(path, os.X_OK))

    def test_outputs_are_tsv_not_csv(self) -> None:
        """Prevent comma-delimited outputs from entering the new package."""

        tracked_sources = list((PACKAGE_ROOT / "src").rglob("*.py"))
        tracked_sources.extend([PACKAGE_ROOT / "Snakefile"])
        for path in tracked_sources:
            with self.subTest(path=path.name):
                self.assertNotIn(".csv", path.read_text(encoding="utf-8"))

    def test_snakefile_serialises_the_frozen_case_order(self) -> None:
        """Prevent scheduler choice from changing paired observation order."""

        text = (PACKAGE_ROOT / "Snakefile").read_text(encoding="utf-8")
        self.assertIn("RUN_SEQUENCE", text)
        self.assertIn("previous=previous_case_directory", text)


if __name__ == "__main__":
    unittest.main()
