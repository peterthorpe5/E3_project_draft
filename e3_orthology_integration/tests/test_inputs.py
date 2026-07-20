"""Unit tests for candidate, OrthoFinder and SQLite source readers."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from e3orthology.candidates import (
    iter_candidate_records,
    load_candidate_index,
    split_candidate_accessions,
)
from e3orthology.errors import InputValidationError
from e3orthology.orthofinder import (
    discover_results_directory,
    iter_membership_records,
    read_species_columns,
)
from e3orthology.sqlite_audit import connect_readonly, lookup_inherited_groups, table_columns
from tests.helpers import create_candidate_parquet, create_sqlite, write_text


class CandidateTests(unittest.TestCase):
    """Exercise candidate parsing, deduplication and schema validation."""

    def test_split_and_load_candidate_records(self) -> None:
        """Delimited accessions are sorted and indexed by accession."""

        self.assertEqual(
            split_candidate_accessions(value="B; A;B;;", delimiter=";"),
            ("A", "B"),
        )
        self.assertEqual(split_candidate_accessions(value=None, delimiter=";"), ())
        with self.assertRaises(ValueError):
            split_candidate_accessions(value="A", delimiter="")
        with tempfile.TemporaryDirectory() as temporary:
            path = create_candidate_parquet(Path(temporary) / "candidates.parquet")
            arguments = {
                "parquet_path": path,
                "cluster_column": "representative_id",
                "accession_column": "matched_seed_ids_calculated",
                "representative_original_id_column": "representative_original_id",
                "representative_entry_column": "representative_entry",
                "delimiter": ";",
            }
            records = list(iter_candidate_records(**arguments))
            index = load_candidate_index(**arguments)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0].representative_original_id, "rep one")
            self.assertEqual(sorted(index), ["NOPE01", "Q9SA03"])
            duplicate_path = Path(temporary) / "duplicate.parquet"
            table = pa.table(
                {
                    "representative_id": ["cluster", "cluster"],
                    "matched_seed_ids_calculated": ["Q9SA03", "Q9SA03"],
                    "representative_original_id": ["a", "a"],
                    "representative_entry": ["a", "a"],
                }
            )
            pq.write_table(table, duplicate_path)
            duplicate_arguments = {**arguments, "parquet_path": duplicate_path}
            self.assertEqual(len(list(iter_candidate_records(**duplicate_arguments))), 1)

    def test_candidate_reader_rejects_invalid_inputs(self) -> None:
        """Missing columns, empty values and invalid batches fail early."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(InputValidationError):
                discover_results_directory(source_root=root / "missing", expected_name="Results")
            base_arguments = {
                "cluster_column": "cluster",
                "accession_column": "accessions",
                "representative_original_id_column": "original",
                "representative_entry_column": "entry",
                "delimiter": ";",
            }
            missing = root / "missing.parquet"
            pq.write_table(pa.table({"cluster": ["x"]}), missing)
            with self.assertRaises(InputValidationError):
                list(iter_candidate_records(parquet_path=missing, **base_arguments))
            for name, table in (
                (
                    "empty_cluster",
                    pa.table(
                        {
                            "cluster": [""],
                            "accessions": ["A"],
                            "original": [None],
                            "entry": [None],
                        }
                    ),
                ),
                (
                    "empty_accessions",
                    pa.table(
                        {
                            "cluster": ["x"],
                            "accessions": [None],
                            "original": [None],
                            "entry": [None],
                        }
                    ),
                ),
            ):
                path = root / f"{name}.parquet"
                pq.write_table(table, path)
                with self.subTest(name=name), self.assertRaises(InputValidationError):
                    list(iter_candidate_records(parquet_path=path, **base_arguments))
            with self.assertRaises(ValueError):
                list(iter_candidate_records(parquet_path=missing, batch_size=0, **base_arguments))


