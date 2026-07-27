"""Unit tests for general IO and path-layout helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from e3parquet.io_utils import (
    canonical_relative_path,
    derived_output_path,
    is_probable_parquet_file,
    iter_source_files,
    path_has_hidden_or_macos_sidecar_part,
    safe_path_from_relative,
    table_name_from_relative_path,
)


class TestCanonicalPaths(unittest.TestCase):
    """Tests for clearer derived output path naming."""

    def test_main_folder_e3_database_is_renamed_in_derived_path(self) -> None:
        """Inherited vague folders should become explicit derived folders."""
        canonical = canonical_relative_path(
            "Main_folder/E3_database/tables/e3_ligases.csv"
        )
        self.assertEqual(canonical, "curated_e3_database/tables/e3_ligases.csv")

    def test_other_things_deepclust_is_renamed_in_derived_path(self) -> None:
        """DeepClust outputs should get a clear derived prefix."""
        canonical = canonical_relative_path(
            "Other_things/Denbi/denbi_data/E3_discovery_engine/output/x.parquet"
        )
        self.assertEqual(canonical, "deepclust_discovery_engine/output/x.parquet")

    def test_table_name_uses_canonical_path(self) -> None:
        """Derived table names should avoid the inherited Main_folder wording."""
        name = table_name_from_relative_path(
            "Main_folder/E3_database/tables/e3_ligases.csv"
        )
        self.assertEqual(name, "curated_e3_database_tables_e3_ligases.csv")

    def test_derived_output_path_preserves_nested_meaning(self) -> None:
        """Derived Parquet outputs should live in explicit nested folders."""
        output = derived_output_path(
            Path("parquet/source_tables"),
            "Main_folder/E3_database/tables/e3_ligases.csv",
        )
        self.assertEqual(
            output.as_posix(),
            "parquet/source_tables/curated_e3_database/tables/"
            "e3_ligases.csv.parquet",
        )

    def test_safe_path_from_relative_removes_spaces(self) -> None:
        """Safe nested paths should keep hierarchy while removing bad chars."""
        output = safe_path_from_relative("a folder/file name.csv")
        self.assertEqual(output.as_posix(), "a_folder/file_name.csv")


class TestHiddenAndParquetDetection(unittest.TestCase):
    """Tests for macOS sidecar and Parquet validation helpers."""

    def test_nested_macos_sidecar_part_is_detected(self) -> None:
        """Any AppleDouble path component should be treated as hidden."""
        self.assertTrue(
            path_has_hidden_or_macos_sidecar_part(Path("x/._bad.parquet"))
        )
        self.assertFalse(
            path_has_hidden_or_macos_sidecar_part(Path("x/good.parquet"))
        )

    def test_iter_source_files_skips_nested_sidecar_files(self) -> None:
        """Source iteration should not include macOS sidecar files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data").mkdir()
            (root / "data" / "good.csv").write_text("a\n1\n", encoding="utf-8")
            (root / "data" / "._good.csv").write_text("sidecar", encoding="utf-8")
            files = [path.name for path in iter_source_files(root)]
            self.assertEqual(files, ["good.csv"])

    def test_probable_parquet_requires_magic_bytes(self) -> None:
        """Real Parquet-like files should have PAR1 header and footer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good = root / "good.parquet"
            bad = root / "bad.parquet"
            sidecar = root / "._good.parquet"
            good.write_bytes(b"PAR1payloadPAR1")
            bad.write_bytes(b"not parquet")
            sidecar.write_bytes(b"PAR1payloadPAR1")

            self.assertTrue(is_probable_parquet_file(good))
            self.assertFalse(is_probable_parquet_file(bad))
            self.assertFalse(is_probable_parquet_file(sidecar))


if __name__ == "__main__":
    unittest.main()
