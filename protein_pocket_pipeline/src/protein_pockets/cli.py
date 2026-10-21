"""Simple named-option CLI for local AlphaFold pocket analysis."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from pathlib import Path

import duckdb

from . import __version__
from .io import load_samples, write_json
from .models import Settings
from .pipeline import run_pipeline
from .tools import inspect_tools


def build_parser() -> argparse.ArgumentParser:
    """Construct the run/check CLI with named options for all user inputs.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        prog="protein-pockets",
        description="Predict and rank pockets from local protein models.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "check"):
        sub = subparsers.add_parser(name=command)
        sub.add_argument("--fpocket", default="fpocket", help="fpocket executable")
        sub.add_argument("--p2rank", default="prank", help="P2Rank prank executable")
        sub.add_argument(
            "--require-p2rank", default="2.5.1", help="Required version substring"
        )
        sub.add_argument("--predict-config", default="alphafold")
        sub.add_argument("--rescore-config", default="rescore_2024")
        sub.add_argument("--output", type=Path, required=command == "run")
        if command == "run":
            inputs = sub.add_mutually_exclusive_group(required=True)
            inputs.add_argument(
                "--models", type=Path, help="Flat folder of PDB/mmCIF models"
            )
            inputs.add_argument(
                "--manifest", type=Path, help="TSV with sample_id and model_path"
            )
            sub.add_argument(
                "--fasta", type=Path, help="Optional representative protein FASTA"
            )
            sub.add_argument(
                "--chain",
                default="",
                help="Author chain ID, or all for complex analysis",
            )
            sub.add_argument("--confidence", choices=["plddt", "none"], default="plddt")
            sub.add_argument("--threads", type=int, default=4)
            sub.add_argument("--timeout", type=float, default=3600)
            sub.add_argument("--plddt-threshold", type=float, default=70)
            sub.add_argument("--pocket-confidence-fraction", type=float, default=0.8)
            sub.add_argument("--overlap-threshold", type=float, default=0.25)
            sub.add_argument("--allow-fragments", action="store_true")
            sub.add_argument("--skip-rescore", action="store_true")
            sub.add_argument("--resume", action="store_true")
    return parser


def main(*, argv: list[str] | None = None) -> int:
    """Run the CLI and return a shell-compatible exit status.

    Args:
        argv: Optional command-line strings for programmatic use and tests.

    Returns:
        0 for success, 1 for input/setup errors, 2 for partial model results,
        or 130 after interruption.
    """
    arguments = build_parser().parse_args(args=argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("protein_pockets").setLevel(level=logging.INFO)
    try:
        options = {
            "required_p2rank": arguments.require_p2rank,
            "predict_config": arguments.predict_config,
            "rescore_config": arguments.rescore_config,
        }
        if arguments.command == "run":
            options.update(
                confidence=arguments.confidence,
                threads=arguments.threads,
                timeout=arguments.timeout,
                high_confidence=arguments.plddt_threshold,
                pocket_fraction=arguments.pocket_confidence_fraction,
                overlap=arguments.overlap_threshold,
                rescore=not arguments.skip_rescore,
                allow_fragments=arguments.allow_fragments,
            )
        settings = Settings(**options)
        samples = None
        if arguments.command == "run":
            samples = load_samples(
                models=arguments.models,
                manifest=arguments.manifest,
                fasta=arguments.fasta,
                chain=arguments.chain,
            )
        tools = inspect_tools(
            fpocket=arguments.fpocket, p2rank=arguments.p2rank, settings=settings
        )
        if arguments.command == "check":
            if arguments.output:
                write_json(path=arguments.output, data=tools)
            else:
                print(json.dumps(tools, indent=2))
            return 0
        assert samples is not None
        return run_pipeline(
            samples=samples,
            output=arguments.output,
            tools=tools,
            settings=settings,
            resume=arguments.resume,
        )
    except KeyboardInterrupt:
        logging.getLogger(__name__).error(
            "Interrupted. Use the identical command with --resume."
        )
        return 130
    except (
        ValueError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        duckdb.Error,
    ) as error:
        logging.getLogger(__name__).error("%s", error)
        return 1
