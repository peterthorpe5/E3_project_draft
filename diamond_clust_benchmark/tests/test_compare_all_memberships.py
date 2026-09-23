"""Tests for the standalone all-against-all membership analysis."""

from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.helpers import FIXTURES, PACKAGE_ROOT


def _load_script_module():
    """Load the standalone script as a testable Python module."""

    path = PACKAGE_ROOT / "scripts" / "compare_all_memberships.py"
    specification = importlib.util.spec_from_file_location(
        "compare_all_memberships",
        path,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Could not import {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


ANALYSIS = _load_script_module()


class AllAgainstAllTests(unittest.TestCase):
    """Exercise metrics, validation, plots and the resumable command."""

    def setUp(self) -> None:
        """Create a temporary synthetic benchmark result tree."""

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.run_root = self.root / "run"
        self.output = self.root / "all_pairs"
        self.sentinels = self.root / "sentinels.tsv"
        self.sentinels.write_text(
            "sequence_id\nseqA\nseqC\n",
            encoding="utf-8",
        )
        cases = []
        sources = {
            "method_a": FIXTURES / "baseline.tsv",
            "method_b": FIXTURES / "changed.tsv",
            "method_c": FIXTURES / "baseline.tsv",
        }
        for case_id, source in sources.items():
            cases.append(
                {
                    "case_id": case_id,
                    "expected_version": "test",
                    "command": "deepclust",
                    "identity_mode": "exact",
                    "cluster_steps": [],
                }
            )
            repeat = self.run_root / "cases" / case_id / "repeat_1"
            repeat.mkdir(parents=True)
            (repeat / "clusters.tsv").write_text(
                source.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        second_repeat = self.run_root / "cases" / "method_a" / "repeat_2"
        second_repeat.mkdir(parents=True)
        (second_repeat / "clusters.tsv").write_text(
            (FIXTURES / "baseline.tsv").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.config = self.root / "config.yaml"
        self.config.write_text(
            yaml.safe_dump(
                {
                    "inputs": {"sentinel_ids_tsv": str(self.sentinels)},
                    "benchmark": {
                        "quality_repeat": 1,
                        "cases": cases,
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        """Remove temporary test data."""

        self.temporary.cleanup()

    def _membership(self, method_id: str, filename: str) -> object:
        """Create a small MembershipInput for a fixture."""

        return ANALYSIS.MembershipInput(
            method_id=method_id,
            display_name=method_id,
            repeat=1,
            path=FIXTURES / filename,
        )

    def test_exact_and_changed_partition_metrics(self) -> None:
        """Calculate related similarity metrics without using DuckDB."""

        baseline = self._membership("baseline", "baseline.tsv")
        exact = self._membership("exact", "baseline.tsv")
        changed = self._membership("changed", "changed.tsv")
        sentinels = ANALYSIS.read_sentinels(self.sentinels)
        exact_result = ANALYSIS.compare_mappings(
            baseline,
            exact,
            ANALYSIS.load_mapping(baseline.path),
            ANALYSIS.load_mapping(exact.path),
            sentinels,
        )
        exact_metrics = exact_result["pair_metrics"]
        self.assertEqual(exact_metrics["pairwise_f1"], 1.0)
        self.assertEqual(exact_metrics["pairwise_jaccard"], 1.0)
        self.assertEqual(exact_metrics["adjusted_rand_index"], 1.0)
        self.assertEqual(
            exact_metrics["normalised_variation_of_information"],
            0.0,
        )
        changed_result = ANALYSIS.compare_mappings(
            baseline,
            changed,
            ANALYSIS.load_mapping(baseline.path),
            ANALYSIS.load_mapping(changed.path),
            sentinels,
        )
        metrics = changed_result["pair_metrics"]
        expected_jaccard = metrics["pairwise_f1"] / (
            2.0 - metrics["pairwise_f1"]
        )
        self.assertAlmostEqual(metrics["pairwise_jaccard"], expected_jaccard)
        self.assertLess(metrics["adjusted_rand_index"], 1.0)
        self.assertGreater(
            metrics["normalised_variation_of_information"],
            0.0,
        )
        self.assertLess(
            changed_result["sentinel_metrics"]["neighbour_jaccard"],
            1.0,
        )
        self.assertTrue(changed_result["size_stratified"])

    def test_configuration_discovery_and_validation(self) -> None:
        """Discover quality and repeat memberships and reject bad options."""

        payload = ANALYSIS.load_yaml(self.config)
        quality, retained, sentinel = ANALYSIS.discover_memberships(
            payload,
            self.config,
            self.run_root,
        )
        self.assertEqual(len(quality), 3)
        self.assertEqual(len(retained), 4)
        self.assertEqual(sentinel, self.sentinels.resolve())
        self.assertEqual(ANALYSIS.validate_memory_limit("200 GB"), "200GB")
        with self.assertRaises(ANALYSIS.AnalysisError):
            ANALYSIS.validate_memory_limit("200")
        with self.assertRaises(ANALYSIS.AnalysisError):
            ANALYSIS.percentile([], 0.5)

    def test_end_to_end_outputs_and_repeat_stability(self) -> None:
        """Create every core table, figure, report and completion marker."""

        return_code = ANALYSIS.main(
            [
                "--config",
                str(self.config),
                "--run-root",
                str(self.run_root),
                "--output-directory",
                str(self.output),
                "--formats",
                "png",
                "--dpi",
                "72",
                "--small-file-limit-bytes",
                "1000000",
            ]
        )
        self.assertEqual(return_code, 0)
        expected = [
            "COMPLETE",
            "tables/method_cluster_summary.tsv",
            "tables/pairwise_method_comparisons.tsv",
            "tables/directional_split_merge_summary.tsv",
            "tables/sentinel_method_comparisons.tsv",
            "tables/sentinel_per_sequence_comparisons.tsv",
            "tables/size_stratified_best_match.tsv",
            "tables/repeat_stability.tsv",
            "figures/pairwise_f1.png",
            "figures/pairwise_jaccard.png",
            "figures/adjusted_rand_index.png",
            "figures/normalised_variation_of_information.png",
            "figures/sentinel_neighbour_jaccard.png",
            "figures/method_similarity_dendrogram.png",
            "figures/cluster_size_profiles.png",
            "figures/directional_split_merge.png",
            "figures/repeat_stability.png",
            "reports/all_against_all_summary.html",
            "provenance/analysis_manifest.json",
        ]
        for relative in expected:
            with self.subTest(relative=relative):
                self.assertTrue((self.output / relative).is_file())
        with (self.output / "tables" / "pairwise_method_comparisons.tsv").open(
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            pair_rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(pair_rows), 3)
        with (self.output / "tables" / "repeat_stability.tsv").open(
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            repeat_rows = list(csv.DictReader(handle, delimiter="\t"))
        measured = [row for row in repeat_rows if row["status"] == "measured"]
        unavailable = [
            row
            for row in repeat_rows
            if row["status"].startswith("not_estimable")
        ]
        self.assertEqual(len(measured), 1)
        self.assertEqual(len(unavailable), 2)
        self.assertEqual(float(measured[0]["pairwise_f1"]), 1.0)
        payload = ANALYSIS.load_yaml(self.config)
        quality, _retained, _sentinel = ANALYSIS.discover_memberships(
            payload,
            self.config,
            self.run_root,
        )
        checkpoint = (
            self.output
            / "checkpoints"
            / ANALYSIS.checkpoint_name(quality[0], quality[1])
        )
        self.assertIsNotNone(
            ANALYSIS.load_checkpoint(
                checkpoint,
                quality[0],
                quality[1],
                {"seqA", "seqC"},
            )
        )
        self.assertIsNone(
            ANALYSIS.load_checkpoint(
                checkpoint,
                quality[0],
                quality[1],
                {"seqA"},
            )
        )
        report = (
            self.output / "reports" / "all_against_all_summary.html"
        ).read_text(encoding="utf-8")
        self.assertIn("cannot determine", report)
        self.assertIn("biologically correct", report)

    def test_identifier_mismatch_and_output_protection(self) -> None:
        """Reject differing members and accidental reuse of completed output."""

        missing = self.root / "missing.tsv"
        missing.write_text(
            "centroid\tmember\nseqA\tseqA\n",
            encoding="utf-8",
        )
        baseline = self._membership("baseline", "baseline.tsv")
        altered = ANALYSIS.MembershipInput(
            method_id="missing",
            display_name="missing",
            repeat=1,
            path=missing,
        )
        with self.assertRaises(ANALYSIS.AnalysisError):
            ANALYSIS.compare_mappings(
                baseline,
                altered,
                ANALYSIS.load_mapping(baseline.path),
                ANALYSIS.load_mapping(altered.path),
                set(),
            )
        self.output.mkdir()
        (self.output / "COMPLETE").write_text("done\n", encoding="utf-8")
        with self.assertRaises(ANALYSIS.AnalysisError):
            ANALYSIS._validate_existing_output(self.output, resume=True)


if __name__ == "__main__":
    unittest.main()
