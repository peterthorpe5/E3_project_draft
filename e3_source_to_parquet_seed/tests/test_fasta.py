"""Unit tests for FASTA parsing."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from e3parquet.fasta import infer_accession_from_header, parse_fasta_file


class TestFastaParsing(unittest.TestCase):
    """Tests for FASTA parser behaviour."""

    def test_infer_accession_from_uniprot_header(self) -> None:
        """UniProt-style headers should expose the accession token."""
        accession = infer_accession_from_header("sp|Q39090|ABC_ARATH Example")
        self.assertEqual(accession, "Q39090")

    def test_parse_fasta_preserves_header_and_metadata(self) -> None:
        """FASTA parsing should preserve sequence, header and source metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fasta = root / "seqs.fasta"
            fasta.write_text(
                ">sp|Q39090|ABC_ARATH Example protein\nMAGA\nTT\n"
                ">A0A000 another protein\nCC\n",
                encoding="utf-8",
            )
            manifest = {
                "sha256": "dummy-sha",
                "size_bytes": "42",
                "mtime_utc": "2026-01-01T00:00:00+00:00",
            }

            records = parse_fasta_file(fasta, root, manifest)

            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["inferred_accession"], "Q39090")
            self.assertEqual(records[0]["sequence"], "MAGATT")
            self.assertEqual(records[0]["sequence_length"], 6)
            expected_md5 = hashlib.md5(b"MAGATT").hexdigest()
            self.assertEqual(records[0]["sequence_md5"], expected_md5)
            self.assertEqual(records[0]["_source_file"], "seqs.fasta")
            self.assertEqual(records[0]["_source_file_sha256"], "dummy-sha")


if __name__ == "__main__":
    unittest.main()
