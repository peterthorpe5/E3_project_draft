"""Unit tests for macOS sidecar cleanup helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from e3parquet.cleanup import clean_macos_sidecar_files, find_macos_sidecar_files


class TestCleanupHelpers(unittest.TestCase):
    """Tests for detecting and cleaning AppleDouble sidecar files."""

    def test_find_macos_sidecar_files(self) -> None:
        """Only sidecar files should be returned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "nested").mkdir()
            good = root / "nested" / "good.parquet"
            sidecar = root / "nested" / "._good.parquet"
            good.write_text("ok", encoding="utf-8")
            sidecar.write_text("sidecar", encoding="utf-8")

            self.assertEqual(find_macos_sidecar_files(root), [sidecar])

    def test_clean_macos_sidecar_files_dry_run_and_delete(self) -> None:
        """Dry-run should not delete; delete mode should remove the sidecar."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sidecar = root / "._file.csv"
            sidecar.write_text("sidecar", encoding="utf-8")

            dry_run = clean_macos_sidecar_files(root, delete=False)
            self.assertEqual(dry_run[0]["status"], "would_delete")
            self.assertTrue(sidecar.exists())

            deleted = clean_macos_sidecar_files(root, delete=True)
            self.assertEqual(deleted[0]["status"], "deleted")
            self.assertFalse(sidecar.exists())


if __name__ == "__main__":
    unittest.main()
