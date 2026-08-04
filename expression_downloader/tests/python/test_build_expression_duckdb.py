"""Semantic and corruption tests for the Expression Atlas DuckDB builder."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SCRIPT = Path(__file__).resolve().parents[2] / "inst" / "python" / "build_expression_duckdb.py"
spec = importlib.util.spec_from_file_location("build_expression_duckdb", SCRIPT)
builder = importlib.util.module_from_spec(spec)
sys.modules["build_expression_duckdb"] = builder
assert spec.loader is not None
spec.loader.exec_module(builder)


def write_dataset_file(root: Path, dataset: str, records: list[dict[str, object]]) -> None:
    """Write one partition-shaped Parquet fixture."""
    path = (
        root
        / "parquet"
        / dataset
        / "species_column=Arabidopsis_thaliana"
        / "experiment_accession=E-TEST-1"
        / "part.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(records), path)


def expression_record(
    *,
    gene_id: str = "AT1G1",
    group_id: str = "g1",
    unit: str = "TPM",
    value: float = 1.0,
) -> dict[str, object]:
    """Return one internally consistent five-number expression record."""
    return {
        "source_database": "ExpressionAtlas",
        "experiment_accession": "E-TEST-1",
        "species_column": "Arabidopsis_thaliana",
        "gene_id": gene_id,
        "gene_name": "GENE1",
        "sample_or_condition": group_id,
        "expression_value": value,
        "expression_minimum": value - 0.2,
        "expression_lower_quartile": value - 0.1,
        "expression_median": value,
        "expression_upper_quartile": value + 0.1,
        "expression_maximum": value + 0.2,
        "expression_value_statistic": "median",
        "expression_summary_type": "atlas_five_number_summary",
        "expression_unit": unit,
        "source_file": "/raw/E-TEST-1-tpms.tsv",
        "source_file_sha256": "a" * 64,
    }


def metadata_record(
    *,
    group_id: str = "g1",
    tissue: str = "leaf",
) -> dict[str, object]:
    """Return one configuration-backed metadata group record."""
    return {
        "source_database": "ExpressionAtlas",
        "experiment_accession": "E-TEST-1",
        "species_column": "Arabidopsis_thaliana",
        "sample_or_condition": group_id,
        "atlas_group_label": tissue,
        "assay_ids": "SRR1",
        "assay_count": 1,
        "metadata_record_id": f"E-TEST-1:{group_id}",
        "organism": "Arabidopsis thaliana",
        "organism_part": tissue,
        "developmental_stage": "adult",
        "genotype": "Col-0",
        "cultivar": "",
        "treatment": "control",
        "condition": "treatment=control",
        "assay_name": "SRR1",
        "source_name": "sample1",
        "sample_name": "sample1",
        "source_file": "/raw/E-TEST-1.condensed-sdrf.tsv",
        "source_file_sha256": "b" * 64,
        "configuration_file": "/raw/E-TEST-1-configuration.xml",
        "configuration_file_sha256": "c" * 64,
        "expression_file_sha256": "a" * 64,
    }


class BuildExpressionDuckdbTests(unittest.TestCase):
    """Prove database views preserve corrected expression semantics."""

    def make_valid_source(self, root: Path) -> None:
        """Write one valid expression and metadata context."""
        write_dataset_file(root, "atlas_expression_long", [expression_record()])
        write_dataset_file(root, "atlas_sample_metadata_wide", [metadata_record()])

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_valid_build_preserves_join_cardinality_and_tissue(self) -> None:
        """One expression context must remain one joined, tissue-labelled context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.make_valid_source(root)
            database = root / "e3_expression.duckdb"

            result = builder.build_database(root, database)

            self.assertEqual(result.expression_rows, 1)
            self.assertEqual(result.expression_rows_with_metadata, 1)
            self.assertEqual(result.mapped_tissue_rows, 1)
            validation = root / "manifests" / "atlas_duckdb_validation.tsv"
            self.assertTrue(validation.is_file())
            connection = builder.duckdb.connect(str(database), read_only=True)
            row = connection.execute(
                "SELECT expression_value, organism_part, atlas_group_label "
                "FROM atlas_expression_with_sample_metadata"
            ).fetchone()
            connection.close()
            self.assertEqual(row, (1.0, "leaf", "leaf"))

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_duplicate_expression_context_fails_closed(self) -> None:
        """Duplicate scientific keys must not inflate positive-context fractions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            record = expression_record()
            write_dataset_file(root, "atlas_expression_long", [record, record])
            write_dataset_file(root, "atlas_sample_metadata_wide", [metadata_record()])

            with self.assertRaisesRegex(ValueError, "duplicate context keys"):
                builder.build_database(root, root / "invalid.duckdb")
            self.assertFalse((root / "invalid.duckdb").exists())

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_invalid_five_number_semantics_fail_closed(self) -> None:
        """A median/value mismatch must be rejected before publishing views."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            record = expression_record()
            record["expression_value"] = 999.0
            write_dataset_file(root, "atlas_expression_long", [record])
            write_dataset_file(root, "atlas_sample_metadata_wide", [metadata_record()])

            with self.assertRaisesRegex(ValueError, "invalid semantic rows"):
                builder.build_database(root, root / "invalid.duckdb")

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_duplicate_metadata_keys_fail_before_row_multiplication(self) -> None:
        """Ambiguous tissue rows must never multiply an expression context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_dataset_file(root, "atlas_expression_long", [expression_record()])
            write_dataset_file(
                root,
                "atlas_sample_metadata_wide",
                [metadata_record(tissue="leaf"), metadata_record(tissue="root")],
            )

            with self.assertRaisesRegex(ValueError, "duplicate join keys"):
                builder.build_database(root, root / "invalid.duckdb")

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_failed_forced_rebuild_preserves_existing_database(self) -> None:
        """Validation failure must not destroy the previously published database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            database = root / "e3_expression.duckdb"
            database.write_bytes(b"previous release")
            write_dataset_file(
                root,
                "atlas_expression_long",
                [expression_record(), expression_record()],
            )
            write_dataset_file(root, "atlas_sample_metadata_wide", [metadata_record()])

            with self.assertRaisesRegex(ValueError, "duplicate context keys"):
                builder.build_database(root, database, force=True)
            self.assertEqual(database.read_bytes(), b"previous release")

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_changed_expression_source_rejects_stale_metadata(self) -> None:
        """Tissue metadata must be checksum-bound to the expression matrix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_dataset_file(root, "atlas_expression_long", [expression_record()])
            stale = metadata_record()
            stale["expression_file_sha256"] = "d" * 64
            write_dataset_file(root, "atlas_sample_metadata_wide", [stale])

            with self.assertRaisesRegex(ValueError, "changed expression source"):
                builder.build_database(root, root / "invalid.duckdb")

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_single_value_zero_code_and_units_partition_exactly(self) -> None:
        """Documented non-summary cells should remain valid and unit-separated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            single = expression_record(group_id="g1", unit="TPM", value=0.5)
            zero = expression_record(group_id="g2", unit="FPKM", value=0.0)
            for record, summary_type in (
                (single, "single_value"),
                (zero, "atlas_zero_code"),
            ):
                record["expression_summary_type"] = summary_type
                record["expression_value_statistic"] = summary_type
                for field in (
                    "expression_minimum",
                    "expression_lower_quartile",
                    "expression_median",
                    "expression_upper_quartile",
                    "expression_maximum",
                ):
                    record[field] = None
            write_dataset_file(root, "atlas_expression_long", [single, zero])
            write_dataset_file(
                root,
                "atlas_sample_metadata_wide",
                [metadata_record(group_id="g1"), metadata_record(group_id="g2")],
            )

            result = builder.build_database(root, root / "valid.duckdb")

            self.assertEqual(result.expression_rows, 2)
            self.assertEqual(result.tpm_rows, 1)
            self.assertEqual(result.fpkm_rows, 1)
            self.assertEqual(result.selected_expression_rows, 1)
            self.assertEqual(result.expression_rows_with_metadata, 1)
            with builder.duckdb.connect(
                str(root / "valid.duckdb"),
                read_only=True,
            ) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT DISTINCT expression_unit FROM atlas_expression_selected"
                    ).fetchall(),
                    [("TPM",)],
                )

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_fpkm_is_selected_only_when_tpm_is_absent(self) -> None:
        """An FPKM-only experiment should remain available as the fallback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            record = expression_record(unit="FPKM")
            metadata = metadata_record()
            write_dataset_file(root, "atlas_expression_long", [record])
            write_dataset_file(root, "atlas_sample_metadata_wide", [metadata])

            result = builder.build_database(root, root / "fallback.duckdb")

            self.assertEqual(result.tpm_rows, 0)
            self.assertEqual(result.fpkm_rows, 1)
            self.assertEqual(result.selected_expression_rows, 1)

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_selected_context_without_metadata_fails_closed(self) -> None:
        """A missing XML/SDRF group must not become an unlabeled context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_dataset_file(root, "atlas_expression_long", [expression_record()])
            write_dataset_file(
                root,
                "atlas_sample_metadata_wide",
                [metadata_record(group_id="g2")],
            )

            with self.assertRaisesRegex(
                ValueError,
                "without configuration-backed sample metadata",
            ):
                builder.build_database(root, root / "invalid.duckdb")

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_missing_datasets_and_required_columns_fail_closed(self) -> None:
        """An empty or older-schema dataset must never publish a database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaisesRegex(ValueError, "No expression Parquet"):
                builder.build_database(root, root / "missing.duckdb")

            write_dataset_file(
                root,
                "atlas_expression_long",
                [{"gene_id": "AT1G1", "expression_value": 1.0}],
            )
            with self.assertRaisesRegex(ValueError, "missing required columns"):
                builder.build_database(root, root / "old-schema.duckdb")

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_optional_alias_and_long_metadata_views_are_published(self) -> None:
        """Optional supporting relations should remain queryable when supplied."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.make_valid_source(root)
            write_dataset_file(
                root,
                "gene_identifier_aliases",
                [{"gene_id": "AT1G1", "alias": "GENE1"}],
            )
            write_dataset_file(
                root,
                "atlas_sample_metadata_long",
                [{"sample_or_condition": "g1", "metadata_field": "organism part"}],
            )
            database = root / "valid.duckdb"

            builder.build_database(root, database)

            with builder.duckdb.connect(str(database), read_only=True) as connection:
                self.assertEqual(
                    connection.execute("SELECT alias FROM gene_identifier_aliases").fetchone()[0],
                    "GENE1",
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT metadata_field FROM atlas_sample_metadata_long"
                    ).fetchone()[0],
                    "organism part",
                )

    @unittest.skipIf(builder.duckdb is None, "duckdb is not installed")
    def test_cli_and_existing_database_guard(self) -> None:
        """The command should publish once and require force for replacement."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.make_valid_source(root)
            database = root / "expression.duckdb"

            status = builder.main(
                [
                    "--output_dir",
                    str(root),
                    "--duckdb_path",
                    str(database),
                ]
            )

            self.assertEqual(status, 0)
            with self.assertRaises(FileExistsError):
                builder.build_database(root, database)
            self.assertTrue(builder.parse_bool("yes"))
            self.assertFalse(builder.parse_bool("no"))
            with self.assertRaisesRegex(Exception, "expected true or false"):
                builder.parse_bool("maybe")


if __name__ == "__main__":
    unittest.main()
