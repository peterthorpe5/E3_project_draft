"""Tests for Expression Atlas sample metadata importer."""

from __future__ import annotations

import csv
import gzip
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2] / "inst" / "python" / "import_sample_metadata_to_parquet.py"
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

    def test_duplicate_preferred_metadata_fields_are_merged(self) -> None:
        """Repeated SDRF fields must not disappear from flattened tissue data."""
        header = metadata_importer.make_unique(
            [
                "Assay Group",
                "Characteristics[organism part]",
                "Characteristics[organism part]",
            ]
        )
        row = dict(zip(header, ["g1", "leaf", "root"]))

        self.assertEqual(
            metadata_importer.get_preferred_value(row, "organism_part"),
            "leaf; root",
        )

    def test_metadata_helper_contracts_and_conflicts(self) -> None:
        """Filename, category, ordering and merge helpers should be explicit."""
        self.assertTrue(metadata_importer.parse_bool(True))
        self.assertFalse(metadata_importer.parse_bool("unknown", default=False))
        self.assertEqual(
            metadata_importer.metadata_file_kind("E.condensed-sdrf.tsv"),
            "condensed_sdrf",
        )
        self.assertEqual(
            metadata_importer.metadata_file_kind("E.sdrf.txt.bak"),
            "backup_sdrf",
        )
        self.assertLess(
            metadata_importer.metadata_file_priority("E.condensed-sdrf.tsv"),
            metadata_importer.metadata_file_priority("E.sdrf.txt"),
        )
        self.assertEqual(metadata_importer.merge_metadata_value("leaf", "leaf"), "leaf")
        self.assertEqual(metadata_importer.merge_metadata_value("", "root"), "root")
        self.assertEqual(metadata_importer.group_label_sort_key("g10")[0], 10)
        self.assertGreater(
            metadata_importer.group_label_sort_key("sample")[0],
            10,
        )
        self.assertEqual(
            metadata_importer.metadata_category("Factor Value[treatment]"),
            "factor_value",
        )
        self.assertEqual(metadata_importer.vertical_metadata_category("factor"), "factor_value")
        self.assertTrue(
            metadata_importer.looks_like_vertical_condensed_row(
                ["E-TEST-1", "", "SRR1", "factor", "treatment", "control"],
                metadata_importer.MetadataJob(
                    Path("metadata.tsv"),
                    "E-TEST-1",
                    "Species_a",
                ),
            )
        )
        with self.assertRaisesRegex(ValueError, "Conflicting assay counts"):
            metadata_importer.merge_wide_record(
                {"sample_or_condition": "g1", "assay_count": 1},
                {"sample_or_condition": "g1", "assay_count": 2},
            )

    def test_metadata_helpers_fail_closed_at_input_boundaries(self) -> None:
        """Missing, ambiguous and malformed metadata inputs must be explicit."""
        self.assertTrue(metadata_importer.parse_bool(None, default=True))
        self.assertEqual(
            metadata_importer.metadata_file_kind("metadata.tsv"),
            "sample_metadata",
        )
        self.assertEqual(
            metadata_importer.metadata_file_priority("metadata.unknown"),
            2,
        )
        self.assertEqual(
            metadata_importer.merge_metadata_value("leaf", ""),
            "leaf",
        )
        self.assertEqual(
            metadata_importer.make_unique(["", "", "Assay Name"]),
            ["unnamed_column", "unnamed_column_2", "Assay Name"],
        )
        self.assertEqual(
            metadata_importer.choose_sample_or_condition({"irrelevant": "g2"}),
            "g2",
        )
        self.assertEqual(
            metadata_importer.choose_sample_or_condition({"Sample Name": "sample-A"}),
            "sample-A",
        )
        self.assertEqual(
            metadata_importer.choose_sample_or_condition({"field": "value"}),
            "",
        )
        self.assertEqual(
            metadata_importer.metadata_category("Comment[ENA_RUN]"),
            "comment",
        )
        self.assertEqual(
            metadata_importer.metadata_category("Protocol REF"),
            "protocol",
        )
        self.assertEqual(metadata_importer.metadata_category("Assay Name"), "field")
        self.assertEqual(
            metadata_importer.vertical_metadata_category("comment"),
            "comment",
        )
        self.assertEqual(
            metadata_importer.vertical_metadata_category("protocol"),
            "protocol",
        )
        self.assertEqual(metadata_importer.vertical_metadata_category(""), "field")
        job = metadata_importer.MetadataJob(
            Path("metadata.tsv"),
            "E-TEST-1",
            "Species_a",
        )
        self.assertFalse(
            metadata_importer.looks_like_vertical_condensed_row(
                ["too", "short"],
                job,
            )
        )
        self.assertFalse(
            metadata_importer.looks_like_vertical_condensed_row(
                ["E-OTHER-1", "", "SRR1", "factor", "treatment", "x"],
                job,
            )
        )

    def test_hash_and_compressed_input_contracts(self) -> None:
        """Raw provenance and gzip handling should be deterministic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            compressed = tmp / "metadata.tsv.gz"
            with gzip.open(compressed, "wt", encoding="utf-8") as handle:
                handle.write("Assay Group\ng1\n")
            with metadata_importer.open_text(compressed) as handle:
                self.assertEqual(handle.readline().strip(), "Assay Group")
            self.assertEqual(
                metadata_importer.resolve_file_sha256(None, "", "optional"),
                "",
            )
            with self.assertRaisesRegex(ValueError, "missing or empty"):
                metadata_importer.resolve_file_sha256(
                    tmp / "missing.tsv",
                    "",
                    "metadata",
                )
            with self.assertRaisesRegex(ValueError, "Malformed"):
                metadata_importer.resolve_file_sha256(
                    compressed,
                    "not-a-digest",
                    "metadata",
                )

    def test_expression_group_header_contracts(self) -> None:
        """Matrix groups must be complete while retaining Atlas column order."""
        self.assertEqual(metadata_importer.read_expression_group_labels(None), [])
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            empty = tmp / "empty.tsv"
            empty.touch()
            self.assertEqual(
                metadata_importer.read_expression_group_labels(empty),
                [],
            )
            invalid = tmp / "invalid.tsv"
            invalid.write_text(
                "Gene ID\tGene Name\tleaf\nGENE1\tname\t1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "non-group"):
                metadata_importer.read_expression_group_labels(invalid)

            lexicographic = tmp / "lexicographic.tsv"
            lexicographic.write_text(
                "Gene ID\tGene Name\tg1\tg10\tg2\tg3\tg4\tg5\tg6\tg7\tg8\tg9\n"
                "GENE1\tname\t1\t1\t1\t1\t1\t1\t1\t1\t1\t1\n",
                encoding="utf-8",
            )
            self.assertEqual(
                metadata_importer.read_expression_group_labels(lexicographic),
                ["g1", "g10", "g2", "g3", "g4", "g5", "g6", "g7", "g8", "g9"],
            )
            sparse = tmp / "sparse.tsv"
            sparse.write_text(
                "Gene ID\tGene Name\tg8\tg11\tg21\nGENE1\tname\t1\t2\t3\n",
                encoding="utf-8",
            )
            self.assertEqual(
                metadata_importer.read_expression_group_labels(sparse),
                ["g8", "g11", "g21"],
            )

    def test_configuration_xml_rejects_every_ambiguous_shape(self) -> None:
        """Invalid XML group IDs, duplication and missing assays must all fail."""
        cases = (
            ("<configuration>", "Invalid Expression Atlas"),
            (
                "<configuration><assay_group id='leaf'>"
                "<assay>SRR1</assay></assay_group></configuration>",
                "invalid assay-group ID",
            ),
            (
                "<configuration><assay_group id='g1'>"
                "<assay>SRR1</assay></assay_group>"
                "<assay_group id='g1'><assay>SRR2</assay>"
                "</assay_group></configuration>",
                "duplicate assay-group ID",
            ),
            (
                "<configuration><assay_group id='g1'/></configuration>",
                "missing or duplicate assays",
            ),
            ("<configuration/>", "contains no assay groups"),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            missing = tmp / "missing.xml"
            with self.assertRaisesRegex(ValueError, "is missing"):
                metadata_importer.read_configuration_groups(missing)
            for index, (xml_text, message) in enumerate(cases):
                with self.subTest(message=message):
                    path = tmp / f"case-{index}.xml"
                    path.write_text(xml_text, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        metadata_importer.read_configuration_groups(path)

    def test_group_validation_rejects_ambiguity_and_maps_by_identifier(self) -> None:
        """Group joins must reject ambiguity but remain independent of order."""
        groups = metadata_importer.OrderedDict(
            [
                ("g1", metadata_importer.AssayGroup("g1", "leaf", ("S1",))),
                ("g2", metadata_importer.AssayGroup("g2", "root", ("S2",))),
            ]
        )
        with self.assertRaisesRegex(ValueError, "duplicate group"):
            metadata_importer.validate_matrix_configuration_groups(
                ["g1", "g1"],
                groups,
            )
        with self.assertRaisesRegex(ValueError, "non-group"):
            metadata_importer.validate_matrix_configuration_groups(
                ["g1", "leaf"],
                groups,
            )
        reordered = metadata_importer.validate_matrix_configuration_groups(
            ["g2", "g1"],
            groups,
        )
        self.assertEqual([group.group_id for group in reordered], ["g2", "g1"])
        subset = metadata_importer.validate_matrix_configuration_groups(
            ["g1"],
            groups,
        )
        self.assertEqual([group.group_id for group in subset], ["g1"])

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
                        "file_type": "configuration_xml",
                        "local_path": str(tmp / "configuration.xml"),
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
        self.assertEqual(jobs[0].configuration_xml.name, "configuration.xml")

    def test_preflight_requires_metadata_matrix_and_configuration(self) -> None:
        """Metadata publication must require every checksum-bound authority."""
        with self.assertRaisesRegex(ValueError, "selected no sample-metadata"):
            metadata_importer.preflight_metadata_jobs([])
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.tsv"
            job = metadata_importer.MetadataJob(
                metadata_tsv=missing,
                experiment_accession="E-TEST-1",
                species_column="Zea_mays",
            )
            with self.assertRaisesRegex(
                ValueError,
                "sample_metadata,tpms_or_fpkms,configuration_xml",
            ):
                metadata_importer.preflight_metadata_jobs([job])

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

    def test_configuration_xml_provides_exact_group_assays(self) -> None:
        """Atlas XML, not factor order, must define each matrix group."""

        with tempfile.TemporaryDirectory() as tmpdir:
            configuration = Path(tmpdir) / "configuration.xml"
            configuration.write_text(
                "<configuration><analytics><assay_groups>"
                '<assay_group id="g1" label="leaf"><assay>SRR2</assay>'
                "</assay_group>"
                '<assay_group id="g2" label="root"><assay>SRR1</assay>'
                "</assay_group>"
                "</assay_groups></analytics></configuration>",
                encoding="utf-8",
            )

            groups = metadata_importer.read_configuration_groups(configuration)
            matched = metadata_importer.validate_matrix_configuration_groups(
                ["g1", "g2"],
                groups,
            )

        self.assertEqual(matched[0].assay_ids, ("SRR2",))
        self.assertEqual(matched[1].assay_ids, ("SRR1",))

    def test_matrix_configuration_disagreement_is_rejected(self) -> None:
        """Missing or additional XML groups must fail closed."""

        groups = metadata_importer.OrderedDict(
            [
                ("g1", metadata_importer.AssayGroup("g1", "leaf", ("SRR1",))),
                ("g2", metadata_importer.AssayGroup("g2", "root", ("SRR2",))),
            ]
        )

        with self.assertRaisesRegex(ValueError, "groups disagree"):
            metadata_importer.validate_matrix_configuration_groups(
                ["g1", "g3"],
                groups,
            )

    def test_sparse_matrix_groups_map_by_authoritative_identifier(self) -> None:
        """Sparse matrix IDs must map to the same literal XML group IDs."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            metadata = tmp / "E-TEST-1.condensed-sdrf.tsv"
            expression = tmp / "E-TEST-1-tpms.tsv"
            configuration = tmp / "E-TEST-1-configuration.xml"
            metadata.write_text(
                "E-TEST-1\t\tSRR1\tcharacteristic\torganism part\tflower\n"
                "E-TEST-1\t\tSRR1\tfactor\torganism part\tflower\n"
                "E-TEST-1\t\tSRR2\tcharacteristic\torganism part\tleaf\n"
                "E-TEST-1\t\tSRR2\tfactor\torganism part\tleaf\n"
                "E-TEST-1\t\tSRR3\tcharacteristic\torganism part\troot\n"
                "E-TEST-1\t\tSRR3\tfactor\torganism part\troot\n",
                encoding="utf-8",
            )
            expression.write_text(
                "GeneID\tGene Name\tg1\tg3\nGENE1\tname\t1,1,1,1,1\t3,3,3,3,3\n",
                encoding="utf-8",
            )
            configuration.write_text(
                "<configuration><analytics><assay_groups>"
                '<assay_group id="g1" label="flower"><assay>SRR1</assay>'
                "</assay_group>"
                '<assay_group id="g3" label="root"><assay>SRR3</assay>'
                "</assay_group>"
                "</assay_groups></analytics></configuration>",
                encoding="utf-8",
            )
            job = metadata_importer.MetadataJob(
                metadata_tsv=metadata,
                experiment_accession="E-TEST-1",
                species_column="Solanum_tuberosum",
                expression_tsv=expression,
                configuration_xml=configuration,
            )

            wide, _long, _metadata_count, mapped_count = (
                metadata_importer.read_metadata_records(job)
            )

        group_rows = {
            row["sample_or_condition"]: row
            for row in wide
            if row["sample_or_condition"] in {"g1", "g3"}
        }
        self.assertEqual(mapped_count, 2)
        self.assertEqual(group_rows["g1"]["assay_ids"], "SRR1")
        self.assertEqual(group_rows["g3"]["assay_ids"], "SRR3")

    def test_configuration_accepts_order_variation_but_rejects_reused_assays(self) -> None:
        """XML group order is irrelevant, while assay membership stays unique."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reordered = root / "reordered.xml"
            reordered.write_text(
                "<configuration><analytics><assay_groups>"
                '<assay_group id="g2"><assay>SRR2</assay></assay_group>'
                '<assay_group id="g1"><assay>SRR1</assay></assay_group>'
                "</assay_groups></analytics></configuration>",
                encoding="utf-8",
            )
            self.assertEqual(
                list(metadata_importer.read_configuration_groups(reordered)),
                ["g2", "g1"],
            )

            sparse = root / "sparse.xml"
            sparse.write_text(
                "<configuration><analytics><assay_groups>"
                '<assay_group id="g8"><assay>SRR8</assay></assay_group>'
                '<assay_group id="g21"><assay>SRR21</assay></assay_group>'
                "</assay_groups></analytics></configuration>",
                encoding="utf-8",
            )
            self.assertEqual(
                list(metadata_importer.read_configuration_groups(sparse)),
                ["g8", "g21"],
            )

            reused = root / "reused.xml"
            reused.write_text(
                "<configuration><analytics><assay_groups>"
                '<assay_group id="g1"><assay>SRR1</assay></assay_group>'
                '<assay_group id="g2"><assay>SRR1</assay></assay_group>'
                "</assay_groups></analytics></configuration>",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "multiple groups"):
                metadata_importer.read_configuration_groups(reused)

    def test_tabular_metadata_rejects_truncated_rows(self) -> None:
        """Missing metadata fields must not be padded into apparently valid rows."""

        job = metadata_importer.MetadataJob(
            metadata_tsv=Path("metadata.tsv"),
            experiment_accession="E-TEST-1",
            species_column="Zea_mays",
        )
        with self.assertRaisesRegex(ValueError, "fields; expected"):
            metadata_importer.parse_tabular_metadata(
                job,
                ["Assay Group", "Characteristics[organism part]"],
                [["g1"]],
            )

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
                metadata_importer.make_closed_temp_path(tmp, ".parquet.partial") for _ in range(25)
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
                "Assay Group\tCharacteristics[organism]\t"
                "Characteristics[organism part]\tFactor Value[treatment]\n"
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
            wide_path = (
                tmp
                / "parquet"
                / "atlas_sample_metadata_wide"
                / "species_column=Arabidopsis_thaliana"
                / "experiment_accession=E-TEST-1"
                / "sample_metadata.parquet"
            )
            self.assertTrue(
                metadata_importer.parquet_has_current_schema(
                    wide_path,
                    metadata_importer.wide_schema(),
                )
            )
            table = metadata_importer.pq.ParquetFile(wide_path).read()
            source_hashes = table.column("source_file_sha256").to_pylist()
            self.assertEqual(source_hashes, [metadata_importer.sha256_file(metadata)] * 2)

    @unittest.skipIf(metadata_importer.pa is None, "pyarrow is not installed")
    def test_changed_metadata_source_rebuilds_same_schema_output(self) -> None:
        """A source checksum change must invalidate an otherwise current Parquet."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            metadata = tmp / "metadata.tsv"
            metadata.write_text(
                "Assay Group\tCharacteristics[organism part]\ng1\tleaf\n",
                encoding="utf-8",
            )
            job = metadata_importer.MetadataJob(
                metadata_tsv=metadata,
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
            )
            first = metadata_importer.write_partitioned_metadata(job, tmp, force=False)
            metadata.write_text(
                "Assay Group\tCharacteristics[organism part]\ng1\troot\n",
                encoding="utf-8",
            )
            second = metadata_importer.write_partitioned_metadata(job, tmp, force=False)
            wide_path = (
                tmp
                / "parquet"
                / "atlas_sample_metadata_wide"
                / "species_column=Arabidopsis_thaliana"
                / "experiment_accession=E-TEST-1"
                / "sample_metadata.parquet"
            )

            self.assertTrue(first.success)
            self.assertEqual(second.action, "imported_to_parquet")
            records = metadata_importer.pq.ParquetFile(wide_path).read().to_pylist()
            self.assertEqual(records[0]["organism_part"], "root")

    def test_metadata_manifest_sha256_mismatch_fails_closed(self) -> None:
        """Metadata differing from its manifest digest must not be imported."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            metadata = tmp / "metadata.tsv"
            metadata.write_text(
                "Assay Group\tCharacteristics[organism part]\ng1\tleaf\n",
                encoding="utf-8",
            )
            job = metadata_importer.MetadataJob(
                metadata_tsv=metadata,
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
                metadata_sha256="0" * 64,
            )

            result = metadata_importer.write_partitioned_metadata(job, tmp, force=False)

            self.assertFalse(result.success)
            self.assertEqual(result.action, "source_validation_failed")
            self.assertIn("SHA-256 mismatch", result.message)

    @unittest.skipIf(metadata_importer.pa is None, "pyarrow is not installed")
    def test_expression_groups_require_complete_configuration_backed_metadata(self) -> None:
        """Every matrix gN column must have an authoritative metadata record."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            metadata = tmp / "metadata.tsv"
            expression = tmp / "matrix.tsv"
            configuration = tmp / "configuration.xml"
            metadata.write_text(
                "Assay Group\tCharacteristics[organism part]\ng1\tleaf\n",
                encoding="utf-8",
            )
            expression.write_text(
                "Gene ID\tGene Name\tg1\tg2\nAT1G1\tGENE1\t1\t2\n",
                encoding="utf-8",
            )
            configuration.write_text(
                "<configuration><analytics><assay_groups>"
                '<assay_group id="g1" label="leaf"><assay>SRR1</assay>'
                "</assay_group>"
                '<assay_group id="g2" label="root"><assay>SRR2</assay>'
                "</assay_group>"
                "</assay_groups></analytics></configuration>",
                encoding="utf-8",
            )
            incomplete = metadata_importer.MetadataJob(
                metadata_tsv=metadata,
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
                expression_tsv=expression,
                configuration_xml=configuration,
            )
            no_configuration = metadata_importer.MetadataJob(
                metadata_tsv=metadata,
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
                expression_tsv=expression,
            )

            incomplete_result = metadata_importer.write_partitioned_metadata(
                incomplete,
                tmp / "incomplete",
                force=True,
            )
            no_configuration_result = metadata_importer.write_partitioned_metadata(
                no_configuration,
                tmp / "no_configuration",
                force=True,
            )

            self.assertFalse(incomplete_result.success)
            self.assertEqual(incomplete_result.action, "import_failed")
            self.assertIn("groups: ['g2']", incomplete_result.message)
            self.assertFalse(no_configuration_result.success)
            self.assertIn("configuration XML", no_configuration_result.message)
            self.assertEqual(list((tmp / "incomplete").rglob("*.parquet")), [])

    @unittest.skipIf(metadata_importer.pa is None, "pyarrow is not installed")
    def test_vertical_condensed_sdrf_maps_authoritative_groups(self) -> None:
        """Vertical metadata should use XML-defined assay groups."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            metadata = tmp / "E-TEST-1.condensed-sdrf.tsv"
            expression = tmp / "E-TEST-1-tpms.tsv"
            configuration = tmp / "E-TEST-1-configuration.xml"
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
                "GeneID\tGene Name\tg1\tg2\nGENE1\tname\t1,1,1,1,1\t3,3,3,3,3\n",
                encoding="utf-8",
            )
            configuration.write_text(
                "<configuration><analytics><assay_groups>"
                '<assay_group id="g1" label="leaf section 1">'
                "<assay>SRR1</assay></assay_group>"
                '<assay_group id="g2" label="leaf section 2">'
                "<assay>SRR2</assay></assay_group>"
                "</assay_groups></analytics></configuration>",
                encoding="utf-8",
            )
            job = metadata_importer.MetadataJob(
                metadata_tsv=metadata,
                experiment_accession="E-TEST-1",
                species_column="Zea_mays",
                expression_tsv=expression,
                configuration_xml=configuration,
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
            self.assertEqual(group_records["g2"]["atlas_group_label"], "leaf section 2")
            self.assertEqual(group_records["g2"]["assay_ids"], "SRR2")
            self.assertEqual(group_records["g2"]["assay_count"], 1)

    @unittest.skipIf(metadata_importer.pa is None, "pyarrow is not installed")
    def test_main_fails_if_any_selected_metadata_source_cannot_import(self) -> None:
        """A partial metadata build must return a non-zero process status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            good = tmp / "good.tsv"
            missing = tmp / "missing.tsv"
            good.write_text(
                "Assay Group\tCharacteristics[organism part]\ng1\tleaf\n",
                encoding="utf-8",
            )
            manifest = tmp / "atlas_downloaded_files.tsv"
            manifest.write_text(
                "species_column\texperiment_accession\tfile_type\t"
                "local_path\tsuccess\n"
                f"Species_a\tE-TEST-1\tsample_metadata\t{good}\ttrue\n"
                f"Species_b\tE-TEST-2\tsample_metadata\t{missing}\ttrue\n",
                encoding="utf-8",
            )
            output = tmp / "output"

            with self.assertRaisesRegex(SystemExit, "Preflight found 2/2"):
                metadata_importer.main(
                    [
                        "--downloaded_files_tsv",
                        str(manifest),
                        "--output_dir",
                        str(output),
                    ]
                )
            self.assertFalse((output / "manifests").exists())

    @unittest.skipIf(metadata_importer.pa is None, "pyarrow is not installed")
    def test_main_returns_success_for_a_complete_metadata_set(self) -> None:
        """Every selected metadata source should be required for success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            metadata = tmp / "E-TEST-1.condensed-sdrf.tsv"
            metadata.write_text(
                "E-TEST-1\t\tERR1\tcharacteristic\torganism part\troot\n",
                encoding="utf-8",
            )
            expression = tmp / "expression.tsv"
            expression.write_text(
                "Gene ID\tGene Name\tg1\nZm1\tGENE1\t1,2,3,4,5\n",
                encoding="utf-8",
            )
            configuration = tmp / "configuration.xml"
            configuration.write_text(
                '<configuration><assay_group id="g1" label="root">'
                "<assay>ERR1</assay></assay_group></configuration>",
                encoding="utf-8",
            )
            manifest = tmp / "atlas_downloaded_files.tsv"
            manifest.write_text(
                "species_column\texperiment_accession\tfile_type\t"
                "local_path\tsuccess\n"
                f"Species_a\tE-TEST-1\tsample_metadata\t{metadata}\ttrue\n"
                f"Species_a\tE-TEST-1\ttpms\t{expression}\ttrue\n"
                f"Species_a\tE-TEST-1\tconfiguration_xml\t{configuration}\ttrue\n",
                encoding="utf-8",
            )

            status = metadata_importer.main(
                [
                    "--downloaded_files_tsv",
                    str(manifest),
                    "--output_dir",
                    str(tmp / "output"),
                ]
            )

            self.assertEqual(status, 0)


if __name__ == "__main__":
    unittest.main()
