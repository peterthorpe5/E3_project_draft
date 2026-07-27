#!/usr/bin/env python3
"""Convert selected inherited E3 PROTAC source files to Parquet tables.

This script performs a source-preserving first pass. It keeps original columns
as strings where possible and adds provenance columns to every generated table.
Biologically curated/typed tables can be built later from these stable raw
Parquet layers.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Mapping

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from e3parquet.fasta import iter_fasta_files, parse_fasta_file  # noqa: E402
from e3parquet.file_manifest import (  # noqa: E402
    build_file_manifest,
    manifest_by_relative_path,
)
from e3parquet.io_utils import (  # noqa: E402
    derived_output_path,
    is_probable_parquet_file,
    maybe_write_parquet,
    normalise_relative_path,
    path_has_hidden_or_macos_sidecar_part,
    table_name_from_relative_path,
    write_tsv,
)
from e3parquet.logging_utils import configure_logging  # noqa: E402
from e3parquet.tabular import (  # noqa: E402
    MAX_TEXT_BYTES_DEFAULT,
    add_source_columns,
    ingest_text_lines,
    iter_tabular_files,
    iter_text_files,
    output_table_name,
    read_tabular_file,
)

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Convert selected E3 PROTAC source files to Parquet."
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
        help="Derived output directory.",
    )
    parser.add_argument(
        "--no-checksum",
        action="store_true",
        help="Do not calculate SHA256 checksums.",
    )
    parser.add_argument(
        "--include-txt-as-tabular",
        action="store_true",
        help="Also try parsing .txt files as tables. They are always preserved as lines.",
    )
    parser.add_argument(
        "--max-fasta-bytes",
        type=int,
        default=250_000_000,
        help="Maximum FASTA size to parse by default. Larger files stay in manifest.",
    )
    parser.add_argument(
        "--parse-large-fasta",
        action="store_true",
        help="Parse FASTA files larger than --max-fasta-bytes.",
    )
    parser.add_argument(
        "--max-text-bytes",
        type=int,
        default=MAX_TEXT_BYTES_DEFAULT,
        help="Maximum text file size for line-level capture.",
    )
    parser.add_argument(
        "--copy-existing-parquet",
        action="store_true",
        help=(
            "Copy valid inherited Parquet files into "
            "derived/parquet/inherited_parquet."
        ),
    )
    parser.add_argument(
        "--copy-invalid-parquet",
        action="store_true",
        help=(
            "Copy files ending in .parquet even when magic-byte validation "
            "fails. Not recommended; disabled by default."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print DEBUG messages to console.",
    )
    return parser.parse_args()


def require_pyarrow() -> None:
    """Fail early if Parquet support is unavailable."""
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "pyarrow is required to write Parquet. Install with: "
            "conda install -c conda-forge pyarrow pandas openpyxl"
        ) from exc


def write_dataframe_parquet(dataframe: pd.DataFrame, output_path: Path) -> None:
    """Write a dataframe as Parquet with directory creation."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_parquet(output_path, index=False)


def ingest_tabular_sources(
    raw_root: Path,
    parquet_root: Path,
    manifest_index: Mapping[str, Mapping[str, object]],
    include_txt_as_tabular: bool,
) -> List[Dict[str, object]]:
    """Ingest CSV/TSV/XLSX sources to one Parquet table per source/sheet."""
    catalog: List[Dict[str, object]] = []
    output_dir = parquet_root / "source_tables"

    for source_file in iter_tabular_files(raw_root, include_txt=include_txt_as_tabular):
        rel_path = normalise_relative_path(source_file.relative_to(raw_root))
        manifest_record = manifest_index.get(rel_path, {})
        try:
            tables = read_tabular_file(source_file)
        except Exception as exc:  # pragma: no cover - defensive logging path
            LOGGER.exception("Failed reading tabular source: %s", rel_path)
            catalog.append(
                {
                    "table_name": "",
                    "source_file": rel_path,
                    "source_sheet": "",
                    "rows": "",
                    "columns": "",
                    "output_parquet": "",
                    "status": "failed_read",
                    "error": str(exc),
                }
            )
            continue

        for sheet_name, dataframe in tables:
            table_name = output_table_name(Path(rel_path), sheet_name)
            output_path = derived_output_path(
                output_dir,
                rel_path,
                suffix=".parquet",
                sheet_name=sheet_name,
            )
            try:
                enriched = add_source_columns(
                    dataframe=dataframe,
                    source_file=source_file,
                    raw_root=raw_root,
                    source_kind="tabular",
                    manifest_record=manifest_record,
                    source_sheet=sheet_name,
                )
                write_dataframe_parquet(enriched, output_path)
                catalog.append(
                    {
                        "table_name": table_name,
                        "source_file": rel_path,
                        "source_sheet": sheet_name,
                        "rows": len(enriched),
                        "columns": len(enriched.columns),
                        "output_parquet": normalise_relative_path(
                            output_path.relative_to(parquet_root.parent)
                        ),
                        "status": "written",
                        "error": "",
                    }
                )
                LOGGER.info("Wrote tabular Parquet: %s", output_path)
            except Exception as exc:  # pragma: no cover - defensive logging path
                LOGGER.exception("Failed writing tabular source: %s", rel_path)
                catalog.append(
                    {
                        "table_name": table_name,
                        "source_file": rel_path,
                        "source_sheet": sheet_name,
                        "rows": len(dataframe),
                        "columns": len(dataframe.columns),
                        "output_parquet": "",
                        "status": "failed_write",
                        "error": str(exc),
                    }
                )
    return catalog


