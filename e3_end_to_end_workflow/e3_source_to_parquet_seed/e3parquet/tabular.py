"""Tabular and text ingestion utilities for the E3 PROTAC rebuild."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

import pandas as pd

from e3parquet.io_utils import (
    TABULAR_SUFFIXES,
    TEXT_SUFFIXES,
    json_dumps_compact,
    normalise_relative_path,
    path_has_hidden_or_macos_sidecar_part,
    table_name_from_relative_path,
)

LOGGER = logging.getLogger(__name__)


MAX_TEXT_BYTES_DEFAULT = 10_000_000


def detect_delimiter(path: Path, max_lines: int = 20) -> str:
    """Detect a simple delimiter for CSV/TSV-like files."""
    counts = {"\t": 0, ",": 0, ";": 0}
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for index, line in enumerate(handle):
            if index >= max_lines:
                break
            for delimiter in counts:
                counts[delimiter] += line.count(delimiter)
    best_delimiter, best_count = max(counts.items(), key=lambda item: item[1])
    if best_count == 0:
        return "\t"
    return best_delimiter


def add_source_columns(
    dataframe: pd.DataFrame,
    source_file: Path,
    raw_root: Path,
    source_kind: str,
    manifest_record: Optional[Mapping[str, object]] = None,
    source_sheet: str = "",
) -> pd.DataFrame:
    """Add source/provenance columns to a dataframe."""
    rel_path = normalise_relative_path(source_file.relative_to(raw_root))
    output = dataframe.copy()
    output.insert(0, "_row_number_in_source", range(1, len(output) + 1))
    output["_source_file"] = rel_path
    output["_source_kind"] = source_kind
    output["_source_sheet"] = source_sheet
    output["_source_file_sha256"] = (
        str(manifest_record.get("sha256", "")) if manifest_record else ""
    )
    output["_source_file_size_bytes"] = (
        str(manifest_record.get("size_bytes", "")) if manifest_record else ""
    )
    output["_source_file_mtime_utc"] = (
        str(manifest_record.get("mtime_utc", "")) if manifest_record else ""
    )
    output["_ingested_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    output["_original_columns_json"] = json_dumps_compact(list(dataframe.columns))
    return output


def read_tabular_file(path: Path) -> List[Tuple[str, pd.DataFrame]]:
    """Read a tabular source file as one or more string-preserved tables.

    CSV/TSV files return one table with an empty sheet name. Excel files return
    one table per sheet. Values are read as strings to avoid accidental type
    coercion during this source-preservation stage.
    """
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        dataframe = pd.read_csv(
            path,
            sep=delimiter,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        )
        return [("", dataframe)]
    if suffix in {".xlsx", ".xls"}:
        excel_file = pd.ExcelFile(path)
        tables: List[Tuple[str, pd.DataFrame]] = []
        for sheet_name in excel_file.sheet_names:
            dataframe = pd.read_excel(
                excel_file,
                sheet_name=sheet_name,
                dtype=str,
                keep_default_na=False,
            )
            tables.append((sheet_name, dataframe))
        return tables

    # Some inherited .txt files are simple tabular accession lists. Detect a
    # delimiter and try to read them. If parsing fails, text-line ingestion will
    # still preserve their content.
    delimiter = detect_delimiter(path)
    dataframe = pd.read_csv(
        path,
        sep=delimiter,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
        engine="python",
    )
    return [("", dataframe)]


def iter_tabular_files(raw_root: Path, include_txt: bool = False) -> Iterable[Path]:
    """Yield tabular candidate files under a raw root."""
    suffixes = set(TABULAR_SUFFIXES)
    if include_txt:
        suffixes.update({".txt"})
    for path in sorted(raw_root.rglob("*")):
        if path.is_file() and path.suffix.lower() in suffixes:
            if path_has_hidden_or_macos_sidecar_part(path):
                continue
            yield path


def output_table_name(source_file: Path, sheet_name: str = "") -> str:
    """Create a stable table name from a source path and optional sheet."""
    return table_name_from_relative_path(source_file, sheet_name=sheet_name)


def ingest_text_lines(
    path: Path,
    raw_root: Path,
    manifest_record: Optional[Mapping[str, object]] = None,
    max_text_bytes: int = MAX_TEXT_BYTES_DEFAULT,
) -> List[Dict[str, object]]:
    """Preserve text-like source files as line-level records."""
    rel_path = normalise_relative_path(path.relative_to(raw_root))
    size_bytes = path.stat().st_size
    if size_bytes > max_text_bytes:
        LOGGER.warning("Skipping text-line capture for large file: %s", rel_path)
        return [
            {
                "line_number": "",
                "line_text": "",
                "capture_status": "skipped_too_large",
                "_source_file": rel_path,
                "_source_file_sha256": str(manifest_record.get("sha256", ""))
                if manifest_record
                else "",
                "_source_file_size_bytes": str(size_bytes),
                "_source_file_mtime_utc": str(
                    manifest_record.get("mtime_utc", "")
                )
                if manifest_record
                else "",
                "_ingested_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
        ]

    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            records.append(
                {
                    "line_number": line_number,
                    "line_text": line.rstrip("\n\r"),
                    "capture_status": "captured",
                    "_source_file": rel_path,
                    "_source_file_sha256": str(
                        manifest_record.get("sha256", "")
                    )
                    if manifest_record
                    else "",
                    "_source_file_size_bytes": str(size_bytes),
                    "_source_file_mtime_utc": str(
                        manifest_record.get("mtime_utc", "")
                    )
                    if manifest_record
                    else "",
                    "_ingested_at_utc": dt.datetime.now(
                        dt.timezone.utc
                    ).isoformat(),
                }
            )
    return records


def iter_text_files(raw_root: Path) -> Iterable[Path]:
    """Yield text/SQL files for line-level preservation."""
    for path in sorted(raw_root.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            if path_has_hidden_or_macos_sidecar_part(path):
                continue
            yield path
