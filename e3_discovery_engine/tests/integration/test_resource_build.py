import tempfile
import unittest
from pathlib import Path

import duckdb

from e3_discovery.clusters import (
    Thresholds,
    cluster_tsv_to_parquet,
    realign_tsv_to_parquet,
)
from e3_discovery.fasta import prepare_combined_fasta
from e3_discovery.manifest import SampleRecord
from e3_discovery.resource import build_duckdb_resource
from e3_discovery.seeds import prepare_seed_table


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class ResourceIntegrationTests(unittest.TestCase):
    def test_build_resource_from_synthetic_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequence_parquet = root / "sequences.parquet"
            prepare_combined_fasta(
                [
                    SampleRecord("species_a", FIXTURES / "species_a.fasta", "A"),
                    SampleRecord("species_b", FIXTURES / "species_b.fasta", "B"),
                ],
                root / "combined.fasta",
                sequence_parquet,
                root / "sample_summary.tsv",
                batch_size=1,
            )
            seed_parquet = root / "seeds.parquet"
            prepare_seed_table(
                FIXTURES / "e3_seeds.csv",
                root / "seeds.tsv",
                seed_parquet,
            )
            cluster_parquet = root / "clusters.parquet"
            cluster_tsv_to_parquet(
                FIXTURES / "raw_clusters.tsv",
                cluster_parquet,
                batch_size=1,
            )
            realign_parquet = root / "realign.parquet"
            thresholds = Thresholds(50, 50, 50, 20, 1e-10)
            realign_tsv_to_parquet(
                FIXTURES / "realignments.tsv",
                realign_parquet,
                thresholds,
                batch_size=1,
            )
            database = root / "resource.duckdb"
            result = build_duckdb_resource(
                database,
                sequence_parquet,
                seed_parquet,
                cluster_parquet,
                realign_parquet,
                thresholds,
                root / "curated",
                root / "fastas",
                root / "validation.tsv",
                metadata={"test": True},
            )
            self.assertEqual(result["row_counts"]["e3_seeded_clusters"], 1)
            self.assertEqual(result["fasta_counts"]["all_member_sequences"], 2)
            connection = duckdb.connect(str(database), read_only=True)
            summary = connection.execute(
                "SELECT raw_member_count, strict_member_count "
                "FROM e3_seeded_cluster_summary"
            ).fetchone()
            self.assertEqual(summary, (2, 2))
            counts = connection.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM all_matched_e3_seed_sequences), "
                "(SELECT COUNT(*) FROM strict_nonseed_candidate_members)"
            ).fetchone()
            self.assertEqual(counts, (1, 1))
            connection.close()
            self.assertTrue(
                (root / "summaries" / "workflow_key_metrics.tsv").is_file()
            )

    def test_build_resource_with_header_only_realignments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequence_parquet = root / "sequences.parquet"
            prepare_combined_fasta(
                [
                    SampleRecord("species_a", FIXTURES / "species_a.fasta", "A"),
                    SampleRecord("species_b", FIXTURES / "species_b.fasta", "B"),
                ],
                root / "combined.fasta",
                sequence_parquet,
                root / "sample_summary.tsv",
                batch_size=1,
            )
            seed_parquet = root / "seeds.parquet"
            prepare_seed_table(
                FIXTURES / "e3_seeds.csv",
                root / "seeds.tsv",
                seed_parquet,
            )
            cluster_parquet = root / "clusters.parquet"
            cluster_tsv_to_parquet(
                FIXTURES / "raw_clusters.tsv",
                cluster_parquet,
                batch_size=1,
            )
            header_only = root / "header_only_realignments.tsv"
            header_only.write_text(
                "qseqid\tsseqid\tpident\tqlen\tslen\tqstart\tqend\t"
                "sstart\tsend\tlength\tevalue\tbitscore\n",
                encoding="utf-8",
            )
            realign_parquet = root / "realign.parquet"
            thresholds = Thresholds(50, 50, 50, 20, 1e-10)
            summary = realign_tsv_to_parquet(
                header_only,
                realign_parquet,
                thresholds,
                batch_size=1,
            )
            self.assertEqual(summary["realignment_rows"], 0)

            result = build_duckdb_resource(
                root / "resource.duckdb",
                sequence_parquet,
                seed_parquet,
                cluster_parquet,
                realign_parquet,
                thresholds,
                root / "curated",
                root / "fastas",
                root / "validation.tsv",
                metadata={"test": "empty_realignments"},
            )
            self.assertEqual(result["row_counts"]["realigned_membership"], 0)
            self.assertEqual(result["row_counts"]["e3_seeded_clusters"], 1)
            self.assertEqual(result["fasta_counts"]["all_member_sequences"], 2)
            self.assertEqual(result["fasta_counts"]["strict_member_sequences"], 0)


if __name__ == "__main__":
    unittest.main()
