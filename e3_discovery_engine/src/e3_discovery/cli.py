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
from e3_discovery.path_safety import (
    prepare_external_tool_path_alias,
    write_path_alias_record,
)
from e3_discovery.pipeline import (
    build_resource_from_config,
    paths_from_config,
    prepare_inputs_from_config,
    thresholds_from_config,
)
from e3_discovery.provenance import write_run_manifest
from e3_discovery.resource_monitor import (
    ProcessTreeResourceMonitor,
    aggregate_resource_usage_directory,
    plot_peak_ram_by_stage,
    summarise_resource_usage,
    write_resource_usage,
    write_resource_usage_outputs,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for all supported workflow stages.

    Returns:
        A configured ``argparse.ArgumentParser`` with required subcommands and
        stage-specific options.
    """

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
    parser.add_argument(
        "--resource-metrics",
        type=Path,
        help=(
            "Optional one-row TSV recording wall time, CPU time and peak "
            "process-tree RAM for this command."
        ),
    )
    parser.add_argument(
        "--resource-sample-interval",
        type=float,
        default=0.2,
        help="Resource-monitor sampling interval in seconds (default: 0.2).",
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
    benchmark.add_argument("--resource-metrics-dir", type=Path)

    return parser


def _print_json(value: Any) -> None:
    """Print a Python value as deterministic, human-readable JSON.

    Args:
        value: JSON-serialisable value or value supported by ``str`` fallback.

    Returns:
        None.
    """
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _run_diamond_stage(command_name: str, config_path: Path) -> Dict[str, Any]:
    """Execute one configured DIAMOND workflow stage.

    The function loads and validates configuration, checks the installed
    DIAMOND version, builds the stage command, captures logs and command
    provenance, and validates expected output files.

    Args:
        command_name: One of ``diamond-makedb``, ``diamond-deepclust`` or
            ``diamond-realign``.
        config_path: Path to the workflow YAML configuration.

    Returns:
        A dictionary containing the DIAMOND version, executed command and
        generated output paths.

    Raises:
        ValueError: If ``command_name`` is unsupported.
        ConfigurationError: If configuration or DIAMOND features are invalid.
        ExternalToolError: If DIAMOND cannot be queried or exits unsuccessfully.
        DataValidationError: If an expected output is absent or empty.
    """
    config = load_config(config_path)
    paths = paths_from_config(config)
    diamond = config["diamond"]
    resources = config["resources"]
    executable = str(diamond.get("executable", "diamond"))
    version = get_diamond_version(executable)
    require_diamond_features(version, str(diamond["identity_mode"]))
    threads = int(resources["threads"])
    memory = str(diamond["memory_limit"])
    path_alias = prepare_external_tool_path_alias(
        real_root=paths.root,
        config_path=config_path,
        configured_parent=diamond.get("path_alias_root"),
    )
    write_path_alias_record(
        paths.provenance_dir / "diamond_path_alias.json",
        path_alias,
        metadata={"diamond_version": str(version)},
    )

    tool_combined_fasta = path_alias.map_path(paths.combined_fasta)
    tool_database = path_alias.map_path(paths.diamond_database)
    tool_clusters = path_alias.map_path(paths.clusters_tsv)
    tool_realignments = path_alias.map_path(paths.realignments_tsv)

    if command_name == "diamond-makedb":
        command = build_makedb_command(
            executable,
            tool_combined_fasta,
            tool_database,
            threads,
        )
        outputs = (paths.diamond_database,)
        log_name = "diamond_makedb"
    elif command_name == "diamond-deepclust":
        command = build_deepclust_command(
            executable=executable,
            database=tool_database,
            output_tsv=tool_clusters,
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
            tool_database,
            tool_clusters,
            tool_realignments,
            threads,
            memory,
            comp_based_stats=int(diamond.get("comp_based_stats", 0)),
            masking=diamond.get("masking"),
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
        "path_alias_created": path_alias.alias_created,
        "external_tool_root": str(path_alias.tool_root),
    }


def run_command(args: argparse.Namespace) -> Dict[str, Any]:
    """Dispatch a parsed command-line namespace to its workflow implementation.

    Args:
        args: Parsed arguments produced by :func:`build_parser`.

    Returns:
        A structured dictionary describing the completed stage and outputs.

    Raises:
        ValueError: If the command name is unsupported.
        E3DiscoveryError: If a selected workflow stage fails validation or an
            external tool fails.
        FileNotFoundError: If a required input path is missing.
    """

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
        result = {
            "record_count": len(records),
            "summary_count": len(summaries),
        }
        if args.resource_metrics_dir is not None:
            resource_records = aggregate_resource_usage_directory(
                args.resource_metrics_dir
            )
            resource_summaries = summarise_resource_usage(resource_records)
            write_resource_usage_outputs(
                resource_records,
                resource_summaries,
                args.output_dir / "resource_usage_records.tsv",
                args.output_dir / "resource_usage_summary.tsv",
            )
            if resource_summaries:
                plot_peak_ram_by_stage(
                    resource_summaries,
                    args.output_dir / "peak_ram_by_stage.png",
                    args.output_dir / "peak_ram_by_stage.pdf",
                )
            result.update(
                {
                    "resource_record_count": len(resource_records),
                    "resource_summary_count": len(resource_summaries),
                }
            )
        return result
    if args.command == "write-provenance":
        config = load_config(args.config)
        paths = paths_from_config(config)
        manifest = write_run_manifest(
            paths.provenance_dir / "run_manifest.json",
            config,
            [
                args.config,
                Path(config["inputs"]["samples_tsv"]),
                Path(config["inputs"]["e3_seed_table"]),
                paths.combined_fasta,
                paths.sequence_parquet,
                paths.seed_parquet,
                paths.clusters_tsv,
                paths.realignments_tsv,
                paths.resource_duckdb,
                paths.validation_tsv,
                paths.summary_dir / "workflow_key_metrics.tsv",
                paths.summary_dir / "realignment_content_summary.tsv",
                paths.root / "benchmark_summary" / "benchmark_summary.tsv",
                paths.root / "benchmark_summary" / "resource_usage_summary.tsv",
            ],
            repository_root=Path.cwd(),
        )
        return manifest
    raise ValueError(f"Unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface with logging and resource monitoring.

    Args:
        argv: Optional argument sequence. ``None`` uses ``sys.argv``.

    Returns:
        ``0`` after successful execution or ``2`` for an expected workflow,
        input or configuration failure.

    Raises:
        SystemExit: If argument parsing fails or help is requested.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    logger = setup_logging(
        log_file=args.log_file,
        verbose=args.verbose,
        logger_name="e3_discovery",
    )
    monitor = None
    if args.resource_metrics is not None:
        monitor = ProcessTreeResourceMonitor(
            stage_name=args.command,
            sample_interval_seconds=args.resource_sample_interval,
        )
        monitor.start()
    return_code = 0
    try:
        result = run_command(args)
        _print_json(result)
    except (E3DiscoveryError, FileNotFoundError, ValueError) as error:
        return_code = 2
        logger.exception("Workflow stage failed: %s", error)
    finally:
        if monitor is not None:
            usage = monitor.stop(return_code=return_code)
            write_resource_usage(usage, args.resource_metrics)
            logger.info(
                "Measured peak process-tree RAM for %s: %.2f MiB",
                args.command,
                usage.peak_rss_mb,
            )
    return return_code


if __name__ == "__main__":
    sys.exit(main())
