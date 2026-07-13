"""High-level orchestration helpers shared by CLI and Snakemake rules."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping

from e3_discovery.clusters import Thresholds, thresholds_from_mapping
from e3_discovery.config import load_config
from e3_discovery.fasta import prepare_combined_fasta
from e3_discovery.manifest import read_sample_manifest
from e3_discovery.resource import build_duckdb_resource
from e3_discovery.seeds import prepare_seed_table

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowPaths:
    """Canonical output paths derived from one workflow root directory."""

    root: Path
    combined_fasta: Path
    sequence_parquet: Path
    sample_summary_tsv: Path
    seed_tsv: Path
    seed_parquet: Path
    diamond_database: Path
    clusters_tsv: Path
    clusters_parquet: Path
    realignments_tsv: Path
    realignments_parquet: Path
    resource_duckdb: Path
    curated_parquet_dir: Path
    fasta_output_dir: Path
    validation_tsv: Path
    logs_dir: Path
    benchmarks_dir: Path
    provenance_dir: Path


def paths_from_config(config: Mapping[str, Any]) -> WorkflowPaths:
    """Create all standard output paths from a validated configuration."""

    root = Path(str(config["outputs"]["root"])).resolve()
    return WorkflowPaths(
        root=root,
        combined_fasta=root / "prepared_inputs" / "combined_proteomes.fasta",
        sequence_parquet=root / "prepared_inputs" / "sequence_records.parquet",
        sample_summary_tsv=root / "qc" / "sample_summary.tsv",
        seed_tsv=root / "prepared_inputs" / "known_e3_seeds.tsv",
        seed_parquet=root / "prepared_inputs" / "known_e3_seeds.parquet",
        diamond_database=root / "diamond" / "combined_proteomes.dmnd",
        clusters_tsv=root / "diamond" / "raw_deepclust_membership.tsv",
        clusters_parquet=root / "parquet" / "raw_deepclust_membership.parquet",
        realignments_tsv=root / "diamond" / "realigned_membership.tsv",
        realignments_parquet=root / "parquet" / "realigned_membership.parquet",
        resource_duckdb=root / "duckdb" / "e3_discovery_resource.duckdb",
        curated_parquet_dir=root / "curated_parquet",
        fasta_output_dir=root / "fasta_exports",
        validation_tsv=root / "qc" / "resource_validation.tsv",
        logs_dir=root / "logs",
        benchmarks_dir=root / "benchmarks",
        provenance_dir=root / "provenance",
    )


def prepare_inputs_from_config(config_path: Path) -> Dict[str, object]:
    """Prepare combined FASTA, sequence metadata, and known E3 seed tables."""

    LOGGER.info("Preparing workflow inputs using %s", config_path)
    config = load_config(config_path)
    paths = paths_from_config(config)
    samples = read_sample_manifest(Path(config["inputs"]["samples_tsv"]))
    fasta_summary = prepare_combined_fasta(
        samples=samples,
        combined_fasta=paths.combined_fasta,
        sequence_parquet=paths.sequence_parquet,
        sample_summary_tsv=paths.sample_summary_tsv,
        identifier_mode=config["inputs"].get("identifier_mode", "prefix_sample"),
        batch_size=int(config["resources"]["parquet_batch_size"]),
        compute_checksums=bool(
            config["inputs"].get("compute_input_checksums", True)
        ),
    )
    seed_summary = prepare_seed_table(
        input_path=Path(config["inputs"]["e3_seed_table"]),
        output_tsv=paths.seed_tsv,
        output_parquet=paths.seed_parquet,
        seed_column=config["inputs"].get("e3_seed_column"),
    )
    return {
        "paths": paths,
        "fasta_summary": fasta_summary,
        "seed_summary": seed_summary,
    }


def thresholds_from_config(config: Mapping[str, Any]) -> Thresholds:
    """Return strict thresholds from a validated workflow configuration."""

    return thresholds_from_mapping(config["thresholds"])


def build_resource_from_config(config_path: Path) -> Dict[str, object]:
    """Build the curated DuckDB and Parquet resource from workflow outputs."""

    LOGGER.info("Building workflow resource using %s", config_path)
    config = load_config(config_path)
    paths = paths_from_config(config)
    return build_duckdb_resource(
        database_path=paths.resource_duckdb,
        sequences_parquet=paths.sequence_parquet,
        seeds_parquet=paths.seed_parquet,
        clusters_parquet=paths.clusters_parquet,
        realignments_parquet=paths.realignments_parquet,
        thresholds=thresholds_from_config(config),
        curated_parquet_dir=paths.curated_parquet_dir,
        fasta_output_dir=paths.fasta_output_dir,
        validation_tsv=paths.validation_tsv,
        metadata={
            "project": config["project"],
            "diamond": config["diamond"],
            "thresholds": config["thresholds"],
        },
        duckdb_threads=int(config["resources"]["threads"]),
    )
