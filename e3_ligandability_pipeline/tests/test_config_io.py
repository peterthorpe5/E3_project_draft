"""Unit tests for configuration, I/O and logging helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import unittest
from pathlib import Path

import pyarrow.parquet as pq

from e3ligandability.config import (
    DEFAULT_CONFIG,
    _require_boolean,
    _require_fraction,
    _require_nonempty_string,
    _require_percentage,
    _require_positive_integer,
    _require_positive_number,
    deep_merge,
    load_config,
    validate_config,
)
from e3ligandability.io_utils import (
    _detect_delimiter,
    _normalise_cell,
    atomic_write_json,
    atomic_write_text,
    ensure_directory,
    flatten,
    normalise_records,
    read_accession_records,
    sha256_file,
    validate_accession,
    write_parquet_records,
    write_tsv_records,
)
from e3ligandability.logging_utils import configure_logging


class ConfigTests(unittest.TestCase):
    """Test configuration merging and validation."""

    def test_deep_merge_does_not_mutate_inputs(self) -> None:
        base = {"a": {"b": 1}, "c": 2}
        override = {"a": {"d": 3}}
        merged = deep_merge(base, override)
        self.assertEqual(merged, {"a": {"b": 1, "d": 3}, "c": 2})
        self.assertEqual(base, {"a": {"b": 1}, "c": 2})

    def test_load_config_defaults_and_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                "external_tools:\n  p2rank_threads: 4\n",
                encoding="utf-8",
            )
            loaded = load_config(path)
        self.assertEqual(loaded["external_tools"]["p2rank_threads"], 4)
        self.assertEqual(
            loaded["alphafold"]["api_base_url"],
            DEFAULT_CONFIG["alphafold"]["api_base_url"],
        )
        self.assertEqual(load_config(None)["project"]["run_label"], "run")

    def test_load_config_errors(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_config(Path("/not/present/config.yaml"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_numeric_validators(self) -> None:
        self.assertEqual(_require_positive_number(2, "x"), 2.0)
        self.assertEqual(_require_fraction(0.5, "x"), 0.5)
        for value in (0, -1, True, "1"):
            with self.assertRaises(ValueError):
                _require_positive_number(value, "x")
        for value in (-0.1, 1.1, True, "0.5"):
            with self.assertRaises(ValueError):
                _require_fraction(value, "x")

    def test_strict_scalar_validators(self) -> None:
        self.assertTrue(_require_boolean(True, "x"))
        self.assertEqual(_require_nonempty_string(" value ", "x"), "value")
        self.assertEqual(_require_positive_integer(2, "x"), 2)
        self.assertEqual(_require_percentage(70, "x"), 70.0)
        for value in (1, "true", None):
            with self.assertRaises(ValueError):
                _require_boolean(value, "x")
        for value in ("", "   ", 1, None):
            with self.assertRaises(ValueError):
                _require_nonempty_string(value, "x")
        for value in (0, -1, 1.5, True, "2"):
            with self.assertRaises(ValueError):
                _require_positive_integer(value, "x")
        for value in (-1, 101, True, "70"):
            with self.assertRaises(ValueError):
                _require_percentage(value, "x")

    def test_validate_config_rejects_invalid_values(self) -> None:
        config = deep_merge(DEFAULT_CONFIG, {})
        config.pop("quality")
        with self.assertRaises(ValueError):
            validate_config(config)

        cases = [
            ("input", "accession_column", ""),
            ("alphafold", "api_base_url", "ftp://example.org"),
            ("alphafold", "retry_total", -1),
            ("alphafold", "download_pae", "yes"),
            ("external_tools", "p2rank_threads", 1.5),
            ("external_tools", "p2rank_version_arguments", []),
            ("quality", "model_confident_threshold", 101),
            ("quality", "model_very_high_threshold", 60),
            ("quality", "api_fraction_tolerance", 1.5),
            ("execution", "continue_on_accession_error", 1),
            ("execution", "checksum_algorithm", "md5"),
            ("output", "write_tsv", "yes"),
        ]
        for section, key, value in cases:
            config = deep_merge(DEFAULT_CONFIG, {})
            config[section][key] = value
            with self.subTest(section=section, key=key):
                with self.assertRaises(ValueError):
                    validate_config(config)

        no_outputs = deep_merge(DEFAULT_CONFIG, {})
        no_outputs["output"] = {
            "write_tsv": False,
            "write_parquet": False,
            "write_duckdb": False,
        }
        with self.assertRaises(ValueError):
            validate_config(no_outputs)

        duckdb_without_parquet = deep_merge(DEFAULT_CONFIG, {})
        duckdb_without_parquet["output"]["write_parquet"] = False
        with self.assertRaises(ValueError):
            validate_config(duckdb_without_parquet)


class IoTests(unittest.TestCase):
    """Test atomic and tabular I/O helpers."""

    def test_directory_atomic_text_json_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = ensure_directory(Path(tmp) / "nested")
            text_path = directory / "x.txt"
            atomic_write_text(text_path, "abc")
            self.assertEqual(text_path.read_text(encoding="utf-8"), "abc")
            self.assertEqual(
                sha256_file(text_path),
                hashlib.sha256(b"abc").hexdigest(),
            )
            json_path = directory / "x.json"
            atomic_write_json(json_path, {"b": 2, "a": 1})
            self.assertEqual(json.loads(json_path.read_text()), {"a": 1, "b": 2})
            with self.assertRaises(ValueError):
                sha256_file(text_path, chunk_size=0)

    def test_validate_accession(self) -> None:
        self.assertEqual(validate_accession(" Q9ABC1 "), "Q9ABC1")
        for value in ("", "bad accession", "../escape"):
            with self.assertRaises(ValueError):
                validate_accession(value)

    def test_detect_and_read_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = root / "a.txt"
            text.write_text("# comment\nQ1\n\nQ2\n", encoding="utf-8")
            records = read_accession_records(text)
            self.assertEqual([row["accession"] for row in records], ["Q1", "Q2"])

            tsv = root / "a.tsv"
            tsv.write_text(
                "accession\tmodel_path\nQ3\t/model.cif\n",
                encoding="utf-8",
            )
            self.assertEqual(_detect_delimiter(tsv), "\t")
            self.assertEqual(read_accession_records(tsv)[0]["model_path"], "/model.cif")

            csv_path = root / "a.csv"
            csv_path.write_text("accession,model_path\nQ4,x\n", encoding="utf-8")
            self.assertEqual(_detect_delimiter(csv_path), ",")

            duplicate = root / "duplicate.txt"
            duplicate.write_text("Q1\nQ1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_accession_records(duplicate)

            missing_column = root / "bad.tsv"
            missing_column.write_text("id\nQ1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_accession_records(missing_column)

    def test_normalisation_and_table_writes(self) -> None:
        self.assertEqual(_normalise_cell(Path("x")), "x")
        self.assertEqual(_normalise_cell({"b": 2, "a": 1}), '{"a": 1, "b": 2}')
        fields, rows = normalise_records([{"b": 2}, {"a": [1, 2]}])
        self.assertEqual(fields, ["a", "b"])
        self.assertEqual(rows[1]["a"], "[1, 2]")
        self.assertEqual(flatten([[1, 2], [3]]), [1, 2, 3])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = [{"accession": "Q1", "value": 1}]
            tsv = root / "x.tsv"
            parquet = root / "x.parquet"
            write_tsv_records(tsv, records)
            write_parquet_records(parquet, records)
            self.assertIn("Q1", tsv.read_text(encoding="utf-8"))
            table = pq.read_table(parquet)
            self.assertEqual(table.num_rows, 1)

    def test_logging_writes_file_and_console_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "run.log"
            logger = configure_logging(log_path, verbose=True)
            logger.info("hello")
            for handler in logger.handlers:
                handler.flush()
            self.assertIn("hello", log_path.read_text(encoding="utf-8"))
            self.assertFalse(logger.propagate)
            self.assertGreaterEqual(len(logger.handlers), 2)
            self.assertIsInstance(logger, logging.Logger)


if __name__ == "__main__":
    unittest.main()
