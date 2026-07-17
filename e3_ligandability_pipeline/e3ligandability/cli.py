"""Command-line interface for the production ligandability workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .config import load_config
from .io_utils import (
    ensure_directory,
    read_accession_records,
    write_parquet_records,
    write_tsv_records,
)
from .logging_utils import configure_logging
from .pipeline import preflight_external_tools, run_pipeline
from .regression import run_legacy_model_regression


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command-line parser.

    Returns:
        Configured argument parser.
    """

    parser = argparse.ArgumentParser(
        prog="e3-ligandability",
        description=(
            "Validated AlphaFold, FPocket and P2Rank ligandability workflow "
            "for shortlisted plant E3 candidates."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Run the production ligandability workflow.",
    )
    run_parser.add_argument("--input", required=True, type=Path)
    run_parser.add_argument("--output-dir", required=True, type=Path)
    run_parser.add_argument("--config", type=Path)
    run_parser.add_argument("--git-repository", type=Path)
    run_parser.add_argument("--verbose", action="store_true")

    regression_parser = subparsers.add_parser(
        "validate-legacy",
        help="Compare retained inherited models with inherited pLDDT metadata.",
    )
    regression_parser.add_argument("--testing-root", required=True, type=Path)
    regression_parser.add_argument("--metadata-csv", required=True, type=Path)
    regression_parser.add_argument("--output-dir", required=True, type=Path)
    regression_parser.add_argument("--mean-tolerance", type=float, default=0.25)
    regression_parser.add_argument(
        "--fraction-tolerance",
        type=float,
        default=0.01,
    )
    regression_parser.add_argument("--verbose", action="store_true")

    tools_parser = subparsers.add_parser(
        "inspect-tools",
        help="Resolve FPocket/P2Rank and report their version output.",
    )
    tools_parser.add_argument("--config", type=Path)
    tools_parser.add_argument("--output", type=Path)
    tools_parser.add_argument("--verbose", action="store_true")
    return parser


def run_command(args: argparse.Namespace) -> int:
    """Execute the production ``run`` subcommand.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Process exit code.
    """

    output_root = ensure_directory(args.output_dir)
    logger = configure_logging(
        output_root / "logs" / "e3_ligandability.log",
        verbose=bool(args.verbose),
    )
    config = load_config(args.config)
    records = read_accession_records(
        args.input,
        accession_column=str(config["input"]["accession_column"]),
    )
    logger.info("Accessions accepted: %d", len(records))
    outcome = run_pipeline(
        input_path=args.input,
        accession_records=records,
        output_root=output_root,
        config=config,
        git_repository=args.git_repository,
    )
    logger.info("Run manifest: %s", outcome["manifest_path"])
    logger.info("Failed accessions: %s", outcome["failed_accessions"])
    logger.info("Failed checks: %s", outcome["failed_checks"])
    return 0 if outcome["success"] else 2


def run_legacy_command(args: argparse.Namespace) -> int:
    """Execute inherited model-level regression validation.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Zero when every regression row passes, otherwise two.
    """

    output_root = ensure_directory(args.output_dir)
    logger = configure_logging(
        output_root / "logs" / "legacy_regression.log",
        verbose=bool(args.verbose),
    )
    records = run_legacy_model_regression(
        testing_root=args.testing_root,
        metadata_csv=args.metadata_csv,
        mean_tolerance=float(args.mean_tolerance),
        fraction_tolerance=float(args.fraction_tolerance),
    )
    tsv_path = output_root / "legacy_model_regression.tsv"
    parquet_path = output_root / "legacy_model_regression.parquet"
    write_tsv_records(tsv_path, records)
    write_parquet_records(parquet_path, records)
    failed = [record["accession"] for record in records if record["status"] != "PASS"]
    logger.info("Regression rows: %d", len(records))
    logger.info("Non-passing accessions: %s", failed)
    return 0 if not failed else 2


def inspect_tools_command(args: argparse.Namespace) -> int:
    """Execute external-tool preflight and print structured results.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Process exit code.
    """

    output = args.output or Path.cwd() / "tool_versions.json"
    logger = configure_logging(
        output.with_suffix(".log"),
        verbose=bool(args.verbose),
    )
    config = load_config(args.config)
    fpocket, p2rank, versions = preflight_external_tools(config)
    payload = {
        "fpocket_executable": None if fpocket is None else str(fpocket),
        "p2rank_executable": None if p2rank is None else str(p2rank),
        "versions": versions,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info("Tool inspection written: %s", output.resolve())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected command.

    Args:
        argv: Optional argument vector excluding the executable name.

    Returns:
        Process exit code.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run_command(args)
        if args.command == "validate-legacy":
            return run_legacy_command(args)
        if args.command == "inspect-tools":
            return inspect_tools_command(args)
    except Exception as error:  # noqa: BLE001 - CLI provides concise failure.
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    parser.error(f"Unsupported command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
