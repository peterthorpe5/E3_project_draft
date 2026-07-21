"""Unit and integration tests for the named-option CLI."""

from __future__ import annotations

import argparse
import runpy
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from e3orthology.cli import (
    apply_cli_config,
    build_parser,
    bundled_species_manifest,
    main,
    positive_integer,
    runtime_from_args,
)
from e3orthology.config import load_config
from tests.helpers import create_fixture


class CommandLineTests(unittest.TestCase):
    """Exercise argument parsing, overrides, path resolution and exit codes."""

    def test_positive_integer_and_bundled_manifest(self) -> None:
        """Custom argument and bundled-data resolvers validate their results."""

        self.assertEqual(positive_integer("4"), 4)
        self.assertTrue(bundled_species_manifest().is_file())
        for value in ("0", "-1", "nope"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                positive_integer(value)

    def test_parser_and_configuration_overrides(self) -> None:
        """Every future-run scientific override is retained in configuration."""

        parser = build_parser()
        args = parser.parse_args(
            [
                "--results-directory-name",
                "Results_Aug01",
                "--expected-species-count",
                "72",
                "--regression-accession",
                "ACCESSION",
                "--expected-raw-identifier",
                "raw-accession",
                "--expected-orthogroup",
                "OG1",
                "--expected-hierarchical-orthogroup",
                "HOG1",
                "--skip-sqlite-regression",
                "--threads",
                "8",
                "--force-stage",
                "01_build_identifier_map",
            ]
        )
        config = apply_cli_config(config=load_config(path=None), args=args)
        self.assertEqual(config["input"]["results_directory_name"], "Results_Aug01")
        self.assertEqual(config["input"]["expected_species_count"], 72)
        self.assertFalse(config["input"]["require_sqlite_regression"])
        self.assertEqual(config["regression"]["accession"], "ACCESSION")
        self.assertEqual(config["regression"]["expected_raw_identifier"], "raw-accession")
        self.assertEqual(config["execution"]["threads"], 8)

    def test_module_entry_point_returns_main_exit_code(self) -> None:
        """The module entry point propagates the CLI return code."""

        with patch("e3orthology.cli.main", return_value=7), self.assertRaises(SystemExit) as raised:
            runpy.run_module("e3orthology", run_name="__main__")
        self.assertEqual(raised.exception.code, 7)

    def test_runtime_path_resolution(self) -> None:
        """Direct results and data-root-relative paths resolve correctly."""

        with tempfile.TemporaryDirectory() as temporary:
            fixture_paths, config = create_fixture(Path(temporary))
            parser = build_parser()
            args = parser.parse_args(
                [
                    "--project-root",
                    temporary,
                    "--data-dir",
                    temporary,
                    "--orthofinder-results-dir",
                    str(fixture_paths.results_directory),
                    "--candidate-evidence",
                    str(fixture_paths.candidate_evidence),
                    "--sqlite-database",
                    str(fixture_paths.sqlite_database),
                    "--species-manifest",
                    str(fixture_paths.species_manifest),
                    "--output-root",
                    "new_output",
                    "--run-name",
                    "new_run",
                ]
            )
            paths = runtime_from_args(args=args, config=config)
            self.assertEqual(paths.results_directory, fixture_paths.results_directory)
            self.assertEqual(paths.output_root, Path(temporary).resolve() / "new_output")
            self.assertEqual(paths.run_name, "new_run")

    def test_print_run_root_exits_without_running_pipeline(self) -> None:
        """The shell-wrapper resolver prints one absolute path without starting stages."""

        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = create_fixture(Path(temporary))
            arguments = [
                "--project-root",
                temporary,
                "--orthofinder-results-dir",
                str(paths.results_directory),
                "--candidate-evidence",
                str(paths.candidate_evidence),
                "--sqlite-database",
                str(paths.sqlite_database),
                "--species-manifest",
                str(paths.species_manifest),
                "--output-root",
                str(paths.output_root),
                "--run-name",
                paths.run_name,
                "--print-run-root",
            ]
            standard_output = StringIO()
            with (
                patch("e3orthology.cli.run_pipeline") as run_pipeline,
                redirect_stdout(standard_output),
            ):
                exit_code = main(arguments)
            self.assertEqual(exit_code, 0)
            self.assertEqual(standard_output.getvalue().strip(), str(paths.run_root))
            run_pipeline.assert_not_called()

    def test_main_end_to_end_expected_and_unexpected_exit_codes(self) -> None:
        """CLI success, expected input failure and unexpected defect codes differ."""

        with tempfile.TemporaryDirectory() as temporary:
            paths, config = create_fixture(Path(temporary))
            config_path = Path(temporary) / "config.yaml"
            config_path.write_text(
                "input:\n  expected_species_count: 2\n"
                "execution:\n  parquet_block_size_bytes: 1024\n",
                encoding="utf-8",
            )
            arguments = [
                "--project-root",
                temporary,
                "--orthofinder-results-dir",
                str(paths.results_directory),
                "--candidate-evidence",
                str(paths.candidate_evidence),
                "--sqlite-database",
                str(paths.sqlite_database),
                "--species-manifest",
                str(paths.species_manifest),
                "--output-root",
                str(paths.output_root),
                "--run-name",
                "cli_run",
                "--config",
                str(config_path),
                "--stop-after",
                "00_preflight",
            ]
            self.assertEqual(main(arguments), 0)
            self.assertEqual(main([*arguments, "--run-name", "bad/name"]), 2)
            with patch("e3orthology.cli.run_pipeline", side_effect=ValueError("defect")):
                self.assertEqual(main([*arguments, "--run-name", "unexpected"]), 1)
