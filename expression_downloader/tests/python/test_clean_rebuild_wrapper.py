#!/usr/bin/env python3
"""Integration tests for the clean-rebuild shell boundary."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SOURCE_WRAPPER = (
    Path(__file__).resolve().parents[2]
    / "inst"
    / "scripts"
    / "run_clean_rebuild_from_existing.sh"
)


class TestCleanRebuildWrapper(unittest.TestCase):
    """Prove fail-fast ordering and defensive path checks."""

    def setUp(self) -> None:
        """Create an isolated wrapper with controllable stage doubles."""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.script_dir = self.root / "scripts"
        self.script_dir.mkdir()
        self.wrapper = self.script_dir / SOURCE_WRAPPER.name
        shutil.copy2(SOURCE_WRAPPER, self.wrapper)
        self.manifest = self.root / "source.tsv"
        self.manifest.write_text("header\nrow\n", encoding="utf-8")
        self.raw_root = self.root / "raw"
        (self.raw_root / "downloads").mkdir(parents=True)
        self.output = self.root / "output"
        self.call_log = self.root / "calls.txt"

    def tearDown(self) -> None:
        """Remove all isolated stage doubles and outputs."""
        self.temporary.cleanup()

    def install_stage_double(self, name: str, *, exit_status: int = 0) -> None:
        """Install a shell stage that records its name and returns a status."""
        stage = self.script_dir / name
        stage.write_text(
            "#!/usr/bin/env bash\n"
            "set -Eeuo pipefail\n"
            f"printf '%s\\n' '{name}' >> \"${{CALL_LOG}}\"\n"
            f"exit {exit_status}\n",
            encoding="utf-8",
        )
        stage.chmod(0o755)

    def command(self) -> list[str]:
        """Return the complete named-argument wrapper command."""
        return [
            str(self.wrapper),
            "--source_manifest", str(self.manifest),
            "--raw_root", str(self.raw_root),
            "--output_dir", str(self.output),
            "--download_missing_configuration", "true",
            "--timeout_seconds", "5",
            "--retries", "0",
            "--chunk_rows", "10",
        ]

    def stage_environment(self) -> dict[str, str]:
        """Return an environment that exposes the stage call log."""
        environment = os.environ.copy()
        environment["CALL_LOG"] = str(self.call_log)
        return environment

    def test_wrapper_runs_metadata_before_expression_and_database(self) -> None:
        """A successful rebuild must follow the assurance-preserving order."""
        stages = [
            "03_prepare_existing_atlas_downloads.sh",
            "05_python_import_sample_metadata_to_parquet.sh",
            "04_python_import_expression_to_parquet.sh",
            "06_python_create_duckdb_views.sh",
        ]
        for stage in stages:
            self.install_stage_double(stage)

        result = subprocess.run(
            self.command(),
            check=False,
            capture_output=True,
            text=True,
            env=self.stage_environment(),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(self.call_log.read_text(encoding="utf-8").splitlines(), stages)
        copied = self.output / "manifests" / "source_atlas_downloaded_files.tsv"
        self.assertEqual(copied.read_text(encoding="utf-8"), self.manifest.read_text())

    def test_metadata_failure_prevents_expression_and_database(self) -> None:
        """A metadata failure must stop both expensive and publishable stages."""
        self.install_stage_double("03_prepare_existing_atlas_downloads.sh")
        self.install_stage_double(
            "05_python_import_sample_metadata_to_parquet.sh",
            exit_status=7,
        )
        self.install_stage_double("04_python_import_expression_to_parquet.sh")
        self.install_stage_double("06_python_create_duckdb_views.sh")

        result = subprocess.run(
            self.command(),
            check=False,
            capture_output=True,
            text=True,
            env=self.stage_environment(),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            self.call_log.read_text(encoding="utf-8").splitlines(),
            [
                "03_prepare_existing_atlas_downloads.sh",
                "05_python_import_sample_metadata_to_parquet.sh",
            ],
        )
        self.assertIn("configuration-backed metadata import", result.stderr)

    def test_wrapper_rejects_missing_arguments_and_existing_output(self) -> None:
        """Ambiguous or overwrite-prone invocations must fail before stages."""
        missing = subprocess.run(
            [str(self.wrapper)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIn("are required", missing.stderr)

        self.output.mkdir()
        existing = subprocess.run(
            self.command(),
            check=False,
            capture_output=True,
            text=True,
            env=self.stage_environment(),
        )
        self.assertNotEqual(existing.returncode, 0)
        self.assertIn("output already exists", existing.stderr)
        self.assertFalse(self.call_log.exists())


if __name__ == "__main__":
    unittest.main()
