#!/usr/bin/env python3
"""Write a Markdown report describing files used by the E3 resource build."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from e3parquet.logging_utils import configure_logging  # noqa: E402
from e3parquet.reports import write_files_used_report  # noqa: E402

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Write E3 files-used Markdown report.")
    parser.add_argument("--derived-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--max-rows", type=int, default=100)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Run report writer."""
    args = parse_args()
    log_dir = args.derived_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(log_dir / "e3_write_files_used_report.log", verbose=args.verbose)
    output = args.output or args.derived_dir / "docs" / "FILES_USED_AND_CURATED_VIEWS.md"
    try:
        write_files_used_report(args.derived_dir, output, max_rows=args.max_rows)
    except Exception:  # noqa: BLE001
        LOGGER.exception("Failed writing files-used report")
        return 1
    LOGGER.info("Wrote files-used report: %s", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
