"""Resource monitoring and case-execution tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from diamond_clust_benchmark.config import load_config
from diamond_clust_benchmark.exceptions import ExternalCommandError
from diamond_clust_benchmark.runner import (
    StageMetrics,
    _archive_existing_output,
    _log_tail,
    _resolve_scratch_root,
    combine_metrics,
    read_metrics,
    run_case,
    run_monitored_command,
    validate_runtime,
)
from tests.helpers import metric, write_config


class RunnerTests(unittest.TestCase):
    """Exercise external commands, metrics and atomic publication."""

    def setUp(self) -> None:
        """Create an isolated runtime configuration."""

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = load_config(write_config(self.root, repeats=2))

    def tearDown(self) -> None:
        """Remove runtime outputs."""

        self.temporary.cleanup()

    def test_monitored_command_success_and_failure(self) -> None:
        """Capture successful resources and include failed-command log tails."""

        success_log = self.root / "success.log"
        observed = run_monitored_command(
            [sys.executable, "-c", "import time; print('ok'); time.sleep(0.06)"],
            success_log,
            "case",
            1,
            "stage",
            0.01,
        )
        self.assertEqual(observed.exit_code, 0)
        self.assertGreater(observed.wall_seconds, 0)
        self.assertIn("ok", success_log.read_text())
        failure_log = self.root / "failure.log"
        with self.assertRaisesRegex(ExternalCommandError, "bad output"):
            run_monitored_command(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('bad output'); sys.exit(3)",
                ],
                failure_log,
                "case",
                1,
                "stage",
                0.01,
            )
        with self.assertRaises(ValueError):
            run_monitored_command([], failure_log, "case", 1, "x", 0.1)
        with self.assertRaises(ValueError):
            run_monitored_command(["x"], failure_log, "case", 0, "x", 0.1)
        with self.assertRaises(ValueError):
            run_monitored_command(["x"], failure_log, "case", 1, "x", 0)

    def test_combine_metrics_and_log_tail(self) -> None:
        """Combine sequential resources and validate identifier guards."""

        first = metric("case", 1, "one", 2.0)
        second = metric("case", 1, "two", 3.0)
        combined = combine_metrics([first, second], "case", 1, "both")
        self.assertEqual(combined.wall_seconds, 5.0)
        self.assertEqual(combined.write_bytes, 40)
        with self.assertRaises(ValueError):
            combine_metrics([], "case", 1, "none")
        with self.assertRaises(ValueError):
            combine_metrics([first], "other", 1, "bad")
        log = self.root / "tail.log"
        log.write_text("one\ntwo\nthree\n", encoding="utf-8")
        self.assertEqual(_log_tail(log, 2), "two\nthree")
        self.assertEqual(_log_tail(self.root / "absent"), "")
        with self.assertRaises(ValueError):
            _log_tail(log, 0)

    def test_scratch_and_archiving(self) -> None:
        """Resolve configured scratch and preserve incomplete outputs."""

        scratch = _resolve_scratch_root(self.config)
        self.assertTrue(scratch.is_dir())
        incomplete = self.root / "results" / "cases" / "x" / "repeat_1"
        incomplete.mkdir(parents=True)
        (incomplete / "partial").write_text("value", encoding="utf-8")
        failed = self.root / "results" / "failed"
        _archive_existing_output(incomplete, failed)
        self.assertFalse(incomplete.exists())
        self.assertEqual(len(list(failed.iterdir())), 1)
        complete = self.root / "complete"
        complete.mkdir()
        (complete / "COMPLETE").write_text("done", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            _archive_existing_output(complete, failed)
        _archive_existing_output(self.root / "absent", failed)

    def test_external_case_execution_and_runtime_preflight(self) -> None:
        """Run fake DIAMOND through every real subprocess and output contract."""

        output = self.config.output_root / "cases" / "baseline" / "repeat_1"
        with mock.patch.dict(os.environ, {"FAKE_DIAMOND_DELAY": "0.06"}):
            completed = run_case(
                self.config,
                "baseline",
                1,
                output,
                True,
            )
        self.assertEqual(completed, output)
        self.assertTrue((output / "COMPLETE").is_file())
        self.assertTrue((output / "clusters.tsv").is_file())
        metrics = read_metrics(output / "metrics.tsv")
        self.assertEqual(
            [record.stage for record in metrics],
            ["makedb", "cluster", "realign", "pairwise_pipeline", "total_pipeline"],
        )
        manifest = json.loads((output / "case_manifest.json").read_text())
        self.assertEqual(manifest["retained_clusters"], str(output / "clusters.tsv"))
        self.assertEqual(validate_runtime(self.config)["status"], "PASS")
        with self.assertRaises(FileExistsError):
            run_case(self.config, "baseline", 1, output, True)
        with self.assertRaises(ValueError):
            run_case(self.config, "baseline", 3, output, False)

    def test_failed_case_is_preserved(self) -> None:
        """Move a failed external run into the persistent failure directory."""

        output = self.config.output_root / "cases" / "baseline" / "repeat_2"
        environment = {
            "FAKE_DIAMOND_DELAY": "0.06",
            "FAKE_DIAMOND_FAIL_STAGE": "deepclust",
        }
        with mock.patch.dict(os.environ, environment):
            with self.assertRaises(ExternalCommandError):
                run_case(self.config, "baseline", 2, output, False)
        failures = list((self.config.output_root / "failed").iterdir())
        self.assertEqual(len(failures), 1)
        failure = json.loads((failures[0] / "failure.json").read_text())
        self.assertEqual(failure["error_type"], "ExternalCommandError")

    def test_read_metrics_rejects_wrong_schema(self) -> None:
        """Reject arbitrary TSVs as resource measurements."""

        path = self.root / "wrong.tsv"
        path.write_text("wrong\nvalue\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            read_metrics(path)


if __name__ == "__main__":
    unittest.main()
