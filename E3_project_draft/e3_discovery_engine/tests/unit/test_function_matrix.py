import ast
import csv
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "e3_discovery"
MATRIX = ROOT / "tests" / "FUNCTION_TEST_MATRIX.tsv"


def source_functions():
    functions = set()
    for path in sorted(SOURCE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.add((path.stem, node.name))
            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(
                        child,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    ):
                        functions.add((path.stem, f"{node.name}.{child.name}"))
    return functions


class FunctionTestMatrixTests(unittest.TestCase):
    def test_every_defined_function_is_mapped_to_existing_tests(self):
        with MATRIX.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        mapped = {(row["module"], row["function"]) for row in rows}
        self.assertEqual(mapped, source_functions())
        for row in rows:
            with self.subTest(function=row["function"]):
                test_files = row["test_files"].split(";")
                self.assertTrue(test_files)
                for relative in test_files:
                    self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
