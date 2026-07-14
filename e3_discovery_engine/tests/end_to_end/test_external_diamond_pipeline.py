import os
import shutil
import tempfile
import unittest
from pathlib import Path

from e3_discovery.clusters import (
    Thresholds,
    cluster_tsv_to_parquet,
    realign_tsv_to_parquet,
)
from e3_discovery.diamond import (
    SemanticVersion,
    build_deepclust_command,
    build_makedb_command,
    build_realign_command,
    get_diamond_version,
    run_external_command,
    validate_expected_outputs,
)
from e3_discovery.fasta import prepare_combined_fasta
from e3_discovery.manifest import SampleRecord
from e3_discovery.resource import build_duckdb_resource
from e3_discovery.seeds import prepare_seed_table


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RUN_EXTERNAL = os.environ.get("RUN_DIAMOND_E2E") == "1"
DIAMOND = shutil.which("diamond")
PERSISTENT_OUTPUT = os.environ.get("E3_DIAMOND_E2E_DIR")


@unittest.skipUnless(
    RUN_EXTERNAL and DIAMOND,
    "Set RUN_DIAMOND_E2E=1 in an environment containing DIAMOND",
)
class ExternalDiamondPipelineTests(unittest.TestCase):
    def test_complete_small_diamond_pipeline(self):
        if PERSISTENT_OUTPUT:
            root = Path(PERSISTENT_OUTPUT).expanduser().resolve()
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True)
            self._run_pipeline(root)
            return

        with tempfile.TemporaryDirectory() as tmp:
            self._run_pipeline(Path(tmp))

    def _run_pipeline(self, root: Path) -> None:
        combined = root / "combined.fasta"
        sequences = root / "sequences.parquet"
        prepare_combined_fasta(
            [
                SampleRecord("species_a", FIXTURES / "species_a.fasta", "A"),
                SampleRecord("species_b", FIXTURES / "species_b.fasta", "B"),
            ],
            combined,
            sequences,
            root / "sample_summary.tsv",
            batch_size=1,
        )
        seeds = root / "seeds.parquet"
        prepare_seed_table(
            FIXTURES / "e3_seeds.csv",
            root / "seeds.tsv",
            seeds,
        )

        database = root / "combined.dmnd"
        clusters = root / "clusters.tsv"
        realignments = root / "realignments.tsv"
        version = get_diamond_version(str(DIAMOND))
        identity_mode = (
            "exact"
            if version >= SemanticVersion(2, 2, 1)
            else "approximate"
        )
        commands = [
            (
                build_makedb_command(
                    str(DIAMOND), combined, database, threads=1
                ),
                root / "makedb.log",
                (database,),
            ),
            (
                build_deepclust_command(
                    executable=str(DIAMOND),
                    database=database,
                    output_tsv=clusters,
                    threads=1,
                    memory_limit="4G",
                    identity_mode=identity_mode,
                    identity_percent=20,
                    mutual_cover_percent=20,
                    clustering_evalue=10,
                    comp_based_stats=0,
                    masking="none",
                ),
                root / "deepclust.log",
                (clusters,),
            ),
            (
                build_realign_command(
                    str(DIAMOND),
                    database,
                    clusters,
                    realignments,
                    threads=1,
                    memory_limit="4G",
                    comp_based_stats=0,
                    masking="none",
                ),
                root / "realign.log",
                (realignments,),
            ),
        ]
        for command, log_path, outputs in commands:
            run_external_command(
                command,
                log_path,
                command_record_path=log_path.with_suffix(".command.json"),
            )
            validate_expected_outputs(outputs)

        cluster_parquet = root / "clusters.parquet"
        realign_parquet = root / "realignments.parquet"
        thresholds = Thresholds(20, 20, 20, 1, 10)
        cluster_tsv_to_parquet(clusters, cluster_parquet, batch_size=1)
        realign_tsv_to_parquet(
            realignments,
            realign_parquet,
            thresholds,
            batch_size=1,
        )
        result = build_duckdb_resource(
            root / "resource.duckdb",
            sequences,
            seeds,
            cluster_parquet,
            realign_parquet,
            thresholds,
            root / "curated",
            root / "fastas",
            root / "validation.tsv",
            metadata={"external_test": True},
            duckdb_threads=1,
        )
        self.assertGreaterEqual(
            result["row_counts"]["e3_seeded_clusters"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
