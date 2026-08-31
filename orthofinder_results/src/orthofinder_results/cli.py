"""Named command-line interface for OrthoFinder result interrogation."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

from . import __version__
from .errors import OrthoFinderResultsError
from .io_utils import atomic_write_text, configure_logging
from .pipeline import inspect_results, run_pipeline

_LOGGER = logging.getLogger("orthofinder_results.cli")


def build_parser() -> argparse.ArgumentParser:
    """Build the all-named-option command-line parser.

    Returns:
        Configured argument parser.
    """

    parser = argparse.ArgumentParser(
        prog="orthofinder-results",
        description=(
            "Version-aware interrogation of OrthoFinder 2 and 3 results with "
            "TSV, Parquet, DuckDB and offline HTML publication."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--action",
        required=True,
        choices=("inspect", "run"),
        help="Read-only layout inspection or complete resource publication.",
    )
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument(
        "--inspection-output",
        type=Path,
        help="Required persistent JSON output for --action inspect.",
    )
    parser.add_argument("--output-dir", type=Path, help="Formal output for --action run.")
    parser.add_argument("--run-id", help="Immutable run identifier for --action run.")
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Explicit persistent staging root; defaults beside --output-dir.",
    )
    parser.add_argument(
        "--alignment-dir",
        type=Path,
        help="Optional aligned FASTA directory; discovered OrthoFinder MSAs are used otherwise.",
    )
    parser.add_argument(
        "--distance-source",
        choices=("AUTO", "ALIGNED_SEQUENCE", "RESOLVED_GENE_TREE", "NONE"),
        default="AUTO",
        help="Distance authority; AUTO prefers alignments then resolved gene trees.",
    )
    parser.add_argument(
        "--distance-group-type",
        choices=("AUTO", "HOG", "LEGACY_ORTHOGROUP"),
        default="AUTO",
    )
    parser.add_argument("--distance-hierarchy-node", default="N0")
    parser.add_argument(
        "--distance-max-groups",
        type=int,
        default=0,
        help="Maximum aligned groups; zero means all supplied alignments.",
    )
    parser.add_argument("--distance-max-members", type=int, default=250)
    parser.add_argument("--parse-gene-trees", action="store_true")
    parser.add_argument(
        "--report-max-statistic-rows",
        type=int,
        default=100000,
        help="Maximum embedded group rows; zero means all rows.",
    )
    parser.add_argument("--report-max-groups", type=int, default=25)
    parser.add_argument("--report-max-members", type=int, default=250)
    parser.add_argument("--report-nearest-neighbours", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute a named package action.

    Args:
        argv: Optional argument sequence excluding the program name.

    Returns:
        Process exit status.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(verbose=args.verbose)
    try:
        if args.action == "inspect":
            _validate_inspect_arguments(parser=parser, args=args)
            record = inspect_results(results_dir=args.results_dir)
            atomic_write_text(
                path=args.inspection_output,
                text=json.dumps(record, indent=2, sort_keys=True) + "\n",
            )
            _LOGGER.info("Inspection written to %s", args.inspection_output.resolve())
            return 0
        _validate_run_arguments(parser=parser, args=args)
        manifest = run_pipeline(
            results_dir=args.results_dir,
            output_dir=args.output_dir,
            run_id=args.run_id,
            work_dir=args.work_dir,
            alignment_dir=args.alignment_dir,
            distance_source=args.distance_source,
            distance_group_type=args.distance_group_type,
            distance_hierarchy_node=args.distance_hierarchy_node,
            distance_max_groups=args.distance_max_groups,
            distance_max_members=args.distance_max_members,
            parse_gene_trees=args.parse_gene_trees,
            report_max_statistic_rows=args.report_max_statistic_rows,
            report_max_groups=args.report_max_groups,
            report_max_members=args.report_max_members,
            report_nearest_neighbours=args.report_nearest_neighbours,
            resume=args.resume,
            force=args.force,
            verbose=args.verbose,
        )
        _LOGGER.info("Completed run %s with status %s", manifest["run_id"], manifest["status"])
        return 0
    except OrthoFinderResultsError as error:
        _LOGGER.error("%s", error)
        return 2


def _validate_inspect_arguments(
    *, parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Validate arguments specific to layout inspection.

    Args:
        parser: Parser used for a controlled error.
        args: Parsed arguments.
    """

    if args.inspection_output is None:
        parser.error("--inspection-output is required for --action inspect.")
    if args.output_dir is not None or args.run_id is not None:
        parser.error("--output-dir and --run-id are not valid for --action inspect.")


def _validate_run_arguments(*, parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Validate arguments specific to resource publication.

    Args:
        parser: Parser used for a controlled error.
        args: Parsed arguments.
    """

    missing = [
        name
        for name, value in (("--output-dir", args.output_dir), ("--run-id", args.run_id))
        if value is None
    ]
    if missing:
        parser.error(f"{' and '.join(missing)} required for --action run.")
    if args.inspection_output is not None:
        parser.error("--inspection-output is not valid for --action run.")
