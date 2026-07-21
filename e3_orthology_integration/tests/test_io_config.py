"""Unit tests for file, configuration and logging utilities."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pyarrow.parquet as pq

from e3orthology.config import (
    DEFAULT_CONFIG,
    deep_merge,
    load_config,
    resolve_project_path,
    validate_config,
)
from e3orthology.errors import ConfigurationError, InputValidationError
from e3orthology.io_utils import (
    atomic_write_json,
    atomic_write_text,
    canonical_digest,
    configure_arrow_threads,
    ensure_readable_file,
    file_record,
    link_or_copy,
    sha256_file,
    tsv_to_parquet,
    utc_now_iso,
    write_tsv,
)
from e3orthology.logging_utils import configure_logging
from tests.helpers import write_text


class FileUtilityTests(unittest.TestCase):
    """Exercise atomic writes, checksums and portable table conversion."""

    def test_time_checksum_digest_and_file_validation(self) -> None:
        """Core provenance functions return stable, validated values."""

        with tempfile.TemporaryDirectory() as temporary:
            path = write_text(Path(temporary) / "source.txt", "abc")
            self.assertIn("+00:00", utc_now_iso())
            self.assertEqual(
                sha256_file(path=path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )
            self.assertEqual(
                canonical_digest(value={"b": 2, "a": 1}), canonical_digest(value={"a": 1, "b": 2})
            )
            self.assertEqual(ensure_readable_file(path=path), path.resolve())
            self.assertEqual(file_record(path=path, include_sha256=False)["sha256"], None)
            with self.assertRaises(ValueError):
                sha256_file(path=path, chunk_size=0)
            with self.assertRaises(InputValidationError):
                ensure_readable_file(path=Path(temporary) / "missing")
            empty = Path(temporary) / "empty"
            empty.touch()
            with self.assertRaises(InputValidationError):
                ensure_readable_file(path=empty)

    def test_arrow_thread_limits_are_explicit_and_validated(self) -> None:
        """The execution thread setting configures both PyArrow thread pools."""

        with (
            patch("e3orthology.io_utils.pa.set_cpu_count") as set_cpu_count,
            patch("e3orthology.io_utils.pa.set_io_thread_count") as set_io_thread_count,
        ):
            configure_arrow_threads(threads=4)
        set_cpu_count.assert_called_once_with(4)
        set_io_thread_count.assert_called_once_with(4)
        for invalid in (True, 0, -1, 1.5):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                configure_arrow_threads(threads=invalid)  # type: ignore[arg-type]

    def test_atomic_text_json_tsv_and_parquet(self) -> None:
        """Atomic portable outputs contain the expected rows and schema."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text_path = root / "nested" / "value.txt"
            json_path = root / "value.json"
            tsv_path = root / "table.tsv"
            parquet_path = root / "table.parquet"
            atomic_write_text(path=text_path, text="hello\n")
            atomic_write_json(path=json_path, value={"b": 2, "a": 1})
            count = write_tsv(
                path=tsv_path,
                fieldnames=("name", "value"),
                records=({"name": "x", "value": None}, {"name": "y", "value": 2}),
            )
            parquet_count = tsv_to_parquet(
                tsv_path=tsv_path,
                parquet_path=parquet_path,
                block_size=64,
            )
            self.assertEqual(text_path.read_text(encoding="utf-8"), "hello\n")
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), {"a": 1, "b": 2})
            self.assertEqual(count, 2)
            self.assertEqual(parquet_count, 2)
            self.assertEqual(pq.read_table(parquet_path).num_rows, 2)
            with self.assertRaises(ValueError):
                write_tsv(path=root / "bad.tsv", fieldnames=(), records=())
            with self.assertRaises(ValueError):
                tsv_to_parquet(tsv_path=tsv_path, parquet_path=root / "bad.pq", block_size=0)

    def test_atomic_failure_cleanup_and_unreadable_guard(self) -> None:
        """Write failures remove temporary files and unreadable inputs are rejected."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "destination"
            with patch("e3orthology.io_utils.os.replace", side_effect=OSError("replace")):
                with self.assertRaises(OSError):
                    atomic_write_text(path=destination, text="payload")
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.glob("*.tmp")), [])
            source = write_text(root / "source", "payload")
            with patch("e3orthology.io_utils.os.access", return_value=False):
                with self.assertRaises(InputValidationError):
                    ensure_readable_file(path=source)
            bad_tsv = root / "bad.tsv"
            with patch(
                "e3orthology.io_utils.csv.DictWriter.writerow",
                side_effect=OSError("write"),
            ):
                with self.assertRaises(OSError):
                    write_tsv(
                        path=bad_tsv,
                        fieldnames=("expected",),
                        records=({"expected": "value"},),
                    )
            self.assertFalse(bad_tsv.exists())

    def test_link_or_copy_and_destination_protection(self) -> None:
        """Publication links or copies while refusing replacement."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_text(root / "source", "payload")
            destination = root / "destination"
            self.assertIn(
                link_or_copy(source=source, destination=destination),
                {"hard_link", "copy2"},
            )
            with self.assertRaises(FileExistsError):
                link_or_copy(source=source, destination=destination)
            copied = root / "copied"
            with patch("e3orthology.io_utils.os.link", side_effect=OSError("cross-device")):
                self.assertEqual(link_or_copy(source=source, destination=copied), "copy2")


