import tempfile
import unittest
from pathlib import Path

import duckdb

from e3_discovery.clusters import Thresholds
from e3_discovery.resource import (
    build_duckdb_resource,
    get_table_row_counts,
    sql_literal,
    validate_resource,
)


class ResourceUnitTests(unittest.TestCase):
    def test_sql_literal(self):
        self.assertEqual(sql_literal("O'Reilly"), "'O''Reilly'")
        self.assertEqual(sql_literal(True), "TRUE")
        self.assertEqual(sql_literal(None), "NULL")
        self.assertEqual(sql_literal(3), "3")

    def test_get_table_row_counts(self):
        connection = duckdb.connect(":memory:")
        connection.execute("CREATE TABLE x AS SELECT 1 AS a")
        self.assertEqual(get_table_row_counts(connection, ["x"]), {"x": 1})
        connection.close()

    def test_validate_resource_reports_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            connection = duckdb.connect(":memory:")
            connection.execute(
                "CREATE TABLE sequence_records "
                "(internal_id VARCHAR, entry VARCHAR, original_id VARCHAR)"
            )
            connection.execute(
                "INSERT INTO sequence_records VALUES ('a', 'A', 'a')"
            )
            connection.execute(
                "CREATE TABLE raw_cluster_sequences "
                "(representative_id VARCHAR, sequence_id VARCHAR)"
            )
            connection.execute(
                "INSERT INTO raw_cluster_sequences VALUES ('r', 'missing')"
            )
            connection.execute(
                "CREATE TABLE e3_seeded_clusters "
                "(representative_id VARCHAR)"
            )
            connection.execute(
                "CREATE TABLE strict_e3_seeded_cluster_members "
                "(member_id VARCHAR)"
            )
            with self.assertRaises(Exception):
                validate_resource(connection, Path(tmp) / "findings.tsv")
            self.assertTrue((Path(tmp) / "findings.tsv").is_file())
            connection.close()

    def test_build_resource_rejects_bad_duckdb_threads(self):
        with self.assertRaises(ValueError):
            build_duckdb_resource(
                Path("resource.duckdb"),
                Path("sequences.parquet"),
                Path("seeds.parquet"),
                Path("clusters.parquet"),
                Path("realignments.parquet"),
                Thresholds(50, 50, 50, 20, 1e-10),
                Path("curated"),
                Path("fastas"),
                Path("validation.tsv"),
                duckdb_threads=0,
            )


if __name__ == "__main__":
    unittest.main()
