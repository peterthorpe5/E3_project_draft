import tempfile
import unittest
from pathlib import Path

from e3_discovery.exceptions import DataValidationError
from e3_discovery.manifest import (
    SampleRecord,
    read_sample_manifest,
    validate_sample_records,
    write_sample_manifest,
)


class ManifestTests(unittest.TestCase):
    def make_fasta(self, root, name="a.fasta"):
        path = Path(root) / name
        path.write_text(">a\nMKT\n", encoding="utf-8")
        return path

    def test_read_sample_manifest_retains_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            fasta = self.make_fasta(tmp)
            manifest = Path(tmp) / "samples.tsv"
            manifest.write_text(
                "sample_id\tfasta_path\tspecies\textra\n"
                f"s1\t{fasta.name}\tSpecies one\tvalue\n",
                encoding="utf-8",
            )
            record = read_sample_manifest(manifest)[0]
            self.assertEqual(record.species, "Species one")
            self.assertEqual(record.metadata["extra"], "value")

    def test_read_sample_manifest_requires_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "samples.tsv"
            manifest.write_text("sample_id\nfoo\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                read_sample_manifest(manifest)

    def test_validate_sample_records_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.make_fasta(tmp, "a.fasta")
            b = self.make_fasta(tmp, "b.fasta")
            records = [SampleRecord("same", a), SampleRecord("same", b)]
            with self.assertRaises(DataValidationError):
                validate_sample_records(records)

    def test_validate_sample_records_rejects_bad_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            fasta = self.make_fasta(tmp)
            with self.assertRaises(DataValidationError):
                validate_sample_records([SampleRecord("bad id", fasta)])

    def test_validate_sample_records_rejects_missing_fasta(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                validate_sample_records([SampleRecord("s1", Path(tmp) / "none")])

    def test_write_sample_manifest_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            fasta = self.make_fasta(tmp)
            output = Path(tmp) / "samples.tsv"
            count = write_sample_manifest(
                [SampleRecord("s1", fasta, species="Species")], output
            )
            self.assertEqual(count, 1)
            self.assertEqual(read_sample_manifest(output)[0].sample_id, "s1")


if __name__ == "__main__":
    unittest.main()
