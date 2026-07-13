import tempfile
import unittest
from pathlib import Path

from e3_discovery.config import load_config, load_yaml, resolve_paths, validate_config
from e3_discovery.exceptions import ConfigurationError


def valid_config():
    return {
        "project": {"name": "test"},
        "inputs": {
            "samples_tsv": "samples.tsv",
            "e3_seed_table": "seeds.csv",
            "identifier_mode": "prefix_sample",
        },
        "outputs": {"root": "results"},
        "diamond": {
            "identity_mode": "approximate",
            "identity_percent": 50,
            "mutual_cover_percent": 50,
            "clustering_evalue": 0.1,
            "memory_limit": "8G",
            "comp_based_stats": 1,
            "extra_args": [],
        },
        "thresholds": {
            "minimum_percent_identity": 50,
            "minimum_representative_coverage": 50,
            "minimum_member_coverage": 50,
            "minimum_bitscore": 20,
            "maximum_evalue": 1e-10,
        },
        "resources": {"threads": 2, "parquet_batch_size": 100},
    }


class ConfigTests(unittest.TestCase):
    def test_validate_config_accepts_valid(self):
        validate_config(valid_config())

    def test_validate_config_rejects_missing_section(self):
        config = valid_config()
        del config["diamond"]
        with self.assertRaises(ConfigurationError):
            validate_config(config)

    def test_validate_config_rejects_bad_identity_mode(self):
        config = valid_config()
        config["diamond"]["identity_mode"] = "wrong"
        with self.assertRaises(ConfigurationError):
            validate_config(config)

    def test_validate_config_rejects_adjusted_matrix_with_exact_identity(self):
        config = valid_config()
        config["diamond"]["identity_mode"] = "exact"
        config["diamond"]["comp_based_stats"] = 6
        with self.assertRaisesRegex(ConfigurationError, "must be 0 or 1"):
            validate_config(config)

    def test_validate_config_rejects_invalid_comp_based_stats(self):
        config = valid_config()
        config["diamond"]["comp_based_stats"] = 7
        with self.assertRaisesRegex(ConfigurationError, "integer from 0 to 6"):
            validate_config(config)

    def test_validate_config_rejects_bad_threads(self):
        config = valid_config()
        config["resources"]["threads"] = 0
        with self.assertRaises(ConfigurationError):
            validate_config(config)

    def test_validate_config_rejects_bad_identifier_mode(self):
        config = valid_config()
        config["inputs"]["identifier_mode"] = "bad"
        with self.assertRaises(ConfigurationError):
            validate_config(config)

    def test_validate_config_rejects_bad_clustering_evalue(self):
        config = valid_config()
        config["diamond"]["clustering_evalue"] = 0
        with self.assertRaises(ConfigurationError):
            validate_config(config)

    def test_validate_config_rejects_bad_benchmark_repeats(self):
        config = valid_config()
        config["benchmarking"] = {"repeats": 0}
        with self.assertRaises(ConfigurationError):
            validate_config(config)

    def test_validate_config_rejects_non_list_cluster_steps(self):
        config = valid_config()
        config["diamond"]["cluster_steps"] = "fast"
        with self.assertRaises(ConfigurationError):
            validate_config(config)

    def test_load_yaml_requires_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("- a\n- b\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_yaml(path)

    def test_resolve_paths_relative_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            resolved = resolve_paths(valid_config(), config_path)
            self.assertEqual(
                resolved["outputs"]["root"], str((Path(tmp) / "results").resolve())
            )

    def test_load_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            import yaml

            path.write_text(yaml.safe_dump(valid_config()), encoding="utf-8")
            loaded = load_config(path)
            self.assertEqual(loaded["project"]["name"], "test")


if __name__ == "__main__":
    unittest.main()
