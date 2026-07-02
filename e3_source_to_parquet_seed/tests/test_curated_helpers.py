"""Tests for curated E3 view helper functions."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from e3parquet.curated import (
    coalesce_columns_sql,
    duckdb_quote_identifier,
    duckdb_quote_literal,
    extract_select_queries_from_files,
    find_column,
    normalise_column_name,
    normalise_records_for_parquet,
    raw_source_column_projection,
    run_sqlite_regression_queries,
    score_catalog_record,
    select_best_catalog_view,
    select_views_by_terms,
    split_sql_statements,
    strip_sql_comments,
)


class TestCuratedHelpers(unittest.TestCase):
    """Pure-function tests for curated curation helpers."""

    def test_quote_identifier_escapes_double_quotes(self) -> None:
        self.assertEqual(duckdb_quote_identifier('a"b'), '"a""b"')

    def test_quote_literal_escapes_single_quotes(self) -> None:
        self.assertEqual(duckdb_quote_literal("a'b"), "'a''b'")

    def test_normalise_column_name_removes_case_and_punctuation(self) -> None:
        self.assertEqual(normalise_column_name("Gene Names (primary)"), "genenamesprimary")

    def test_find_column_is_case_and_punctuation_insensitive(self) -> None:
        columns = ["Entry", "Gene Names", "Organism ID"]
        self.assertEqual(find_column(columns, ["gene_names"]), "Gene Names")
        self.assertEqual(find_column(columns, ["organism_id"]), "Organism ID")
        self.assertIsNone(find_column(columns, ["missing"]))

    def test_coalesce_columns_sql_uses_available_columns_once(self) -> None:
        sql = coalesce_columns_sql("t", ["Entry", "entry"], ["entry", "Entry"])
        self.assertIn('"t"."entry"', sql)
        self.assertNotEqual(sql, "NULL")

    def test_split_sql_statements_handles_semicolon_inside_string(self) -> None:
        statements = split_sql_statements("SELECT ';' AS x; SELECT 2;")
        self.assertEqual(len(statements), 2)
        self.assertIn("';'", statements[0])

    def test_strip_sql_comments_removes_whole_line_comments(self) -> None:
        cleaned = strip_sql_comments("-- hello\nSELECT 1;\n  -- bye")
        self.assertEqual(cleaned, "SELECT 1;")

    def test_score_catalog_record_prefers_curated_e3_database(self) -> None:
        good = {
            "view_name": "parquet__source_tables__curated_e3_database__tables__e3_ligases.csv",
            "parquet_file": "parquet/source_tables/curated_e3_database/tables/e3_ligases.csv.parquet",
        }
        weak = {
            "view_name": "parquet__source_tables__inherited_reports__M1-E3_ligases-Jan-2026.csv",
            "parquet_file": "parquet/source_tables/inherited_reports/M1-E3_ligases-Jan-2026.csv.parquet",
        }
        self.assertGreater(
            score_catalog_record(good, ["e3_ligases.csv"]),
            score_catalog_record(weak, ["e3_ligases.csv"]),
        )

    def test_select_best_catalog_view_returns_none_when_no_match(self) -> None:
        catalog = [{"view_name": "abc", "parquet_file": "abc.parquet", "status": "created"}]
        self.assertIsNone(select_best_catalog_view(catalog, ["e3_ligases.csv"]))

    def test_select_best_catalog_view_ignores_failed_status(self) -> None:
        catalog = [
            {"view_name": "bad", "parquet_file": "e3_ligases.csv.parquet", "status": "failed"},
            {"view_name": "good", "parquet_file": "curated_e3_database/e3_ligases.csv.parquet", "status": "created"},
        ]
        self.assertEqual(select_best_catalog_view(catalog, ["e3_ligases.csv"]), "good")

    def test_select_views_by_terms_excludes_terms(self) -> None:
        catalog = [
            {"view_name": "one", "parquet_file": "pocket_scores.parquet"},
            {"view_name": "two", "parquet_file": "sql_queries/pocket_notes.parquet"},
        ]
        self.assertEqual(select_views_by_terms(catalog, ["pocket"], ["sql_queries"]), ["one"])


class TestSqliteRegressionHelpers(unittest.TestCase):
    """Tests for SQL query extraction and SQLite regression checks."""

    def test_extract_select_queries_only_keeps_select_and_with(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sql_dir = root / "Main_folder" / "E3_database" / "sql_queries"
            sql_dir.mkdir(parents=True)
            sql_file = sql_dir / "queries.sql"
            sql_file.write_text(
                "CREATE TABLE x(a INT);\nSELECT * FROM x;\nWITH y AS (SELECT 1 AS a) SELECT * FROM y;",
                encoding="utf-8",
            )
            queries = extract_select_queries_from_files([sql_file], root)
            self.assertEqual(len(queries), 2)
            self.assertTrue(queries[0]["sql_text"].lower().startswith("select"))
            self.assertTrue(queries[1]["sql_text"].lower().startswith("with"))

    def test_run_sqlite_regression_queries_records_success_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "e3_ligase_sqlite_db.db"
            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE e3_ligases(entry TEXT)")
                connection.execute("INSERT INTO e3_ligases VALUES ('Q1')")
            sql_dir = root / "Main_folder" / "E3_database" / "sql_queries"
            sql_dir.mkdir(parents=True)
            sql_file = sql_dir / "queries.sql"
            sql_file.write_text(
                "SELECT * FROM e3_ligases;\nSELECT * FROM missing_table;",
                encoding="utf-8",
            )
            results = run_sqlite_regression_queries(db_path, [sql_file], root)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["sqlite_status"], "ok")
            self.assertEqual(results[0]["sqlite_row_count"], 1)
            self.assertEqual(results[1]["sqlite_status"], "failed")
            self.assertIn("missing_table", results[1]["sqlite_error"])


if __name__ == "__main__":
    unittest.main()

class TestParquetNormalisation(unittest.TestCase):
    """Regression tests for robust audit Parquet writing."""

    def test_normalise_records_for_parquet_turns_mixed_types_into_strings(self):
        """Mixed success/failure regression rows should be Arrow-friendly."""
        records = [
            {"query_id": "ok", "sqlite_row_count": 12, "sqlite_error": ""},
            {"query_id": "failed", "sqlite_row_count": "", "sqlite_error": "no table"},
            {"query_id": "none", "sqlite_row_count": None, "sqlite_error": None},
        ]
        clean = normalise_records_for_parquet(records)
        self.assertEqual(clean[0]["sqlite_row_count"], "12")
        self.assertEqual(clean[1]["sqlite_row_count"], "")
        self.assertEqual(clean[2]["sqlite_row_count"], "")
        self.assertTrue(all(isinstance(row["sqlite_row_count"], str) for row in clean))

    def test_raw_source_projection_renames_source_sequence_column(self):
        """Source columns must not collide with curated aliases like sequence."""
        projection = raw_source_column_projection(
            "t",
            ["protein_accession", "sequence", "sequence_md5", "_source_file"],
            reserved_aliases=("protein_accession", "sequence", "sequence_md5"),
        )
        self.assertIn('AS "_raw_sequence"', projection)
        self.assertNotIn('AS "sequence"', projection)
