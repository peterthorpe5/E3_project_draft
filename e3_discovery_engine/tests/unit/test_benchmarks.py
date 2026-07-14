import tempfile
import unittest
from pathlib import Path

from e3_discovery.benchmarks import (
    _is_hidden_benchmark_artifact,
    aggregate_benchmark_directory,
    parse_snakemake_benchmark,
    plot_runtime_by_rule,
    summarise_benchmarks,
    write_benchmark_outputs,
)
from e3_discovery.exceptions import DataValidationError


class BenchmarkTests(unittest.TestCase):
    def benchmark_file(self, root):
        path = Path(root) / "rule.tsv"
        path.write_text(
            "s\th:m:s\tmax_rss\tcpu_time\n"
            "10\t00:00:10\t100\t20\n"
            "14\t00:00:14\t120\t25\n",
            encoding="utf-8",
        )
        return path

    def test_parse_snakemake_benchmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = parse_snakemake_benchmark(self.benchmark_file(tmp))
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["s"], 10.0)

    def test_parse_rejects_missing_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.tsv"
            path.write_text("x\n1\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                parse_snakemake_benchmark(path)

    def test_aggregate_benchmark_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.benchmark_file(tmp)
            records = aggregate_benchmark_directory(Path(tmp), {"dataset": "test"})
            self.assertEqual(records[0]["dataset"], "test")

    def test_hidden_appledouble_benchmark_sidecar_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.benchmark_file(root)
            sidecar = root / "._rule.tsv"
            sidecar.write_bytes(b"AppleDouble metadata\xb0not UTF-8")

            records = aggregate_benchmark_directory(root)

            self.assertEqual(len(records), 2)
            self.assertTrue(
                all(
                    Path(record["benchmark_file"]).name == "rule.tsv"
                    for record in records
                )
            )

    def test_hidden_benchmark_artifact_detection(self):
        root = Path("benchmarks")
        self.assertTrue(
            _is_hidden_benchmark_artifact(root / "._rule.tsv", root)
        )
        self.assertTrue(
            _is_hidden_benchmark_artifact(
                root / ".temporary" / "rule.tsv",
                root,
            )
        )
        self.assertFalse(
            _is_hidden_benchmark_artifact(root / "rule.tsv", root)
        )

    def test_parse_rejects_binary_benchmark_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "binary.tsv"
            path.write_bytes(b"benchmark metadata\xb0not UTF-8")

            with self.assertRaisesRegex(
                DataValidationError,
                "not UTF-8 text",
            ):
                parse_snakemake_benchmark(path)

    def test_summarise_benchmarks(self):
        records = [
            {"rule_name": "x", "s": 10.0, "max_rss": 100.0},
            {"rule_name": "x", "s": 14.0, "max_rss": 120.0},
        ]
        summary = summarise_benchmarks(records)[0]
        self.assertEqual(summary["mean_seconds"], 12.0)
        self.assertEqual(summary["standard_deviation_seconds"], 2.0)

    def test_write_outputs_and_plot(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [{"rule_name": "x", "s": 10.0, "max_rss": 100.0}]
            summary = summarise_benchmarks(records)
            write_benchmark_outputs(
                records,
                summary,
                Path(tmp) / "records.tsv",
                Path(tmp) / "records.parquet",
                Path(tmp) / "summary.tsv",
            )
            plot_runtime_by_rule(
                summary,
                Path(tmp) / "plot.png",
                Path(tmp) / "plot.pdf",
            )
            self.assertTrue((Path(tmp) / "records.parquet").is_file())
            self.assertTrue((Path(tmp) / "plot.png").is_file())

    def test_plot_rejects_empty(self):
        with self.assertRaises(ValueError):
            plot_runtime_by_rule([], Path("x.png"))


if __name__ == "__main__":
    unittest.main()
