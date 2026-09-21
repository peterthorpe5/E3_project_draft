"""Cluster-membership summary and concordance tests."""

from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diamond_clust_benchmark.exceptions import DataValidationError
from diamond_clust_benchmark.membership import (
    _combination_two,
    _read_sentinel_ids,
    _sql_path,
    compare_memberships,
    compare_memberships_small,
    iter_membership,
    membership_sha256,
    summarise_membership,
)
from tests.helpers import FIXTURES


class MembershipTests(unittest.TestCase):
    """Check structural validation and representative-independent metrics."""

    def setUp(self) -> None:
        """Create a temporary membership workspace."""

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.baseline = FIXTURES / "baseline.tsv"

    def tearDown(self) -> None:
        """Remove test files."""

        self.temporary.cleanup()

    def test_iteration_hash_and_summary(self) -> None:
        """Read header variants and calculate validated counts with DuckDB."""

        rows = list(iter_membership(self.baseline))
        self.assertEqual(rows[1], ("seqA", "seqB"))
        self.assertEqual(len(membership_sha256(self.baseline)), 64)
        summary = summarise_membership(self.baseline)
        self.assertEqual(summary["membership_rows"], 4)
        self.assertEqual(summary["cluster_count"], 2)
        self.assertEqual(summary["largest_cluster_size"], 2)
        self.assertEqual(summary["representative_self_rows"], 2)

    def test_gzip_and_small_summary_fallback(self) -> None:
        """Read compressed memberships and cover the bounded Python fallback."""

        compressed = self.root / "membership.tsv.gz"
        with gzip.open(compressed, "wt", encoding="utf-8") as handle:
            handle.write(self.baseline.read_text())
        self.assertEqual(len(list(iter_membership(compressed))), 4)
        with mock.patch.dict("sys.modules", {"duckdb": None}):
            summary = summarise_membership(self.baseline)
        self.assertEqual(summary["unique_members"], 4)
        with self.assertRaises(ValueError):
            summarise_membership(self.baseline, small_file_limit_bytes=0)

    def test_invalid_membership_tables(self) -> None:
        """Reject empty, unrecognised, malformed and duplicate membership rows."""

        variants = {
            "empty": "",
            "header": "wrong\tmember\na\ta\n",
            "row": "centroid\tmember\na\n",
            "duplicate": "centroid\tmember\na\ta\nb\ta\n",
            "no_data": "centroid\tmember\n",
        }
        for name, content in variants.items():
            with self.subTest(name=name):
                path = self.root / f"{name}.tsv"
                path.write_text(content, encoding="utf-8")
                if name in {"duplicate", "no_data"}:
                    with self.assertRaises(DataValidationError):
                        summarise_membership(path)
                else:
                    with self.assertRaises(DataValidationError):
                        list(iter_membership(path))
        with self.assertRaises(FileNotFoundError):
            list(iter_membership(self.root / "missing.tsv"))

    def test_small_and_duckdb_concordance(self) -> None:
        """Measure exact and altered partitions with sentinel neighbourhoods."""

        sentinels = FIXTURES / "sentinels.tsv"
        exact = compare_memberships_small(
            self.baseline,
            self.baseline,
            sentinels,
        )
        self.assertEqual(exact["pairwise_f1"], 1.0)
        self.assertEqual(exact["sentinel_recall"], 1.0)
        changed = compare_memberships(
            self.baseline,
            FIXTURES / "changed.tsv",
            sentinels,
        )
        self.assertLess(changed["pairwise_f1"], 1.0)
        self.assertEqual(changed["member_count"], 4)
        no_sentinels = compare_memberships_small(self.baseline, self.baseline)
        self.assertEqual(no_sentinels["sentinel_count"], 0)

    def test_concordance_rejects_identifier_and_sentinel_errors(self) -> None:
        """Reject missing members, duplicates, bad sentinels and no matches."""

        missing = self.root / "missing.tsv"
        missing.write_text(
            "centroid\tmember\nseqA\tseqA\nseqA\tseqB\n",
            encoding="utf-8",
        )
        duplicate = self.root / "duplicate.tsv"
        duplicate.write_text(
            "centroid\tmember\nseqA\tseqA\nseqC\tseqA\n",
            encoding="utf-8",
        )
        for function in (compare_memberships_small, compare_memberships):
            with self.subTest(function=function.__name__):
                with self.assertRaises(DataValidationError):
                    function(self.baseline, missing)
                with self.assertRaises(DataValidationError):
                    function(duplicate, duplicate)
        bad_header = self.root / "sentinel_bad.tsv"
        bad_header.write_text("id\nseqA\n", encoding="utf-8")
        with self.assertRaises(DataValidationError):
            _read_sentinel_ids(bad_header)
        empty = self.root / "sentinel_empty.tsv"
        empty.write_text("sequence_id\n", encoding="utf-8")
        with self.assertRaises(DataValidationError):
            _read_sentinel_ids(empty)
        absent = self.root / "sentinel_absent.tsv"
        absent.write_text("sequence_id\nunknown\n", encoding="utf-8")
        with self.assertRaises(DataValidationError):
            compare_memberships_small(self.baseline, self.baseline, absent)

    def test_small_helpers(self) -> None:
        """Cover combination arithmetic and safe SQL path escaping."""

        self.assertEqual(_combination_two(5), 10)
        escaped = _sql_path(self.root / "it's.tsv")
        self.assertIn("it''s.tsv", escaped)
        self.assertEqual(_read_sentinel_ids(None), set())
        with self.assertRaises(ValueError):
            compare_memberships(
                self.baseline,
                self.baseline,
                small_file_limit_bytes=0,
            )


if __name__ == "__main__":
    unittest.main()
