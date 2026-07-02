"""Tests for the Python Expression Atlas Parquet importer."""

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
    / "import_expression_to_parquet.py"
)

spec = importlib.util.spec_from_file_location("import_expression_to_parquet", SCRIPT)
importer = importlib.util.module_from_spec(spec)
sys.modules["import_expression_to_parquet"] = importer
assert spec.loader is not None
spec.loader.exec_module(importer)


class ImportExpressionToParquetTests(unittest.TestCase):
    """Test the streaming Python importer."""

    def test_column_layout_detection(self) -> None:
        """The importer detects gene ID, gene name and expression columns."""

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "matrix.tsv"
            path.write_text(
                "Gene ID\tGene Name\tleaf\troot\n"
                "AT1G1\tGENE1\t1.0\t2.0\n",
                encoding="utf-8",
            )

            layout = importer.detect_column_layout(path)

        self.assertEqual(layout.gene_id_index, 0)
        self.assertEqual(layout.gene_name_index, 1)
        self.assertEqual([layout.header[i] for i in layout.expression_indices], ["leaf", "root"])

    @unittest.skipIf(importer.pa is None, "pyarrow is not installed")
    def test_matrix_import_writes_rows(self) -> None:
        """A small wide matrix is converted into long Parquet rows."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            matrix = tmp / "matrix.tsv"
            matrix.write_text(
                "Gene ID\tGene Name\tleaf\troot\n"
                "AT1G1\tGENE1\t1.0\t2.0\n"
                "AT1G2\tGENE2\t0\t3.5\n",
                encoding="utf-8",
            )
            output = tmp / "out.parquet"
            job = importer.MatrixJob(
                expression_tsv=matrix,
                output_parquet=output,
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
                expression_unit="TPM",
                file_type="tpms",
            )

            result = importer.normalise_matrix_to_parquet(
                job=job,
                force=True,
                chunk_rows=2,
            )

            self.assertTrue(result.success)
            self.assertEqual(result.imported_rows, 4)
            self.assertEqual(importer.parquet_row_count(output), 4)

    def test_jobs_are_built_from_manifest(self) -> None:
        """Only successful TPM/FPKM rows become import jobs."""

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
                        "experiment_accession": "E-TEST-2",
                        "file_type": "tpms",
                        "local_path": str(tmp / "matrix.tsv"),
                        "success": "true",
                    }
                )
                writer.writerow(
                    {
                        "species_column": "Zea_mays",
                        "experiment_accession": "E-TEST-2",
                        "file_type": "sample_metadata",
                        "local_path": str(tmp / "metadata.tsv"),
                        "success": "true",
                    }
                )

            jobs = importer.build_jobs(downloaded_files_tsv=manifest, output_dir=tmp)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].expression_unit, "TPM")


if __name__ == "__main__":
    unittest.main()
