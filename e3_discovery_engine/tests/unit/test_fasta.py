import csv
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

    def test_iter_fasta_reports_empty_record_context(self):
        """Strict parsing reports the exact empty record and header line."""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty_record.fasta"
            path.write_text(
                ">good\nMKT\n>empty_record\n>next\nAAA\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                DataValidationError,
                r"record 2; header='empty_record'",
            ):
                list(iter_fasta(path))

    def test_iter_fasta_skips_audited_empty_records(self):
        """Explicit skip mode excludes empty records and preserves indices."""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audited.fasta"
            path.write_text(
                ">first\nMKT\n>empty_record\n>third\nAAA\n",
                encoding="utf-8",
            )
            skipped = []
            records = list(
                iter_fasta(
                    path,
                    empty_sequence_policy="skip",
                    skipped_records=skipped,
                    maximum_skipped_empty_sequences=1,
                )
            )
            self.assertEqual(
                [record.identifier for record in records],
                ["first", "third"],
            )
            self.assertEqual(
                [record.source_record_index for record in records],
                [1, 3],
            )
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0].header_line, 3)
            self.assertEqual(skipped[0].issue_type, "empty_sequence")

    def test_iter_fasta_enforces_empty_record_safeguard(self):
        """Skip mode stops when empty records exceed the configured maximum."""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "too_many_empty.fasta"
            path.write_text(
                ">empty_one\n>empty_two\n>valid\nAAA\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                DataValidationError,
                "safeguard exceeded",
            ):
                list(
                    iter_fasta(
                        path,
                        empty_sequence_policy="skip",
                        maximum_skipped_empty_sequences=1,
                    )
                )

    def test_prepare_combined_fasta_records_skipped_onekp_rows(self):
        """Preparation records permitted 1KP exclusions in both QC tables."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fasta = root / "onekp.fasta"
            fasta.write_text(
                ">scaffold-AALA-1-Species_one\nMKT\n"
                ">scaffold-AALA-2-Species_one\n"
                ">scaffold-BBBB-3-Species_two\nAAA\n",
                encoding="utf-8",
            )
            sample = SampleRecord(
                "onekp_dataset",
                fasta,
                species="1KP combined dataset",
                metadata={
                    "header_parser": "onekp_scaffold",
                    "header_parser_strict": "true",
                    "empty_sequence_policy": "skip",
                    "maximum_skipped_empty_sequences": "10",
                },
            )
            skipped_tsv = root / "skipped.tsv"
            summary_tsv = root / "summary.tsv"
            result = prepare_combined_fasta(
                [sample],
                root / "combined.fasta",
                root / "sequences.parquet",
                summary_tsv,
                skipped_records_tsv=skipped_tsv,
                batch_size=1,
                compute_checksums=False,
            )
            with summary_tsv.open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                summary = next(csv.DictReader(handle, delimiter="\t"))
            with skipped_tsv.open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                skipped = list(csv.DictReader(handle, delimiter="\t"))
            table = pq.read_table(root / "sequences.parquet")
            self.assertEqual(result["sequence_count"], 2)
            self.assertEqual(result["skipped_record_count"], 1)
            self.assertEqual(summary["source_record_count"], "3")
            self.assertEqual(summary["skipped_record_count"], "1")
            self.assertEqual(skipped[0]["source_record_index"], "2")
            self.assertEqual(
                table.column("record_index").to_pylist(),
                [1, 3],
            )

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
