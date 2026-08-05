"""Repository-level validation for scientific test traceability."""

from __future__ import annotations

import ast
import csv
import unittest
from pathlib import Path


class ScientificAssuranceMatrixTests(unittest.TestCase):
    """Keep every claimed Python assurance reference executable and named."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load the assurance authority once."""
        cls.repository_root = Path(__file__).resolve().parents[1]
        cls.matrix = (
            cls.repository_root
            / "docs"
            / "SCIENTIFIC_TEST_ASSURANCE_MATRIX.tsv"
        )
        with cls.matrix.open(encoding="utf-8", newline="") as handle:
            cls.rows = list(csv.DictReader(handle, delimiter="\t"))

    def test_matrix_has_complete_unique_contract_rows(self) -> None:
        """Every row must identify one package, contract and release status."""
        self.assertGreaterEqual(len(self.rows), 12)
        expected = {
            "package",
            "scientific_contract",
            "known_answer_test",
            "boundary_or_corruption_test",
            "provenance_or_cardinality_test",
            "status",
        }
        self.assertEqual(set(self.rows[0]), expected)
        identities = set()
        for row in self.rows:
            self.assertTrue(all(str(value).strip() for value in row.values()))
            identity = (row["package"], row["scientific_contract"])
            self.assertNotIn(identity, identities)
            identities.add(identity)
            self.assertIn(
                row["status"],
                {
                    "PASS",
                    "PENDING_DEPENDENCY_ENVIRONMENT",
                    "PENDING_R_ENVIRONMENT",
                },
            )

    def test_every_python_reference_names_a_real_test(self) -> None:
        """A traceability row may not cite a misspelled or removed Python test."""
        reference_fields = (
            "known_answer_test",
            "boundary_or_corruption_test",
            "provenance_or_cardinality_test",
        )
        for row in self.rows:
            for field in reference_fields:
                reference = row[field]
                relative_path, *identifiers = reference.split("::")
                test_path = (
                    self.repository_root / row["package"] / relative_path
                )
                self.assertTrue(test_path.is_file(), str(test_path))
                if test_path.suffix != ".py":
                    self.assertEqual(row["status"], "PENDING_R_ENVIRONMENT")
                    continue
                self.assertTrue(identifiers, reference)
                expected_name = identifiers[-1]
                tree = ast.parse(test_path.read_text(encoding="utf-8"))
                observed = {
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                self.assertIn(expected_name, observed, reference)


if __name__ == "__main__":
    unittest.main()