def ingest_fasta_sources(
    raw_root: Path,
    parquet_root: Path,
    manifest_index: Mapping[str, Mapping[str, object]],
    max_fasta_bytes: int,
    parse_large_fasta: bool,
) -> List[Dict[str, object]]:
    """Ingest FASTA files to one Parquet file per source FASTA."""
    catalog: List[Dict[str, object]] = []
    output_dir = parquet_root / "sequences"

    for source_file in iter_fasta_files(raw_root):
        rel_path = normalise_relative_path(source_file.relative_to(raw_root))
        manifest_record = manifest_index.get(rel_path, {})
        size_bytes = source_file.stat().st_size
        table_name = f"fasta__{table_name_from_relative_path(rel_path)}"
        output_path = derived_output_path(output_dir, rel_path, suffix=".parquet")

        if size_bytes > max_fasta_bytes and not parse_large_fasta:
            LOGGER.warning(
                "Skipping large FASTA by default: %s (%d bytes)",
                rel_path,
                size_bytes,
            )
            catalog.append(
                {
                    "table_name": table_name,
                    "source_file": rel_path,
                    "rows": "",
                    "output_parquet": "",
                    "status": "skipped_large_fasta",
                    "size_bytes": size_bytes,
                    "error": "",
                }
            )
            continue

        try:
            records = parse_fasta_file(source_file, raw_root, manifest_record)
            dataframe = pd.DataFrame.from_records(records)
            write_dataframe_parquet(dataframe, output_path)
            catalog.append(
                {
                    "table_name": table_name,
                    "source_file": rel_path,
                    "rows": len(dataframe),
                    "output_parquet": normalise_relative_path(
                        output_path.relative_to(parquet_root.parent)
                    ),
                    "status": "written",
                    "size_bytes": size_bytes,
                    "error": "",
                }
            )
            LOGGER.info("Wrote FASTA Parquet: %s", output_path)
        except Exception as exc:  # pragma: no cover - defensive logging path
            LOGGER.exception("Failed parsing FASTA source: %s", rel_path)
            catalog.append(
                {
                    "table_name": table_name,
                    "source_file": rel_path,
                    "rows": "",
                    "output_parquet": "",
                    "status": "failed",
                    "size_bytes": size_bytes,
                    "error": str(exc),
                }
            )
    return catalog


def ingest_text_sources(
    raw_root: Path,
    parquet_root: Path,
    manifest_index: Mapping[str, Mapping[str, object]],
    max_text_bytes: int,
) -> List[Dict[str, object]]:
    """Preserve SQL/TXT files as line-level Parquet files."""
    all_records: List[Dict[str, object]] = []
    catalog: List[Dict[str, object]] = []
    for source_file in iter_text_files(raw_root):
        rel_path = normalise_relative_path(source_file.relative_to(raw_root))
        manifest_record = manifest_index.get(rel_path, {})
        try:
            records = ingest_text_lines(
                source_file,
                raw_root,
                manifest_record=manifest_record,
                max_text_bytes=max_text_bytes,
            )
            all_records.extend(records)
            catalog.append(
                {
                    "source_file": rel_path,
                    "lines_captured": len(records),
                    "status": "captured",
                    "error": "",
                }
            )
        except Exception as exc:  # pragma: no cover - defensive logging path
            LOGGER.exception("Failed preserving text source: %s", rel_path)
            catalog.append(
                {
                    "source_file": rel_path,
                    "lines_captured": "",
                    "status": "failed",
                    "error": str(exc),
                }
            )

    if all_records:
        output_path = parquet_root / "text" / "text_lines.parquet"
        dataframe = pd.DataFrame.from_records(all_records)
        write_dataframe_parquet(dataframe, output_path)
        LOGGER.info("Wrote text-lines Parquet: %s", output_path)
    return catalog


