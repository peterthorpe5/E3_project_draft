"""Static safety and completeness contracts for the Snakemake workflow."""

from pathlib import Path
import unittest


class SnakefileContractTests(unittest.TestCase):
    """Protect workflow-level behaviours not exercised without Snakemake."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[2]
        cls.text = (cls.root / "Snakefile").read_text(encoding="utf-8")

    def test_expected_rules_are_present(self) -> None:
        for rule in (
            "prepare_inputs",
            "make_diamond_database",
            "run_deepclust",
            "realign_clusters",
            "convert_cluster_membership",
            "convert_realignments",
            "build_resource",
            "aggregate_benchmarks",
            "write_provenance",
        ):
            self.assertIn(f"rule {rule}:", self.text)

    def test_unsafe_legacy_commands_are_absent(self) -> None:
        self.assertNotIn("gunzip ", self.text)
        self.assertNotIn(">>", self.text)
        self.assertNotIn("/home/ubuntu", self.text)

    def test_configuration_and_nonempty_contracts_are_present(self) -> None:
        self.assertIn("E3_DISCOVERY_CONFIG", self.text)
        self.assertIn("ensure(", self.text)
        self.assertIn("non_empty=True", self.text)
        self.assertIn("BENCHMARK_REPEATS", self.text)

    def test_rule_logs_and_benchmarks_are_retained(self) -> None:
        self.assertGreaterEqual(self.text.count("log:"), 9)
        self.assertGreaterEqual(self.text.count("benchmark:"), 6)


if __name__ == "__main__":
    unittest.main()
