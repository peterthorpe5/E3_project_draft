"""Named command-line interface for OrthoFinder result interrogation."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Sequence

from . import __version__
from .errors import OrthoFinderResultsError
from .io_utils import atomic_write_text, configure_logging, validate_persistent_path
from .pipeline import inspect_results, regenerate_report, run_pipeline

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
            "compressed TSV, Parquet, DuckDB and offline HTML publication."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--action",
        required=True,
        choices=("inspect", "run", "report"),
        help=(
            "Read-only layout inspection, complete resource publication, or "
            "report-only regeneration from a completed resource."
        ),
    )
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument(
        "--inspection-output",
        type=Path,
        help="Required persistent JSON output for --action inspect.",
    )
    parser.add_argument("--output-dir", type=Path, help="Formal output for --action run.")
    parser.add_argument("--run-id", help="Immutable run identifier for --action run.")
    parser.add_argument(
        "--resource-dir",
        type=Path,
        help="Completed orthofinder-results resource for --action report.",
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        help="New standalone HTML file for --action report.",
    )
    parser.add_argument(
        "--log-output",
        type=Path,
        help="Persistent log file for --action report; defaults beside the HTML.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help=(
            "Optional staging root; Slurm uses node-local temporary storage by "
            "default, while direct runs default beside --output-dir."
        ),
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
        help="Maximum groups for distance computation; zero means all eligible groups.",
    )
    parser.add_argument("--distance-max-members", type=int, default=250)
    parser.add_argument("--parse-gene-trees", action="store_true")
    parser.add_argument(
        "--report-max-statistic-rows",
        type=int,
        default=20000,
        help="Maximum embedded group rows (1-50,000; default 20,000).",
    )
    parser.add_argument("--report-max-groups", type=int, default=25)
    parser.add_argument("--report-max-members", type=int, default=250)
    parser.add_argument("--report-nearest-neighbours", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--keep-failed-work",
        action="store_true",
        help=(
            "Retain failed staging/copy directories for diagnosis; by default "
            "tracebacks are logged and partial data are removed."
        ),
    )
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
        if args.action == "report":
            _validate_report_arguments(parser=parser, args=args)
            log_output = validate_persistent_path(
                path=args.log_output or args.report_output.with_suffix(".log"),
                role="log_output",
            )
            configure_logging(log_path=log_output, verbose=args.verbose)
            record = regenerate_report(
                resource_dir=args.resource_dir,
                output_path=args.report_output,
                work_dir=args.work_dir,
                report_max_statistic_rows=args.report_max_statistic_rows,
                report_max_groups=args.report_max_groups,
                report_max_members=args.report_max_members,
                report_nearest_neighbours=args.report_nearest_neighbours,
                force=args.force,
            )
            _LOGGER.info(
                "Report regenerated: %s bytes at %s",
                f"{record['size_bytes']:,}",
                record["path"],
            )
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
            keep_failed_work=args.keep_failed_work,
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
    if args.results_dir is None:
        parser.error("--results-dir is required for --action inspect.")
    if any(
        value is not None
        for value in (args.output_dir, args.run_id, args.resource_dir, args.report_output)
    ):
        parser.error("Run and report output arguments are not valid for --action inspect.")


def _validate_run_arguments(*, parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Validate arguments specific to resource publication.

    Args:
        parser: Parser used for a controlled error.
        args: Parsed arguments.
    """

    missing = [
        name
        for name, value in (
            ("--results-dir", args.results_dir),
            ("--output-dir", args.output_dir),
            ("--run-id", args.run_id),
        )
        if value is None
    ]
    if missing:
        parser.error(f"{' and '.join(missing)} required for --action run.")
    if args.inspection_output is not None:
        parser.error("--inspection-output is not valid for --action run.")
    if any(value is not None for value in (args.resource_dir, args.report_output, args.log_output)):
        parser.error("Report-only arguments are not valid for --action run.")


def _validate_report_arguments(
    *, parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """Validate arguments specific to standalone report regeneration.

    Args:
        parser: Parser used for a controlled error.
        args: Parsed arguments.
    """

    missing = [
        name
        for name, value in (
            ("--resource-dir", args.resource_dir),
            ("--report-output", args.report_output),
        )
        if value is None
    ]
    if missing:
        parser.error(f"{' and '.join(missing)} required for --action report.")
    if any(
        value is not None
        for value in (args.results_dir, args.inspection_output, args.output_dir, args.run_id)
    ):
        parser.error("Inspection and run arguments are not valid for --action report.")
    resource = args.resource_dir.expanduser().resolve()
    report_paths = [args.report_output]
    if args.log_output is not None:
        report_paths.append(args.log_output)
    if any(
        resource == path.expanduser().resolve()
        or resource in path.expanduser().resolve().parents
        for path in report_paths
    ):
        parser.error(
            "--report-output and --log-output must be outside the immutable --resource-dir."
        )