def copy_existing_parquets(
    raw_root: Path,
    parquet_root: Path,
    copy_invalid_parquet: bool = False,
) -> List[Dict[str, object]]:
    """Copy inherited Parquet files into the derived area without rewriting.

    Only real Parquet files are copied by default. This deliberately excludes
    macOS AppleDouble files such as ``._concated_seqs.parquet``, which caused
    DuckDB view creation to fail in v0.1.
    """
    catalog: List[Dict[str, object]] = []
    output_dir = parquet_root / "inherited_parquet"

    for source_file in sorted(raw_root.rglob("*.parquet")):
        rel_path = normalise_relative_path(source_file.relative_to(raw_root))

        if path_has_hidden_or_macos_sidecar_part(source_file):
            catalog.append(
                {
                    "source_file": rel_path,
                    "output_parquet": "",
                    "status": "skipped_hidden_sidecar",
                    "error": "",
                }
            )
            LOGGER.warning("Skipping macOS sidecar Parquet: %s", rel_path)
            continue

        is_valid = is_probable_parquet_file(source_file)
        if not is_valid and not copy_invalid_parquet:
            catalog.append(
                {
                    "source_file": rel_path,
                    "output_parquet": "",
                    "status": "skipped_invalid_parquet",
                    "error": "missing PAR1 header/footer",
                }
            )
            LOGGER.warning("Skipping invalid Parquet-like file: %s", rel_path)
            continue

        destination = derived_output_path(
            output_dir,
            rel_path,
            suffix=".parquet",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination)
        catalog.append(
            {
                "source_file": rel_path,
                "output_parquet": normalise_relative_path(
                    destination.relative_to(parquet_root.parent)
                ),
                "status": "copied",
                "error": "" if is_valid else "copied_without_validation",
            }
        )
        LOGGER.info("Copied inherited Parquet: %s", destination)

    return catalog


def main() -> int:
    """Run source-to-Parquet conversion."""
    args = parse_args()
    qc_dir = args.out_dir / "qc"
    parquet_root = args.out_dir / "parquet"
    log_dir = args.out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(log_dir / "e3_convert_seed_sources.log", verbose=args.verbose)

    try:
        require_pyarrow()
        manifest = build_file_manifest(
            raw_root=args.raw_root,
            checksum=not args.no_checksum,
            include_hidden=False,
        )
        manifest_index = manifest_by_relative_path(manifest)
        qc_dir.mkdir(parents=True, exist_ok=True)
        write_tsv(manifest, qc_dir / "source_file_manifest.tsv")
        maybe_write_parquet(manifest, qc_dir / "source_file_manifest.parquet")

        tabular_catalog = ingest_tabular_sources(
            args.raw_root,
            parquet_root,
            manifest_index,
            include_txt_as_tabular=args.include_txt_as_tabular,
        )
        fasta_catalog = ingest_fasta_sources(
            args.raw_root,
            parquet_root,
            manifest_index,
            max_fasta_bytes=args.max_fasta_bytes,
            parse_large_fasta=args.parse_large_fasta,
        )
        text_catalog = ingest_text_sources(
            args.raw_root,
            parquet_root,
            manifest_index,
            max_text_bytes=args.max_text_bytes,
        )
        copied_parquet_catalog: List[Dict[str, object]] = []
        if args.copy_existing_parquet:
            copied_parquet_catalog = copy_existing_parquets(
                args.raw_root,
                parquet_root,
                copy_invalid_parquet=args.copy_invalid_parquet,
            )

        write_tsv(tabular_catalog, qc_dir / "tabular_table_catalog.tsv")
        write_tsv(fasta_catalog, qc_dir / "fasta_table_catalog.tsv")
        write_tsv(text_catalog, qc_dir / "text_file_catalog.tsv")
        write_tsv(
            copied_parquet_catalog,
            qc_dir / "copied_existing_parquet_catalog.tsv",
        )
        LOGGER.info("Conversion complete. Output: %s", args.out_dir)
    except Exception:
        LOGGER.exception("Source conversion failed")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
