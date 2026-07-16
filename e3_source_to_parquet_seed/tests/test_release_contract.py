"""Release-contract tests for the candidate evidence integration layer."""

from __future__ import annotations

import ast
import csv
import tomllib
import unittest
from pathlib import Path

from e3parquet import __version__
from e3parquet.candidate_evidence import REQUIRED_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_MODULE = REPO_ROOT / "e3parquet" / "candidate_evidence.py"
CLI_MODULE = REPO_ROOT / "scripts" / "e3_build_candidate_evidence.py"
SCHEMA_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "production_duckdb_columns_20260716.tsv"
)
TRACEABILITY = REPO_ROOT / "docs" / "CANDIDATE_EVIDENCE_TEST_TRACEABILITY.tsv"


class TestReleaseContract(unittest.TestCase):
    """Check versioning, documentation, production schema and test mapping."""

    def test_version_is_consistent_across_release_files(self) -> None:
        """Package, project metadata and README should report one version."""
        with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(project["project"]["version"], __version__)
        self.assertIn(f"Version {__version__}", readme)

    def test_all_python_functions_have_docstrings(self) -> None:
        """Every function in package and command modules should be documented."""
        missing = []
        paths = sorted((REPO_ROOT / "e3parquet").glob("*.py"))
        paths.extend(sorted((REPO_ROOT / "scripts").glob("*.py")))
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not ast.get_docstring(node):
                        missing.append(
                            f"{path.relative_to(REPO_ROOT)}:"
                            f"{node.lineno}:{node.name}"
                        )
        self.assertEqual(missing, [])

    def test_required_columns_match_inspected_production_schema(self) -> None:
        """Required fields should exist in the real 16 July production schema."""
        observed: dict[str, set[str]] = {}
        with SCHEMA_FIXTURE.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                observed.setdefault(row["table_name"], set()).add(
                    row["column_name"]
                )
        problems = []
        for table_name, required in REQUIRED_COLUMNS.items():
            missing = sorted(required - observed.get(table_name, set()))
            if missing:
                problems.append(f"{table_name}: {', '.join(missing)}")
        self.assertEqual(problems, [])

    def test_every_new_function_has_test_traceability(self) -> None:
        """Every top-level new function should map to one or more named tests."""
        expected = set()
        for path in (CANDIDATE_MODULE, CLI_MODULE):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            expected.update(
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
        with TRACEABILITY.open(encoding="utf-8", newline="") as handle:
            traced = {
                row["function_or_contract"]
                for row in csv.DictReader(handle, delimiter="\t")
            }
        self.assertEqual(sorted(expected - traced), [])

    def test_documentation_records_scientific_limit_and_read_only_source(self) -> None:
        """The guide should retain the core interpretation and data safety rule."""
        text = (
            REPO_ROOT / "docs" / "CANDIDATE_EVIDENCE_RESOURCE.md"
        ).read_text(encoding="utf-8")
        self.assertIn("attached read-only", text)
        self.assertIn(
            "does not prove that every member is an E3 ligase",
            text,
        )
        self.assertIn("ARIA Milestone 1", text)
        self.assertIn("Milestone 2", text)


if __name__ == "__main__":
    unittest.main()
