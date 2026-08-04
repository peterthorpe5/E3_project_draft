"""Raw-file-to-DuckDB known-answer assurance for Expression Atlas evidence."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[2] / "inst" / "python"


def load_script(module_name: str, filename: str):
    """Load one command module directly from the repository source tree."""
    specification = importlib.util.spec_from_file_location(
        module_name,
        SCRIPT_ROOT / filename,
    )
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    assert specification.loader is not None
    specification.loader.exec_module(module)
    return module


expression = load_script(
    "assurance_import_expression",
    "import_expression_to_parquet.py",
)
metadata = load_script(
    "assurance_import_metadata",
    "import_sample_metadata_to_parquet.py",
)
database_builder = load_script(
    "assurance_build_expression_database",
    "build_expression_duckdb.py",
)


class ExpressionRawToDatabaseAssuranceTests(unittest.TestCase):
    """Prove raw Atlas encodings and tissues survive every processing layer."""

    @unittest.skipIf(
        expression.pa is None or metadata.pa is None or database_builder.duckdb is None,
        "pyarrow and duckdb are required",
    )
    def test_raw_matrix_xml_and_sdrf_produce_exact_context_rows(self) -> None:
        """Five-number medians, boundary values and XML tissues must remain exact."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            matrix = raw / "E-TEST-1-tpms.tsv"
            sdrf = raw / "E-TEST-1.condensed-sdrf.tsv"
            configuration = raw / "E-TEST-1-configuration.xml"
            matrix.write_text(
                "Gene ID\tGene Name\tg1\tg2\n"
                "AT1G1\tGENE1\t3,3,3,4,5\t0,0,0.5,0.5,1\n"
                "AT1G2\tGENE2\t-\t1,2,3,4,5\n",
                encoding="utf-8",
            )
            sdrf.write_text(
                "E-TEST-1\t\tSRR1\tcharacteristic\torganism\tArabidopsis thaliana\n"
                "E-TEST-1\t\tSRR1\tcharacteristic\torganism part\tleaf\n"
                "E-TEST-1\t\tSRR1\tfactor\ttreatment\tcontrol\n"
                "E-TEST-1\t\tSRR2\tcharacteristic\torganism\tArabidopsis thaliana\n"
                "E-TEST-1\t\tSRR2\tcharacteristic\torganism part\troot\n"
                "E-TEST-1\t\tSRR2\tfactor\ttreatment\tcompound\n",
                encoding="utf-8",
            )
            configuration.write_text(
                "<configuration><analytics><assay_groups>"
                '<assay_group id="g1" label="leaf control">'
                "<assay>SRR1</assay></assay_group>"
                '<assay_group id="g2" label="root compound">'
                "<assay>SRR2</assay></assay_group>"
                "</assay_groups></analytics></configuration>",
                encoding="utf-8",
            )
            output = root / "output"
            expression_path = (
                output
                / "parquet"
                / "atlas_expression_long"
                / "species_column=Arabidopsis_thaliana"
                / "experiment_accession=E-TEST-1"
                / "tpms.parquet"
            )
            expression_job = expression.MatrixJob(
                expression_tsv=matrix,
                output_parquet=expression_path,
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
                expression_unit="TPM",
                file_type="tpms",
            )

            expression_result = expression.normalise_matrix_to_parquet(
                expression_job,
                force=True,
                chunk_rows=2,
            )
            metadata_result = metadata.write_partitioned_metadata(
                metadata.MetadataJob(
                    metadata_tsv=sdrf,
                    experiment_accession="E-TEST-1",
                    species_column="Arabidopsis_thaliana",
                    expression_tsv=matrix,
                    configuration_xml=configuration,
                ),
                output,
                force=True,
            )
            database = output / "expression.duckdb"
            build_result = database_builder.build_database(output, database)

            self.assertTrue(expression_result.success)
            self.assertEqual(expression_result.imported_rows, 4)
            self.assertTrue(metadata_result.success)
            self.assertEqual(metadata_result.mapped_group_records, 2)
            self.assertEqual(build_result.expression_rows, 4)
            self.assertEqual(build_result.expression_rows_with_metadata, 4)
            with database_builder.duckdb.connect(
                str(database),
                read_only=True,
            ) as connection:
                rows = connection.execute(
                    "SELECT gene_id, sample_or_condition, expression_value, "
                    "expression_summary_type, organism_part, atlas_group_label, "
                    "source_file_sha256 = metadata_expression_file_sha256 "
                    "AS provenance_matches "
                    "FROM atlas_expression_with_sample_metadata "
                    "ORDER BY gene_id, sample_or_condition"
                ).fetchall()
            self.assertEqual(
                rows,
                [
                    (
                        "AT1G1",
                        "g1",
                        3.0,
                        "atlas_five_number_summary",
                        "leaf",
                        "leaf control",
                        True,
                    ),
                    (
                        "AT1G1",
                        "g2",
                        0.5,
                        "atlas_five_number_summary",
                        "root",
                        "root compound",
                        True,
                    ),
                    (
                        "AT1G2",
                        "g1",
                        0.0,
                        "atlas_zero_code",
                        "leaf",
                        "leaf control",
                        True,
                    ),
                    (
                        "AT1G2",
                        "g2",
                        3.0,
                        "atlas_five_number_summary",
                        "root",
                        "root compound",
                        True,
                    ),
                ],
            )


if __name__ == "__main__":
    unittest.main()
