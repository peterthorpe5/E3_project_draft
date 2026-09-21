"""Named command-line interface tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diamond_clust_benchmark.cli import build_parser, main
from tests.helpers import write_config


class CliTests(unittest.TestCase):
    """Exercise each non-report CLI operation with named arguments."""

    def setUp(self) -> None:
        """Create a one-repeat fake-DIAMOND configuration."""

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = write_config(self.root, repeats=1)

    def tearDown(self) -> None:
        """Remove CLI outputs."""

        self.temporary.cleanup()

    def test_parser_and_validation_commands(self) -> None:
        """Build the parser and emit configuration/runtime JSON."""

        self.assertEqual(build_parser().prog, "diamond-clust-benchmark")
        validated = self.root / "validated.json"
        self.assertEqual(
            main(
                [
                    "--verbose",
                    "validate-config",
                    "--config",
                    str(self.config),
                    "--output",
                    str(validated),
                ]
            ),
            0,
        )
        self.assertEqual(
            json.loads(validated.read_text())["project_name"],
            "test_benchmark",
        )
        runtime = self.root / "runtime.json"
        self.assertEqual(
            main(
                [
                    "validate-runtime",
                    "--config",
                    str(self.config),
                    "--output",
                    str(runtime),
                ]
            ),
            0,
        )
        self.assertEqual(json.loads(runtime.read_text())["status"], "PASS")

    def test_profile_and_run_case_commands(self) -> None:
        """Profile the fixture and execute one retained external case."""

        profile = self.root / "profile.tsv"
        self.assertEqual(
            main(
                [
                    "profile-input",
                    "--config",
                    str(self.config),
                    "--output",
                    str(profile),
                ]
            ),
            0,
        )
        self.assertIn("\t4\t52", profile.read_text())
        output = self.root / "case"
        with mock.patch.dict(os.environ, {"FAKE_DIAMOND_DELAY": "0.06"}):
            status = main(
                [
                    "run-case",
                    "--config",
                    str(self.config),
                    "--case-id",
                    "baseline",
                    "--repeat",
                    "1",
                    "--output-directory",
                    str(output),
                    "--retain-clusters",
                ]
            )
        self.assertEqual(status, 0)
        self.assertTrue((output / "COMPLETE").is_file())


if __name__ == "__main__":
    unittest.main()
