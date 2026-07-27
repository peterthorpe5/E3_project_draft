#!/usr/bin/env python3
"""Build a manifest for the curated inherited E3 PROTAC source files."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from e3parquet.file_manifest import build_file_manifest  # noqa: E402
from e3parquet.io_utils import maybe_write_parquet, write_tsv  # noqa: E402
from e3parquet.logging_utils import configure_logging  # noqa: E402

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build a source-file manifest for selected E3 PROTAC data."
    )
    parser.add_argument(
        "--raw-root",
        required=True,
        type=Path,
        help="Curated raw inherited source directory.",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Output directory for manifest and logs.",
    )
    parser.add_argument(
        "--no-checksum",
        action="store_true",
        help="Do not calculate SHA256 checksums.",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden/macOS sidecar files. Default: false.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print DEBUG messages to console.",
    )
    return parser.parse_args()


def main() -> int:
    """Run manifest creation."""
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.out_dir / "e3_build_manifest.log"
    configure_logging(log_path, verbose=args.verbose)

    try:
        manifest = build_file_manifest(
            raw_root=args.raw_root,
            checksum=not args.no_checksum,
            include_hidden=args.include_hidden,
        )
        tsv_path = args.out_dir / "source_file_manifest.tsv"
        parquet_path = args.out_dir / "source_file_manifest.parquet"
        write_tsv(manifest, tsv_path)
        wrote_parquet = maybe_write_parquet(manifest, parquet_path)
        LOGGER.info("Wrote manifest TSV: %s", tsv_path)
        if wrote_parquet:
            LOGGER.info("Wrote manifest Parquet: %s", parquet_path)
        else:
            LOGGER.warning(
                "Did not write Parquet manifest. Install pandas+pyarrow if needed."
            )
    except Exception:
        LOGGER.exception("Manifest creation failed")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
