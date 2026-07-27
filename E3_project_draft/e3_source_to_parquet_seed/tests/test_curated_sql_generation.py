"""Tests for generated SQL snippets used in curated views."""

from __future__ import annotations

import unittest

from e3parquet.curated import coalesce_columns_sql, try_cast_numeric_sql, safe_view_suffix


class TestCuratedSqlGeneration(unittest.TestCase):
    """Small SQL generation tests."""

    def test_coalesce_columns_sql_returns_null_when_no_candidates(self) -> None:
        self.assertEqual(coalesce_columns_sql("t", ["A"], ["missing"]), "NULL")

    def test_coalesce_columns_sql_returns_single_expression_without_coalesce(self) -> None:
        sql = coalesce_columns_sql("t", ["Accession"], ["Accession"])
        self.assertTrue(sql.startswith("NULLIF"))
        self.assertNotIn("COALESCE", sql)

    def test_coalesce_columns_sql_returns_coalesce_for_multiple_columns(self) -> None:
        sql = coalesce_columns_sql("t", ["Accession", "Entry"], ["Accession", "Entry"])
        self.assertTrue(sql.startswith("COALESCE"))

    def test_try_cast_numeric_sql_wraps_expression(self) -> None:
        self.assertEqual(try_cast_numeric_sql("x"), "TRY_CAST(x AS DOUBLE)")

    def test_safe_view_suffix_removes_common_prefixes(self) -> None:
        suffix = safe_view_suffix("parquet__source_tables__curated_e3_database__tables__e3_ligases.csv")
        self.assertNotIn("parquet__", suffix)
        self.assertLessEqual(len(suffix), 96)


if __name__ == "__main__":
    unittest.main()
