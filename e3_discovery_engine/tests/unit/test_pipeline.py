import unittest
from pathlib import Path

from e3_discovery.pipeline import paths_from_config, thresholds_from_config


class PipelineTests(unittest.TestCase):
    def config(self):
        return {
            "outputs": {"root": "/tmp/example"},
            "thresholds": {
                "minimum_percent_identity": 50,
                "minimum_representative_coverage": 50,
                "minimum_member_coverage": 50,
                "minimum_bitscore": 20,
                "maximum_evalue": 1e-10,
            },
        }

    def test_paths_from_config(self):
        paths = paths_from_config(self.config())
        self.assertEqual(paths.root, Path("/tmp/example"))
        self.assertTrue(str(paths.resource_duckdb).endswith(".duckdb"))

    def test_thresholds_from_config(self):
        thresholds = thresholds_from_config(self.config())
        self.assertEqual(thresholds.minimum_percent_identity, 50)


if __name__ == "__main__":
    unittest.main()
