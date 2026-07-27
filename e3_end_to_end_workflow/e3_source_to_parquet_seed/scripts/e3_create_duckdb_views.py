#!/usr/bin/env python3
"""Create DuckDB views over derived E3 PROTAC Parquet files."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from e3parquet.duckdb_views import create_views_for_parquets  # noqa: E402
from e3parquet.io_utils import write_tsv  # noqa: E402
from e3parquet.logging_utils import configure_logging  # noqa: E402

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create DuckDB views over derived Parquet files."
    )
    parser.add_argument(
        "--derived-dir",
        required=True,
        type=Path,
        help="Derived output directory containing the parquet/ directory.",
    )
    parser.add_argument(
        "--duckdb-path",
        required=True,
        type=Path,
        help="Output DuckDB database path.",
    )
    parser.add_argument(
        "--skip-parquet-magic-validation",
        action="store_true",
        help=(
            "Do not check PAR1 magic bytes before asking DuckDB to read "
            "Parquet files. Not recommended for inherited Mac copies."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print DEBUG messages to console.",
    )
    return parser.parse_args()


def main() -> int:
    """Run DuckDB view creation."""
    args = parse_args()
    log_dir = args.derived_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(log_dir / "e3_create_duckdb_views.log", args.verbose)

    try:
        parquet_dir = args.derived_dir / "parquet"
        catalog = create_views_for_parquets(
            derived_dir=parquet_dir,
            duckdb_path=args.duckdb_path,
            overwrite=True,
            validate_magic=not args.skip_parquet_magic_validation,
        )
        write_tsv(catalog, args.derived_dir / "qc" / "duckdb_view_catalog.tsv")
        created_count = sum(1 for row in catalog if row["status"] == "created")
        LOGGER.info("Created %d views", created_count)
    except Exception:
        LOGGER.exception("DuckDB view creation failed")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
