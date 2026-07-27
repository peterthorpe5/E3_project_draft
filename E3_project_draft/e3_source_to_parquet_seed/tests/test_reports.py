"""Tests for Markdown report generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from e3parquet.reports import count_by, markdown_table, read_tsv, write_files_used_report


class TestReportHelpers(unittest.TestCase):
    """Tests for report helper functions."""

    def test_read_tsv_returns_empty_for_missing_file(self) -> None:
        self.assertEqual(read_tsv(Path("/definitely/missing.tsv")), [])

    def test_count_by_counts_blank_values(self) -> None:
        records = [{"role": "a"}, {"role": ""}, {}]
        self.assertEqual(count_by(records, "role"), {"a": 1, "<blank>": 2})

    def test_markdown_table_handles_empty_records(self) -> None:
        self.assertEqual(markdown_table([], ["a"]), ["No records found."])

    def test_markdown_table_limits_rows(self) -> None:
        records = [{"a": str(index)} for index in range(3)]
        lines = markdown_table(records, ["a"], max_rows=2)
        self.assertTrue(any("Showing 2 of 3" in line for line in lines))

    def test_write_files_used_report_creates_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            derived = Path(temp_dir)
            qc = derived / "qc"
            qc.mkdir()
            (qc / "source_file_manifest.tsv").write_text(
                "relative_path\tfile_format\tlogical_role_guess\tsize_bytes\tsha256\n"
                "a.csv\tcsv\te3_ligase_source\t10\tabc\n",
                encoding="utf-8",
            )
            (qc / "tabular_table_catalog.tsv").write_text(
                "table_name\tsource_file\tsource_sheet\trows\tcolumns\tstatus\n"
                "a\ta.csv\t\t1\t2\twritten\n",
                encoding="utf-8",
            )
            output = derived / "docs" / "FILES_USED.md"
            write_files_used_report(derived, output, max_rows=10)
            text = output.read_text(encoding="utf-8")
            self.assertIn("E3 PROTAC source files", text)
            self.assertIn("a.csv", text)
            self.assertIn("e3_ligase_source", text)


if __name__ == "__main__":
    unittest.main()