class ConfigurationAndLoggingTests(unittest.TestCase):
    """Exercise configuration precedence, validation and handler replacement."""

    def test_deep_merge_load_and_path_resolution(self) -> None:
        """YAML overrides are recursive and do not mutate defaults."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            merged = deep_merge(base={"a": {"b": 1}}, override={"a": {"c": 2}})
            self.assertEqual(merged, {"a": {"b": 1, "c": 2}})
            config_path = write_text(
                root / "config.yaml",
                "input:\n  expected_species_count: 72\nexecution:\n  threads: 8\n",
            )
            config = load_config(path=config_path)
            self.assertEqual(config["input"]["expected_species_count"], 72)
            self.assertEqual(config["execution"]["threads"], 8)
            self.assertEqual(DEFAULT_CONFIG["input"]["expected_species_count"], 60)
            self.assertEqual(resolve_project_path(project_root=root, value="a"), root / "a")
            self.assertEqual(resolve_project_path(project_root=root, value=root / "b"), root / "b")

    def test_invalid_configs_are_rejected(self) -> None:
        """Malformed YAML and invalid scientific values fail explicitly."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ConfigurationError):
                load_config(path=root / "missing")
            with self.assertRaises(ConfigurationError):
                load_config(path=write_text(root / "list.yaml", "- item\n"))
            with self.assertRaises(ConfigurationError):
                load_config(path=write_text(root / "bad.yaml", "input: [\n"))
            self.assertEqual(
                load_config(path=write_text(root / "empty.yaml", "\n")), load_config(path=None)
            )
            invalid_values = (
                "input:\n  expected_species_count: 0\n",
                "input:\n  expected_species_count: false\n",
                "identifiers:\n  minimum_uniprot_parse_fraction: 1.2\n",
                "identifiers:\n  minimum_uniprot_parse_fraction: false\n",
                "execution:\n  parquet_block_size_bytes: 0\n",
                "execution:\n  threads: false\n",
                "output:\n  write_tsv: nope\n",
                "regression:\n  accession: ''\n",
            )
            for index, content in enumerate(invalid_values):
                with self.subTest(index=index), self.assertRaises(ConfigurationError):
                    load_config(path=write_text(root / f"invalid_{index}.yaml", content))
            with self.assertRaises(ConfigurationError):
                validate_config(config={})

    def test_logging_replaces_handlers_and_writes_file(self) -> None:
        """Repeated configuration does not duplicate log handlers."""

        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "pipeline.log"
            logger = configure_logging(log_path=log_path, verbose=True)
            logger.debug("debug message")
            self.assertEqual(logger.level, logging.DEBUG)
            self.assertEqual(len(logger.handlers), 2)
            logger = configure_logging(log_path=None, verbose=False)
            self.assertEqual(logger.level, logging.INFO)
            self.assertEqual(len(logger.handlers), 1)
            self.assertIn("debug message", log_path.read_text(encoding="utf-8"))
