"""Benchmark aggregation, decisions and report tests."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from diamond_clust_benchmark.config import load_config
from diamond_clust_benchmark.report import (
    _format_seconds,
    _speedup_svg,
    build_decisions,
    calculate_quality,
    collect_metrics,
    generate_report,
    paired_speedup_interval,
    percentile,
    render_html,
    summarise_metrics,
)
from tests.helpers import FIXTURES, case_mapping, metric, write_config, write_metrics


class ReportTests(unittest.TestCase):
    """Verify paired statistics, guardrails and final artifacts."""

    def setUp(self) -> None:
        """Create a two-case deterministic run layout."""

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        candidate = case_mapping("candidate")
        candidate["command"] = "linclust"
        self.config = load_config(
            write_config(self.root, [case_mapping(), candidate], repeats=2)
        )
        self.run_root = self.config.output_root
        for case_id, seconds in (("baseline", (10.0, 12.0)), ("candidate", (8.0, 9.0))):
            for repeat, wall in enumerate(seconds, start=1):
                repeat_root = (
                    self.run_root
                    / "cases"
                    / case_id
                    / f"repeat_{repeat}"
                )
                write_metrics(
                    repeat_root / "metrics.tsv",
                    [metric(case_id, repeat, "pairwise_pipeline", wall)],
                )
                (repeat_root / "COMPLETE").write_text("done\n", encoding="utf-8")
                if repeat == 1:
                    shutil.copy2(
                        FIXTURES / "baseline.tsv",
                        repeat_root / "clusters.tsv",
                    )

    def tearDown(self) -> None:
        """Remove report outputs."""

        self.temporary.cleanup()

    def test_metric_collection_summary_and_quality(self) -> None:
        """Read all repeats and summarise resource and concordance evidence."""

        records = collect_metrics(self.config, self.run_root)
        self.assertEqual(len(records), 4)
        summary = summarise_metrics(records)
        self.assertEqual(len(summary), 2)
        baseline = next(row for row in summary if row["case_id"] == "baseline")
        self.assertEqual(baseline["mean_wall_seconds"], 11.0)
        quality = calculate_quality(self.config, self.run_root)
        self.assertEqual(len(quality), 2)
        self.assertTrue(all(row["pairwise_f1"] == 1.0 for row in quality))
        missing = self.run_root / "cases" / "candidate" / "repeat_2" / "COMPLETE"
        missing.unlink()
        with self.assertRaises(FileNotFoundError):
            collect_metrics(self.config, self.run_root)

    def test_percentiles_and_paired_speedup(self) -> None:
        """Calculate deterministic paired speed-up and validate inputs."""

        self.assertEqual(percentile([0, 10], 0.5), 5.0)
        mean, low, high = paired_speedup_interval(
            {1: 10.0, 2: 20.0},
            {1: 8.0, 2: 16.0},
            100,
        )
        self.assertAlmostEqual(mean, 20.0)
        self.assertAlmostEqual(low, 20.0)
        self.assertAlmostEqual(high, 20.0)
        for values, probability in (([], 0.5), ([1], -0.1), ([1], 1.1)):
            with self.subTest(values=values, probability=probability):
                with self.assertRaises(ValueError):
                    percentile(values, probability)
        with self.assertRaises(ValueError):
            paired_speedup_interval({1: 1}, {2: 1}, 10)
        with self.assertRaises(ValueError):
            paired_speedup_interval({1: 1}, {1: 1}, 0)
        with self.assertRaises(ValueError):
            paired_speedup_interval({1: 0}, {1: 1}, 10)

    def test_decisions_html_and_complete_report(self) -> None:
        """Pass the faster concordant case and publish every report output."""

        records = collect_metrics(self.config, self.run_root)
        quality = calculate_quality(self.config, self.run_root)
        decisions = build_decisions(self.config, records, quality)
        candidate = next(row for row in decisions if row["case_id"] == "candidate")
        self.assertTrue(candidate["overall_pass"])
        self.assertGreater(candidate["mean_speedup_percent"], 10)
        html = render_html(self.config, decisions)
        self.assertIn("Fastest passing strategy: candidate", html)
        self.assertIn("<svg", _speedup_svg(decisions))
        self.assertEqual(_format_seconds(30), "30.00 s")
        self.assertEqual(_format_seconds(120), "2.00 min")
        self.assertEqual(_format_seconds(7200), "2.00 h")
        manifest = generate_report(self.config, self.run_root)
        self.assertEqual(manifest["fastest_passing_case"], "candidate")
        self.assertTrue(Path(manifest["html_report"]).is_file())
        saved = json.loads(
            (self.run_root / "reports" / "report_manifest.json").read_text()
        )
        self.assertEqual(saved["status"], "COMPLETE")

    def test_failed_quality_has_no_winner(self) -> None:
        """Prevent a fast method from passing with poor concordance."""

        records = collect_metrics(self.config, self.run_root)
        quality = calculate_quality(self.config, self.run_root)
        quality[1]["pairwise_f1"] = 0.5
        decisions = build_decisions(self.config, records, quality)
        self.assertFalse(decisions[1]["overall_pass"])
        self.assertIn("No candidate", render_html(self.config, decisions))
        baseline_only = [decisions[0]]
        self.assertEqual(_speedup_svg(baseline_only), "")

    def test_missing_quality_membership_is_rejected(self) -> None:
        """Require the configured retained membership for every case."""

        path = self.run_root / "cases" / "candidate" / "repeat_1" / "clusters.tsv"
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            calculate_quality(self.config, self.run_root)


if __name__ == "__main__":
    unittest.main()
