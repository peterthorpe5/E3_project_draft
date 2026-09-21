"""FASTA profiling and atomic I/O tests."""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from diamond_clust_benchmark.exceptions import DataValidationError
from diamond_clust_benchmark.fasta import (
    open_text,
    profile_fasta,
    sha256_file,
    write_fasta_profile,
)
from diamond_clust_benchmark.io_utils import ensure_parent, write_json, write_tsv
from tests.helpers import FIXTURES


class FastaAndIoTests(unittest.TestCase):
    """Exercise bounded FASTA parsing and atomic writers."""

    def setUp(self) -> None:
        """Create a disposable output directory."""

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        """Remove test files."""

        self.temporary.cleanup()

    def test_profile_plain_and_gzip_fasta(self) -> None:
        """Count the controlled fixture and transparently read gzip text."""

        profile = profile_fasta(FIXTURES / "proteins.fasta")
        self.assertEqual(profile["sequence_count"], 4)
        self.assertEqual(profile["residue_count"], 52)
        compressed = self.root / "proteins.fasta.gz"
        with gzip.open(compressed, "wt", encoding="utf-8") as handle:
            handle.write((FIXTURES / "proteins.fasta").read_text())
        with open_text(compressed) as handle:
            self.assertTrue(handle.readline().startswith(">seqA"))
        self.assertEqual(profile_fasta(compressed)["residue_count"], 52)

    def test_profile_rejects_malformed_fasta(self) -> None:
        """Reject missing files, blank IDs, text-first and empty records."""

        with self.assertRaises(FileNotFoundError):
            profile_fasta(self.root / "missing.faa")
        variants = [
            "ACDE\n",
            ">\nACDE\n",
            ">one\n>two\nACDE\n",
            ">one\nACDE\n>two\n",
            "\n",
        ]
        for index, content in enumerate(variants):
            with self.subTest(index=index):
                path = self.root / f"bad_{index}.faa"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(DataValidationError):
                    profile_fasta(path)

    def test_hash_and_profile_writers(self) -> None:
        """Write matching TSV/JSON provenance and validate hash arguments."""

        source = FIXTURES / "proteins.fasta"
        self.assertEqual(len(sha256_file(source)), 64)
        with self.assertRaises(ValueError):
            sha256_file(source, block_size=0)
        profile = profile_fasta(source)
        output = self.root / "nested" / "profile.tsv"
        write_fasta_profile(profile, output)
        self.assertTrue(output.is_file())
        payload = json.loads(output.with_suffix(".json").read_text())
        self.assertEqual(payload["sequence_count"], 4)

    def test_atomic_json_and_tsv_helpers(self) -> None:
        """Create parents and deterministic tab-delimited files."""

        destination = ensure_parent(self.root / "nested" / "value.json")
        self.assertTrue(destination.parent.is_dir())
        write_json(destination, {"b": 2, "a": 1})
        self.assertEqual(json.loads(destination.read_text()), {"a": 1, "b": 2})
        table = self.root / "table.tsv"
        write_tsv(table, [{"name": "value"}], ["name"])
        self.assertEqual(table.read_text(), "name\nvalue\n")
        with self.assertRaises(ValueError):
            write_tsv(table, [], [])
        with self.assertRaises(ValueError):
            write_tsv(table, [{"extra": 1}], ["name"])


if __name__ == "__main__":
    unittest.main()
