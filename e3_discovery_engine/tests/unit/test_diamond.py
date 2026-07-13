import tempfile
import unittest
from pathlib import Path
from unittest import mock

from e3_discovery.diamond import (
    SemanticVersion,
    build_deepclust_command,
    build_makedb_command,
    build_realign_command,
    get_diamond_version,
    parse_semantic_version,
    require_diamond_features,
    run_external_command,
    validate_expected_outputs,
)
from e3_discovery.exceptions import ConfigurationError, ExternalToolError


class DiamondTests(unittest.TestCase):
    def test_parse_semantic_version(self):
        self.assertEqual(
            parse_semantic_version("diamond version 2.2.3"),
            SemanticVersion(2, 2, 3),
        )
        self.assertEqual(str(SemanticVersion(2, 2, 3)), "2.2.3")
        with self.assertRaises(ValueError):
            parse_semantic_version("unknown")

    @mock.patch("e3_discovery.diamond.subprocess.run")
    def test_get_diamond_version(self, mocked):
        mocked.return_value.returncode = 0
        mocked.return_value.stdout = "diamond version 2.2.3"
        mocked.return_value.stderr = ""
        self.assertEqual(get_diamond_version(), SemanticVersion(2, 2, 3))

    def test_require_diamond_features(self):
        require_diamond_features(SemanticVersion(2, 2, 3), "exact")
        with self.assertRaises(ConfigurationError):
            require_diamond_features(SemanticVersion(2, 1, 23), "exact")

    def test_build_makedb_command(self):
        command = build_makedb_command("diamond", Path("a"), Path("b"), 4)
        self.assertIn("makedb", command)
        self.assertIn("4", command)

    def test_build_deepclust_command_approximate(self):
        command = build_deepclust_command(
            "diamond", Path("db"), Path("out"), 4, "8G", "approximate", 50, 50, 0.1
        )
        self.assertIn("--approx-id", command)
        self.assertIn("--mutual-cover", command)

    def test_build_deepclust_command_exact_and_options(self):
        command = build_deepclust_command(
            "diamond",
            Path("db"),
            Path("out"),
            4,
            "8G",
            "exact",
            50,
            50,
            0.1,
            cluster_steps=["fast", "sensitive"],
            masking="seg",
            extra_args=["--no-reassign"],
        )
        self.assertIn("--id", command)
        self.assertIn("--cluster-steps", command)
        self.assertIn("seg", command)

    def test_build_realign_command_has_exact_fields(self):
        command = build_realign_command(
            "diamond", Path("db"), Path("clusters"), Path("out"), 4, "8G"
        )
        for field in ("pident", "qlen", "slen", "length", "bitscore"):
            self.assertIn(field, command)

    def test_run_external_command_success_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.txt"
            command_record = Path(tmp) / "command.json"
            run_external_command(
                ["python", "-c", "print('ok')"],
                log,
                command_record,
            )
            self.assertIn("ok", log.read_text())
            self.assertTrue(command_record.is_file())
            with self.assertRaises(ExternalToolError):
                run_external_command(
                    ["python", "-c", "raise SystemExit(3)"],
                    log,
                )

    def test_validate_expected_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out"
            path.write_text("x")
            self.assertEqual(validate_expected_outputs([path]), (path,))
            with self.assertRaises(ValueError):
                validate_expected_outputs([])


if __name__ == "__main__":
    unittest.main()
