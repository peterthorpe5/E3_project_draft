"""Tests for the candidate evidence command line and shell wrapper."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from e3parquet.candidate_evidence import BuildResult

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "scripts" / "e3_build_candidate_evidence.py"
WRAPPER_PATH = REPO_ROOT / "run_e3_candidate_evidence.sh"


def load_cli_module():
    """Load the standalone command module without requiring a package entry point."""
    specification = importlib.util.spec_from_file_location(
        "e3_build_candidate_evidence_cli",
        CLI_PATH,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Could not load CLI module: {CLI_PATH}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class TestCandidateEvidenceCli(unittest.TestCase):
    """Verify CLI parsing, output layout, status codes, and shell safeguards."""

    def setUp(self) -> None:
        """Create an isolated directory and load the command module."""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.duckdb"
        self.source.write_bytes(b"duckdb-placeholder")
        self.output = self.root / "output"
        self.cli = load_cli_module()

    def tearDown(self) -> None:
        """Remove temporary test paths."""
        self.temporary.cleanup()

    def test_parse_args_and_config_layout(self) -> None:
        """Arguments should resolve to the documented formal output paths."""
        argv = [
            str(CLI_PATH),
            "--discovery-duckdb",
            str(self.source),
            "--output-dir",
            str(self.output),
            "--overwrite",
            "--skip-source-sha256",
            "--verbose",
        ]
        with patch.object(sys, "argv", argv):
            args = self.cli.parse_args()
        config = self.cli.config_from_args(args=args)
        self.assertTrue(config.overwrite)
        self.assertFalse(config.source_sha256)
        self.assertEqual(
            config.output_tsv,
            self.output.resolve()
            / "candidate_evidence"
            / "e3_cluster_candidate_evidence.tsv",
        )
        self.assertEqual(
            config.output_parquet,
            self.output.resolve()
            / "candidate_evidence"
            / "e3_cluster_candidate_evidence.parquet",
        )
        self.assertEqual(
            config.validation_tsv,
            self.output.resolve()
            / "qc"
            / "e3_cluster_candidate_evidence_validation.tsv",
        )

    def test_main_success_prints_machine_readable_result(self) -> None:
        """A successful command should return zero and print JSON paths."""
        args = argparse.Namespace(
            discovery_duckdb=self.source,
            output_dir=self.output,
            overwrite=False,
            skip_source_sha256=True,
            verbose=False,
        )
        result = BuildResult(
            row_count=7255,
            check_count=20,
            output_duckdb=self.output / "candidate.duckdb",
            output_tsv=self.output / "candidate.tsv",
            output_parquet=self.output / "candidate.parquet",
            validation_tsv=self.output / "validation.tsv",
            manifest_json=self.output / "manifest.json",
        )
        output = io.StringIO()
        with (
            patch.object(self.cli, "parse_args", return_value=args),
            patch.object(self.cli, "configure_logging"),
            patch.object(self.cli, "build", return_value=result),
            redirect_stdout(output),
        ):
            status = self.cli.main()
        self.assertEqual(status, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["row_count"], 7255)
        self.assertEqual(payload["check_count"], 20)
        self.assertEqual(payload["output_tsv"], str(result.output_tsv))

    def test_main_failure_returns_nonzero(self) -> None:
        """A build exception should be logged and returned as status one."""
        args = argparse.Namespace(
            discovery_duckdb=self.source,
            output_dir=self.output,
            overwrite=False,
            skip_source_sha256=True,
            verbose=False,
        )
        with (
            patch.object(self.cli, "parse_args", return_value=args),
            patch.object(self.cli, "configure_logging"),
            patch.object(
                self.cli,
                "build",
                side_effect=RuntimeError("synthetic failure"),
            ),
            patch.object(self.cli.LOGGER, "exception"),
        ):
            status = self.cli.main()
        self.assertEqual(status, 1)

    def test_shell_wrapper_contains_required_batch_safeguards(self) -> None:
        """The wrapper should activate Conda explicitly and retain logs."""
        text = WRAPPER_PATH.read_text(encoding="utf-8")
        required_fragments = (
            "set -euo pipefail",
            "${BASH_SOURCE[0]}",
            "/etc/profile.d/conda.sh",
            "conda activate",
            "tee -a",
            "e3_cluster_candidate_evidence.tsv",
            "e3_cluster_candidate_evidence.parquet",
            "e3_cluster_candidate_evidence_validation.tsv",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text)
        self.assertTrue(WRAPPER_PATH.stat().st_mode & 0o100)


if __name__ == "__main__":
    unittest.main()
