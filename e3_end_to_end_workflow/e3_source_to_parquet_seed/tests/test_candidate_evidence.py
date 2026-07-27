"""Tests for the E3 cluster candidate evidence integration layer."""

from __future__ import annotations

import builtins
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

from e3parquet.candidate_evidence import (
    METADATA_TABLE,
    SOURCE_CATALOG,
    TABLE_NAME,
    VALIDATION_TABLE,
    BuildConfig,
    BuildResult,
    CandidateEvidenceError,
    Check,
    SchemaError,
    ValidationError,
    breadth_cte,
    build,
    check_records,
    cleanup,
    create_evidence_table,
    equality_check,
    evidence_sql,
    export_outputs,
    group_count_expression,
    identifier,
    manifest_record,
    publish,
    quote_literal,
    relation_columns,
    result_dict,
    scalar,
    sql_values,
    store_internal_tables,
    table_columns,
    temporary_path,
    validate_evidence,
    validate_exported_outputs,
    validate_paths,
    validate_schema,
    write_json_temp,
)


def create_source_database(*, path: Path) -> None:
    """Create a compact, internally consistent discovery DuckDB."""
    connection = duckdb.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE e3_seeded_cluster_summary (
                representative_id VARCHAR,
                known_e3_sequence_count BIGINT,
                known_e3_seed_count BIGINT,
                known_e3_seed_ids VARCHAR,
                raw_member_count BIGINT,
                strict_member_count BIGINT,
                sample_count BIGINT,
                species_count BIGINT,
                minimum_observed_pident DOUBLE,
                median_observed_pident DOUBLE,
                maximum_observed_pident DOUBLE,
                minimum_member_coverage DOUBLE,
                median_member_coverage DOUBLE,
                maximum_member_coverage DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO e3_seeded_cluster_summary VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "onekp_dataset@@rep1",
                    1,
                    1,
                    "S1",
                    3,
                    2,
                    3,
                    3,
                    40.0,
                    70.0,
                    100.0,
                    20.0,
                    80.0,
                    100.0,
                ),
                (
                    "Arabidopsis_thaliana@@rep2",
                    1,
                    1,
                    "S2",
                    2,
                    1,
                    1,
                    1,
                    45.0,
                    60.0,
                    100.0,
                    30.0,
                    70.0,
                    100.0,
                ),
            ],
        )
        connection.execute(
            """
            CREATE TABLE sequence_records (
                internal_id VARCHAR,
                source_file_sample_id VARCHAR,
                source_file_species VARCHAR,
                sample_id VARCHAR,
                species VARCHAR,
                taxon_id VARCHAR,
                proteome_id VARCHAR,
                onekp_sample_code VARCHAR,
                original_id VARCHAR,
                entry VARCHAR,
                sequence_length BIGINT,
                sequence_md5 VARCHAR,
                source_path VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO sequence_records VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "onekp_dataset@@rep1",
                    "onekp_dataset",
                    "1KP combined dataset",
                    "AAAA",
                    "Plant one",
                    "",
                    "",
                    "AAAA",
                    "rep1",
                    "S1",
                    100,
                    "md5-1",
                    "/onekp.fasta",
                ),
                (
                    "Zea_mays@@member1",
                    "Zea_mays",
                    "Zea mays",
                    "Zea_mays",
                    "Zea mays",
                    "4577",
                    "",
                    "",
                    "member1",
                    "",
                    110,
                    "md5-2",
                    "/maize.fasta",
                ),
                (
                    "onekp_dataset@@member2",
                    "onekp_dataset",
                    "1KP combined dataset",
                    "BBBB",
                    "Plant two",
                    "",
                    "",
                    "BBBB",
                    "member2",
                    "",
                    120,
                    "md5-3",
                    "/onekp.fasta",
                ),
                (
                    "Arabidopsis_thaliana@@rep2",
                    "Arabidopsis_thaliana",
                    "Arabidopsis thaliana",
                    "Arabidopsis_thaliana",
                    "Arabidopsis thaliana",
                    "3702",
                    "",
                    "",
                    "rep2",
                    "",
                    130,
                    "md5-4",
                    "/arabidopsis.fasta",
                ),
                (
                    "Arabidopsis_thaliana@@seed2",
                    "Arabidopsis_thaliana",
                    "Arabidopsis thaliana",
                    "Arabidopsis_thaliana",
                    "Arabidopsis thaliana",
                    "3702",
                    "",
                    "",
                    "seed2",
                    "S2",
                    140,
                    "md5-5",
                    "/arabidopsis.fasta",
                ),
            ],
        )
        membership_columns = """
            representative_id VARCHAR,
            member_id VARCHAR,
            source_file_sample_id VARCHAR,
            sample_id VARCHAR,
            species VARCHAR
        """
        connection.execute(
            f"CREATE TABLE e3_seeded_cluster_members ({membership_columns})"
        )
        connection.execute(
            f"CREATE TABLE strict_e3_seeded_cluster_members "
            f"({membership_columns})"
        )
        raw_rows = [
            (
                "onekp_dataset@@rep1",
                "onekp_dataset@@rep1",
                "onekp_dataset",
                "AAAA",
                "Plant one",
            ),
            (
                "onekp_dataset@@rep1",
                "Zea_mays@@member1",
                "Zea_mays",
                "Zea_mays",
                "Zea mays",
            ),
            (
                "onekp_dataset@@rep1",
                "onekp_dataset@@member2",
                "onekp_dataset",
                "BBBB",
                "Plant two",
            ),
            (
                "Arabidopsis_thaliana@@rep2",
                "Arabidopsis_thaliana@@rep2",
                "Arabidopsis_thaliana",
                "Arabidopsis_thaliana",
                "Arabidopsis thaliana",
            ),
            (
                "Arabidopsis_thaliana@@rep2",
                "Arabidopsis_thaliana@@seed2",
                "Arabidopsis_thaliana",
                "Arabidopsis_thaliana",
                "Arabidopsis thaliana",
            ),
        ]
        connection.executemany(
            "INSERT INTO e3_seeded_cluster_members VALUES (?, ?, ?, ?, ?)",
            raw_rows,
        )
        connection.executemany(
            "INSERT INTO strict_e3_seeded_cluster_members "
            "VALUES (?, ?, ?, ?, ?)",
            [raw_rows[0], raw_rows[1], raw_rows[3]],
        )
        connection.execute(
            """
            CREATE TABLE all_matched_e3_seed_sequences (
                internal_id VARCHAR,
                seed_id VARCHAR,
                representative_id VARCHAR,
                passes_strict_thresholds BOOLEAN
            )
            """
        )
        connection.executemany(
            "INSERT INTO all_matched_e3_seed_sequences VALUES (?, ?, ?, ?)",
            [
                ("onekp_dataset@@rep1", "S1", "onekp_dataset@@rep1", True),
                (
                    "Arabidopsis_thaliana@@seed2",
                    "S2",
                    "Arabidopsis_thaliana@@rep2",
                    False,
                ),
            ],
        )
        connection.execute(
            "CREATE TABLE known_e3_seeds "
            "(seed_id VARCHAR, seed_metadata_json VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO known_e3_seeds VALUES (?, ?)",
            [
                (
                    "S1",
                    json.dumps(
                        {
                            "category": "Ring finger",
                            "reviewed": "reviewed",
                            "ubiquitin_go_term": "Ubiquitin GO term",
                            "exclusion_go_term": "",
                            "organism": "Plant one",
                            "protein_names": "Seed one",
                        }
                    ),
                ),
                (
                    "S2",
                    json.dumps(
                        {
                            "category": "BTB",
                            "reviewed": "unreviewed",
                            "ubiquitin_go_term": "Non-Ubiquitin GO term",
                            "exclusion_go_term": "GO:EXCLUDE",
                            "organism": "Arabidopsis thaliana",
                            "protein_names": "Seed two",
                        }
                    ),
                ),
            ],
        )
        connection.execute(
            "CREATE TABLE strict_matched_e3_seed_sequences "
            "(internal_id VARCHAR, representative_id VARCHAR)"
        )
        connection.execute(
            "INSERT INTO strict_matched_e3_seed_sequences VALUES "
            "('onekp_dataset@@rep1', 'onekp_dataset@@rep1')"
        )
        connection.execute(
            "CREATE TABLE non_strict_matched_e3_seed_sequences "
            "(internal_id VARCHAR, representative_id VARCHAR)"
        )
        connection.execute(
            "INSERT INTO non_strict_matched_e3_seed_sequences VALUES "
            "('Arabidopsis_thaliana@@seed2', "
            "'Arabidopsis_thaliana@@rep2')"
        )
        connection.execute(
            "CREATE TABLE strict_nonseed_candidate_members "
            "(representative_id VARCHAR, member_id VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO strict_nonseed_candidate_members VALUES (?, ?)",
            [
                ("onekp_dataset@@rep1", "Zea_mays@@member1"),
                (
                    "Arabidopsis_thaliana@@rep2",
                    "Arabidopsis_thaliana@@rep2",
                ),
            ],
        )
    finally:
        connection.close()


class CandidateTestCase(unittest.TestCase):
    """Base test case with a synthetic production-like DuckDB."""

    def setUp(self) -> None:
        """Create isolated source and output paths."""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.duckdb"
        create_source_database(path=self.source)
        self.output = self.root / "output"

    def tearDown(self) -> None:
        """Remove all temporary test files."""
        self.temporary.cleanup()

    def config(self, *, overwrite: bool = False) -> BuildConfig:
        """Return a standard test build configuration."""
        return BuildConfig(
            discovery_duckdb=self.source,
            output_duckdb=self.output / "candidate.duckdb",
            output_tsv=self.output / "candidate.tsv",
            output_parquet=self.output / "candidate.parquet",
            validation_tsv=self.output / "validation.tsv",
            manifest_json=self.output / "manifest.json",
            log_path=self.output / "build.log",
            overwrite=overwrite,
            source_sha256=True,
        )

    def attached(self) -> duckdb.DuckDBPyConnection:
        """Return a connection with the source attached read-only."""
        connection = duckdb.connect()
        connection.execute(
            f"ATTACH {quote_literal(value=str(self.source))} "
            f"AS {identifier(value=SOURCE_CATALOG)} (READ_ONLY)"
        )
        return connection


class TestSqlAndSchema(CandidateTestCase):
    """Tests for controlled SQL and source schema contracts."""

    def test_quote_literal_and_identifier(self) -> None:
        """SQL quoting should escape values and reject unsafe identifiers."""
        self.assertEqual(quote_literal(value="Pete's"), "'Pete''s'")
        self.assertEqual(identifier(value="table_1"), '"table_1"')
        for value in ("", "1table", "bad-name"):
            with self.assertRaises(ValueError):
                identifier(value=value)

    def test_sql_values_and_named_group(self) -> None:
        """SQL list and group helpers should reject unsupported inputs."""
        self.assertEqual(sql_values(values=("a", "b")), "'a', 'b'")
        with self.assertRaises(ValueError):
            sql_values(values=())
        self.assertIn(
            "Zea_mays",
            group_count_expression(group_name="cereal"),
        )
        with self.assertRaises(ValueError):
            group_count_expression(group_name="unknown")

    def test_breadth_and_evidence_sql_include_core_sources(self) -> None:
        """Generated SQL should include breadth, seed and member layers."""
        self.assertIn(
            "e3_seeded_cluster_members",
            breadth_cte(
                table_name="e3_seeded_cluster_members",
                cte_name="raw_breadth",
            ),
        )
        sql = evidence_sql()
        self.assertIn("seed_annotation", sql)
        self.assertIn("strict_nonseed_candidate_members", sql)

    def test_table_columns_and_schema_validation(self) -> None:
        """The complete synthetic schema should pass validation."""
        connection = self.attached()
        try:
            columns = table_columns(
                connection=connection,
                catalog=SOURCE_CATALOG,
                table_name="known_e3_seeds",
            )
            validate_schema(connection=connection)
        finally:
            connection.close()
        self.assertIn("seed_metadata_json", columns)

    def test_schema_validation_reports_missing_table_and_column(self) -> None:
        """Missing source objects should produce explicit schema errors."""
        connection = duckdb.connect()
        try:
            connection.execute("ATTACH ':memory:' AS discovery")
            with self.assertRaises(SchemaError):
                validate_schema(connection=connection)
        finally:
            connection.close()

        writable = duckdb.connect(str(self.source))
        try:
            writable.execute("ALTER TABLE known_e3_seeds DROP seed_metadata_json")
        finally:
            writable.close()
        attached = self.attached()
        try:
            with self.assertRaises(SchemaError):
                validate_schema(connection=attached)
        finally:
            attached.close()


class TestEvidenceAndValidation(CandidateTestCase):
    """Tests for table creation and scientific accounting checks."""

    def test_create_evidence_table_contains_expected_cluster_values(self) -> None:
        """The table should contain one row per cluster and correct breadth."""
        connection = self.attached()
        try:
            count = create_evidence_table(connection=connection)
            row = connection.execute(
                f"SELECT strict_nonseed_candidate_count, "
                "strict_named_cereal_proteome_count, seed_categories "
                f"FROM {identifier(value=TABLE_NAME)} WHERE "
                "representative_id = 'onekp_dataset@@rep1'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(count, 2)
        self.assertEqual(row, (1, 1, "Ring finger"))

    def test_scalar_and_equality_check(self) -> None:
        """Scalar and equality helpers should reject null and mark status."""
        connection = duckdb.connect()
        try:
            self.assertEqual(scalar(connection=connection, sql="SELECT 3"), 3)
            with self.assertRaises(ValidationError):
                scalar(connection=connection, sql="SELECT NULL")
        finally:
            connection.close()
        self.assertTrue(
            equality_check(
                name="x",
                observed=1,
                expected=1,
                details="ok",
            ).passed
        )

    def test_validate_evidence_passes_and_detects_corruption(self) -> None:
        """Consistent data should pass; changed counts should fail."""
        connection = self.attached()
        try:
            create_evidence_table(connection=connection)
            checks = validate_evidence(connection=connection)
            connection.execute(
                f"UPDATE {identifier(value=TABLE_NAME)} SET strict_member_count = 99 "
                "WHERE representative_id = 'onekp_dataset@@rep1'"
            )
            with self.assertRaises(ValidationError):
                validate_evidence(connection=connection)
        finally:
            connection.close()
        self.assertTrue(all(check.passed for check in checks))

    def test_check_records_use_explicit_status(self) -> None:
        """Validation exports should use explicit PASS and FAIL labels."""
        records = check_records(
            checks=(
                Check("a", True, "1", "1", "ok"),
                Check("b", False, "0", "1", "bad"),
            )
        )
        self.assertEqual(records[0]["status"], "PASS")
        self.assertEqual(records[1]["status"], "FAIL")


class TestOutputsAndBuild(CandidateTestCase):
    """Tests for atomic outputs, provenance and complete builds."""

    def test_temporary_write_publish_cleanup_helpers(self) -> None:
        """Staging helpers should write, publish and clean safely."""
        formal = self.root / "manifest.json"
        staged = write_json_temp(value={"a": 1}, formal_path=formal)
        self.assertNotEqual(staged, formal)
        publish(staged=staged, formal=formal)
        self.assertEqual(json.loads(formal.read_text()), {"a": 1})
        with self.assertRaises(CandidateEvidenceError):
            publish(staged=self.root / "missing", formal=formal)

        file_path = self.root / "temporary"
        directory = self.root / "directory"
        file_path.write_text("x", encoding="utf-8")
        directory.mkdir()
        cleanup(paths=(file_path, directory, self.root / "absent"))
        self.assertFalse(file_path.exists())
        self.assertFalse(directory.exists())
        self.assertNotEqual(
            temporary_path(formal_path=formal),
            temporary_path(formal_path=formal),
        )

    def test_validate_paths_rejects_missing_existing_and_aliases(self) -> None:
        """Path validation should protect source and existing outputs."""
        config = self.config()
        missing = BuildConfig(
            **{**config.__dict__, "discovery_duckdb": self.root / "missing"}
        )
        with self.assertRaises(FileNotFoundError):
            validate_paths(config=missing)
        source_alias = BuildConfig(
            **{**config.__dict__, "output_duckdb": self.source}
        )
        with self.assertRaises(CandidateEvidenceError):
            validate_paths(config=source_alias)
        duplicate = BuildConfig(
            **{**config.__dict__, "output_parquet": config.output_tsv}
        )
        with self.assertRaises(CandidateEvidenceError):
            validate_paths(config=duplicate)
        config.output_tsv.parent.mkdir(parents=True)
        config.output_tsv.write_text("existing", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            validate_paths(config=config)
        validate_paths(config=self.config(overwrite=True))

    def test_relation_and_export_validation_failure_branches(self) -> None:
        """Unresolvable relations, empty files and altered schemas should fail."""
        cursor = MagicMock()
        cursor.description = None
        connection_mock = MagicMock()
        connection_mock.execute.return_value = cursor
        with self.assertRaises(ValidationError):
            relation_columns(
                connection=connection_mock,
                relation_sql="synthetic_relation",
            )

        connection = self.attached()
        try:
            row_count = create_evidence_table(connection=connection)
            empty_tsv = self.root / "empty.tsv"
            empty_parquet = self.root / "empty.parquet"
            empty_tsv.touch()
            empty_parquet.touch()
            with self.assertRaises(ValidationError):
                validate_exported_outputs(
                    connection=connection,
                    tsv_path=empty_tsv,
                    parquet_path=empty_parquet,
                    expected_row_count=row_count,
                )

            tsv = self.root / "candidate.tsv"
            parquet = self.root / "candidate.parquet"
            staged_tsv, staged_parquet = export_outputs(
                connection=connection,
                tsv_path=tsv,
                parquet_path=parquet,
            )
            staged_tsv.write_text("wrong_column\nvalue\n", encoding="utf-8")
            with self.assertRaises(ValidationError):
                validate_exported_outputs(
                    connection=connection,
                    tsv_path=staged_tsv,
                    parquet_path=staged_parquet,
                    expected_row_count=row_count,
                )
        finally:
            connection.close()

    def test_cleanup_logs_operating_system_errors(self) -> None:
        """Cleanup should log and continue when a staged path cannot be removed."""
        staged = self.root / "staged.tsv"
        staged.write_text("value\n", encoding="utf-8")
        with (
            patch.object(Path, "unlink", side_effect=OSError("locked")),
            patch("e3parquet.candidate_evidence.LOGGER.exception") as log_mock,
        ):
            cleanup(paths=[staged])
        log_mock.assert_called_once()

    def test_export_validation_checks_rows_schema_and_missing_files(self) -> None:
        """Staged exports should match table rows and schema exactly."""
        connection = self.attached()
        try:
            row_count = create_evidence_table(connection=connection)
            tsv = self.root / "candidate.tsv"
            parquet = self.root / "candidate.parquet"
            staged_tsv, staged_parquet = export_outputs(
                connection=connection,
                tsv_path=tsv,
                parquet_path=parquet,
            )
            checks = validate_exported_outputs(
                connection=connection,
                tsv_path=staged_tsv,
                parquet_path=staged_parquet,
                expected_row_count=row_count,
            )
            self.assertEqual(len(checks), 4)
            self.assertTrue(all(check.passed for check in checks))
            self.assertEqual(
                relation_columns(
                    connection=connection,
                    relation_sql=identifier(value=TABLE_NAME),
                ),
                relation_columns(
                    connection=connection,
                    relation_sql=(
                        "read_parquet("
                        f"{quote_literal(value=str(staged_parquet))})"
                    ),
                ),
            )
            staged_tsv.unlink()
            with self.assertRaises(ValidationError):
                validate_exported_outputs(
                    connection=connection,
                    tsv_path=staged_tsv,
                    parquet_path=staged_parquet,
                    expected_row_count=row_count,
                )
        finally:
            connection.close()

    def test_export_manifest_and_internal_tables(self) -> None:
        """Exports and embedded metadata should be readable."""
        connection = self.attached()
        try:
            create_evidence_table(connection=connection)
            checks = validate_evidence(connection=connection)
            temp_tsv, temp_parquet = export_outputs(
                connection=connection,
                tsv_path=self.root / "out.tsv",
                parquet_path=self.root / "out.parquet",
            )
            manifest = manifest_record(
                config=self.config(),
                row_count=2,
                checks=checks,
                started_at="2026-07-16T00:00:00+00:00",
                finished_at="2026-07-16T00:01:00+00:00",
                source_hash="abc",
            )
            store_internal_tables(
                connection=connection,
                checks=checks,
                manifest=manifest,
            )
            parquet_count = connection.execute(
                "SELECT COUNT(*) FROM read_parquet(?)",
                [str(temp_parquet)],
            ).fetchone()[0]
            validation_count = connection.execute(
                f"SELECT COUNT(*) FROM {identifier(value=VALIDATION_TABLE)}"
            ).fetchone()[0]
            metadata = connection.execute(
                f"SELECT metadata_json FROM {identifier(value=METADATA_TABLE)}"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertTrue(temp_tsv.is_file())
        self.assertEqual(parquet_count, 2)
        self.assertEqual(validation_count, len(checks))
        self.assertEqual(json.loads(metadata)["candidate_row_count"], 2)

    def test_complete_build_and_overwrite_contract(self) -> None:
        """A complete build should publish validated formal outputs."""
        config = self.config()
        result = build(config=config)
        self.assertEqual(result.row_count, 2)
        for path in (
            config.output_duckdb,
            config.output_tsv,
            config.output_parquet,
            config.validation_tsv,
            config.manifest_json,
        ):
            self.assertTrue(path.is_file())
        with self.assertRaises(FileExistsError):
            build(config=config)
        self.assertEqual(build(config=self.config(overwrite=True)).row_count, 2)

    def test_failed_build_cleans_staged_files(self) -> None:
        """Malformed source JSON should not leave formal or staged outputs."""
        connection = duckdb.connect(str(self.source))
        try:
            connection.execute(
                "UPDATE known_e3_seeds SET seed_metadata_json = '{bad' "
                "WHERE seed_id = 'S1'"
            )
        finally:
            connection.close()
        with (
            self.assertRaises(Exception),
            patch("e3parquet.candidate_evidence.LOGGER.exception"),
        ):
            build(config=self.config())
        self.assertFalse(self.config().output_duckdb.exists())
        self.assertEqual(list(self.output.rglob("*.tmp.*")), [])

    def test_missing_duckdb_dependency_has_clear_error(self) -> None:
        """A missing DuckDB dependency should raise a package-level error."""
        original_import = builtins.__import__

        def guarded(name: str, *args: object, **kwargs: object) -> object:
            """Reject only the local DuckDB import under test."""
            if name == "duckdb":
                raise ImportError("missing")
            return original_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=guarded),
            self.assertRaises(CandidateEvidenceError),
        ):
            build(config=self.config())

    def test_result_dict_serialises_paths(self) -> None:
        """Result reporting should convert pathlib paths to strings."""
        result = BuildResult(
            row_count=2,
            check_count=1,
            output_duckdb=self.root / "a.duckdb",
            output_tsv=self.root / "a.tsv",
            output_parquet=self.root / "a.parquet",
            validation_tsv=self.root / "validation.tsv",
            manifest_json=self.root / "manifest.json",
        )
        self.assertIsInstance(result_dict(result=result)["output_tsv"], str)


if __name__ == "__main__":
    unittest.main()
