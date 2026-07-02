#!/usr/bin/env python3
"""Build curated E3 PROTAC DuckDB views from source-first Parquet tables."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from e3parquet.curated import (  # noqa: E402
    DebugRecorder,
    create_curated_views,
    inspect_expression_duckdb,
    locate_sqlite_db,
    run_sqlite_regression_queries,
    source_sql_files,
    write_expression_status,
    write_regression_results,
)
from e3parquet.logging_utils import configure_logging  # noqa: E402

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build curated DuckDB views for the E3 PROTAC resource."
    )
    parser.add_argument(
        "--raw-root",
        required=True,
        type=Path,
        help="Curated raw inherited source directory.",
    )
    parser.add_argument(
        "--derived-dir",
        required=True,
        type=Path,
        help="Derived directory created by e3_convert_seed_sources.py.",
    )
    parser.add_argument(
        "--duckdb-path",
        type=Path,
        default=None,
        help="DuckDB resource path. Defaults to derived/duckdb/e3_protac_resource.duckdb.",
    )
    parser.add_argument(
        "--sqlite-db",
        type=Path,
        default=None,
        help="Optional inherited SQLite DB for regression-only query checks.",
    )
    parser.add_argument(
        "--skip-sqlite-regression",
        action="store_true",
        help="Do not run inherited SQLite SQL query regression checks.",
    )
    parser.add_argument(
        "--expression-duckdb",
        type=Path,
        default=None,
        help="Optional separate Expression Atlas/RNAseq DuckDB to inspect and report.",
    )
    parser.add_argument(
        "--skip-materialised-parquet",
        action="store_true",
        help="Create DuckDB views only; do not export curated views to Parquet.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print DEBUG messages to console.",
    )
    return parser.parse_args()


def main() -> int:
    """Run curated resource build."""
    args = parse_args()
    duckdb_path = args.duckdb_path or args.derived_dir / "duckdb" / "e3_protac_resource.duckdb"
    log_dir = args.derived_dir / "logs"
    qc_dir = args.derived_dir / "qc"
    log_dir.mkdir(parents=True, exist_ok=True)
    qc_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(log_dir / "e3_build_curated_resource.log", verbose=args.verbose)

    debug = DebugRecorder()
    try:
        debug.add("start", "running", "Starting curated E3 resource build.", raw_root=args.raw_root, derived_dir=args.derived_dir, duckdb_path=duckdb_path)

        expression_records = inspect_expression_duckdb(args.expression_duckdb)
        write_expression_status(
            expression_records,
            qc_dir / "expression_resource_status.tsv",
            qc_dir / "expression_resource_status.parquet",
        )
        debug.add(
            "expression_resource_status",
            "written",
            "Wrote expression/RNAseq resource status report.",
            records=len(expression_records),
        )

        if not args.skip_sqlite_regression:
            sqlite_db = args.sqlite_db or locate_sqlite_db(args.raw_root)
            sql_files = source_sql_files(args.raw_root)
            if sqlite_db is None:
                debug.add("sqlite_regression", "missing", "No inherited SQLite DB found; skipped SQLite regression checks.")
            elif not sql_files:
                debug.add("sqlite_regression", "missing", "No SQL query files found; skipped SQLite regression checks.", sqlite_db=sqlite_db)
            else:
                debug.add(
                    "sqlite_regression",
                    "running",
                    "Running non-destructive SELECT/WITH queries against inherited SQLite DB as a regression reference.",
                    sqlite_db=sqlite_db,
                    sql_files=[str(path) for path in sql_files],
                )
                regression_records = run_sqlite_regression_queries(sqlite_db, sql_files, args.raw_root)
                write_regression_results(
                    regression_records,
                    qc_dir / "sqlite_regression_query_results.tsv",
                    qc_dir / "sqlite_regression_query_results.parquet",
                )
                debug.add(
                    "sqlite_regression",
                    "written",
                    "Wrote SQLite regression query results.",
                    query_count=len(regression_records),
                    failed_queries=sum(1 for record in regression_records if record.get("sqlite_status") == "failed"),
                )
        else:
            debug.add("sqlite_regression", "skipped", "SQLite regression checks skipped by user option.")

        views = create_curated_views(
            duckdb_path=duckdb_path,
            derived_dir=args.derived_dir,
            debug=debug,
            materialise_parquet=not args.skip_materialised_parquet,
        )
        debug.add("finish", "complete", "Curated resource build completed.", curated_views=views)
    except Exception:  # noqa: BLE001 - log all production failures for user debugging
        LOGGER.exception("Curated resource build failed")
        debug.add("finish", "failed", "Curated resource build failed; see Python traceback in log file.")
        debug.write(qc_dir / "curated_resource_debug.tsv", qc_dir / "curated_resource_debug.md")
        return 1

    debug.write(qc_dir / "curated_resource_debug.tsv", qc_dir / "curated_resource_debug.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
