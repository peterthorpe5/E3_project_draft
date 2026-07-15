import gzip
import tempfile
import unittest
from pathlib import Path

import pyarrow.parquet as pq

from e3_discovery.exceptions import DataValidationError
from e3_discovery.fasta import (
    extract_entry,
    iter_fasta,
    make_internal_id,
    normalise_sequence_id,
    prepare_combined_fasta,
    sequence_schema,
    validate_protein_sequence,
    write_fasta_records,
)
from e3_discovery.manifest import SampleRecord


class FastaTests(unittest.TestCase):
    def test_normalise_sequence_id(self):
        self.assertEqual(normalise_sequence_id("abc def"), "abc")
        with self.assertRaises(DataValidationError):
            normalise_sequence_id("")

    def test_extract_entry_uniprot_and_plain(self):
        self.assertEqual(extract_entry("sp|P12345|NAME"), "P12345")
        self.assertEqual(extract_entry("plain"), "plain")

    def test_validate_protein_sequence(self):
        self.assertEqual(validate_protein_sequence("mk t\n"), "MKT")
        with self.assertRaises(DataValidationError):
            validate_protein_sequence("MK1")

    def test_iter_fasta_plain_and_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "a.fasta"
            zipped = Path(tmp) / "a.fasta.gz"
            content = ">a description\nMKT\n>b\nAAA\n"
            plain.write_text(content, encoding="utf-8")
            with gzip.open(zipped, "wt", encoding="utf-8") as handle:
                handle.write(content)
            self.assertEqual([r.identifier for r in iter_fasta(plain)], ["a", "b"])
            self.assertEqual([r.identifier for r in iter_fasta(zipped)], ["a", "b"])

    def test_iter_fasta_rejects_sequence_before_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.fasta"
            path.write_text("MKT\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                list(iter_fasta(path))

    def test_make_internal_id_modes(self):
        self.assertEqual(make_internal_id("s1", "abc", "preserve"), "abc")
        self.assertEqual(make_internal_id("s1", "abc", "prefix_sample"), "s1@@abc")
        with self.assertRaises(ValueError):
            make_internal_id("s1", "abc", "bad")

    def test_sequence_schema_has_expected_fields(self):
        self.assertIn("sample_metadata_json", sequence_schema().names)
        self.assertIn("source_file_sample_id", sequence_schema().names)
        self.assertIn("onekp_sample_code", sequence_schema().names)
        self.assertIn("header_parse_status", sequence_schema().names)

    def test_prepare_combined_fasta_streams_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            fasta = Path(tmp) / "a.fasta"
            fasta.write_text(">sp|P1|ONE desc\nMKTAA\n", encoding="utf-8")
            result = prepare_combined_fasta(
                [SampleRecord("s1", fasta, species="Species")],
                Path(tmp) / "combined.fasta",
                Path(tmp) / "sequences.parquet",
                Path(tmp) / "summary.tsv",
                batch_size=1,
            )
            table = pq.read_table(Path(tmp) / "sequences.parquet")
            self.assertEqual(result["sequence_count"], 1)
            self.assertEqual(table.column("entry")[0].as_py(), "P1")
            self.assertIn("s1@@sp|P1|ONE", (Path(tmp) / "combined.fasta").read_text())

    def test_prepare_combined_fasta_parses_onekp_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            fasta = Path(tmp) / "onekp.fasta"
            fasta.write_text(
                ">scaffold-AALA-2000001-Meliosma_cuneifolia\nMKTAA\n"
                ">scaffold-BBBB-2000002-Other_species\nMKTAA\n",
                encoding="utf-8",
            )
            sample = SampleRecord(
                "onekp_dataset",
                fasta,
                species="1KP combined dataset",
                metadata={
                    "header_parser": "onekp_scaffold",
                    "header_parser_strict": "true",
                },
            )
            result = prepare_combined_fasta(
                [sample],
                Path(tmp) / "combined.fasta",
                Path(tmp) / "sequences.parquet",
                Path(tmp) / "summary.tsv",
                batch_size=1,
            )
            table = pq.read_table(Path(tmp) / "sequences.parquet")
            self.assertEqual(result["source_file_count"], 1)
            self.assertEqual(result["biological_sample_count"], 2)
            self.assertEqual(table.column("sample_id")[0].as_py(), "AALA")
            self.assertEqual(
                table.column("species")[0].as_py(),
                "Meliosma cuneifolia",
            )
            self.assertEqual(
                table.column("source_file_sample_id")[0].as_py(),
                "onekp_dataset",
            )
            self.assertEqual(
                table.column("header_parse_status")[0].as_py(),
                "parsed",
            )

    def test_prepare_combined_fasta_rejects_duplicates_in_preserve_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name in ("a", "b"):
                path = Path(tmp) / f"{name}.fasta"
                path.write_text(">same\nMKT\n", encoding="utf-8")
                paths.append(path)
            with self.assertRaises(DataValidationError):
                prepare_combined_fasta(
                    [SampleRecord("a", paths[0]), SampleRecord("b", paths[1])],
                    Path(tmp) / "combined.fasta",
                    Path(tmp) / "sequences.parquet",
                    Path(tmp) / "summary.tsv",
                    identifier_mode="preserve",
                )

    def test_write_fasta_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.fasta"
            self.assertEqual(write_fasta_records([("a", "MKT")], output), 1)
            self.assertEqual(output.read_text(), ">a\nMKT\n")


if __name__ == "__main__":
    unittest.main()
