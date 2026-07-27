"""Unit tests for tabular and text ingestion utilities."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from e3parquet.tabular import (
    add_source_columns,
    detect_delimiter,
    ingest_text_lines,
    output_table_name,
    read_tabular_file,
)


class TestTabularUtilities(unittest.TestCase):
    """Tests for tabular source helpers."""

    def test_detect_delimiter_prefers_tabs(self) -> None:
        """Delimiter detection should handle TSV files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "table.txt"
            path.write_text("a\tb\n1\t2\n", encoding="utf-8")
            self.assertEqual(detect_delimiter(path), "\t")

    def test_read_csv_preserves_values_as_strings(self) -> None:
        """CSV reading should preserve input values as strings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "table.csv"
            path.write_text("accession,value\nQ39090,001\n", encoding="utf-8")
            tables = read_tabular_file(path)
            self.assertEqual(len(tables), 1)
            _, dataframe = tables[0]
            self.assertEqual(dataframe.loc[0, "value"], "001")

    def test_add_source_columns(self) -> None:
        """Source metadata should be added to every tabular record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "data.tsv"
            source.write_text("a\n1\n", encoding="utf-8")
            dataframe = pd.DataFrame({"a": ["1"]})
            enriched = add_source_columns(
                dataframe,
                source_file=source,
                raw_root=root,
                source_kind="tabular",
                manifest_record={"sha256": "abc", "size_bytes": 12},
            )
            self.assertIn("_source_file", enriched.columns)
            self.assertEqual(enriched.loc[0, "_source_file"], "data.tsv")
            self.assertEqual(enriched.loc[0, "_source_file_sha256"], "abc")
            self.assertEqual(enriched.loc[0, "_row_number_in_source"], 1)

    def test_text_line_ingestion(self) -> None:
        """Text files should be preserved line by line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            text = root / "query.sql"
            text.write_text("SELECT *\nFROM table;\n", encoding="utf-8")
            records = ingest_text_lines(text, root)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["line_text"], "SELECT *")
            self.assertEqual(records[1]["line_number"], 2)

    def test_output_table_name_includes_sheet(self) -> None:
        """Excel sheet names should be reflected in output table names."""
        name = output_table_name(Path("folder/table.xlsx"), "Sheet 1")
        self.assertIn("sheet", name)
        self.assertIn("Sheet_1", name)


if __name__ == "__main__":
    unittest.main()
