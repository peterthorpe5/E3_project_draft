"""Unit tests for DuckDB view helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from e3parquet.duckdb_views import parquet_paths, view_name_for_parquet


class TestDuckdbViewHelpers(unittest.TestCase):
    """Tests for DuckDB view helper functions."""

    def test_view_name_for_parquet_is_stable(self) -> None:
        """A nested parquet path should become a stable view name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "parquet" / "source_tables" / "table.parquet"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"PAR1payloadPAR1")
            view_name = view_name_for_parquet(path, root / "parquet")
            self.assertEqual(view_name, "source_tables_table")

    def test_parquet_paths_skip_invalid_and_sidecar_files(self) -> None:
        """Only valid Parquet files should be passed to DuckDB by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "nested").mkdir()
            good = root / "nested" / "good.parquet"
            invalid = root / "nested" / "invalid.parquet"
            sidecar = root / "nested" / "._good.parquet"
            good.write_bytes(b"PAR1payloadPAR1")
            invalid.write_bytes(b"not parquet")
            sidecar.write_bytes(b"PAR1payloadPAR1")

            self.assertEqual(parquet_paths(root), [good])

    def test_parquet_paths_can_skip_magic_validation(self) -> None:
        """Magic validation can be disabled, but sidecars still stay excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            invalid = root / "invalid.parquet"
            sidecar = root / "._invalid.parquet"
            invalid.write_bytes(b"not parquet")
            sidecar.write_bytes(b"not parquet")

            self.assertEqual(parquet_paths(root, validate_magic=False), [invalid])


if __name__ == "__main__":
    unittest.main()
