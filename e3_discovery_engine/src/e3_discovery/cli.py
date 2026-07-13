"""Command-line interface for production E3 discovery workflow stages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Sequence

from e3_discovery.benchmarks import (
    aggregate_benchmark_directory,
    plot_runtime_by_rule,
    summarise_benchmarks,
    write_benchmark_outputs,
)
from e3_discovery.clusters import (
    cluster_tsv_to_parquet,
    realign_tsv_to_parquet,
)
from e3_discovery.config import load_config
from e3_discovery.diamond import (
    build_deepclust_command,
    build_makedb_command,
    build_realign_command,
    get_diamond_version,
    require_diamond_features,
    run_external_command,
    validate_expected_outputs,
)
from e3_discovery.exceptions import E3DiscoveryError
from e3_discovery.logging_utils import setup_logging
from e3_discovery.pipeline import (
    build_resource_from_config,
    paths_from_config,
    prepare_inputs_from_config,
    thresholds_from_config,
)
from e3_discovery.provenance import write_run_manifest


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser and all subcommands."""

    parser = argparse.ArgumentParser(
        prog="e3-discovery",
        description=(
            "Reproducible DIAMOND DeepClust workflow for identifying sequence "
            "clusters containing at least one known E3 candidate."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Optional persistent log file in addition to console logging.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("prepare", "build-resource", "write-provenance"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", required=True, type=Path)

    clusters = subparsers.add_parser("convert-clusters")
    clusters.add_argument("--input", required=True, type=Path)
    clusters.add_argument("--output", required=True, type=Path)
    clusters.add_argument("--batch-size", type=int, default=250_000)

    realignments = subparsers.add_parser("convert-realignments")
    realignments.add_argument("--config", required=True, type=Path)
    realignments.add_argument("--input", required=True, type=Path)
    realignments.add_argument("--output", required=True, type=Path)
    realignments.add_argument("--batch-size", type=int, default=250_000)

    for name in ("diamond-makedb", "diamond-deepclust", "diamond-realign"):
        command = subparsers.add_parser(name)
        command.add_argument("--config", required=True, type=Path)

    benchmark = subparsers.add_parser("aggregate-benchmarks")
    benchmark.add_argument("--benchmark-dir", required=True, type=Path)
    benchmark.add_argument("--output-dir", required=True, type=Path)

    return parser


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _run_diamond_stage(command_name: str, config_path: Path) -> Dict[str, Any]:
    config = load_config(config_path)
    paths = paths_from_config(config)
    diamond = config["diamond"]
    resources = config["resources"]
    executable = str(diamond.get("executable", "diamond"))
    version = get_diamond_version(executable)
    require_diamond_features(version, str(diamond["identity_mode"]))
    threads = int(resources["threads"])
    memory = str(diamond["memory_limit"])

    if command_name == "diamond-makedb":
        command = build_makedb_command(
            executable,
            paths.combined_fasta,
            paths.diamond_database,
            threads,
        )
        outputs = (paths.diamond_database,)
        log_name = "diamond_makedb"
    elif command_name == "diamond-deepclust":
        command = build_deepclust_command(
            executable=executable,
            database=paths.diamond_database,
            output_tsv=paths.clusters_tsv,
            threads=threads,
            memory_limit=memory,
            identity_mode=str(diamond["identity_mode"]),
            identity_percent=float(diamond["identity_percent"]),
            mutual_cover_percent=float(diamond["mutual_cover_percent"]),
            clustering_evalue=float(diamond["clustering_evalue"]),
            comp_based_stats=int(diamond.get("comp_based_stats", 0)),
            cluster_steps=diamond.get("cluster_steps"),
            masking=diamond.get("masking"),
            extra_args=diamond.get("extra_args"),
        )
        outputs = (paths.clusters_tsv,)
        log_name = "diamond_deepclust"
    elif command_name == "diamond-realign":
        command = build_realign_command(
            executable,
            paths.diamond_database,
            paths.clusters_tsv,
            paths.realignments_tsv,
            threads,
            memory,
            comp_based_stats=int(diamond.get("comp_based_stats", 0)),
        )
        outputs = (paths.realignments_tsv,)
        log_name = "diamond_realign"
    else:
        raise ValueError(f"Unknown DIAMOND stage: {command_name}")

    run_external_command(
        command,
        paths.logs_dir / f"{log_name}.log",
        paths.provenance_dir / f"{log_name}_command.json",
    )
    validate_expected_outputs(outputs)
    return {
        "diamond_version": str(version),
        "command": command,
        "outputs": [str(path) for path in outputs],
    }


def run_command(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute a parsed CLI subcommand and return its structured result."""

    if args.command == "prepare":
        return prepare_inputs_from_config(args.config)
    if args.command == "convert-clusters":
        return cluster_tsv_to_parquet(args.input, args.output, args.batch_size)
    if args.command == "convert-realignments":
        config = load_config(args.config)
        return realign_tsv_to_parquet(
            args.input,
            args.output,
            thresholds_from_config(config),
            args.batch_size,
        )
    if args.command == "build-resource":
        return build_resource_from_config(args.config)
    if args.command in {
        "diamond-makedb",
        "diamond-deepclust",
        "diamond-realign",
    }:
        return _run_diamond_stage(args.command, args.config)
    if args.command == "aggregate-benchmarks":
        records = aggregate_benchmark_directory(args.benchmark_dir)
        summaries = summarise_benchmarks(records)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_benchmark_outputs(
            records,
            summaries,
            args.output_dir / "benchmark_records.tsv",
            args.output_dir / "benchmark_records.parquet",
            args.output_dir / "benchmark_summary.tsv",
        )
        plot_runtime_by_rule(
            summaries,
            args.output_dir / "runtime_by_rule.png",
            args.output_dir / "runtime_by_rule.pdf",
        )
        return {"record_count": len(records), "summary_count": len(summaries)}
    if args.command == "write-provenance":
        config = load_config(args.config)
        paths = paths_from_config(config)
        manifest = write_run_manifest(
            paths.provenance_dir / "run_manifest.json",
            config,
            [
                paths.combined_fasta,
                paths.sequence_parquet,
                paths.seed_parquet,
                paths.clusters_tsv,
                paths.realignments_tsv,
                paths.resource_duckdb,
            ],
        )
        return manifest
    raise ValueError(f"Unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point with structured logging and expected-error handling."""

    parser = build_parser()
    args = parser.parse_args(argv)
    logger = setup_logging(
        log_file=args.log_file,
        verbose=args.verbose,
        logger_name="e3_discovery",
    )
    try:
        result = run_command(args)
        _print_json(result)
        return 0
    except (E3DiscoveryError, FileNotFoundError, ValueError) as error:
        logger.exception("Workflow stage failed: %s", error)
        return 2


if __name__ == "__main__":
    sys.exit(main())
