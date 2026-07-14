import tempfile
import unittest
from pathlib import Path

import duckdb
import yaml

from e3_discovery.clusters import cluster_tsv_to_parquet, realign_tsv_to_parquet
from e3_discovery.config import load_config
from e3_discovery.pipeline import (
    build_resource_from_config,
    paths_from_config,
    prepare_inputs_from_config,
    thresholds_from_config,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class SyntheticEndToEndTests(unittest.TestCase):
    def test_complete_python_managed_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            samples = root / "samples.tsv"
            samples.write_text(
                "sample_id\tfasta_path\tspecies\ttaxon_id\tproteome_id\n"
                f"species_a\t{FIXTURES / 'species_a.fasta'}\tA\t1\tPA\n"
                f"species_b\t{FIXTURES / 'species_b.fasta'}\tB\t2\tPB\n",
                encoding="utf-8",
            )
            config_data = {
                "project": {"name": "synthetic_e2e"},
                "inputs": {
                    "samples_tsv": str(samples),
                    "e3_seed_table": str(FIXTURES / "e3_seeds.csv"),
                    "e3_seed_column": "Entry",
                    "identifier_mode": "prefix_sample",
                    "compute_input_checksums": True,
                },
                "outputs": {"root": str(root / "results")},
                "diamond": {
                    "identity_mode": "approximate",
                    "identity_percent": 50,
                    "mutual_cover_percent": 50,
                    "clustering_evalue": 0.1,
                    "memory_limit": "8G",
                    "extra_args": [],
                },
                "thresholds": {
                    "minimum_percent_identity": 50,
                    "minimum_representative_coverage": 50,
                    "minimum_member_coverage": 50,
                    "minimum_bitscore": 20,
                    "maximum_evalue": 1e-10,
                },
                "resources": {"threads": 2, "parquet_batch_size": 1},
            }
            config_path = root / "config.yaml"
            config_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
            prepare_inputs_from_config(config_path)
            config = load_config(config_path)
            paths = paths_from_config(config)
            cluster_tsv_to_parquet(
                FIXTURES / "raw_clusters.tsv",
                paths.clusters_parquet,
                batch_size=1,
            )
            realign_tsv_to_parquet(
                FIXTURES / "realignments_diamond_2_2_3.tsv",
                paths.realignments_parquet,
                thresholds_from_config(config),
                batch_size=1,
            )
            result = build_resource_from_config(config_path)
            self.assertTrue(paths.resource_duckdb.is_file())
            self.assertEqual(result["row_counts"]["e3_seeded_clusters"], 1)
            connection = duckdb.connect(str(paths.resource_duckdb), read_only=True)
            seeds = connection.execute(
                "SELECT known_e3_seed_ids FROM e3_seeded_clusters"
            ).fetchone()[0]
            connection.close()
            self.assertEqual(seeds, "E3A1")
            self.assertTrue(
                (paths.fasta_output_dir / "e3_seeded_all_members.fasta").is_file()
            )


if __name__ == "__main__":
    unittest.main()
