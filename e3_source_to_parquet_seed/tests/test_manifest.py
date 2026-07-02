"""Unit tests for source-file manifest creation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from e3parquet.file_manifest import build_file_manifest
from e3parquet.io_utils import (
    guess_file_format,
    guess_logical_role,
    is_hidden_or_macos_sidecar,
    safe_name,
)


class TestManifestUtilities(unittest.TestCase):
    """Tests for manifest helper functions."""

    def test_safe_name_removes_problem_characters(self) -> None:
        """Safe names should be stable and filesystem friendly."""
        self.assertEqual(safe_name("a path/with spaces.csv"), "a_path_with_spaces.csv")

    def test_hidden_macos_sidecar_detection(self) -> None:
        """macOS resource-fork files should be recognised."""
        self.assertTrue(is_hidden_or_macos_sidecar(Path("._example.csv")))
        self.assertTrue(is_hidden_or_macos_sidecar(Path(".DS_Store")))
        self.assertFalse(is_hidden_or_macos_sidecar(Path("example.csv")))

    def test_file_format_guess(self) -> None:
        """Common inherited file suffixes should be classified."""
        self.assertEqual(guess_file_format(Path("x.fasta")), "fasta")
        self.assertEqual(guess_file_format(Path("x.tsv")), "tsv")
        self.assertEqual(guess_file_format(Path("x.db")), "sqlite")

    def test_logical_role_guess(self) -> None:
        """Path keywords should provide useful role guesses."""
        self.assertEqual(
            guess_logical_role("Main_folder/E3_database/tables/e3_ligases.csv"),
            "e3_ligase_source",
        )
        self.assertEqual(
            guess_logical_role("some/path/fpocket/pocket_details.csv"),
            "ligandability",
        )
        self.assertEqual(
            guess_logical_role("some/path/Orthogroups.tsv"),
            "orthology",
        )


class TestBuildFileManifest(unittest.TestCase):
    """Tests for manifest creation."""

    def test_manifest_contains_source_metadata(self) -> None:
        """A small source tree should produce deterministic manifest records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "Main_folder" / "E3_database" / "tables"
            source.mkdir(parents=True)
            (source / "e3_ligases.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            (source / "._ignore.csv").write_text("sidecar", encoding="utf-8")

            manifest = build_file_manifest(root, checksum=True, include_hidden=False)

            self.assertEqual(len(manifest), 1)
            record = manifest[0]
            self.assertEqual(
                record["relative_path"],
                "Main_folder/E3_database/tables/e3_ligases.csv",
            )
            self.assertEqual(record["file_format"], "csv")
            self.assertTrue(record["sha256"])
            self.assertIn("mtime_utc", record)


if __name__ == "__main__":
    unittest.main()
