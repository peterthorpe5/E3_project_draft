"""Tests for curated debug reporting."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from e3parquet.curated import DebugRecorder, inspect_expression_duckdb, locate_sqlite_db, source_sql_files


class TestDebugRecorder(unittest.TestCase):
    """Tests for verbose debug reports."""

    def test_debug_recorder_writes_tsv_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            recorder = DebugRecorder()
            recorder.add("step1", "created", "A useful message", rows=3, sources=["a", "b"])
            tsv = root / "debug.tsv"
            md = root / "debug.md"
            recorder.write(tsv, md)
            self.assertTrue(tsv.exists())
            self.assertTrue(md.exists())
            self.assertIn("A useful message", md.read_text(encoding="utf-8"))
            self.assertIn("created", tsv.read_text(encoding="utf-8"))

    def test_inspect_expression_duckdb_not_provided(self) -> None:
        records = inspect_expression_duckdb(None)
        self.assertEqual(records[0]["status"], "not_provided")
        self.assertIn("Expression", records[0]["message"])

    def test_inspect_expression_duckdb_missing_file(self) -> None:
        records = inspect_expression_duckdb(Path("/definitely/missing/e3_expression.duckdb"))
        self.assertEqual(records[0]["status"], "missing_file")

    def test_locate_sqlite_db_prefers_main_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            main = root / "Main_folder" / "E3_database" / "e3_ligase_sqlite_db.db"
            other = root / "Other_things" / "e3_ligase_sqlite_db.db"
            main.parent.mkdir(parents=True)
            other.parent.mkdir(parents=True)
            main.write_text("main", encoding="utf-8")
            other.write_text("other", encoding="utf-8")
            self.assertEqual(locate_sqlite_db(root), main)

    def test_source_sql_files_finds_only_sql_query_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sql_dir = root / "Main_folder" / "E3_database" / "sql_queries"
            sql_dir.mkdir(parents=True)
            wanted = sql_dir / "queries.txt"
            wanted.write_text("SELECT 1;", encoding="utf-8")
            ignored = root / "notes.txt"
            ignored.write_text("SELECT 2;", encoding="utf-8")
            self.assertEqual(source_sql_files(root), [wanted])


if __name__ == "__main__":
    unittest.main()
