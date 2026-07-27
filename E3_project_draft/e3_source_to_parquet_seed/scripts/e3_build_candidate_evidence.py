#!/usr/bin/env python3
"""Build the validated E3 cluster candidate evidence resource."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from e3parquet.candidate_evidence import BuildConfig, build, result_dict  # noqa: E402
from e3parquet.logging_utils import configure_logging  # noqa: E402

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse candidate evidence command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Build a one-row-per-E3-seeded-cluster evidence resource from "
            "the completed E3 Discovery Engine DuckDB."
        )
    )
    parser.add_argument(
        "--discovery-duckdb",
        required=True,
        type=Path,
        help="Completed production E3 Discovery Engine DuckDB.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Destination root for DuckDB, TSV, Parquet, QC and provenance.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing formal outputs only after a successful build.",
    )
    parser.add_argument(
        "--skip-source-sha256",
        action="store_true",
        help="Skip hashing the source DuckDB; the omission is recorded.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print DEBUG messages to the console.",
    )
    return parser.parse_args()


def config_from_args(*, args: argparse.Namespace) -> BuildConfig:
    """Resolve the documented output layout from parsed arguments."""
    root = args.output_dir.resolve()
    return BuildConfig(
        discovery_duckdb=args.discovery_duckdb.resolve(),
        output_duckdb=root / "duckdb" / "e3_candidate_evidence.duckdb",
        output_tsv=(
            root
            / "candidate_evidence"
            / "e3_cluster_candidate_evidence.tsv"
        ),
        output_parquet=(
            root
            / "candidate_evidence"
            / "e3_cluster_candidate_evidence.parquet"
        ),
        validation_tsv=(
            root
            / "qc"
            / "e3_cluster_candidate_evidence_validation.tsv"
        ),
        manifest_json=(
            root
            / "provenance"
            / "e3_cluster_candidate_evidence_manifest.json"
        ),
        log_path=root / "logs" / "e3_build_candidate_evidence.log",
        overwrite=bool(args.overwrite),
        source_sha256=not bool(args.skip_source_sha256),
    )


def main() -> int:
    """Run the build and print its formal output paths as JSON."""
    args = parse_args()
    config = config_from_args(args=args)
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    configure_logging(log_path=config.log_path, verbose=args.verbose)
    try:
        result = build(config=config)
    except Exception:
        LOGGER.exception("Candidate evidence command failed")
        return 1
    print(json.dumps(result_dict(result=result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
