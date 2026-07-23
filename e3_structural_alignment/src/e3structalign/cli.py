"""Named-option command-line interface for structural alignment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from e3structalign import __version__
from e3structalign.errors import StructuralAlignmentError
from e3structalign.pipeline import AlignmentSettings, run_pipeline


def fraction(value: str) -> float:
    """Parse an inclusive zero-to-one command-line fraction."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be numeric") from exc
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("must be between zero and one")
    return parsed


def positive_float(value: str) -> float:
    """Parse a strictly positive command-line float."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be numeric") from exc
    if parsed <= 0.0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def positive_integer(value: str) -> int:
    """Parse a strictly positive command-line integer."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the complete CLI parser."""
    parser = argparse.ArgumentParser(prog="e3-structure-align")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser(
        "run",
        help="Superpose structures and compare selected pockets.",
    )
    run.add_argument("--selected-pockets", type=Path, required=True)
    run.add_argument("--pocket-residue-mappings", type=Path, required=True)
    run.add_argument("--asset-manifest", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--usalign-executable", default="USalign")
    run.add_argument("--tmalign-executable", default="TMalign")
    run.add_argument("--skip-usalign", action="store_true")
    run.add_argument("--skip-tmalign", action="store_true")
    run.add_argument("--threads", type=positive_integer, default=4)
    run.add_argument(
        "--distance-threshold-angstrom",
        type=positive_float,
        default=4.0,
    )
    run.add_argument(
        "--maximum-centroid-distance-angstrom",
        type=positive_float,
        default=8.0,
    )
    run.add_argument(
        "--minimum-pocket-overlap-fraction",
        type=fraction,
        default=0.5,
    )
    run.add_argument(
        "--minimum-global-tm-score",
        type=fraction,
        default=0.5,
    )
    run.add_argument(
        "--minimum-group-support-fraction",
        type=fraction,
        default=0.75,
    )
    output_mode = run.add_mutually_exclusive_group()
    output_mode.add_argument("--resume", action="store_true")
    output_mode.add_argument("--force", action="store_true")
    run.add_argument("--verbose", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and convert expected failures to exit status two."""
    args = build_parser().parse_args(argv)
    try:
        if args.command != "run":
            raise StructuralAlignmentError(f"Unsupported command: {args.command}")
        manifest = run_pipeline(
            selected_pockets_path=args.selected_pockets,
            pocket_residue_mappings_path=args.pocket_residue_mappings,
            asset_manifest_path=args.asset_manifest,
            output_dir=args.output_dir,
            settings=AlignmentSettings(
                usalign_executable=args.usalign_executable,
                tmalign_executable=args.tmalign_executable,
                run_usalign=not args.skip_usalign,
                run_tmalign=not args.skip_tmalign,
                threads=args.threads,
                distance_threshold_angstrom=args.distance_threshold_angstrom,
                maximum_centroid_distance_angstrom=(
                    args.maximum_centroid_distance_angstrom
                ),
                minimum_pocket_overlap_fraction=(
                    args.minimum_pocket_overlap_fraction
                ),
                minimum_global_tm_score=args.minimum_global_tm_score,
                minimum_group_support_fraction=(
                    args.minimum_group_support_fraction
                ),
            ),
            resume=args.resume,
            force=args.force,
            verbose=args.verbose,
        )
        print(
            json.dumps(
                {
                    "status": "complete",
                    "run_manifest": str(manifest),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except StructuralAlignmentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
