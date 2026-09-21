"""Command-line interface for the DIAMOND clustering benchmark package."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Optional, Sequence

from diamond_clust_benchmark import __version__
from diamond_clust_benchmark.config import (
    configuration_to_dict,
    load_config,
)
from diamond_clust_benchmark.fasta import profile_fasta, write_fasta_profile
from diamond_clust_benchmark.io_utils import write_json
from diamond_clust_benchmark.report import generate_report
from diamond_clust_benchmark.runner import run_case, validate_runtime


def build_parser() -> argparse.ArgumentParser:
    """Build the package argument parser.

    Returns:
        Configured parser using named arguments for all operational inputs.
    """

    parser = argparse.ArgumentParser(
        prog="diamond-clust-benchmark",
        description="Benchmark DIAMOND clustering speed and concordance.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config")
    validate.add_argument("--config", required=True, type=Path)
    validate.add_argument("--output", type=Path)

    runtime = subparsers.add_parser("validate-runtime")
    runtime.add_argument("--config", required=True, type=Path)
    runtime.add_argument("--output", required=True, type=Path)

    profile = subparsers.add_parser("profile-input")
    profile.add_argument("--config", required=True, type=Path)
    profile.add_argument("--output", required=True, type=Path)

    run = subparsers.add_parser("run-case")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--case-id", required=True)
    run.add_argument("--repeat", required=True, type=int)
    run.add_argument("--output-directory", required=True, type=Path)
    run.add_argument("--retain-clusters", action="store_true")

    report = subparsers.add_parser("report")
    report.add_argument("--config", required=True, type=Path)
    report.add_argument("--run-root", required=True, type=Path)
    return parser


def _configure_logging(verbose: bool) -> None:
    """Configure concise timestamped package logging."""

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main(arguments: Optional[Sequence[str]] = None) -> int:
    """Run the command-line interface.

    Args:
        arguments: Optional argument sequence for testing.

    Returns:
        Process exit status.
    """

    parser = build_parser()
    parsed = parser.parse_args(arguments)
    _configure_logging(parsed.verbose)
    if parsed.command == "validate-config":
        config = load_config(parsed.config)
        payload = configuration_to_dict(config)
        if parsed.output:
            write_json(parsed.output, payload)
        else:
            print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if parsed.command == "validate-runtime":
        config = load_config(parsed.config)
        write_json(parsed.output, validate_runtime(config))
        return 0
    if parsed.command == "profile-input":
        config = load_config(parsed.config)
        profile = profile_fasta(config.input_fasta)
        if (
            config.expected_sequences is not None
            and int(profile["sequence_count"]) != config.expected_sequences
        ):
            parser.error(
                "Observed FASTA sequence count does not match expected_sequences"
            )
        if (
            config.expected_residues is not None
            and int(profile["residue_count"]) != config.expected_residues
        ):
            parser.error(
                "Observed FASTA residue count does not match expected_residues"
            )
        write_fasta_profile(profile, parsed.output)
        return 0
    if parsed.command == "run-case":
        config = load_config(parsed.config)
        run_case(
            config,
            parsed.case_id,
            parsed.repeat,
            parsed.output_directory,
            parsed.retain_clusters,
        )
        return 0
    if parsed.command == "report":
        config = load_config(parsed.config)
        print(json.dumps(generate_report(config, parsed.run_root), indent=2))
        return 0
    parser.error(f"Unsupported command: {parsed.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
