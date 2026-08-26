"""Named-option command-line interface for top-group pocket review reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from e3structalign import __version__
from e3structalign.errors import StructuralAlignmentError
from e3structalign.review_models import ReviewInputOverrides, ReviewSettings


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
    """Build the complete pocket-review command-line parser."""
    parser = argparse.ArgumentParser(
        prog="e3-pocket-review",
        description=(
            "Generate ranked, self-contained 3D pocket and sequence-alignment "
            "review pages from a completed E3 workflow run."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--review-limit", type=positive_integer, default=50)
    parser.add_argument(
        "--member-pocket-top-k",
        type=positive_integer,
        default=5,
    )
    parser.add_argument("--shortlist", type=Path)
    parser.add_argument("--selected-pockets", type=Path)
    parser.add_argument("--ranked-pockets", type=Path)
    parser.add_argument("--ranked-pocket-sequence-coordinates", type=Path)
    parser.add_argument("--asset-manifest", type=Path)
    parser.add_argument("--alignments-root", type=Path)
    parser.add_argument("--structural-summary", type=Path)
    parser.add_argument("--sensitivity-group-summary", type=Path)
    parser.add_argument("--sensitivity-member-summary", type=Path)
    parser.add_argument("--structural-alignments", type=Path)
    parser.add_argument("--structural-pocket-comparisons", type=Path)
    parser.add_argument("--structural-interactive-root", type=Path)
    parser.add_argument(
        "--supplementary-group-sequences",
        type=Path,
        help=(
            "Optional exact group-member sequence table retained even when a "
            "member has no assessable structure or pocket."
        ),
    )
    output_mode = parser.add_mutually_exclusive_group()
    output_mode.add_argument("--resume", action="store_true")
    output_mode.add_argument("--force", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the report command and convert controlled failures to status two."""
    args = build_parser().parse_args(argv)
    try:
        from e3structalign.review_pipeline import build_review_report

        manifest = build_review_report(
            run_root=args.run_root,
            output_dir=args.output_dir,
            settings=ReviewSettings(
                review_limit=args.review_limit,
                member_pocket_top_k=args.member_pocket_top_k,
            ),
            overrides=ReviewInputOverrides(
                shortlist=args.shortlist,
                selected_pockets=args.selected_pockets,
                ranked_pockets=args.ranked_pockets,
                ranked_pocket_sequence_coordinates=(
                    args.ranked_pocket_sequence_coordinates
                ),
                asset_manifest=args.asset_manifest,
                alignments_root=args.alignments_root,
                structural_summary=args.structural_summary,
                sensitivity_group_summary=args.sensitivity_group_summary,
                sensitivity_member_summary=args.sensitivity_member_summary,
                structural_alignments=args.structural_alignments,
                structural_pocket_comparisons=(
                    args.structural_pocket_comparisons
                ),
                structural_interactive_root=(
                    args.structural_interactive_root
                ),
                supplementary_group_sequences=(
                    args.supplementary_group_sequences
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
                    "index_html": str(manifest.parents[1] / "index.html"),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except StructuralAlignmentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
