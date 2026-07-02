#!/usr/bin/env python3
"""Report or delete macOS sidecar files from derived E3 outputs."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from e3parquet.cleanup import clean_macos_sidecar_files  # noqa: E402
from e3parquet.io_utils import write_tsv  # noqa: E402
from e3parquet.logging_utils import configure_logging  # noqa: E402

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Report or delete macOS AppleDouble sidecar files."
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Directory to scan, usually the curated working copy root.",
    )
    parser.add_argument(
        "--out-tsv",
        required=True,
        type=Path,
        help="Output TSV report path.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete sidecar files. Default is dry-run/report only.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print DEBUG messages to console.",
    )
    return parser.parse_args()


def main() -> int:
    """Run sidecar cleanup/reporting."""
    args = parse_args()
    log_dir = args.out_tsv.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(log_dir / "e3_clean_macos_sidecars.log", args.verbose)

    try:
        records = clean_macos_sidecar_files(args.root, delete=args.delete)
        write_tsv(records, args.out_tsv)
        LOGGER.info("Sidecar scan complete: %d records", len(records))
    except Exception:
        LOGGER.exception("Sidecar cleanup failed")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
