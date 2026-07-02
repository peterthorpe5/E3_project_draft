"""Tests for the top-level shell pipeline wrapper."""

from __future__ import annotations

import unittest
from pathlib import Path


class TestPipelineWrapper(unittest.TestCase):
    """Static checks for the shell wrapper argument wiring."""

    def setUp(self) -> None:
        """Load the wrapper text."""
        self.repo_root = Path(__file__).resolve().parents[1]
        self.wrapper = self.repo_root / "run_e3_seed_pipeline.sh"
        self.text = self.wrapper.read_text(encoding="utf-8")

    def test_manifest_step_uses_out_dir_argument(self) -> None:
        """The manifest script requires --out-dir, not --out-tsv."""
        manifest_block_start = self.text.index("python scripts/e3_build_manifest.py")
        manifest_block_end = self.text.index("echo \"[2/6]", manifest_block_start)
        manifest_block = self.text[manifest_block_start:manifest_block_end]
        self.assertIn("--out-dir", manifest_block)
        self.assertNotIn("--out-tsv", manifest_block)

    def test_optional_derived_dir_argument_is_supported(self) -> None:
        """The wrapper should allow a custom output directory as argument 3."""
        self.assertIn("DERIVED_DIR=\"${3:-${PROJECT_ROOT}/derived}\"", self.text)
        self.assertIn("Usage: $0 PROJECT_ROOT [EXPRESSION_DUCKDB] [DERIVED_DIR]", self.text)

    def test_wrapper_reports_key_outputs(self) -> None:
        """The wrapper should print the important output locations."""
        self.assertIn("Done. Derived output directory", self.text)
        self.assertIn("Done. Main DuckDB", self.text)
        self.assertIn("curated_resource_debug.md", self.text)
        self.assertIn("expression_resource_status.tsv", self.text)


if __name__ == "__main__":
    unittest.main()
