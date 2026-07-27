"""Tests for Expression Atlas sample metadata importer."""

from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "inst"
    / "python"
    / "import_sample_metadata_to_parquet.py"
)

spec = importlib.util.spec_from_file_location("import_sample_metadata_to_parquet", SCRIPT)
metadata_importer = importlib.util.module_from_spec(spec)
sys.modules["import_sample_metadata_to_parquet"] = metadata_importer
assert spec.loader is not None
spec.loader.exec_module(metadata_importer)


class ImportSampleMetadataToParquetTests(unittest.TestCase):
    """Test SDRF/condensed-SDRF metadata handling."""

    def test_group_label_detection_from_group_column(self) -> None:
        """Atlas-style group labels should be detected from group columns."""

        row = {
            "Assay Group": "g1",
            "Characteristics[organism part]": "leaf",
        }
        self.assertEqual(metadata_importer.choose_sample_or_condition(row), "g1")

    def test_preferred_organism_part_is_extracted(self) -> None:
        """Common SDRF fields should flatten into preferred metadata columns."""

        row = {
            "Characteristics[organism part]": "root",
            "Factor Value[treatment]": "drought",
        }
        self.assertEqual(metadata_importer.get_preferred_value(row, "organism_part"), "root")
        self.assertEqual(metadata_importer.get_preferred_value(row, "treatment"), "drought")

    def test_jobs_are_built_from_download_manifest(self) -> None:
        """Only successful sample_metadata rows become metadata import jobs."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            manifest = tmp / "atlas_downloaded_files.tsv"
            fieldnames = [
                "species_column",
                "atlas_species_query",
                "experiment_accession",
                "file_type",
                "file_name",
                "url",
                "local_path",
                "action",
                "success",
                "local_bytes",
                "checked_at",
            ]
            with manifest.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
                writer.writeheader()
                writer.writerow(
                    {
                        "species_column": "Zea_mays",
                        "experiment_accession": "E-TEST-1",
                        "file_type": "sample_metadata",
                        "local_path": str(tmp / "metadata.tsv"),
                        "success": "true",
                    }
                )
                writer.writerow(
                    {
                        "species_column": "Zea_mays",
                        "experiment_accession": "E-TEST-1",
                        "file_type": "tpms",
                        "local_path": str(tmp / "tpms.tsv"),
                        "success": "true",
                    }
                )

            jobs = metadata_importer.build_jobs(downloaded_files_tsv=manifest)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].experiment_accession, "E-TEST-1")
        self.assertEqual(jobs[0].expression_tsv.name, "tpms.tsv")



    def test_condensed_sdrf_is_preferred_over_full_sdrf(self) -> None:
        """Only one preferred metadata file should be used per experiment."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            manifest = tmp / "atlas_downloaded_files.tsv"
            full_sdrf = tmp / "E-TEST-1.sdrf.txt"
            condensed = tmp / "E-TEST-1.condensed-sdrf.tsv"
            full_sdrf.write_text("Assay Name\nGSM1\n", encoding="utf-8")
            condensed.write_text("Assay Group\ng1\n", encoding="utf-8")
            fieldnames = [
                "species_column",
                "experiment_accession",
                "file_type",
                "local_path",
                "success",
            ]
            with manifest.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
                writer.writeheader()
                writer.writerow(
                    {
                        "species_column": "Zea_mays",
                        "experiment_accession": "E-TEST-1",
                        "file_type": "sample_metadata",
                        "local_path": str(full_sdrf),
                        "success": "true",
                    }
                )
                writer.writerow(
                    {
                        "species_column": "Zea_mays",
                        "experiment_accession": "E-TEST-1",
                        "file_type": "sample_metadata",
                        "local_path": str(condensed),
                        "success": "true",
                    }
                )

            jobs = metadata_importer.build_jobs(downloaded_files_tsv=manifest)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].metadata_tsv.name, "E-TEST-1.condensed-sdrf.tsv")
        self.assertEqual(jobs[0].metadata_file_kind, "condensed_sdrf")

    def test_wide_records_are_collapsed_by_group_label(self) -> None:
        """Duplicate group metadata should collapse to one join-safe row."""

        first = {
            "source_database": "ExpressionAtlas",
            "experiment_accession": "E-TEST-1",
            "species_column": "Zea_mays",
            "sample_or_condition": "g1",
            "organism_part": "leaf",
            "treatment": "control",
        }
        second = {
            "source_database": "ExpressionAtlas",
            "experiment_accession": "E-TEST-1",
            "species_column": "Zea_mays",
            "sample_or_condition": "g1",
            "organism_part": "root",
            "treatment": "control",
        }

        merged = metadata_importer.merge_wide_record(first, second)

        self.assertEqual(merged["sample_or_condition"], "g1")
        self.assertEqual(merged["organism_part"], "leaf; root")
        self.assertEqual(merged["treatment"], "control")

    def test_make_closed_temp_path_is_writable_after_creation(self) -> None:
        """Temporary Parquet paths should not keep leaked descriptors open."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            created_paths = [
                metadata_importer.make_closed_temp_path(tmp, ".parquet.partial")
                for _ in range(25)
            ]

            for created_path in created_paths:
                created_path.write_text("ok", encoding="utf-8")
                self.assertTrue(created_path.exists())

    @unittest.skipIf(metadata_importer.pa is None, "pyarrow is not installed")
    def test_metadata_import_writes_rows(self) -> None:
        """A small metadata TSV should produce wide and long Parquet rows."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            metadata = tmp / "metadata.tsv"
            metadata.write_text(
                "Assay Group\tCharacteristics[organism]\tCharacteristics[organism part]\tFactor Value[treatment]\n"
                "g1\tArabidopsis thaliana\tleaf\tcontrol\n"
                "g2\tArabidopsis thaliana\troot\tdrought\n",
                encoding="utf-8",
            )
            job = metadata_importer.MetadataJob(
                metadata_tsv=metadata,
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
            )

            result = metadata_importer.write_partitioned_metadata(
                job=job,
                output_dir=tmp,
                force=True,
            )

            self.assertTrue(result.success)
            self.assertEqual(result.metadata_records, 2)
            self.assertEqual(result.wide_rows, 2)
            self.assertGreater(result.long_rows, 0)
            self.assertEqual(result.mapped_group_records, 2)

    @unittest.skipIf(metadata_importer.pa is None, "pyarrow is not installed")
    def test_vertical_condensed_sdrf_infers_expression_groups(self) -> None:
        """Vertical condensed SDRF metadata should infer g-label groups."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            metadata = tmp / "E-TEST-1.condensed-sdrf.tsv"
            expression = tmp / "E-TEST-1-tpms.tsv"
            metadata.write_text(
                "E-TEST-1\t\tSRR1\tcharacteristic\tage\t9 day\n"
                "E-TEST-1\t\tSRR1\tcharacteristic\tcultivar\tB73\n"
                "E-TEST-1\t\tSRR1\tcharacteristic\torganism part\tleaf\n"
                "E-TEST-1\t\tSRR1\tfactor\tsampling site\tleaf section 1\n"
                "E-TEST-1\t\tSRR2\tcharacteristic\tage\t9 day\n"
                "E-TEST-1\t\tSRR2\tcharacteristic\tcultivar\tB73\n"
                "E-TEST-1\t\tSRR2\tcharacteristic\torganism part\tleaf\n"
                "E-TEST-1\t\tSRR2\tfactor\tsampling site\tleaf section 2\n",
                encoding="utf-8",
            )
            expression.write_text(
                "GeneID\tGene Name\tg1\tg2\n"
                "GENE1\tname\t1,2\t3,4\n",
                encoding="utf-8",
            )
            job = metadata_importer.MetadataJob(
                metadata_tsv=metadata,
                experiment_accession="E-TEST-1",
                species_column="Zea_mays",
                expression_tsv=expression,
            )

            result = metadata_importer.write_partitioned_metadata(
                job=job,
                output_dir=tmp,
                force=True,
            )

            self.assertTrue(result.success)
            self.assertEqual(result.mapped_group_records, 2)
            wide_path = (
                tmp
                / "parquet"
                / "atlas_sample_metadata_wide"
                / "species_column=Zea_mays"
                / "experiment_accession=E-TEST-1"
                / "sample_metadata.parquet"
            )
            table = metadata_importer.pq.ParquetFile(wide_path).read()
            records = table.to_pylist()
            group_records = {
                row["sample_or_condition"]: row
                for row in records
                if row["sample_or_condition"] in {"g1", "g2"}
            }
            self.assertEqual(group_records["g1"]["organism_part"], "leaf")
            self.assertEqual(group_records["g1"]["developmental_stage"], "9 day")
            self.assertEqual(group_records["g1"]["condition"], "sampling site=leaf section 1")
            self.assertEqual(group_records["g2"]["condition"], "sampling site=leaf section 2")


if __name__ == "__main__":
    unittest.main()
