"""Tests for curated debug reporting."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from e3parquet.curated import (
    DebugRecorder,
    inspect_expression_duckdb,
    locate_sqlite_db,
    source_sql_files,
    write_expression_status,
    write_regression_results,
)


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

    def test_inspect_expression_duckdb_reports_objects_and_empty_database(self) -> None:
        """Inspection should distinguish a valid empty DB from populated data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            empty = root / "empty.duckdb"
            populated = root / "populated.duckdb"
            with duckdb.connect(str(empty)):
                pass
            with duckdb.connect(str(populated)) as connection:
                connection.execute("CREATE TABLE expression(value INTEGER)")
                connection.execute("INSERT INTO expression VALUES (1), (2)")

            self.assertEqual(inspect_expression_duckdb(empty)[0]["status"], "no_objects_found")
            records = inspect_expression_duckdb(populated)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "found")
            self.assertEqual(records[0]["object_name"], "expression")
            self.assertEqual(records[0]["row_count"], 2)

    def test_status_writers_publish_tsv_and_parquet(self) -> None:
        """Mixed audit records should have durable TSV and Parquet forms."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            regression_tsv = root / "regression.tsv"
            regression_parquet = root / "regression.parquet"
            expression_tsv = root / "expression.tsv"
            expression_parquet = root / "expression.parquet"

            write_regression_results(
                [
                    {"query_id": "q1", "sqlite_row_count": 2},
                    {"query_id": "q2", "sqlite_row_count": ""},
                ],
                regression_tsv,
                regression_parquet,
            )
            write_expression_status(
                [{"status": "found", "row_count": 2}],
                expression_tsv,
                expression_parquet,
            )

            self.assertEqual(pq.read_table(regression_parquet).num_rows, 2)
            self.assertEqual(pq.read_table(expression_parquet).num_rows, 1)
            self.assertIn("q1", regression_tsv.read_text(encoding="utf-8"))
            self.assertIn("found", expression_tsv.read_text(encoding="utf-8"))

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
