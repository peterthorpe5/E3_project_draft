"""Defensive launcher for the Streamlit application."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from typing import Sequence

from e3app.config import AppConfig, validate_config
from e3app.errors import AppError


def build_parser() -> argparse.ArgumentParser:
    """Build the named-option launcher interface."""
    parser = argparse.ArgumentParser(prog="e3-python-app")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--resource-duckdb", type=Path)
    source.add_argument("--resource-parquet", type=Path)
    source.add_argument("--resource-run-dir", type=Path)
    parser.add_argument("--expression-duckdb", type=Path)
    parser.add_argument("--pocket-review-dir", type=Path)
    parser.add_argument("--human-plant-review-dir", type=Path)
    parser.add_argument("--max-rows", type=int, default=1000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    return parser


def streamlit_command(args: argparse.Namespace) -> list[str]:
    """Build a shell-safe argv list for the installed Streamlit module."""
    if not 1 <= args.port <= 65535:
        raise AppError("port must be between 1 and 65535")
    if not args.host.strip() or any(character.isspace() for character in args.host):
        raise AppError("host must be non-empty and contain no whitespace")
    spec = find_spec("e3app.streamlit_app")
    if spec is None or not spec.origin:
        raise AppError("Could not locate e3app.streamlit_app")
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        spec.origin,
        "--server.address",
        args.host,
        "--server.port",
        str(args.port),
        "--server.headless",
        str(bool(args.headless)).lower(),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Validate application inputs and launch Streamlit."""
    args = build_parser().parse_args(argv)
    config = AppConfig(
        resource_duckdb=args.resource_duckdb,
        resource_parquet=args.resource_parquet,
        resource_run_dir=args.resource_run_dir,
        expression_duckdb=args.expression_duckdb,
        pocket_review_dir=args.pocket_review_dir,
        max_rows=args.max_rows,
        human_plant_review_dir=args.human_plant_review_dir,
    )
    try:
        validate_config(config)
        if args.validate_only:
            print(f"VALID\t{config.source_mode}\t{config.source_path}")
            return 0
        environment = os.environ.copy()
        for name in (
            "E3_RESOURCE_DUCKDB",
            "E3_RESOURCE_PARQUET",
            "E3_RESOURCE_RUN_DIR",
        ):
            environment.pop(name, None)
        source_variable = {
            "duckdb": "E3_RESOURCE_DUCKDB",
            "master_parquet": "E3_RESOURCE_PARQUET",
            "run_directory": "E3_RESOURCE_RUN_DIR",
        }[config.source_mode]
        environment[source_variable] = str(config.source_path)
        environment["E3_MAX_TABLE_ROWS"] = str(config.max_rows)
        if config.expression_duckdb:
            environment["E3_EXPRESSION_DUCKDB"] = str(config.expression_duckdb.resolve())
        else:
            environment.pop("E3_EXPRESSION_DUCKDB", None)
        if config.pocket_review_dir:
            environment["E3_POCKET_REVIEW_DIR"] = str(
                config.pocket_review_dir.resolve()
            )
        else:
            environment.pop("E3_POCKET_REVIEW_DIR", None)
        if config.human_plant_review_dir:
            environment["E3_HUMAN_PLANT_REVIEW_DIR"] = str(
                config.human_plant_review_dir.resolve()
            )
        else:
            environment.pop("E3_HUMAN_PLANT_REVIEW_DIR", None)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        return subprocess.run(streamlit_command(args), env=environment, check=False).returncode
    except AppError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
