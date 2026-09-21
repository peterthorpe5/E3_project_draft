"""Configuration parsing and rejection tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from diamond_clust_benchmark.config import configuration_to_dict, load_config
from diamond_clust_benchmark.exceptions import ConfigurationError
from tests.helpers import case_mapping, write_config


class ConfigurationTests(unittest.TestCase):
    """Exercise valid and unsafe configuration variants."""

    def setUp(self) -> None:
        """Create one temporary configuration workspace."""

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        """Remove the temporary workspace."""

        self.temporary.cleanup()

    def _mutate(self, callback) -> Path:
        """Create a valid YAML, mutate its mapping and rewrite it."""

        path = write_config(self.root)
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        callback(payload)
        path.write_text(yaml.safe_dump(payload), encoding="utf-8")
        return path

    def test_valid_configuration_and_serialisation(self) -> None:
        """Resolve inputs, enabled cases and JSON-compatible provenance."""

        disabled = case_mapping("disabled")
        disabled["enabled"] = False
        path = write_config(self.root, [case_mapping(), disabled])
        config = load_config(path)
        self.assertEqual(config.project_name, "test_benchmark")
        self.assertEqual(len(config.enabled_cases), 1)
        self.assertEqual(config.case_by_id("baseline").command, "deepclust")
        with self.assertRaises(ConfigurationError):
            config.case_by_id("disabled")
        payload = configuration_to_dict(config)
        self.assertEqual(payload["baseline_case_id"], "baseline")
        self.assertEqual(len(payload["cases"]), 1)

    def test_relative_executable_is_resolved_from_yaml(self) -> None:
        """Make portable test executable paths independent of working directory."""

        executable = self.root / "tool"
        executable.write_text("tool", encoding="utf-8")
        case = case_mapping()
        case["executable"] = "tool/../tool"
        config = load_config(write_config(self.root, [case]))
        self.assertEqual(config.enabled_cases[0].executable, str(executable))

    def test_missing_paths_can_be_deferred(self) -> None:
        """Allow template validation to skip existence checks explicitly."""

        path = self._mutate(
            lambda value: value["inputs"].update({"fasta": "missing.fasta"})
        )
        config = load_config(path, check_paths=False)
        self.assertEqual(config.input_fasta.name, "missing.fasta")
        with self.assertRaises(ConfigurationError):
            load_config(path)

    def test_top_level_and_case_validation(self) -> None:
        """Reject malformed roots, duplicate cases and disabled baselines."""

        bad_yaml = self.root / "bad.yaml"
        bad_yaml.write_text("[not: valid", encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            load_config(bad_yaml)
        not_mapping = self.root / "list.yaml"
        not_mapping.write_text("- value\n", encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            load_config(not_mapping)
        duplicate = write_config(
            self.root,
            [case_mapping("same"), case_mapping("same")],
        )
        with self.assertRaises(ConfigurationError):
            load_config(duplicate)
        path = self._mutate(
            lambda value: value["benchmark"]["cases"][0].update(
                {"enabled": False}
            )
        )
        with self.assertRaises(ConfigurationError):
            load_config(path)

    def test_numeric_and_identifier_validation(self) -> None:
        """Reject unsafe identifiers and invalid resource/decision values."""

        mutations = [
            lambda value: value["project"].update({"name": "bad name"}),
            lambda value: value["resources"].update({"threads": 0}),
            lambda value: value["resources"].update(
                {"diamond_memory_limit": "lots"}
            ),
            lambda value: value["resources"].update(
                {"sampling_interval_seconds": 0}
            ),
            lambda value: value["benchmark"].update({"quality_repeat": 3}),
            lambda value: value["benchmark"].update({"decision_stage": "bad"}),
            lambda value: value["benchmark"].update(
                {"minimum_pairwise_f1": 1.1}
            ),
            lambda value: value["benchmark"].update(
                {"minimum_speedup_percent": -1}
            ),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                directory = self.root / str(index)
                directory.mkdir()
                path = write_config(directory)
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                mutation(payload)
                path.write_text(yaml.safe_dump(payload), encoding="utf-8")
                with self.assertRaises(ConfigurationError):
                    load_config(path)

    def test_case_option_validation(self) -> None:
        """Reject unsupported DIAMOND case settings and reserved overrides."""

        changes = [
            {"case_id": "bad name"},
            {"command": "blastp"},
            {"identity_mode": "guess"},
            {"expected_version": "latest"},
            {"comp_based_stats": 7},
            {"comp_based_stats": 2},
            {"masking": "soft"},
            {"extra_args": ["--threads"]},
            {"extra_args": ["--threads=8"]},
            {"extra_args": ["--masking"]},
            {"extra_args": "--fast"},
            {"cluster_steps": ["bad step"]},
            {"executable": ""},
            {"evalue": 0},
            {"evalue": "not_numeric"},
            {"identity_percent": 101},
            {"identity_percent": ".nan"},
            {"run_realign": "false"},
        ]
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                directory = self.root / f"case_{index}"
                directory.mkdir()
                case = case_mapping()
                case.update(change)
                path = write_config(directory, [case])
                with self.assertRaises((ConfigurationError, ValueError)):
                    load_config(path)


if __name__ == "__main__":
    unittest.main()
