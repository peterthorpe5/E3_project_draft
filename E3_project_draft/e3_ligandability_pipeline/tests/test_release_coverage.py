"""Release-level tests for CLI dispatch and atomic failure contracts."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from e3ligandability.cli import (
    inspect_tools_command,
    main,
    run_command,
    run_legacy_command,
)
from e3ligandability.config import DEFAULT_CONFIG, deep_merge, load_config
from e3ligandability.io_utils import (
    atomic_write_text,
    normalise_records,
    read_accession_records,
    write_parquet_records,
    write_tsv_records,
)


class CliReleaseTests(unittest.TestCase):
    """Exercise every public CLI subcommand and its exit-code contract."""

    def test_inspect_tools_disabled_writes_self_contained_json(self) -> None:
        """Inspect-tools should support a configuration with tools disabled."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            config_path.write_text(
                "external_tools:\n  run_fpocket_p2rank: false\n",
                encoding="utf-8",
            )
            output_path = root / "versions.json"
            exit_code = main(
                [
                    "inspect-tools",
                    "--config",
                    str(config_path),
                    "--output",
                    str(output_path),
                ]
            )
            self.assertEqual(exit_code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIsNone(payload["fpocket_executable"])
            self.assertIsNone(payload["p2rank_executable"])
            self.assertEqual(payload["versions"], [])
            self.assertTrue(output_path.with_suffix(".log").is_file())

    def test_inspect_tools_default_output_and_direct_function(self) -> None:
        """The inspect helper should resolve its documented default output."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            config_path.write_text(
                "external_tools:\n  run_fpocket_p2rank: false\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                output=None,
                verbose=False,
                config=config_path,
            )
            with mock.patch("pathlib.Path.cwd", return_value=root):
                self.assertEqual(inspect_tools_command(args), 0)
            self.assertTrue((root / "tool_versions.json").is_file())

    def test_run_command_returns_two_for_unsuccessful_outcome(self) -> None:
        """The run helper should return two after a validated failed run."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.txt"
            input_path.write_text("Q1\n", encoding="utf-8")
            args = argparse.Namespace(
                output_dir=root / "output",
                verbose=False,
                config=None,
                input=input_path,
                git_repository=None,
            )
            outcome = {
                "manifest_path": "manifest.json",
                "failed_accessions": ["Q1"],
                "failed_checks": [],
                "success": False,
            }
            with mock.patch(
                "e3ligandability.cli.run_pipeline",
                return_value=outcome,
            ):
                self.assertEqual(run_command(args), 2)

    def test_legacy_command_returns_two_for_nonpassing_row(self) -> None:
        """Legacy regression should propagate a non-passing status as exit two."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = argparse.Namespace(
                output_dir=root / "output",
                verbose=False,
                testing_root=root,
                metadata_csv=root / "legacy.csv",
                mean_tolerance=0.25,
                fraction_tolerance=0.01,
            )
            with mock.patch(
                "e3ligandability.cli.run_legacy_model_regression",
                return_value=[{"accession": "Q1", "status": "FAIL"}],
            ):
                self.assertEqual(run_legacy_command(args), 2)
            self.assertTrue(
                (root / "output" / "legacy_model_regression.tsv").is_file()
            )
            self.assertTrue(
                (root / "output" / "legacy_model_regression.parquet").is_file()
            )


class IoReleaseTests(unittest.TestCase):
    """Exercise uncommon but material tabular and atomic I/O branches."""

    def test_empty_yaml_and_delimiter_fallback(self) -> None:
        """Empty YAML and unrecognised text delimiters should remain usable."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_yaml = root / "empty.yaml"
            empty_yaml.write_text("", encoding="utf-8")
            self.assertEqual(load_config(empty_yaml), DEFAULT_CONFIG)

            input_path = root / "accessions.data"
            input_path.write_text("accession\nQ1\n", encoding="utf-8")
            records = read_accession_records(input_path)
            self.assertEqual(records[0]["accession"], "Q1")

    def test_explicit_tsv_fields_and_type_normalisation(self) -> None:
        """Explicit output fields and mixed scalar families should be stable."""

        fields, rows = normalise_records(
            [
                {"numeric": 1, "mixed": True, "nested": {"b": 2}},
                {"numeric": 2.5, "mixed": "yes", "nested": [1, 2]},
            ]
        )
        self.assertEqual(fields, ["mixed", "nested", "numeric"])
        self.assertEqual(rows[0]["numeric"], 1.0)
        self.assertEqual(rows[0]["mixed"], "True")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "table.tsv"
            write_tsv_records(
                output_path,
                [{"a": 1, "b": 2}],
                fieldnames=["b", "a"],
            )
            self.assertEqual(
                output_path.read_text(encoding="utf-8").splitlines()[0],
                "b\ta",
            )

    def test_atomic_and_parquet_failures_remove_temporary_files(self) -> None:
        """Atomic writers must remove incomplete siblings on publication failure."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text_path = root / "output.txt"
            with mock.patch(
                "e3ligandability.io_utils.os.fsync",
                side_effect=OSError("fsync failed"),
            ):
                with self.assertRaises(OSError):
                    atomic_write_text(text_path, "content")
            self.assertFalse(text_path.exists())
            self.assertEqual(list(root.glob(".output.txt.*.tmp")), [])

            parquet_path = root / "output.parquet"
            with mock.patch(
                "e3ligandability.io_utils.pq.write_table",
                side_effect=OSError("write failed"),
            ):
                with self.assertRaises(OSError):
                    write_parquet_records(parquet_path, [{"a": 1}])
            self.assertFalse(parquet_path.exists())
            self.assertFalse((root / ".output.parquet.tmp").exists())


if __name__ == "__main__":
    unittest.main()
