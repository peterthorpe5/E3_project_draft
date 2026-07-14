"""Source-level contracts for production Python docstrings."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "e3_discovery"


def _source_trees():
    """Yield each source path and its parsed abstract syntax tree.

    Yields:
        Pairs containing a Python source path and parsed ``ast.Module``.
    """

    for path in sorted(SOURCE.glob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"))


def _qualified_definitions(node, prefix=""):
    """Yield qualified names and class/function definition nodes recursively.

    Args:
        node: AST node whose body will be inspected.
        prefix: Qualified parent name used for nested definitions.

    Yields:
        Pairs containing a qualified definition name and its AST node.
    """

    for child in getattr(node, "body", []):
        if isinstance(child, ast.ClassDef):
            name = f"{prefix}.{child.name}" if prefix else child.name
            yield name, child
            yield from _qualified_definitions(child, name)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{prefix}.{child.name}" if prefix else child.name
            yield name, child
            yield from _qualified_definitions(child, name)


def _contains_direct_raise(node):
    """Return whether a function contains an explicit non-nested raise.

    Args:
        node: Function definition node to inspect.

    Returns:
        ``True`` when the function body contains an explicit ``raise`` statement.
    """

    class RaiseVisitor(ast.NodeVisitor):
        """Find raise statements while ignoring nested definitions."""

        def __init__(self):
            """Initialise the visitor with no observed raise statement.

            Returns:
                None.
            """

            self.found = False

        def visit_Raise(self, child):
            """Record an explicit raise statement.

            Args:
                child: Raise node encountered during traversal.

            Returns:
                None.
            """

            del child
            self.found = True

        def visit_FunctionDef(self, child):
            """Skip nested synchronous function definitions.

            Args:
                child: Nested function node that must not be traversed.

            Returns:
                None.
            """

            del child

        def visit_AsyncFunctionDef(self, child):
            """Skip nested asynchronous function definitions.

            Args:
                child: Nested function node that must not be traversed.

            Returns:
                None.
            """

            del child

        def visit_ClassDef(self, child):
            """Skip nested class definitions.

            Args:
                child: Nested class node that must not be traversed.

            Returns:
                None.
            """

            del child

    visitor = RaiseVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return visitor.found


class DocstringQualityTests(unittest.TestCase):
    """Enforce the package code-documentation standard."""

    def test_every_source_module_and_definition_has_a_docstring(self):
        """Require docstrings on modules, classes, functions and methods.

        Returns:
            None.
        """

        for path, tree in _source_trees():
            with self.subTest(module=path.name):
                self.assertTrue(ast.get_docstring(tree), path.name)
            for name, node in _qualified_definitions(tree):
                with self.subTest(module=path.name, definition=name):
                    self.assertTrue(ast.get_docstring(node), name)

    def test_summary_lines_end_with_full_stops(self):
        """Require PEP 257-style summary sentences.

        Returns:
            None.
        """

        for path, tree in _source_trees():
            definitions = [(path.stem, tree), *_qualified_definitions(tree)]
            for name, node in definitions:
                doc = ast.get_docstring(node)
                with self.subTest(module=path.name, definition=name):
                    self.assertIsNotNone(doc)
                    self.assertTrue(doc.splitlines()[0].endswith("."), doc)

    def test_function_arguments_and_results_are_documented(self):
        """Require argument and return or yield sections for every function.

        Returns:
            None.
        """

        for path, tree in _source_trees():
            for name, node in _qualified_definitions(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                doc = ast.get_docstring(node) or ""
                arguments = [
                    argument.arg
                    for argument in (
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    )
                    if argument.arg not in {"self", "cls"}
                ]
                if node.args.vararg is not None:
                    arguments.append(node.args.vararg.arg)
                if node.args.kwarg is not None:
                    arguments.append(node.args.kwarg.arg)
                with self.subTest(module=path.name, function=name):
                    if arguments:
                        self.assertIn("Args:", doc)
                        for argument in arguments:
                            self.assertRegex(
                                doc,
                                rf"(?m)^\s{{4,}}{re.escape(argument)}:",
                            )
                    self.assertTrue(
                        "Returns:" in doc or "Yields:" in doc,
                        f"Missing result section: {path.name}:{name}",
                    )

    def test_explicit_raises_are_documented(self):
        """Require a Raises section when a function explicitly raises.

        Returns:
            None.
        """

        for path, tree in _source_trees():
            for name, node in _qualified_definitions(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _contains_direct_raise(node):
                    with self.subTest(module=path.name, function=name):
                        self.assertIn("Raises:", ast.get_docstring(node) or "")


if __name__ == "__main__":
    unittest.main()
