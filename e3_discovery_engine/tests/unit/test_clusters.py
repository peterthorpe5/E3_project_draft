import tempfile
import unittest
from pathlib import Path

import pyarrow.parquet as pq

from e3_discovery.clusters import (
    Thresholds,
    classify_alignment,
    cluster_tsv_to_parquet,
    compute_coverage,
    realign_tsv_to_parquet,
    thresholds_from_mapping,
)
from e3_discovery.exceptions import DataValidationError


class ClusterTests(unittest.TestCase):
    def thresholds(self):
        return Thresholds(50, 50, 50, 20, 1e-10)

    def test_thresholds_validate(self):
        self.thresholds().validate()
        with self.assertRaises(ValueError):
            Thresholds(0, 50, 50, 20, 1e-10).validate()

    def test_compute_coverage(self):
        self.assertEqual(compute_coverage(50, 100), 50.0)
        self.assertEqual(compute_coverage(110, 100), 100.0)
        with self.assertRaises(ValueError):
            compute_coverage(1, 0)

    def test_classify_alignment_pass_and_fail(self):
        base = {
            "pident": 60,
            "representative_length": 100,
            "member_length": 100,
            "alignment_length": 60,
            "bitscore": 21,
            "evalue": 1e-20,
        }
        self.assertTrue(classify_alignment(base, self.thresholds())["passes_all"])
        base["bitscore"] = 20
        self.assertFalse(classify_alignment(base, self.thresholds())["passes_all"])

    def test_cluster_tsv_to_parquet(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "clusters.tsv"
            source.write_text(
                "representative\tmember\nr1\tr1\nr1\tm1\n",
                encoding="utf-8",
            )
            output = Path(tmp) / "clusters.parquet"
            summary = cluster_tsv_to_parquet(source, output, batch_size=1)
            self.assertEqual(summary, {"membership_rows": 2, "cluster_count": 1})
            self.assertEqual(pq.read_table(output).num_rows, 2)

    def test_cluster_tsv_rejects_bad_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bad.tsv"
            source.write_text("x\ty\n1\t2\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                cluster_tsv_to_parquet(source, Path(tmp) / "out.parquet")

    def test_realign_tsv_to_parquet(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "realign.tsv"
            source.write_text(
                "qseqid\tsseqid\tpident\tqlen\tslen\tqstart\tqend\t"
                "sstart\tsend\tlength\tevalue\tbitscore\n"
                "r1\tm1\t60\t100\t100\t1\t60\t1\t60\t60\t1e-20\t30\n",
                encoding="utf-8",
            )
            output = Path(tmp) / "realign.parquet"
            summary = realign_tsv_to_parquet(
                source,
                output,
                self.thresholds(),
                batch_size=1,
            )
            table = pq.read_table(output)
            self.assertEqual(summary["strict_pass_rows"], 1)
            self.assertTrue(table.column("passes_all")[0].as_py())

    def test_realign_tsv_rejects_missing_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bad.tsv"
            source.write_text("qseqid\tsseqid\np\tm\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                realign_tsv_to_parquet(
                    source,
                    Path(tmp) / "out.parquet",
                    self.thresholds(),
                )

    def test_thresholds_from_mapping(self):
        values = {
            "minimum_percent_identity": 50,
            "minimum_representative_coverage": 50,
            "minimum_member_coverage": 50,
            "minimum_bitscore": 20,
            "maximum_evalue": 1e-10,
        }
        self.assertEqual(thresholds_from_mapping(values).minimum_bitscore, 20)


if __name__ == "__main__":
    unittest.main()