class OrthoFinderTests(unittest.TestCase):
    """Exercise result discovery and both membership table structures."""

    def test_discovery_species_and_membership_parsing(self) -> None:
        """Direct and nested result paths yield parsed group memberships."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "nested" / "Results_Feb26"
            orthogroups = write_text(
                results / "Orthogroups.tsv",
                "Orthogroup\tPlant\nOG1\tsp|Q9SA03|FB27_ARATH, Q9SA04\n",
            )
            hierarchical = write_text(
                results / "N0.tsv",
                "HOG\tOG\tGene Tree Parent Clade\tPlant\nHOG1\tOG1\tn0\tQ9SA03\n",
            )
            self.assertEqual(
                discover_results_directory(source_root=root, expected_name="Results_Feb26"),
                results.resolve(),
            )
            self.assertEqual(
                discover_results_directory(
                    source_root=results,
                    expected_name="Results_Feb26",
                ),
                results.resolve(),
            )
            self.assertEqual(
                read_species_columns(table_path=orthogroups, metadata_column_count=1),
                ("Plant",),
            )
            groups = list(iter_membership_records(table_path=orthogroups, record_type="ORTHOGROUP"))
            hogs = list(
                iter_membership_records(
                    table_path=hierarchical,
                    record_type="HIERARCHICAL_ORTHOGROUP",
                )
            )
            self.assertEqual(len(groups), 2)
            self.assertEqual(groups[0].to_record()["parsed_accession"], "Q9SA03")
            self.assertEqual(hogs[0].orthogroup_id, "OG1")

    def test_orthofinder_reader_rejects_ambiguous_and_malformed_tables(self) -> None:
        """Discovery and table structural errors fail explicitly."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(InputValidationError):
                discover_results_directory(source_root=root, expected_name="Results")
            (root / "a" / "Results").mkdir(parents=True)
            (root / "b" / "Results").mkdir(parents=True)
            with self.assertRaises(InputValidationError):
                discover_results_directory(source_root=root, expected_name="Results")
            invalid = write_text(root / "invalid.tsv", "OnlyMetadata\n")
            with self.assertRaises(ValueError):
                read_species_columns(table_path=invalid, metadata_column_count=0)
            with self.assertRaises(InputValidationError):
                read_species_columns(table_path=invalid, metadata_column_count=1)
            with self.assertRaises(ValueError):
                list(iter_membership_records(table_path=invalid, record_type="bad"))
            with self.assertRaises(InputValidationError):
                list(iter_membership_records(table_path=invalid, record_type="ORTHOGROUP"))
            malformed = write_text(
                root / "malformed.tsv",
                "Orthogroup\tPlant\nOG1\tA\textra\n",
            )
            with self.assertRaises(InputValidationError):
                list(iter_membership_records(table_path=malformed, record_type="ORTHOGROUP"))
            empty_group = write_text(root / "empty_group.tsv", "Orthogroup\tPlant\n\tA\n")
            with self.assertRaises(InputValidationError):
                list(iter_membership_records(table_path=empty_group, record_type="ORTHOGROUP"))
            blank_cell = write_text(root / "blank_cell.tsv", "Orthogroup\tPlant\nOG1\t,\n")
            self.assertEqual(
                list(iter_membership_records(table_path=blank_cell, record_type="ORTHOGROUP")),
                [],
            )


class SQLiteTests(unittest.TestCase):
    """Exercise enforced read-only inherited regression queries."""

    def test_lookup_and_schema_inspection(self) -> None:
        """Expected groups are returned and the source remains unmodified."""

        with tempfile.TemporaryDirectory() as temporary:
            database = create_sqlite(Path(temporary) / "inherited.db")
            connection = connect_readonly(path=database)
            try:
                self.assertIn("accession", table_columns(connection=connection, table_name="hogs"))
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("CREATE TABLE forbidden(value TEXT)")
                with self.assertRaises(InputValidationError):
                    table_columns(connection=connection, table_name="missing")
            finally:
                connection.close()
            values = lookup_inherited_groups(path=database, accession="Q9SA03")
            self.assertEqual(values["orthogroup"], "OG0001686")
            self.assertEqual(values["hierarchical_orthogroup"], "N0.HOG0002084")
            missing = lookup_inherited_groups(path=database, accession="MISSING")
            self.assertIsNone(missing["orthogroup"])

    def test_lookup_rejects_schema_and_multiplicity(self) -> None:
        """Missing columns and multiple inherited mappings are not hidden."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bad_schema = root / "bad_schema.db"
            connection = sqlite3.connect(bad_schema)
            connection.executescript(
                "CREATE TABLE orthogroups(accession TEXT); "
                "CREATE TABLE hogs(accession TEXT, hog TEXT);"
            )
            connection.close()
            with self.assertRaises(InputValidationError):
                lookup_inherited_groups(path=bad_schema, accession="Q9SA03")
            database = create_sqlite(root / "multiple.db")
            connection = sqlite3.connect(database)
            connection.execute(
                "INSERT INTO orthogroups(accession, organism, orthogroup) VALUES (?, ?, ?)",
                ("Q9SA03", "x", "OTHER"),
            )
            connection.commit()
            connection.close()
            with self.assertRaises(InputValidationError):
                lookup_inherited_groups(path=database, accession="Q9SA03")

    def test_lookup_rejects_integrity_failure(self) -> None:
        """A non-ok SQLite integrity result blocks all regression queries."""

        class FakeConnection:
            """Minimal connection returning a failed integrity result."""

            def execute(self, statement: str):
                """Return one failed integrity result."""

                return self

            def fetchone(self) -> tuple[str]:
                """Return a non-ok result."""

                return ("corrupt",)

            def close(self) -> None:
                """Satisfy the connection cleanup contract."""

        from unittest.mock import patch

        with patch("e3orthology.sqlite_audit.connect_readonly", return_value=FakeConnection()):
            with self.assertRaises(InputValidationError):
                lookup_inherited_groups(path=Path("unused"), accession="Q9SA03")
