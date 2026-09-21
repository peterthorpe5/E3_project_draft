"""DIAMOND command construction tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from diamond_clust_benchmark.commands import (
    build_cluster_command,
    build_makedb_command,
    build_realign_command,
    command_as_text,
    command_prefix,
    get_version,
    parse_version,
)
from diamond_clust_benchmark.config import load_config
from diamond_clust_benchmark.exceptions import ExternalCommandError
from tests.helpers import write_config


class CommandTests(unittest.TestCase):
    """Verify exact shell-free argument vectors and version guards."""

    def setUp(self) -> None:
        """Load a direct fake-DIAMOND case."""

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.case = load_config(write_config(self.root)).enabled_cases[0]

    def tearDown(self) -> None:
        """Remove test files."""

        self.temporary.cleanup()

    def test_version_parsing_and_direct_resolution(self) -> None:
        """Parse a semantic version and call an external executable."""

        self.assertEqual(parse_version("diamond version 2.2.8"), (2, 2, 8))
        with self.assertRaises(ValueError):
            parse_version("unknown")
        self.assertEqual(command_prefix(self.case), [self.case.executable])
        self.assertEqual(get_version(self.case), "2.2.3")

    def test_conda_prefix_and_version_failures(self) -> None:
        """Construct Conda invocation and reject failed or wrong versions."""

        conda = replace(self.case, conda_environment="candidate")
        self.assertEqual(
            command_prefix(conda)[:5],
            ["conda", "run", "--no-capture-output", "--name", "candidate"],
        )
        with mock.patch.dict(os.environ, {"FAKE_DIAMOND_VERSION": "2.2.4"}):
            with self.assertRaises(ExternalCommandError):
                get_version(self.case)
        with mock.patch.dict(os.environ, {"FAKE_DIAMOND_FAIL_STAGE": "version"}):
            with self.assertRaises(ExternalCommandError):
                get_version(self.case)
        old = replace(self.case, expected_version="2.2.0")
        with mock.patch.dict(os.environ, {"FAKE_DIAMOND_VERSION": "2.2.0"}):
            with self.assertRaises(ExternalCommandError):
                get_version(old)

    def test_makedb_cluster_and_realign_commands(self) -> None:
        """Include managed thresholds, paths, cascade and optional switches."""

        source = self.root / "input fasta.faa"
        database = self.root / "db"
        output = self.root / "clusters.tsv"
        temporary = self.root / "tmp"
        makedb = build_makedb_command(self.case, source, database, 2)
        self.assertEqual(
            makedb[-6:],
            ["--in", str(source), "--db", str(database), "--threads", "2"],
        )
        rich = replace(
            self.case,
            identity_mode="approximate",
            cluster_steps=("faster_lin", "fast"),
            no_reassign=True,
            extra_args=("--single-step",),
        )
        cluster = build_cluster_command(
            rich,
            database,
            output,
            2,
            "2G",
            temporary,
        )
        self.assertIn("--approx-id", cluster)
        self.assertIn("--cluster-steps", cluster)
        self.assertIn("--no-reassign", cluster)
        self.assertEqual(cluster[-1], "--single-step")
        realign = build_realign_command(
            self.case,
            database,
            output,
            self.root / "realign.tsv",
            2,
            "2G",
            temporary,
        )
        self.assertIn("realign", realign)
        self.assertIn("bitscore", realign)
        self.assertIn("--masking", realign)
        self.assertIn("input fasta.faa'", command_as_text(makedb))

    def test_command_builders_reject_zero_threads(self) -> None:
        """Reject non-positive worker counts in every builder."""

        with self.assertRaises(ValueError):
            build_makedb_command(self.case, Path("in"), Path("db"), 0)
        with self.assertRaises(ValueError):
            build_cluster_command(
                self.case,
                Path("db"),
                Path("out"),
                0,
                "2G",
                Path("tmp"),
            )
        with self.assertRaises(ValueError):
            build_realign_command(
                self.case,
                Path("db"),
                Path("clusters"),
                Path("out"),
                0,
                "2G",
                Path("tmp"),
            )


if __name__ == "__main__":
    unittest.main()
