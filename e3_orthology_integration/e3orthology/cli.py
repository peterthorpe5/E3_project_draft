"""Named-option command-line interface for the staged integration workflow."""

from __future__ import annotations

import argparse
import logging
from importlib.resources import files
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .config import load_config, resolve_project_path, validate_config
from .errors import OrthologyIntegrationError
from .logging_utils import configure_logging
from .pipeline import RuntimePaths, build_runtime_paths, run_pipeline

DEFAULT_PROJECT_ROOT = Path("/home/pthorpe001/data/2026_E3_protac")
DEFAULT_ORTHOFINDER_SOURCE = Path("analysis/orthofinder2_feb26_full_archive_staging_20260720")
DEFAULT_CANDIDATE_EVIDENCE = Path(
    "E3_PROTAC_curated/derived_v0_4_0/candidate_evidence/e3_cluster_candidate_evidence.parquet"
)
DEFAULT_SQLITE_DATABASE = Path(
    "SSD_back_up_July_2026/Erin_Butterfield_data/Main_folder/E3_database/e3_ligase_sqlite_db.db"
)
DEFAULT_OUTPUT_ROOT = Path("analysis/e3_orthology_integration")
DEFAULT_RUN_NAME = "results_feb26_identifier_reconciliation_v0_1_0"
STAGE_NAMES = (
    "00_preflight",
    "01_build_identifier_map",
    "02_build_membership",
    "03_map_candidates",
    "04_validate_integration",
    "05_publish_portable_outputs",
)


def positive_integer(value: str) -> int:
    """Parse a positive command-line integer.

    Args:
        value: Raw argument text.

    Returns:
        Positive integer.

    Raises:
        argparse.ArgumentTypeError: If the value is not a positive integer.
    """

    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"Expected an integer; observed {value!r}.") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"Expected a positive integer; observed {value!r}.")
    return parsed


def bundled_species_manifest() -> Path:
    """Return the installed Results_Feb26 target-species manifest.

    Returns:
        Absolute bundled manifest path.
    """

    return Path(str(files("e3orthology").joinpath("data/species_manifest_results_feb26.tsv")))


def build_parser() -> argparse.ArgumentParser:
    """Build the named-option command-line parser.

    Returns:
        Fully configured argument parser.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Reconcile candidate bare accessions with one validated OrthoFinder result "
            "using restartable, checksum-aware stages."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Base directory for relative input and output paths; defaults to --project-root.",
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--orthofinder-source-root",
        type=Path,
        help="Extraction root below which exactly one configured results directory occurs.",
    )
    source_group.add_argument(
        "--orthofinder-results-dir",
        type=Path,
        help="Direct path to the configured OrthoFinder results directory.",
    )
    parser.add_argument("--candidate-evidence", type=Path, default=DEFAULT_CANDIDATE_EVIDENCE)
    parser.add_argument("--sqlite-database", type=Path, default=DEFAULT_SQLITE_DATABASE)
    parser.add_argument("--species-manifest", type=Path, default=bundled_species_manifest())
    parser.add_argument(
        "--output-root",
        "--output-dir",
        dest="output_root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME)
    parser.add_argument("--config", type=Path, help="Optional YAML override configuration.")
    parser.add_argument("--results-directory-name")
    parser.add_argument("--expected-species-count", type=positive_integer)
    parser.add_argument("--regression-accession")
    parser.add_argument("--expected-raw-identifier")
    parser.add_argument("--expected-orthogroup")
    parser.add_argument("--expected-hierarchical-orthogroup")
    parser.add_argument(
        "--skip-sqlite-regression",
        action="store_true",
        help="Disable comparison to inherited SQLite for a deliberate new-data run.",
    )
    parser.add_argument("--threads", type=positive_integer, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--start-at", choices=STAGE_NAMES)
    parser.add_argument("--stop-after", choices=STAGE_NAMES)
    parser.add_argument(
        "--force-stage",
        action="append",
        choices=STAGE_NAMES,
        default=[],
        help="Stage to rerun; may be supplied multiple times.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--print-run-root",
        action="store_true",
        help="Resolve and print the absolute run directory, then exit without writing files.",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def apply_cli_config(*, config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Apply explicit CLI scientific and execution overrides.

    Args:
        config: Validated YAML-plus-default configuration.
        args: Parsed command-line arguments.

    Returns:
        Updated, revalidated configuration.
    """

    if args.results_directory_name is not None:
        config["input"]["results_directory_name"] = args.results_directory_name
    if args.expected_species_count is not None:
        config["input"]["expected_species_count"] = args.expected_species_count
    if args.regression_accession is not None:
        config["regression"]["accession"] = args.regression_accession
    if args.expected_raw_identifier is not None:
        config["regression"]["expected_raw_identifier"] = args.expected_raw_identifier
    if args.expected_orthogroup is not None:
        config["regression"]["expected_orthogroup"] = args.expected_orthogroup
    if args.expected_hierarchical_orthogroup is not None:
        config["regression"]["expected_hierarchical_orthogroup"] = (
            args.expected_hierarchical_orthogroup
        )
    if args.skip_sqlite_regression:
        config["input"]["require_sqlite_regression"] = False
    config["execution"]["threads"] = args.threads
    validate_config(config=config)
    return config


