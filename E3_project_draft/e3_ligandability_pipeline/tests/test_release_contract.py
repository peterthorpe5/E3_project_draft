"""Release-contract tests for documentation, provenance and packaging."""

from __future__ import annotations

import ast
import csv
import hashlib
import subprocess
import tomllib
import unittest
from pathlib import Path

import e3ligandability


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "e3ligandability"
TRACEABILITY_PATH = PROJECT_ROOT / "docs" / "TEST_TRACEABILITY.tsv"
LEGACY_CHECKSUM_PATH = (
    PROJECT_ROOT / "legacy_reference" / "LEGACY_FILE_CHECKSUMS.tsv"
)


def discover_test_ids() -> set[str]:
    """Discover fully qualified unittest method identifiers in the suite.

    Returns:
        Test identifiers matching the traceability-table format.
    """

    identifiers: set[str] = set()
    for path in sorted((PROJECT_ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for class_node in tree.body:
            if not isinstance(class_node, ast.ClassDef):
                continue
            for method_node in class_node.body:
                if (
                    isinstance(method_node, ast.FunctionDef)
                    and method_node.name.startswith("test_")
                ):
                    identifiers.add(
                        f"{path.stem}.{class_node.name}.{method_node.name}"
                    )
    return identifiers


def discover_production_functions() -> set[tuple[str, str, int]]:
    """Discover every function definition in the production package.

    Returns:
        Module, function-name and definition-line tuples.
    """

    functions: set[tuple[str, str, int]] = set()
    for path in sorted(PACKAGE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_name = f"e3ligandability.{path.stem}"
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.add((module_name, node.name, node.lineno))
    return functions


class ReleaseContractTests(unittest.TestCase):
    """Enforce the package's documented production release contract."""

    def test_every_production_function_has_a_docstring(self) -> None:
        """Every production function must carry a non-empty docstring."""

        missing: list[str] = []
        for path in sorted(PACKAGE_ROOT.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not ast.get_docstring(node):
                        missing.append(f"{path.name}:{node.lineno}:{node.name}")
        self.assertEqual(missing, [])

    def test_traceability_covers_every_production_function(self) -> None:
        """Every production function must map to a real named test."""

        with TRACEABILITY_PATH.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        traced = {
            (
                row["module"],
                row["function"],
                int(row["definition_line"]),
            )
            for row in rows
        }
        self.assertEqual(traced, discover_production_functions())
        known_tests = discover_test_ids()
        missing_tests = sorted(
            row["test_id"] for row in rows if row["test_id"] not in known_tests
        )
        self.assertEqual(missing_tests, [])

    def test_package_versions_are_consistent(self) -> None:
        """Runtime and project metadata versions must agree."""

        project = tomllib.loads(
            (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            project["project"]["version"],
            e3ligandability.__version__,
        )

    def test_legacy_reference_files_are_unchanged(self) -> None:
        """Legacy evidence files must match their frozen SHA-256 manifest."""

        with LEGACY_CHECKSUM_PATH.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(rows), 5)
        for row in rows:
            path = PROJECT_ROOT / "legacy_reference" / row["filename"]
            with self.subTest(filename=row["filename"]):
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_size, int(row["bytes"]))
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(digest, row["sha256"])

    def test_cluster_shell_contracts(self) -> None:
        """Cluster wrappers must retain defensive and Dundee Slurm contracts."""

        wrapper = (PROJECT_ROOT / "run_e3_ligandability.sh").read_text(
            encoding="utf-8"
        )
        submitter = (
            PROJECT_ROOT / "scripts" / "submit_e3_ligandability_slurm.sh"
        ).read_text(encoding="utf-8")
        worker = (
            PROJECT_ROOT / "scripts" / "slurm_e3_ligandability_job.sh"
        ).read_text(encoding="utf-8")
        regression = (PROJECT_ROOT / "run_legacy_regression.sh").read_text(
            encoding="utf-8"
        )
        environment = (PROJECT_ROOT / "environment.cluster.yml").read_text(
            encoding="utf-8"
        )
        config = (
            PROJECT_ROOT / "config" / "config.cluster.example.yaml"
        ).read_text(encoding="utf-8")

        for script in (wrapper, submitter, worker, regression):
            self.assertIn("set -euo pipefail", script)
        self.assertIn('E3_SLURM_ACCOUNT:-barton', submitter)
        self.assertIn('E3_SLURM_PARTITION:-general', submitter)
        self.assertIn('conda_explicit_spec.txt', wrapper)
        self.assertIn('conda_environment_no_builds.yaml', wrapper)
        self.assertIn('run --no-capture-output', regression)
        self.assertIn('fpocket=4.2.2', environment)
        self.assertIn('required_p2rank_version_prefix: "2.5.1"', config)
        self.assertNotIn('/Users/ebutterfield', wrapper + submitter + worker)

    def test_production_shell_scripts_pass_bash_syntax(self) -> None:
        """Every non-legacy Bash script must pass ``bash -n``."""

        shell_paths = [PROJECT_ROOT / "run_e3_ligandability.sh"]
        shell_paths.extend(sorted((PROJECT_ROOT / "scripts").glob("*.sh")))
        self.assertGreaterEqual(len(shell_paths), 3)
        for path in shell_paths:
            with self.subTest(path=path.name):
                completed = subprocess.run(
                    ["bash", "-n", str(path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
