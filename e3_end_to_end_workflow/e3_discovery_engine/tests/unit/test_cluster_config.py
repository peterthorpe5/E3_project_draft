"""Tests for full 1KP+ cluster manifest and configuration generation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from e3_discovery.cluster_config import (
    build_full_onekp_cluster_config,
    build_full_onekp_manifest_rows,
    create_full_onekp_cluster_files,
    full_onekp_discovery_root,
    locate_inherited_samples_json,
    read_first_fasta_header,
    read_inherited_sample_names,
    uniprot_header_metadata,
    validate_full_onekp_source_inputs,
    write_cluster_config,
    write_full_onekp_manifest,
)
from e3_discovery.exceptions import DataValidationError


class ClusterConfigTests(unittest.TestCase):
    """Validate deterministic Slurm input generation."""

    def test_read_inherited_sample_names(self) -> None:
        """Read a unique ordered sample list and reject malformed JSON."""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "samples.json"
            path.write_text(
                json.dumps({"Samples": ["A", "onekp_dataset"]}),
                encoding="utf-8",
            )
            self.assertEqual(
                read_inherited_sample_names(path),
                ["A", "onekp_dataset"],
            )
            path.write_text(json.dumps({"Samples": ["A", "A"]}))
            with self.assertRaises(DataValidationError):
                read_inherited_sample_names(path)

    def test_missing_and_malformed_inputs_are_rejected(self) -> None:
        """Exercise defensive errors before expensive cluster preparation."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.json"
            with self.assertRaises(FileNotFoundError):
                read_inherited_sample_names(missing)

            samples = root / "samples.json"
            for payload in ({}, {"Samples": []}, {"Samples": ["A", " "]}):
                samples.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(DataValidationError):
                    read_inherited_sample_names(samples)

            with self.assertRaises(FileNotFoundError):
                read_first_fasta_header(root / "missing.fasta")
            with self.assertRaises(FileNotFoundError):
                build_full_onekp_manifest_rows(["Missing"], root)
            with self.assertRaises(FileNotFoundError):
                create_full_onekp_cluster_files(
                    source_root=root / "source",
                    repository_root=root / "repo",
                    results_root=root / "results",
                    output_dir=root / "generated",
                    threads=1,
                    memory_limit="1G",
                    tmpdir=root / "scratch",
                )

    def test_read_first_fasta_header(self) -> None:
        """Read the first header and reject headerless files."""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.fasta"
            path.write_text("\n>abc description\nMKT\n", encoding="utf-8")
            self.assertEqual(read_first_fasta_header(path), "abc description")
            path.write_text("MKT\n", encoding="utf-8")
            with self.assertRaises(DataValidationError):
                read_first_fasta_header(path)

    def test_uniprot_header_metadata(self) -> None:
        """Extract OS and OX fields with a fallback sample label."""

        metadata = uniprot_header_metadata(
            "Arabidopsis_thaliana",
            "tr|A|A OS=Arabidopsis thaliana OX=3702 GN=X",
        )
        self.assertEqual(metadata["species"], "Arabidopsis thaliana")
        self.assertEqual(metadata["taxon_id"], "3702")
        fallback = uniprot_header_metadata("Sample_name", "plain")
        self.assertEqual(fallback["species"], "Sample name")

    def test_build_full_onekp_manifest_rows(self) -> None:
        """Assign strict 1KP parsing only to the combined FASTA."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Named.fasta").write_text(
                ">tr|P1|P1 OS=Named species OX=123\nMKT\n",
                encoding="utf-8",
            )
            (root / "onekp_dataset.fasta").write_text(
                ">scaffold-AALA-1-Meliosma_cuneifolia\nMKT\n",
                encoding="utf-8",
            )
            rows = build_full_onekp_manifest_rows(
                ["Named", "onekp_dataset"],
                root,
            )
        self.assertEqual(rows[0]["header_parser"], "manifest")
        self.assertEqual(rows[1]["header_parser"], "onekp_scaffold")
        self.assertEqual(rows[1]["header_parser_strict"], "true")
        self.assertEqual(rows[0]["empty_sequence_policy"], "error")
        self.assertEqual(rows[1]["empty_sequence_policy"], "skip")
        self.assertEqual(
            rows[1]["maximum_skipped_empty_sequences"],
            "2",
        )

    def test_write_manifest_and_config(self) -> None:
        """Write deterministic TSV and YAML outputs."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fasta = root / "a.fasta"
            fasta.write_text(">a\nMKT\n", encoding="utf-8")
            row = {
                "sample_id": "a",
                "fasta_path": str(fasta),
                "species": "Species a",
                "taxon_id": "",
                "proteome_id": "",
                "source_database": "test",
                "release": "test",
                "provenance_status": "known",
                "header_parser": "manifest",
                "header_parser_strict": "false",
                "empty_sequence_policy": "error",
                "maximum_skipped_empty_sequences": "0",
            }
            manifest = root / "manifest.tsv"
            self.assertEqual(write_full_onekp_manifest([row], manifest), 1)
            config = build_full_onekp_cluster_config(
                manifest_path=manifest,
                seed_table=root / "seeds.csv",
                results_root=root / "results",
                environment_path=root / "environment.yml",
                threads=32,
                memory_limit="220G",
                tmpdir=root / "scratch",
            )
            config_path = write_cluster_config(config, root / "config.yaml")
            parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["diamond"]["masking"], "tantan")
            self.assertEqual(parsed["resources"]["threads"], 32)
            self.assertIn("diamond_tmp", parsed["diamond"]["tmpdir"])
            with self.assertRaises(DataValidationError):
                write_full_onekp_manifest([], root / "empty.tsv")
            with self.assertRaises(DataValidationError):
                write_cluster_config({}, root / "empty.yaml")

    def test_build_cluster_config_rejects_bad_resources(self) -> None:
        """Reject invalid thread and memory settings."""

        with self.assertRaises(ValueError):
            build_full_onekp_cluster_config(
                Path("m"), Path("s"), Path("r"), Path("e"), 0, "220G", Path("t")
            )
        with self.assertRaises(ValueError):
            build_full_onekp_cluster_config(
                Path("m"), Path("s"), Path("r"), Path("e"), 1, "", Path("t")
            )

    def test_source_preflight_uses_repository_sample_fallback(self) -> None:
        """Preflight reports all inputs and accepts recovered sample metadata."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Erin_Butterfield_data"
            discovery = full_onekp_discovery_root(source)
            fasta_dir = discovery / "files" / "fasta_files"
            fasta_dir.mkdir(parents=True)
            (discovery / "files" / "e3_ligases.csv").write_text(
                "entry\nP1\n",
                encoding="utf-8",
            )
            (fasta_dir / "Named.fasta").write_text(
                ">a\nMKT\n",
                encoding="utf-8",
            )
            repository = root / "repo"
            legacy = repository / "legacy_reference"
            environment = repository / "workflow" / "envs"
            legacy.mkdir(parents=True)
            environment.mkdir(parents=True)
            recovered = legacy / "samples.inherited.json"
            recovered.write_text(
                json.dumps({"Samples": ["Named"]}),
                encoding="utf-8",
            )
            (environment / "production.yml").write_text(
                "name: test\n",
                encoding="utf-8",
            )
            self.assertEqual(
                locate_inherited_samples_json(discovery, repository),
                recovered.resolve(),
            )
            result = validate_full_onekp_source_inputs(source, repository)
            self.assertEqual(result["sample_count"], 1)
            self.assertEqual(result["sample_names"], ["Named"])

    def test_create_full_onekp_cluster_files(self) -> None:
        """Create complete cluster files from the inherited directory layout."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Erin_Butterfield_data"
            discovery = (
                source
                / "Other_things"
                / "Denbi"
                / "denbi_data"
                / "E3_discovery_engine"
            )
            fasta_dir = discovery / "files" / "fasta_files"
            fasta_dir.mkdir(parents=True)
            (discovery / "samples.json").write_text(
                json.dumps({"Samples": ["Named", "onekp_dataset"]}),
                encoding="utf-8",
            )
            (discovery / "files" / "e3_ligases.csv").write_text(
                "entry\nP1\n",
                encoding="utf-8",
            )
            (fasta_dir / "Named.fasta").write_text(
                ">tr|P1|P1 OS=Named species OX=123\nMKT\n",
                encoding="utf-8",
            )
            (fasta_dir / "onekp_dataset.fasta").write_text(
                ">scaffold-AALA-1-Meliosma_cuneifolia\nMKT\n",
                encoding="utf-8",
            )
            repository = root / "repo"
            environment = repository / "workflow" / "envs"
            environment.mkdir(parents=True)
            (environment / "production.yml").write_text(
                "name: test\n",
                encoding="utf-8",
            )
            result = create_full_onekp_cluster_files(
                source_root=source,
                repository_root=repository,
                results_root=root / "results",
                output_dir=root / "generated",
                threads=8,
                memory_limit="64G",
                tmpdir=root / "scratch",
            )
        self.assertEqual(result["sample_count"], 2)
        self.assertTrue(Path(result["manifest_path"]).name.endswith(".tsv"))


if __name__ == "__main__":
    unittest.main()