def runtime_from_args(*, args: argparse.Namespace, config: dict[str, Any]) -> RuntimePaths:
    """Resolve CLI paths into one immutable runtime object.

    Args:
        args: Parsed command-line arguments.
        config: Effective configuration.

    Returns:
        Resolved runtime paths.
    """

    project_root = Path(args.project_root).expanduser().resolve()
    data_dir = project_root if args.data_dir is None else Path(args.data_dir).expanduser().resolve()
    source_value = (
        args.orthofinder_results_dir
        if args.orthofinder_results_dir is not None
        else args.orthofinder_source_root
        if args.orthofinder_source_root is not None
        else DEFAULT_ORTHOFINDER_SOURCE
    )
    return build_runtime_paths(
        project_root=project_root,
        orthofinder_source_root=resolve_project_path(
            project_root=data_dir,
            value=source_value,
        ),
        results_directory_name=str(config["input"]["results_directory_name"]),
        candidate_evidence=resolve_project_path(
            project_root=data_dir,
            value=args.candidate_evidence,
        ),
        sqlite_database=resolve_project_path(
            project_root=data_dir,
            value=args.sqlite_database,
        ),
        species_manifest=resolve_project_path(
            project_root=data_dir,
            value=args.species_manifest,
        ),
        output_root=resolve_project_path(
            project_root=data_dir,
            value=args.output_root,
        ),
        run_name=args.run_name,
        config_path=args.config,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line workflow and translate failures to exit codes.

    Args:
        argv: Optional argument sequence. Uses process arguments when ``None``.

    Returns:
        Zero on success, two for expected validation failures, or one for defects.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(log_path=None, verbose=args.verbose)
    logger = logging.getLogger("e3orthology.cli")
    try:
        config = apply_cli_config(config=load_config(path=args.config), args=args)
        paths = runtime_from_args(args=args, config=config)
        if args.print_run_root:
            print(paths.run_root)
            return 0
        configure_logging(
            log_path=None if args.dry_run else paths.run_root / "logs" / "pipeline.log",
            verbose=args.verbose,
        )
        logger = logging.getLogger("e3orthology.cli")
        logger.info("e3-orthology-integration version %s", __version__)
        logger.info("Effective run name: %s", paths.run_name)
        decisions = run_pipeline(
            paths=paths,
            config=config,
            resume=args.resume,
            start_at=args.start_at,
            stop_after=args.stop_after,
            force_stages=set(args.force_stage),
            dry_run=args.dry_run,
        )
        logger.info("Workflow completed with %d stage decisions.", len(decisions))
        return 0
    except OrthologyIntegrationError as error:
        logger.error("Workflow validation failed: %s", error)
        return 2
    except Exception:
        logger.exception("Unexpected workflow failure.")
        return 1
