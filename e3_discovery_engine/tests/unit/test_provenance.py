import tempfile
import unittest
from pathlib import Path
from unittest import mock

from e3_discovery.provenance import (
    build_file_manifest,
    capture_command_version,
    capture_software_versions,
    write_run_manifest,
)


class ProvenanceTests(unittest.TestCase):
    def test_capture_command_version(self):
        value = capture_command_version(["python", "--version"])
        self.assertIn("exit=0", value)

    @mock.patch("e3_discovery.provenance.shutil.which", return_value=None)
    def test_capture_software_versions_handles_missing(self, _mocked):
        versions = capture_software_versions({"missing": ("none", "--version")})
        self.assertIn("unavailable", versions["missing"])

    def test_build_file_manifest_existing_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "x"
            missing = Path(tmp) / "y"
            existing.write_text("abc")
            manifest = build_file_manifest([existing, missing])
            self.assertTrue(manifest[str(existing.resolve())]["exists"])
            self.assertFalse(manifest[str(missing.resolve())]["exists"])

    def test_write_run_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "x"
            source.write_text("abc")
            output = Path(tmp) / "manifest.json"
            record = write_run_manifest(output, {"a": 1}, [source])
            self.assertTrue(output.is_file())
            self.assertIn("software_versions", record)


if __name__ == "__main__":
    unittest.main()
