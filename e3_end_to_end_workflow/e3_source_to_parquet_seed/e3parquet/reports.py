"""Markdown report writers for the E3 source-first resource."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Dict, List, Sequence


def read_tsv(path: Path) -> List[Dict[str, str]]:
    """Read a TSV file into dictionaries, returning an empty list if absent."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def count_by(records: Sequence[Dict[str, str]], key: str) -> Dict[str, int]:
    """Count records by a dictionary key."""
    counts: Dict[str, int] = {}
    for record in records:
        value = record.get(key, "") or "<blank>"
        counts[value] = counts.get(value, 0) + 1
    return counts


def markdown_table(records: Sequence[Dict[str, str]], columns: Sequence[str], max_rows: int = 50) -> List[str]:
    """Return a compact Markdown table for selected columns."""
    if not records:
        return ["No records found."]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for record in records[:max_rows]:
        values = []
        for column in columns:
            value = str(record.get(column, "")).replace("|", "\\|")
            if len(value) > 120:
                value = value[:117] + "..."
            values.append(value)
        lines.append("| " + " | ".join(values) + " |")
    if len(records) > max_rows:
        lines.append(f"\nShowing {max_rows} of {len(records)} records.")
    return lines


def write_files_used_report(derived_dir: Path, output_path: Path, max_rows: int = 100) -> None:
    """Write a verbose Markdown report describing files used and outputs."""
    qc_dir = derived_dir / "qc"
    manifest = read_tsv(qc_dir / "source_file_manifest.tsv")
    tabular = read_tsv(qc_dir / "tabular_table_catalog.tsv")
    fasta = read_tsv(qc_dir / "fasta_table_catalog.tsv")
    text = read_tsv(qc_dir / "text_file_catalog.tsv")
    inherited_parquet = read_tsv(qc_dir / "copied_existing_parquet_catalog.tsv")
    curated_debug = read_tsv(qc_dir / "curated_resource_debug.tsv")
    sqlite_regression = read_tsv(qc_dir / "sqlite_regression_query_results.tsv")
    expression_status = read_tsv(qc_dir / "expression_resource_status.tsv")

    lines: List[str] = [
        "# E3 PROTAC source files and curated resource report",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "",
        "This document summarises the inherited files used by the source-first rebuild, the Parquet outputs generated from them, and the curated interrogation views produced for DuckDB/Shiny.",
        "It should be committed or archived with each run because it is the human-readable record of what went into the resource.",
        "",
        "## High-level counts",
        "",
        f"- Source files in manifest: {len(manifest)}",
        f"- Tabular source tables written: {sum(1 for r in tabular if r.get('status') == 'written')}",
        f"- FASTA sources parsed: {sum(1 for r in fasta if r.get('status') == 'written')}",
        f"- FASTA sources skipped as large: {sum(1 for r in fasta if r.get('status') == 'skipped_large_fasta')}",
        f"- Text/SQL files captured: {sum(1 for r in text if r.get('status') == 'captured')}",
        f"- Inherited Parquet files copied: {sum(1 for r in inherited_parquet if r.get('status') == 'copied')}",
        f"- SQLite regression queries recorded: {len(sqlite_regression)}",
        "",
        "## Source file roles",
        "",
    ]
    for role, count in sorted(count_by(manifest, "logical_role_guess").items()):
        lines.append(f"- `{role}`: {count}")

    lines.extend(["", "## Source files", ""])
    lines.extend(
        markdown_table(
            manifest,
            ["relative_path", "file_format", "logical_role_guess", "size_bytes", "sha256"],
            max_rows=max_rows,
        )
    )
    lines.extend(["", "## Tabular sources converted", ""])
    lines.extend(
        markdown_table(
            tabular,
            ["table_name", "source_file", "source_sheet", "rows", "columns", "status"],
            max_rows=max_rows,
        )
    )
    lines.extend(["", "## FASTA sources", ""])
    lines.extend(
        markdown_table(
            fasta,
            ["table_name", "source_file", "rows", "status", "size_bytes"],
            max_rows=max_rows,
        )
    )
    lines.extend(["", "## Text and SQL files preserved", ""])
    lines.extend(
        markdown_table(
            text,
            ["source_file", "lines_captured", "status", "error"],
            max_rows=max_rows,
        )
    )
    lines.extend(["", "## Inherited Parquet files", ""])
    lines.extend(
        markdown_table(
            inherited_parquet,
            ["source_file", "output_parquet", "status", "error"],
            max_rows=max_rows,
        )
    )
    lines.extend(["", "## SQLite regression query status", ""])
    lines.extend(
        markdown_table(
            sqlite_regression,
            ["query_id", "source_file", "sqlite_status", "sqlite_row_count", "sqlite_error"],
            max_rows=max_rows,
        )
    )
    lines.extend(["", "## Expression/RNAseq resource status", ""])
    lines.extend(
        markdown_table(
            expression_status,
            ["status", "object_name", "row_count", "message"],
            max_rows=max_rows,
        )
    )
    lines.extend(["", "## Curated build debug records", ""])
    lines.extend(
        markdown_table(
            curated_debug,
            ["step", "status", "message"],
            max_rows=max_rows,
        )
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
