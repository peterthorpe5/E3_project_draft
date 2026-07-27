"""Repository-level checks for the browsable documentation site."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml


def _navigation_paths(value: object) -> list[str]:
    """Recursively collect internal MkDocs navigation paths."""
    if isinstance(value, str):
        return [] if "://" in value else [value]
    if isinstance(value, list):
        paths = []
        for item in value:
            paths.extend(_navigation_paths(item))
        return paths
    if isinstance(value, dict):
        paths = []
        for item in value.values():
            paths.extend(_navigation_paths(item))
        return paths
    return []


class DocumentationSiteTests(unittest.TestCase):
    """Validate the documentation source and deployment contract."""

    @classmethod
    def setUpClass(cls) -> None:
        """Resolve the repository once."""
        cls.repository_root = Path(__file__).resolve().parents[1]
        cls.mkdocs_path = cls.repository_root / "mkdocs.yml"
        cls.docs_root = cls.repository_root / "docs_site"

    def test_every_navigation_page_exists(self) -> None:
        """MkDocs navigation must not refer to missing source pages."""
        configuration = yaml.safe_load(self.mkdocs_path.read_text(encoding="utf-8"))
        paths = _navigation_paths(configuration["nav"])
        self.assertGreaterEqual(len(paths), 13)
        for relative_path in paths:
            self.assertTrue(
                (self.docs_root / relative_path).is_file(),
                relative_path,
            )

    def test_internal_markdown_links_resolve(self) -> None:
        """Simple relative Markdown links must point to existing files."""
        link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        for page in self.docs_root.rglob("*.md"):
            for target in link_pattern.findall(page.read_text(encoding="utf-8")):
                if (
                    "://" in target
                    or target.startswith("#")
                    or target.startswith("mailto:")
                ):
                    continue
                link_path = target.split("#", maxsplit=1)[0]
                if not link_path:
                    continue
                self.assertTrue(
                    (page.parent / link_path).resolve().is_file(),
                    f"{page}: {target}",
                )

    def test_pages_workflow_builds_strictly_and_deploys_official_artifact(self) -> None:
        """The Pages workflow must validate pull requests and deploy built static files."""
        workflow = (
            self.repository_root / ".github" / "workflows" / "docs.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("mkdocs build --strict", workflow)
        self.assertIn("actions/upload-pages-artifact@v3", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)
        self.assertIn("pages: write", workflow)
        self.assertIn("id-token: write", workflow)

    def test_documentation_dependencies_are_major_version_bounded(self) -> None:
        """Documentation dependencies must not use unbounded floating versions."""
        requirements = (
            self.repository_root / "requirements-docs.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("mkdocs>=1.6,<2", requirements)
        self.assertIn("mkdocs-material>=9.6,<10", requirements)


if __name__ == "__main__":
    unittest.main()
