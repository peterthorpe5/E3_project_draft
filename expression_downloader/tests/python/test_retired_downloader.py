"""Regression test for the unsafe legacy download entry point."""

from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "inst" / "python" / "download_atlas_files.py"
SPEC = importlib.util.spec_from_file_location("download_atlas_files", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RetiredDownloaderTests(unittest.TestCase):
    """Ensure the under-specified legacy acquisition route stays disabled."""

    def test_legacy_manifest_downloader_fails_closed(self) -> None:
        """The old R-manifest route must never silently run."""
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = MODULE.main(["--legacy-argument"])
        message = stderr.getvalue()
        self.assertEqual(status, 2)
        self.assertIn("is retired", message)
        self.assertIn("configuration-XML", message)
        self.assertIn("run_python_first_then_r.sh", message)


if __name__ == "__main__":
    unittest.main()
