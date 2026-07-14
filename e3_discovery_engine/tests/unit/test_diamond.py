import tempfile
import unittest
from pathlib import Path
from unittest import mock

from e3_discovery.diamond import (
    SemanticVersion,
    build_deepclust_command,
    build_makedb_command,
    build_realign_command,
    diamond_error_hint,
    get_diamond_version,
    parse_semantic_version,
    read_log_tail,
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
        self.assertEqual(
            command[command.index("--comp-based-stats") + 1], "0"
        )
        self.assertIn("--db", command)
        self.assertNotIn("--database", command)
        self.assertNotIn("--header", command)

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
            comp_based_stats=1,
            extra_args=["--no-reassign"],
        )
        self.assertIn("--id", command)
        self.assertIn("--cluster-steps", command)
        self.assertIn("seg", command)
        self.assertEqual(
            command[command.index("--comp-based-stats") + 1], "1"
        )
        self.assertIn("--db", command)
        self.assertNotIn("--database", command)

    def test_build_realign_command_has_exact_fields(self):
        command = build_realign_command(
            "diamond",
            Path("db"),
            Path("clusters"),
            Path("out"),
            4,
            "8G",
            masking="seg",
        )
        for field in ("pident", "qlen", "slen", "length", "bitscore"):
            self.assertIn(field, command)
        self.assertIn("--db", command)
        self.assertEqual(
            command[command.index("--comp-based-stats") + 1], "0"
        )
        self.assertNotIn("--database", command)
        self.assertEqual(
            command[command.index("--header") + 1],
            "simple",
        )
        self.assertEqual(
            command[command.index("--masking") + 1],
            "seg",
        )

    def test_exact_traceback_rejects_adjusted_matrix_modes(self):
        with self.assertRaisesRegex(ValueError, "adjusted matrix modes"):
            build_deepclust_command(
                "diamond",
                Path("db"),
                Path("out"),
                1,
                "4G",
                "exact",
                50,
                50,
                0.1,
                comp_based_stats=6,
            )
        with self.assertRaisesRegex(ValueError, "adjusted matrix modes"):
            build_realign_command(
                "diamond",
                Path("db"),
                Path("clusters"),
                Path("out"),
                1,
                "4G",
                comp_based_stats=6,
            )

    def test_diamond_error_hint(self):
        self.assertIn(
            "comp_based_stats",
            diamond_error_hint(
                "Error: Traceback with adjusted matrix not supported"
            ),
        )
        self.assertEqual(diamond_error_hint("other error"), "")

    def test_build_deepclust_command_rejects_invalid_masking(self):
        with self.assertRaisesRegex(ValueError, "masking must be one of"):
            build_deepclust_command(
                "diamond",
                Path("db"),
                Path("out"),
                1,
                "4G",
                "exact",
                50,
                50,
                0.1,
                masking="0",
            )
        with self.assertRaisesRegex(ValueError, "masking must be one of"):
            build_realign_command(
                "diamond",
                Path("db"),
                Path("clusters"),
                Path("out"),
                1,
                "4G",
                masking="0",
            )

    def test_build_deepclust_command_rejects_invalid_identity_mode(self):
        with self.assertRaisesRegex(ValueError, "identity_mode must be"):
            build_deepclust_command(
                "diamond",
                Path("db"),
                Path("out"),
                1,
                "4G",
                "unsupported",
                50,
                50,
                0.1,
            )

    def test_read_log_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.txt"
            log.write_text("one\ntwo\nthree\n", encoding="utf-8")
            self.assertEqual(read_log_tail(log, max_lines=2), "two\nthree")
            self.assertEqual(read_log_tail(Path(tmp) / "missing"), "")
            with self.assertRaises(ValueError):
                read_log_tail(log, max_lines=0)

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
            with self.assertRaises(ExternalToolError) as context:
                run_external_command(
                    [
                        "python",
                        "-c",
                        "print('diagnostic'); raise SystemExit(3)",
                    ],
                    log,
                )
            self.assertIn("diagnostic", str(context.exception))

    def test_validate_expected_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out"
            path.write_text("x")
            self.assertEqual(validate_expected_outputs([path]), (path,))
            with self.assertRaises(ValueError):
                validate_expected_outputs([])


if __name__ == "__main__":
    unittest.main()
