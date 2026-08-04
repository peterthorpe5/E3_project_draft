"""Tests for the Python Expression Atlas Parquet importer."""

from __future__ import annotations

import csv
import gzip
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "inst" / "python" / "import_expression_to_parquet.py"

spec = importlib.util.spec_from_file_location("import_expression_to_parquet", SCRIPT)
importer = importlib.util.module_from_spec(spec)
sys.modules["import_expression_to_parquet"] = importer
assert spec.loader is not None
spec.loader.exec_module(importer)


class ImportExpressionToParquetTests(unittest.TestCase):
    """Test the streaming Python importer."""

    def test_five_number_summary_uses_median_without_concatenation(self) -> None:
        """Atlas comma-separated statistics should produce the median level."""

        parsed = importer.parse_expression_summary("3,3,3,4,5")

        self.assertEqual(parsed.expression_value, 3.0)
        self.assertEqual(parsed.minimum, 3.0)
        self.assertEqual(parsed.lower_quartile, 3.0)
        self.assertEqual(parsed.median, 3.0)
        self.assertEqual(parsed.upper_quartile, 4.0)
        self.assertEqual(parsed.maximum, 5.0)
        self.assertEqual(parsed.summary_type, "atlas_five_number_summary")

    def test_decimal_summary_statistics_are_preserved(self) -> None:
        """All five decimal summary statistics must be retained."""

        parsed = importer.parse_expression_summary("0,0,0,0.4,0.7")

        self.assertEqual(
            (
                parsed.minimum,
                parsed.lower_quartile,
                parsed.median,
                parsed.upper_quartile,
                parsed.maximum,
            ),
            (0.0, 0.0, 0.0, 0.4, 0.7),
        )

    def test_invalid_non_finite_statistic_is_rejected(self) -> None:
        """Corrupt or non-finite summary statistics should fail explicitly."""

        with self.assertRaisesRegex(ValueError, "not a finite number"):
            importer.parse_expression_summary("1,1,inf,2,2")

    def test_negative_expression_statistic_is_rejected(self) -> None:
        """Impossible negative TPM/FPKM values should fail explicitly."""

        with self.assertRaisesRegex(ValueError, "negative"):
            importer.parse_expression_summary("-0.1,0,1,2,3")

    def test_three_comma_values_are_not_treated_as_thousands(self) -> None:
        """Malformed comma counts must fail rather than concatenate digits."""

        with self.assertRaisesRegex(ValueError, "one value or the five"):
            importer.parse_expression_summary("3,3,345")

    def test_unsorted_five_number_summary_is_rejected(self) -> None:
        """Quartiles that violate their statistical order must fail closed."""

        with self.assertRaisesRegex(ValueError, "not monotonically ordered"):
            importer.parse_expression_summary("0,4,3,5,6")

    def test_atlas_zero_code_remains_measured_zero(self) -> None:
        """Atlas '-' zero codes must not be confused with unavailable data."""

        parsed = importer.parse_expression_summary("-")

        self.assertEqual(parsed.expression_value, 0.0)
        self.assertEqual(parsed.summary_type, "atlas_zero_code")
        self.assertIsNone(importer.parse_expression_summary("NA"))

    def test_low_level_parsers_cover_gzip_nulls_and_unique_names(self) -> None:
        """Foundational helpers should have explicit, non-coercing behaviour."""
        self.assertTrue(importer.parse_bool("YES"))
        self.assertFalse(importer.parse_bool("unexpected", default=False))
        self.assertEqual(
            importer.make_unique(["A", "A", "", " A "]),
            ["A", "A_2", "unnamed_column", "A_3"],
        )
        self.assertEqual(importer.safe_get([" a "], 0), "a")
        self.assertEqual(importer.safe_get(["a"], None), "")
        self.assertEqual(importer.safe_get(["a"], 2), "")
        self.assertEqual(importer.parse_float(" 1.25 "), 1.25)
        self.assertIsNone(importer.parse_float("not-a-number"))
        self.assertIsNone(importer.parse_float("nan"))

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "matrix.tsv.gz"
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                handle.write("Gene ID\tg1\nAT1G1\t1\n")
            with importer.open_text(path) as handle:
                self.assertEqual(handle.readline().strip(), "Gene ID\tg1")

    def test_record_iterator_emits_summary_provenance(self) -> None:
        """Long records should retain five-number statistics and their meaning."""

        with tempfile.TemporaryDirectory() as tmpdir:
            matrix = Path(tmpdir) / "matrix.tsv"
            matrix.write_text(
                "Gene ID\tGene Name\tg1\nAT1G1\tGENE1\t1.0,2.0,3.0,4.0,5.0\n",
                encoding="utf-8",
            )
            job = importer.MatrixJob(
                expression_tsv=matrix,
                output_parquet=Path(tmpdir) / "out.parquet",
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
                expression_unit="TPM",
                file_type="tpms",
            )
            layout = importer.detect_column_layout(matrix)

            records = [
                record
                for record, _row_number in importer.iter_matrix_records(
                    job=job,
                    layout=layout,
                )
            ]

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["expression_value"], 3.0)
        self.assertEqual(records[0]["expression_minimum"], 1.0)
        self.assertEqual(records[0]["expression_maximum"], 5.0)
        self.assertEqual(records[0]["expression_value_statistic"], "median")

    def test_column_layout_detection(self) -> None:
        """The importer detects gene ID, gene name and expression columns."""

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "matrix.tsv"
            path.write_text(
                "Gene ID\tGene Name\tg1\tg2\nAT1G1\tGENE1\t1.0\t2.0\n",
                encoding="utf-8",
            )

            layout = importer.detect_column_layout(path)

        self.assertEqual(layout.gene_id_index, 0)
        self.assertEqual(layout.gene_name_index, 1)
        self.assertEqual([layout.header[i] for i in layout.expression_indices], ["g1", "g2"])

    def test_column_layout_rejects_non_atlas_group_labels(self) -> None:
        """Free-text columns must not bypass the configuration-backed gN contract."""

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "matrix.tsv"
            path.write_text(
                "Gene ID\tGene Name\tleaf\troot\nAT1G1\tGENE1\t1.0\t2.0\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "ordered group labels"):
                importer.detect_column_layout(path)

    def test_column_layout_rejects_missing_group_number(self) -> None:
        """A missing g2 column must not silently shift condition identities."""

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "matrix.tsv"
            path.write_text(
                "Gene ID\tGene Name\tg1\tg3\nAT1G1\tGENE1\t1.0\t2.0\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "g1..gN"):
                importer.detect_column_layout(path)

    def test_column_layout_rejects_missing_gene_identifier(self) -> None:
        """A matrix without an explicit gene-ID column must not be guessed."""

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "matrix.tsv"
            path.write_text(
                "Description\tleaf\troot\nGENE1\t1.0\t2.0\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "gene-ID"):
                importer.detect_column_layout(path)

    def test_column_layout_rejects_duplicate_headers(self) -> None:
        """Duplicate biological-condition labels must not be renamed silently."""

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "matrix.tsv"
            path.write_text(
                "Gene ID\tg1\tg1\nAT1G1\t1.0\t2.0\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate header"):
                importer.detect_column_layout(path)

    def test_column_layout_rejects_empty_and_ambiguous_headers(self) -> None:
        """No matrix may proceed without one unambiguous identifier column."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            empty = root / "empty.tsv"
            empty.write_text("", encoding="utf-8")
            blank_header = root / "blank-header.tsv"
            blank_header.write_text("Gene ID\t\nAT1G1\t1\n", encoding="utf-8")
            ambiguous = root / "ambiguous.tsv"
            ambiguous.write_text(
                "Gene ID\tIdentifier\tg1\nAT1G1\tAT1G1\t1\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "no header"):
                importer.detect_column_layout(empty)
            with self.assertRaisesRegex(ValueError, "empty header"):
                importer.detect_column_layout(blank_header)
            with self.assertRaisesRegex(ValueError, "exactly one"):
                importer.detect_column_layout(ambiguous)

    def test_record_iterator_rejects_short_rows(self) -> None:
        """Truncated rows must fail rather than create implicit missing values."""

        with tempfile.TemporaryDirectory() as tmpdir:
            matrix = Path(tmpdir) / "matrix.tsv"
            matrix.write_text(
                "Gene ID\tGene Name\tg1\tg2\nAT1G1\tGENE1\t1.0\n",
                encoding="utf-8",
            )
            job = importer.MatrixJob(
                expression_tsv=matrix,
                output_parquet=Path(tmpdir) / "out.parquet",
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
                expression_unit="TPM",
                file_type="tpms",
            )

            with self.assertRaisesRegex(ValueError, "fields; expected"):
                list(
                    importer.iter_matrix_records(
                        job=job,
                        layout=importer.detect_column_layout(matrix),
                    )
                )

    def test_record_iterator_rejects_blank_and_duplicate_gene_ids(self) -> None:
        """Every matrix row must identify one unique gene without silent loss."""

        for rows, message in (
            ("\tGENE1\t1,1,1,1,1\n", "blank gene identifier"),
            (
                "AT1G1\tGENE1\t1,1,1,1,1\nat1g1\tGENE1_DUP\t2,2,2,2,2\n",
                "duplicates gene identifier",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmpdir:
                matrix = Path(tmpdir) / "matrix.tsv"
                matrix.write_text(
                    "Gene ID\tGene Name\tg1\n" + rows,
                    encoding="utf-8",
                )
                job = importer.MatrixJob(
                    expression_tsv=matrix,
                    output_parquet=Path(tmpdir) / "out.parquet",
                    experiment_accession="E-TEST-1",
                    species_column="Arabidopsis_thaliana",
                    expression_unit="TPM",
                    file_type="tpms",
                )

                with self.assertRaisesRegex(ValueError, message):
                    list(
                        importer.iter_matrix_records(
                            job=job,
                            layout=importer.detect_column_layout(matrix),
                        )
                    )

    @unittest.skipIf(importer.pa is None, "pyarrow is not installed")
    def test_matrix_import_writes_rows(self) -> None:
        """A small wide matrix is converted into long Parquet rows."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            matrix = tmp / "matrix.tsv"
            matrix.write_text(
                "Gene ID\tGene Name\tg1\tg2\nAT1G1\tGENE1\t1.0\t2.0\nAT1G2\tGENE2\t0\t3.5\n",
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
            self.assertTrue(importer.parquet_has_current_schema(output))
            table = importer.pq.read_table(output)
            source_hashes = table.column("source_file_sha256").to_pylist()
            self.assertEqual(len(set(source_hashes)), 1)
            self.assertEqual(source_hashes[0], importer.sha256_file(matrix))

    @unittest.skipIf(importer.pa is None, "pyarrow is not installed")
    def test_old_schema_parquet_is_rebuilt_even_without_force(self) -> None:
        """A non-empty legacy Parquet must never bypass corrected parsing."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            matrix = tmp / "matrix.tsv"
            matrix.write_text(
                "Gene ID\tGene Name\tg1\nAT1G1\tGENE1\t3,3,3,4,5\n",
                encoding="utf-8",
            )
            output = tmp / "out.parquet"
            importer.pq.write_table(
                importer.pa.table({"expression_value": [334.0]}),
                output,
            )
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
                force=False,
                chunk_rows=2,
            )

            values = importer.pq.read_table(output).column("expression_value").to_pylist()
            self.assertEqual(result.action, "imported_to_parquet_python")
            self.assertEqual(values, [3.0])
            self.assertTrue(importer.parquet_has_current_schema(output))

    @unittest.skipIf(importer.pa is None, "pyarrow is not installed")
    def test_changed_source_invalidates_current_schema_output(self) -> None:
        """A same-schema Parquet cannot be reused after the raw matrix changes."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            matrix = tmp / "matrix.tsv"
            matrix.write_text(
                "Gene ID\tGene Name\tg1\nAT1G1\tGENE1\t1,1,1,1,1\n",
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
            first = importer.normalise_matrix_to_parquet(job, force=False, chunk_rows=2)
            matrix.write_text(
                "Gene ID\tGene Name\tg1\nAT1G1\tGENE1\t2,2,2,2,2\n",
                encoding="utf-8",
            )
            second = importer.normalise_matrix_to_parquet(job, force=False, chunk_rows=2)

            self.assertTrue(first.success)
            self.assertEqual(second.action, "imported_to_parquet_python")
            self.assertEqual(
                importer.pq.read_table(output).column("expression_value").to_pylist(),
                [2.0],
            )

    def test_manifest_sha256_mismatch_fails_closed(self) -> None:
        """A downloaded file differing from its manifest digest must not import."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            matrix = tmp / "matrix.tsv"
            matrix.write_text(
                "Gene ID\tGene Name\tg1\nAT1G1\tGENE1\t1,1,1,1,1\n",
                encoding="utf-8",
            )
            job = importer.MatrixJob(
                expression_tsv=matrix,
                output_parquet=tmp / "out.parquet",
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
                expression_unit="TPM",
                file_type="tpms",
                source_sha256="0" * 64,
            )

            result = importer.normalise_matrix_to_parquet(job, force=False, chunk_rows=2)

            self.assertFalse(result.success)
            self.assertEqual(result.action, "source_validation_failed")
            self.assertIn("SHA-256 mismatch", result.message)

    def test_malformed_digest_invalid_parquet_and_empty_inputs_fail_closed(self) -> None:
        """Reuse and import guards must reject corrupt or unavailable artefacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            invalid_parquet = root / "invalid.parquet"
            invalid_parquet.write_text("not parquet", encoding="utf-8")
            self.assertEqual(importer.parquet_row_count(invalid_parquet), 0)
            self.assertFalse(importer.parquet_has_current_schema(invalid_parquet))
            missing_job = importer.MatrixJob(
                expression_tsv=root / "missing.tsv",
                output_parquet=root / "out.parquet",
                experiment_accession="E-TEST-1",
                species_column="Species_a",
                expression_unit="TPM",
                file_type="tpms",
            )
            self.assertEqual(
                importer.normalise_matrix_to_parquet(missing_job, False, 2).action,
                "skipped_missing_or_empty_input",
            )

            matrix = root / "matrix.tsv"
            matrix.write_text("Gene ID\tg1\nAT1G1\t1\n", encoding="utf-8")
            malformed_hash_job = importer.replace(
                missing_job,
                expression_tsv=matrix,
                source_sha256="bad-hash",
            )
            result = importer.normalise_matrix_to_parquet(
                malformed_hash_job,
                False,
                2,
            )
            self.assertFalse(result.success)
            self.assertIn("Malformed source SHA-256", result.message)

    @unittest.skipIf(importer.pa is None, "pyarrow is not installed")
    def test_invalid_and_all_null_cells_do_not_publish_parquet(self) -> None:
        """Malformed and evidence-free matrices must leave no final output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name, value, expected_action in (
                ("invalid", "1,2,3", "import_failed"),
                ("all-null", "NA", "imported_zero_rows"),
            ):
                with self.subTest(name=name):
                    matrix = root / f"{name}.tsv"
                    output = root / f"{name}.parquet"
                    matrix.write_text(
                        f"Gene ID\tg1\nAT1G1\t{value}\n",
                        encoding="utf-8",
                    )
                    result = importer.normalise_matrix_to_parquet(
                        importer.MatrixJob(
                            expression_tsv=matrix,
                            output_parquet=output,
                            experiment_accession="E-TEST-1",
                            species_column="Species_a",
                            expression_unit="TPM",
                            file_type="tpms",
                        ),
                        force=True,
                        chunk_rows=1,
                    )
                    self.assertEqual(result.action, expected_action)
                    self.assertFalse(output.exists())

    def test_temporary_file_descriptor_is_closed(self) -> None:
        """Temporary-path creation must not leak a descriptor per matrix."""

        with tempfile.TemporaryDirectory() as tmpdir:
            path = importer.make_closed_temp_path(Path(tmpdir), ".partial")
            path.write_text("ok", encoding="utf-8")

            self.assertEqual(path.read_text(encoding="utf-8"), "ok")

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

    def test_empty_manifest_path_does_not_become_current_directory(self) -> None:
        """A blank local path must not be interpreted as ``Path('.')``."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            manifest = tmp / "atlas_downloaded_files.tsv"
            manifest.write_text(
                "species_column\texperiment_accession\tfile_type\tlocal_path\tsuccess\n"
                "Zea_mays\tE-TEST-2\ttpms\t\ttrue\n",
                encoding="utf-8",
            )

            jobs = importer.build_jobs(manifest, tmp)

        self.assertEqual(jobs, [])

    def test_conflicting_duplicate_manifest_jobs_are_rejected(self) -> None:
        """Two raw inputs must not overwrite the same partition implicitly."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            manifest = tmp / "atlas_downloaded_files.tsv"
            manifest.write_text(
                "species_column\texperiment_accession\tfile_type\tlocal_path\tsuccess\n"
                "Zea_mays\tE-TEST-2\ttpms\t/a.tsv\ttrue\n"
                "Zea_mays\tE-TEST-2\ttpms\t/b.tsv\ttrue\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "conflicting inputs"):
                importer.build_jobs(manifest, tmp)

    @unittest.skipIf(importer.pa is None, "pyarrow is not installed")
    def test_main_fails_if_any_selected_matrix_cannot_be_imported(self) -> None:
        """One successful matrix must not hide another failed import job."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            good = tmp / "good.tsv"
            missing = tmp / "missing.tsv"
            good.write_text(
                "Gene ID\tGene Name\tg1\nAT1G1\tGENE1\t1,2,3,4,5\n",
                encoding="utf-8",
            )
            manifest = tmp / "atlas_downloaded_files.tsv"
            manifest.write_text(
                "species_column\texperiment_accession\tfile_type\t"
                "local_path\tsuccess\n"
                f"Species_a\tE-TEST-1\ttpms\t{good}\ttrue\n"
                f"Species_b\tE-TEST-2\ttpms\t{missing}\ttrue\n",
                encoding="utf-8",
            )
            output = tmp / "output"

            status = importer.main(
                [
                    "--downloaded_files_tsv",
                    str(manifest),
                    "--output_dir",
                    str(output),
                    "--chunk_rows",
                    "1",
                ]
            )

            self.assertEqual(status, 1)
            summary = (output / "manifests" / "atlas_expression_import_summary.tsv").read_text(
                encoding="utf-8"
            )
            self.assertIn("imported_to_parquet_python", summary)
            self.assertIn("skipped_missing_or_empty_input", summary)

    @unittest.skipIf(importer.pa is None, "pyarrow is not installed")
    def test_main_returns_success_only_for_a_complete_import_set(self) -> None:
        """The CLI should succeed when every selected source is validated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            matrix = tmp / "matrix.tsv"
            matrix.write_text(
                "Gene ID\tGene Name\tg1\nAT1G1\tGENE1\t3,3,3,4,5\n",
                encoding="utf-8",
            )
            manifest = tmp / "atlas_downloaded_files.tsv"
            manifest.write_text(
                "species_column\texperiment_accession\tfile_type\t"
                "local_path\tsuccess\n"
                f"Species_a\tE-TEST-1\ttpms\t{matrix}\ttrue\n",
                encoding="utf-8",
            )
            output = tmp / "output"

            status = importer.main(
                [
                    "--downloaded_files_tsv",
                    str(manifest),
                    "--output_dir",
                    str(output),
                ]
            )

            self.assertEqual(status, 0)
            parquet = next((output / "parquet").rglob("*.parquet"))
            self.assertEqual(
                importer.pq.ParquetFile(parquet).read().column("expression_value").to_pylist(),
                [3.0],
            )


if __name__ == "__main__":
    unittest.main()
