"""Known-answer integration tests for the complete curated resource layer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import duckdb

from e3parquet.curated import DebugRecorder, create_curated_views


class TestCuratedResourceIntegration(unittest.TestCase):
    """Verify scientific aggregates and fail-safe empty-source behaviour."""

    @staticmethod
    def _initialise_source_database(database: Path) -> None:
        """Create heterogeneous source tables and their catalogue."""
        with duckdb.connect(str(database)) as connection:
            connection.execute(
                'CREATE TABLE protein_source('
                '"Accession" VARCHAR, "Gene Names" VARCHAR, '
                '"Organism" VARCHAR, "Organism ID" VARCHAR, '
                '"Category" VARCHAR, "Reviewed" VARCHAR, '
                '"Protein names" VARCHAR, "Length" VARCHAR)'
            )
            connection.execute(
                "INSERT INTO protein_source VALUES "
                "('P1', 'GENE1', 'Plant A', '1', 'RING', 'yes', 'One', '100'), "
                "('P2', 'GENE2', 'Plant B', '2', 'HECT', 'no', 'Two', '200')"
            )
            connection.execute(
                "CREATE TABLE sequence_source("
                "accession VARCHAR, fasta_header VARCHAR, sequence VARCHAR, "
                "sequence_length VARCHAR, sequence_md5 VARCHAR)"
            )
            connection.execute(
                "INSERT INTO sequence_source VALUES "
                "('P1', '>P1', 'AAAA', '4', 'md5-p1'), "
                "('P2', '>P2', 'AAAAAA', '6', 'md5-p2')"
            )
            connection.execute(
                "CREATE TABLE literature_source(accession VARCHAR, PMID VARCHAR)"
            )
            connection.execute("INSERT INTO literature_source VALUES ('P1', '12345')")
            connection.execute(
                "CREATE TABLE go_source("
                "accession VARCHAR, go_id VARCHAR, ubiquitin_go_term VARCHAR, "
                "exclusion_go_term VARCHAR)"
            )
            connection.execute(
                "INSERT INTO go_source VALUES ('P1', 'GO:0016567', 'yes', 'no')"
            )
            connection.execute(
                "CREATE TABLE pocket_source("
                "accession VARCHAR, pocket_name VARCHAR, "
                "druggability_score VARCHAR, probability VARCHAR, "
                "rank VARCHAR, P2Rank_score VARCHAR)"
            )
            connection.execute(
                "INSERT INTO pocket_source VALUES "
                "('P1', 'pocket 1', '0.60', '0.70', '1', '7.0'), "
                "('P1', 'pocket 2', '0.80', '0.90', '2', '9.0')"
            )
            connection.execute(
                "CREATE TABLE deepclust_source(accession VARCHAR, cluster VARCHAR)"
            )
            connection.execute("INSERT INTO deepclust_source VALUES ('P1', 'HOG1')")
            connection.execute(
                "CREATE TABLE parquet_view_catalog("
                "view_name VARCHAR, parquet_file VARCHAR, "
                "status VARCHAR, error VARCHAR)"
            )
            rows = [
                (
                    "protein_source",
                    "source_tables/Main_folder/E3_database/e3_ligases.csv.parquet",
                    "created",
                    "",
                ),
                (
                    "sequence_source",
                    "parquet/sequences/plant.parquet",
                    "created",
                    "",
                ),
                (
                    "literature_source",
                    "other_people_data/paper.parquet",
                    "created",
                    "",
                ),
                ("go_source", "source_tables/go_terms.parquet", "created", ""),
                (
                    "pocket_source",
                    "source_tables/fpocket_scores.parquet",
                    "created",
                    "",
                ),
                (
                    "deepclust_source",
                    "source_tables/deepclust.parquet",
                    "created",
                    "",
                ),
            ]
            connection.executemany(
                "INSERT INTO parquet_view_catalog VALUES (?, ?, ?, ?)",
                rows,
            )

    def test_complete_curated_resource_has_exact_known_answers(self) -> None:
        """Every evidence source should contribute only its biological rows."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "resource.duckdb"
            derived = root / "derived"
            qc = derived / "qc"
            qc.mkdir(parents=True)
            (qc / "sqlite_regression_query_results.tsv").write_text(
                "query_id\tsqlite_status\nq1\tok\n",
                encoding="utf-8",
            )
            (qc / "expression_resource_status.tsv").write_text(
                "status\tobject_name\nfound\tatlas_expression_long\n",
                encoding="utf-8",
            )
            self._initialise_source_database(database)
            debug = DebugRecorder()

            names = create_curated_views(
                database,
                derived,
                debug,
                materialise_parquet=True,
            )

            self.assertEqual(len(names), 9)
            self.assertTrue(
                all(
                    (derived / "curated_parquet" / f"{name}.parquet").is_file()
                    for name in names
                )
            )
            with duckdb.connect(str(database), read_only=True) as connection:
                records = connection.execute(
                    "SELECT protein_accession, gene_names_standardised, "
                    "protein_length_standardised, _raw_Accession "
                    "FROM protein_records ORDER BY protein_accession"
                ).fetchall()
                self.assertEqual(
                    records,
                    [("P1", "GENE1", 100, "P1"), ("P2", "GENE2", 200, "P2")],
                )
                summary = connection.execute(
                    "SELECT protein_accession, sequence_record_count, "
                    "ligandability_record_count, max_druggability_score, "
                    "max_pocket_probability, best_pocket_rank, go_record_count, "
                    "has_ubiquitin_go_term, literature_record_count, "
                    "deepclust_record_count, example_cluster_or_orthogroup_id "
                    "FROM candidate_e3_summary ORDER BY protein_accession"
                ).fetchall()
                self.assertEqual(
                    summary,
                    [
                        ("P1", 1, 2, 0.8, 0.9, 1, 1, 1, 1, 1, "HOG1"),
                        ("P2", 1, 0, None, None, None, 0, 0, 0, 0, None),
                    ],
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM go_term_evidence"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM curated_view_catalog"
                    ).fetchone()[0],
                    9,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT sqlite_status FROM sqlite_regression_query_results"
                    ).fetchone()[0],
                    "ok",
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT status FROM expression_resource_status"
                    ).fetchone()[0],
                    "found",
                )
            self.assertTrue(
                any(
                    record["step"] == "go_term_evidence"
                    and record["status"] == "skipped"
                    for record in debug.records
                )
            )

    def test_absent_catalog_creates_typed_empty_views(self) -> None:
        """A missing source catalogue must yield explicit empty relations."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "resource.duckdb"
            with duckdb.connect(str(database)):
                pass
            debug = DebugRecorder()

            names = create_curated_views(
                database,
                root / "derived",
                debug,
                materialise_parquet=False,
            )

            with duckdb.connect(str(database), read_only=True) as connection:
                for name in names:
                    self.assertEqual(
                        connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0],
                        0,
                    )
            self.assertTrue(
                any(
                    record["step"] == "parquet_view_catalog"
                    and record["status"] == "missing"
                    for record in debug.records
                )
            )


if __name__ == "__main__":
    unittest.main()
