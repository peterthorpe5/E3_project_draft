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
    iter_tabular_files,
    iter_text_files,
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

    def test_tsv_text_and_excel_inputs_preserve_their_layout(self) -> None:
        """All supported tabular formats should retain strings and sheets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tsv = root / "values.tsv"
            text = root / "values.txt"
            workbook = root / "values.xlsx"
            tsv.write_text("id\tvalue\nP1\t001\n", encoding="utf-8")
            text.write_text("id;value\nP2;002\n", encoding="utf-8")
            with pd.ExcelWriter(workbook) as writer:
                pd.DataFrame({"id": ["P3"], "value": ["003"]}).to_excel(
                    writer,
                    sheet_name="First",
                    index=False,
                )
                pd.DataFrame({"id": ["P4"]}).to_excel(
                    writer,
                    sheet_name="Second",
                    index=False,
                )

            self.assertEqual(read_tabular_file(tsv)[0][1].loc[0, "value"], "001")
            self.assertEqual(read_tabular_file(text)[0][1].loc[0, "value"], "002")
            excel_tables = read_tabular_file(workbook)
            self.assertEqual([name for name, _frame in excel_tables], ["First", "Second"])
            self.assertEqual(excel_tables[0][1].loc[0, "value"], "003")

    def test_file_iterators_exclude_sidecars_and_honour_text_option(self) -> None:
        """Discovery must never ingest hidden AppleDouble copies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "table.csv"
            text_path = root / "notes.txt"
            sql_path = root / "query.sql"
            csv_path.write_text("id\nP1\n", encoding="utf-8")
            text_path.write_text("text\n", encoding="utf-8")
            sql_path.write_text("SELECT 1;\n", encoding="utf-8")
            (root / "._table.csv").write_text("invalid", encoding="utf-8")
            (root / "._query.sql").write_text("invalid", encoding="utf-8")

            self.assertEqual(list(iter_tabular_files(root)), [csv_path])
            self.assertEqual(
                list(iter_tabular_files(root, include_txt=True)),
                [text_path, csv_path],
            )
            self.assertEqual(list(iter_text_files(root)), [text_path, sql_path])

    def test_large_text_capture_is_explicitly_skipped_with_provenance(self) -> None:
        """The text-size guard should emit an auditable record, not drop data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "large.txt"
            path.write_text("0123456789", encoding="utf-8")

            records = ingest_text_lines(
                path,
                root,
                manifest_record={"sha256": "abc", "mtime_utc": "then"},
                max_text_bytes=5,
            )

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["capture_status"], "skipped_too_large")
            self.assertEqual(records[0]["_source_file_sha256"], "abc")
            self.assertEqual(records[0]["_source_file_size_bytes"], "10")


if __name__ == "__main__":
    unittest.main()
