"""Repository-level documentation and packaging contracts."""

from pathlib import Path
import unittest


class RepositoryContractTests(unittest.TestCase):
    """Ensure production artefacts are present and non-empty."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[2]

    def test_required_documentation_exists(self) -> None:
        required = (
            "README.md",
            "CHANGELOG.md",
            "docs/METHODS.md",
            "docs/SCIENTIFIC_INTERPRETATION.md",
            "docs/DATA_DICTIONARY.md",
            "docs/BENCHMARK_PROTOCOL.md",
            "docs/DATA_SOURCES.md",
            "docs/OPERATIONS_RUNBOOK.md",
            "docs/LEGACY_METHOD_LIMITATIONS.md",
            "docs/RELEASE_CHECKLIST.md",
            "docs/TESTING.md",
            "docs/EXAMPLE_QUERIES.sql",
            "docs/PACKAGE_FILE_REGISTER.md",
            "docs/LEGACY_AUDIT_EVIDENCE_REGISTER.md",
            "docs/CODE_DOCUMENTATION_STANDARD.md",
            "docs/SLURM_FULL_ONEKP_RUNBOOK.md",
        )
        for relative in required:
            path = self.root / relative
            with self.subTest(path=relative):
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 100)

    def test_example_configurations_are_separate(self) -> None:
        production = self.root / "config/config.example.production.yaml"
        legacy = self.root / "config/config.example.legacy_reproduction.yaml"
        self.assertTrue(production.is_file())
        self.assertTrue(legacy.is_file())
        self.assertNotEqual(
            production.read_text(encoding="utf-8"),
            legacy.read_text(encoding="utf-8"),
        )

    def test_production_config_uses_symmetric_masking(self) -> None:
        production = self.root / "config/config.example.production.yaml"
        text = production.read_text(encoding="utf-8")
        self.assertIn("masking: tantan", text)
        self.assertNotIn("masking: seg\n", text)

    def test_slurm_cluster_examples_exist(self) -> None:
        """Require cluster configuration examples and operating scripts."""

        required = (
            "config/config.cluster.full_onekp.example.yaml",
            "config/full_onekp_cluster.example.samples.tsv",
            "scripts/submit_full_onekp_slurm.sh",
            "scripts/slurm_full_onekp_job.sh",
            "scripts/check_full_onekp_slurm.sh",
        )
        for relative in required:
            path = self.root / relative
            with self.subTest(path=relative):
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 100)

    def test_legacy_code_is_labelled_reference_only(self) -> None:
        readme = self.root / "legacy_reference/README.md"
        text = readme.read_text(encoding="utf-8").lower()
        self.assertIn("reference", text)
        self.assertIn("not", text)


if __name__ == "__main__":
    unittest.main()
