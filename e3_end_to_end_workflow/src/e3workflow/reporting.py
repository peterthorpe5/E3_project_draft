"""Self-contained, evidence-based HTML reporting for E3 workflow runs."""

from __future__ import annotations

import csv
import gzip
import html
import json
import math
import os
import shlex
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence, TextIO

import duckdb

from e3workflow import __version__
from e3workflow.config import (
    STAGE_NAMES,
    WorkflowConfig,
    controlled_input_paths,
    stage_dependencies,
    stage_interpretation,
    stage_purpose,
)
from e3workflow.errors import WorkflowError
from e3workflow.io_utils import (
    atomic_write_json,
    atomic_write_text,
    inventory_files,
    read_json,
    read_tsv,
    sha256_file,
    utc_now,
    write_tsv,
)

REPORT_FILENAME = "stage_report.html"
RUN_REPORT_FILENAME = "e3_workflow_summary.html"
MAX_JSON_INSPECTION_BYTES = 10 * 1024 * 1024
MAX_TEXT_PREVIEW_CHARACTERS = 240


def _escape(value: object) -> str:
    """Return one value escaped for safe insertion into HTML."""
    return html.escape(str(value), quote=True)


def _human_bytes(value: int | float) -> str:
    """Format a byte count with binary units."""
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(amount) < 1024.0 or unit == "TiB":
            return f"{amount:,.2f} {unit}"
        amount /= 1024.0
    return f"{amount:,.2f} TiB"


def _number(value: object, default: float = 0.0) -> float:
    """Convert a report value to a finite float or return a default."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _integer(value: object, default: int = 0) -> int:
    """Convert a report value to an integer or return a default."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@contextmanager
def _open_text(path: Path) -> Iterator[TextIO]:
    """Open a plain or gzip-compressed text file for streaming reads."""
    if path.suffix.lower() == ".gz":
        handle = gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")
    else:
        handle = path.open("r", encoding="utf-8", errors="replace", newline="")
    with handle:
        yield handle


def _output_kind(path: Path) -> str:
    """Classify a declared output using conservative filename rules."""
    lower_name = path.name.lower()
    if lower_name.endswith((".tsv", ".tsv.gz")):
        return "TSV table"
    if lower_name.endswith((".fasta", ".fa", ".faa", ".fna", ".fasta.gz", ".fa.gz")):
        return "FASTA sequence file"
    if lower_name.endswith(".json"):
        return "JSON record"
    if lower_name.endswith((".txt", ".log", ".md")):
        return "text file"
    if lower_name.endswith(".parquet"):
        return "Parquet table"
    if lower_name.endswith((".duckdb", ".db", ".sqlite", ".sqlite3")):
        return "database"
    return "file"


def _summarise_tsv(path: Path, preview_rows: int, max_columns: int) -> dict[str, Any]:
    """Count and preview a TSV without loading the complete table into memory."""
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, None)
        if not header or any(not column for column in header):
            raise WorkflowError(f"TSV output has no valid header: {path}")
        selected = header[:max_columns]
        rows: list[dict[str, str]] = []
        row_count = 0
        malformed_rows = 0
        for values in reader:
            row_count += 1
            if len(values) != len(header):
                malformed_rows += 1
            if len(rows) < preview_rows:
                padded = values + [""] * max(0, len(selected) - len(values))
                rows.append(dict(zip(selected, padded[: len(selected)])))
    warning = ""
    if malformed_rows:
        warning = f"{malformed_rows:,} row(s) did not match the header width."
    return {
        "summary": f"{row_count:,} data rows and {len(header):,} columns.",
        "row_count": row_count,
        "column_count": len(header),
        "columns": selected,
        "columns_truncated": len(header) > len(selected),
        "preview": rows,
        "warning": warning,
    }


def _summarise_fasta(path: Path, preview_rows: int) -> dict[str, Any]:
    """Calculate streaming sequence counts and length statistics for a FASTA."""
    sequence_count = 0
    total_residues = 0
    minimum_length: int | None = None
    maximum_length = 0
    current_length: int | None = None
    identifiers: list[str] = []

    def finish_sequence() -> None:
        """Commit the current sequence length to aggregate statistics."""
        nonlocal total_residues, minimum_length, maximum_length, current_length
        if current_length is None:
            return
        total_residues += current_length
        minimum_length = (
            current_length if minimum_length is None else min(minimum_length, current_length)
        )
        maximum_length = max(maximum_length, current_length)

    with _open_text(path) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                finish_sequence()
                sequence_count += 1
                current_length = 0
                if len(identifiers) < preview_rows:
                    identifiers.append(line[1:].split(maxsplit=1)[0])
            elif current_length is not None:
                current_length += len(line)
    finish_sequence()
    mean_length = total_residues / sequence_count if sequence_count else 0.0
    return {
        "summary": (
            f"{sequence_count:,} sequences; {total_residues:,} residues; "
            f"mean length {mean_length:,.1f}."
        ),
        "sequence_count": sequence_count,
        "total_residues": total_residues,
        "minimum_length": minimum_length or 0,
        "maximum_length": maximum_length,
        "mean_length": mean_length,
        "identifiers": identifiers,
        "warning": "" if sequence_count else "No FASTA headers were detected.",
    }


def _summarise_json(path: Path) -> dict[str, Any]:
    """Summarise a reasonably sized JSON result without embedding nested payloads."""
    if path.stat().st_size > MAX_JSON_INSPECTION_BYTES:
        return {
            "summary": "JSON is larger than the safe report-inspection limit.",
            "warning": "Content preview omitted; the complete file remains checksummed.",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"summary": "JSON content could not be inspected.", "warning": str(exc)}
    if isinstance(payload, dict):
        keys = list(payload)[:20]
        scalar_values = {
            key: payload[key]
            for key in keys
            if isinstance(payload[key], (str, int, float, bool)) or payload[key] is None
        }
        return {
            "summary": f"JSON object with {len(payload):,} top-level keys.",
            "keys": keys,
            "scalar_values": scalar_values,
            "warning": "",
        }
    if isinstance(payload, list):
        return {
            "summary": f"JSON array with {len(payload):,} top-level items.",
            "warning": "",
        }
    return {"summary": f"JSON scalar of type {type(payload).__name__}.", "warning": ""}


def _summarise_text(path: Path, preview_rows: int) -> dict[str, Any]:
    """Count lines and retain a bounded non-empty preview from a text output."""
    line_count = 0
    preview: list[str] = []
    with _open_text(path) as handle:
        for line in handle:
            line_count += 1
            stripped = line.strip()
            if stripped and len(preview) < preview_rows:
                preview.append(stripped[:MAX_TEXT_PREVIEW_CHARACTERS])
    return {
        "summary": f"{line_count:,} text lines.",
        "line_count": line_count,
        "text_preview": preview,
        "warning": "",
    }


def _display_cell(value: object) -> str:
    """Convert a database value to bounded, JSON-safe report text."""
    if value is None:
        return ""
    text = str(value)
    return text[:MAX_TEXT_PREVIEW_CHARACTERS]


def _quote_identifier(value: str) -> str:
    """Quote one database identifier obtained from trusted catalogue metadata."""
    return '"' + value.replace('"', '""') + '"'


def _summarise_parquet(path: Path, preview_rows: int, max_columns: int) -> dict[str, Any]:
    """Inspect Parquet metadata and a bounded preview through read-only DuckDB queries."""
    with duckdb.connect(database=":memory:") as connection:
        description = connection.execute(
            query="DESCRIBE SELECT * FROM read_parquet(?)",
            parameters=[str(path)],
        ).fetchall()
        all_columns = [str(row[0]) for row in description]
        selected = all_columns[:max_columns]
        row_count = connection.execute(
            query="SELECT count(*) FROM read_parquet(?)",
            parameters=[str(path)],
        ).fetchone()[0]
        column_sql = ", ".join(_quote_identifier(column) for column in selected)
        preview_values = connection.execute(
            query=f"SELECT {column_sql} FROM read_parquet(?) LIMIT ?",
            parameters=[str(path), preview_rows],
        ).fetchall()
    preview = [
        {
            column: _display_cell(value)
            for column, value in zip(selected, values)
        }
        for values in preview_values
    ]
    return {
        "summary": f"{row_count:,} data rows and {len(all_columns):,} columns.",
        "row_count": row_count,
        "column_count": len(all_columns),
        "columns": selected,
        "columns_truncated": len(all_columns) > len(selected),
        "preview": preview,
        "warning": "",
    }


def _database_relation_rows(
    *, connection: duckdb.DuckDBPyConnection, preview_rows: int
) -> tuple[int, list[dict[str, str]]]:
    """Return bounded DuckDB catalogue rows and counts for physical tables."""
    relations = connection.execute(
        query=(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
            "ORDER BY table_schema, table_name"
        )
    ).fetchall()
    preview: list[dict[str, str]] = []
    for schema, name, relation_type in relations[:preview_rows]:
        row_count: object = "not counted for views"
        if str(relation_type).upper() == "BASE TABLE":
            qualified = f"{_quote_identifier(str(schema))}.{_quote_identifier(str(name))}"
            row_count = connection.execute(query=f"SELECT count(*) FROM {qualified}").fetchone()[0]
        preview.append(
            {
                "schema": str(schema),
                "relation": str(name),
                "type": str(relation_type),
                "row_count": str(row_count),
            }
        )
    return len(relations), preview


def _summarise_duckdb(path: Path, preview_rows: int) -> dict[str, Any]:
    """Inspect DuckDB catalogue and bounded base-table row counts in read-only mode."""
    with duckdb.connect(database=str(path), read_only=True) as connection:
        relation_count, preview = _database_relation_rows(
            connection=connection,
            preview_rows=preview_rows,
        )
    return {
        "summary": f"DuckDB database with {relation_count:,} tables or views.",
        "row_count": relation_count,
        "column_count": 4,
        "columns": ["schema", "relation", "type", "row_count"],
        "columns_truncated": False,
        "preview": preview,
        "warning": "" if relation_count else "No user tables or views were detected.",
    }


def _summarise_sqlite(path: Path, preview_rows: int) -> dict[str, Any]:
    """Inspect SQLite table names and bounded row counts in read-only mode."""
    uri = f"file:{path.resolve()}?mode=ro"
    with sqlite3.connect(database=uri, uri=True) as connection:
        relations = connection.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        preview = []
        for name, relation_type in relations[:preview_rows]:
            row_count: object = "not counted for views"
            if relation_type == "table":
                row_count = connection.execute(
                    f"SELECT count(*) FROM {_quote_identifier(str(name))}"
                ).fetchone()[0]
            preview.append(
                {
                    "relation": str(name),
                    "type": str(relation_type),
                    "row_count": str(row_count),
                }
            )
    return {
        "summary": f"SQLite database with {len(relations):,} tables or views.",
        "row_count": len(relations),
        "column_count": 3,
        "columns": ["relation", "type", "row_count"],
        "columns_truncated": False,
        "preview": preview,
        "warning": "" if relations else "No user tables or views were detected.",
    }


def summarise_output(
    *,
    stage_root: Path,
    relative_path: str,
    preview_rows: int,
    max_columns: int,
) -> dict[str, Any]:
    """Build a bounded, evidence-based summary for one declared output.

    Args:
        stage_root: Temporary stage directory containing the output.
        relative_path: Safe configured path relative to ``stage_root``.
        preview_rows: Maximum rows or identifiers retained in the report.
        max_columns: Maximum TSV columns retained in the report.

    Returns:
        JSON-serialisable output summary with size and checksum provenance.
    """
    path = stage_root / relative_path
    kind = _output_kind(path)
    record: dict[str, Any] = {
        "path": relative_path,
        "kind": kind,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    try:
        if kind == "TSV table":
            record.update(_summarise_tsv(path, preview_rows, max_columns))
        elif kind == "FASTA sequence file":
            record.update(_summarise_fasta(path, preview_rows))
        elif kind == "JSON record":
            record.update(_summarise_json(path))
        elif kind == "text file":
            record.update(_summarise_text(path, preview_rows))
        elif kind == "Parquet table":
            record.update(_summarise_parquet(path, preview_rows, max_columns))
        elif kind == "database" and path.suffix.lower() == ".duckdb":
            record.update(_summarise_duckdb(path, preview_rows))
        elif kind == "database":
            record.update(_summarise_sqlite(path, preview_rows))
        else:
            record.update(
                {
                    "summary": (
                        "Structured content was not interpreted by the orchestration layer; "
                        "size and checksum provenance are retained."
                    ),
                    "warning": "",
                }
            )
    except (
        OSError,
        UnicodeError,
        csv.Error,
        duckdb.Error,
        sqlite3.Error,
        WorkflowError,
    ) as exc:
        record.update(
            {
                "summary": "The output passed its existence contract but could not be previewed.",
                "warning": str(exc),
            }
        )
    return record


def summarise_declared_outputs(
    *, config: WorkflowConfig, stage_name: str, stage_root: Path
) -> list[dict[str, Any]]:
    """Summarise every validated output explicitly declared for a stage."""
    stage = config.stage(stage_name)
    return [
        summarise_output(
            stage_root=stage_root,
            relative_path=relative_path,
            preview_rows=config.reporting.preview_rows,
            max_columns=config.reporting.max_table_columns,
        )
        for relative_path in stage.expected_outputs
    ]


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """Render a responsive HTML table from already bounded values."""
    header_html = "".join(f"<th>{_escape(header)}</th>" for header in headers)
    row_html = "".join(
        "<tr>" + "".join(f"<td>{_escape(value)}</td>" for value in row) + "</tr>"
        for row in rows
    )
    empty = '<tr><td colspan="{}">No records.</td></tr>'.format(max(1, len(headers)))
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + header_html
        + "</tr></thead><tbody>"
        + (row_html or empty)
        + "</tbody></table></div>"
    )


def _key_value_table(rows: Sequence[tuple[object, object]]) -> str:
    """Render a two-column key/value table."""
    return _table(("Field", "Value"), rows)


def _cards(cards: Sequence[tuple[str, str, str]]) -> str:
    """Render prominent metric cards with labels and explanations."""
    return '<div class="cards">' + "".join(
        (
            '<div class="card"><div class="card-label">{}</div>'
            '<div class="card-value">{}</div><div class="card-note">{}</div></div>'
        ).format(_escape(label), _escape(value), _escape(note))
        for label, value, note in cards
    ) + "</div>"


def _bar_chart(
    *, title: str, items: Sequence[tuple[str, float]], unit: str, maximum_items: int
) -> str:
    """Render a labelled horizontal bar chart as self-contained SVG."""
    values = list(items[:maximum_items])
    if not values:
        return '<p class="muted">No values were available for this chart.</p>'
    maximum = max((value for _, value in values), default=0.0) or 1.0
    width = 920
    label_width = 210
    plot_width = 590
    row_height = 30
    height = 60 + row_height * len(values)
    parts = [
        (
            f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{_escape(title)}"><title>{_escape(title)}</title>'
        ),
        f'<text x="10" y="24" class="chart-title">{_escape(title)}</text>',
    ]
    for index, (label, value) in enumerate(values):
        y = 42 + index * row_height
        bar_width = max(1.0, plot_width * max(0.0, value) / maximum)
        parts.extend(
            [
                f'<text x="10" y="{y + 16}" class="axis-label">{_escape(label[:32])}</text>',
                (
                    f'<rect x="{label_width}" y="{y}" width="{bar_width:.2f}" height="19" '
                    'rx="3" class="bar" />'
                ),
                (
                    f'<text x="{label_width + bar_width + 8:.2f}" y="{y + 15}" '
                    f'class="value-label">{value:,.2f} {_escape(unit)}</text>'
                ),
            ]
        )
    parts.append("</svg>")
    return "".join(parts)


def _line_chart(
    *, title: str, points: Sequence[tuple[float, float]], y_unit: str
) -> str:
    """Render one sampled resource series as a compact inline SVG."""
    if len(points) < 2:
        return '<p class="muted">Too few samples were available for a time-series chart.</p>'
    width = 920
    height = 260
    left = 70
    top = 40
    plot_width = 810
    plot_height = 170
    max_x = max(point[0] for point in points) or 1.0
    max_y = max(point[1] for point in points) or 1.0
    coordinates = " ".join(
        (
            f"{left + plot_width * x / max_x:.2f},"
            f"{top + plot_height - plot_height * y / max_y:.2f}"
        )
        for x, y in points
    )
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_escape(title)}"><title>{_escape(title)}</title>'
        f'<text x="10" y="24" class="chart-title">{_escape(title)}</text>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" '
        'class="axis" />'
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" '
        f'y2="{top + plot_height}" class="axis" />'
        f'<polyline points="{coordinates}" class="line" />'
        f'<text x="8" y="{top + 8}" class="axis-label">{max_y:,.2f} {_escape(y_unit)}</text>'
        f'<text x="{left}" y="{height - 18}" class="axis-label">0 s</text>'
        f'<text x="{left + plot_width - 70}" y="{height - 18}" '
        f'class="axis-label">{max_x:,.1f} s</text></svg>'
    )


def _timeseries_points(path: Path, sample_count: int) -> dict[str, list[tuple[float, float]]]:
    """Read bounded CPU and RSS points from a stage's compressed benchmark series."""
    maximum_points = 400
    step = max(1, math.ceil(max(1, sample_count) / maximum_points))
    cpu: list[tuple[float, float]] = []
    rss: list[tuple[float, float]] = []
    if not path.is_file():
        return {"cpu": cpu, "rss": rss}
    with _open_text(path) as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for index, row in enumerate(reader):
            if index % step:
                continue
            elapsed = _number(row.get("elapsed_seconds"))
            cpu.append((elapsed, _number(row.get("interval_cpu_cores"))))
            rss.append((elapsed, _number(row.get("rss_bytes")) / (1024.0**2)))
    return {"cpu": cpu, "rss": rss}


def _result_html(summary: Mapping[str, Any], link_prefix: str) -> str:
    """Render one declared-output summary and its bounded preview."""
    path = str(summary.get("path", ""))
    warning = str(summary.get("warning", ""))
    sections = [
        f'<article class="result"><h3><a href="{_escape(link_prefix + path)}">'
        f'{_escape(path)}</a></h3>',
        _key_value_table(
            (
                ("Type", summary.get("kind", "file")),
                ("Summary", summary.get("summary", "")),
                ("Size", _human_bytes(_integer(summary.get("size_bytes")))),
                ("SHA-256", summary.get("sha256", "")),
            )
        ),
    ]
    preview = summary.get("preview")
    columns = summary.get("columns")
    if isinstance(preview, list) and isinstance(columns, list) and columns:
        preview_rows = [
            [row.get(column, "") for column in columns]
            for row in preview
            if isinstance(row, dict)
        ]
        sections.extend(["<h4>Bounded preview</h4>", _table(columns, preview_rows)])
        if summary.get("columns_truncated"):
            sections.append('<p class="muted">Additional columns are present in the source.</p>')
    identifiers = summary.get("identifiers")
    if isinstance(identifiers, list) and identifiers:
        sections.append(
            "<h4>First sequence identifiers</h4><p><code>"
            + "</code>, <code>".join(_escape(value) for value in identifiers)
            + "</code></p>"
        )
    text_preview = summary.get("text_preview")
    if isinstance(text_preview, list) and text_preview:
        sections.append(
            "<h4>Bounded text preview</h4><pre>"
            + _escape("\n".join(str(value) for value in text_preview))
            + "</pre>"
        )
    if warning:
        sections.append(
            f'<p class="warning"><strong>Inspection note:</strong> {_escape(warning)}</p>'
        )
    sections.append("</article>")
    return "".join(sections)


def _input_records(config: WorkflowConfig, stage_name: str) -> list[tuple[object, ...]]:
    """Return checksum-bound direct inputs for a stage report."""
    dependencies = stage_dependencies(stage_name)
    paths: list[tuple[str, Path]] = []
    if dependencies:
        paths.extend(
            (
                f"stage manifest: {dependency}",
                config.run_root / dependency / "stage_manifest.json",
            )
            for dependency in dependencies
        )
    else:
        input_labels = {
            "proteomes": "proteome manifest",
            "seeds": "known-E3 evidence manifest",
            "shortlist": "shortlist manifest",
        }
        paths.append(("workflow configuration", config.source_path))
        paths.extend(
            (input_labels[label], path) for label, path in controlled_input_paths(config)
        )
    return [
        (label, path, _human_bytes(path.stat().st_size), sha256_file(path))
        for label, path in paths
    ]


def _document(*, title: str, body: str) -> str:
    """Wrap report content in a complete, portable HTML5 document."""
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>
<style>
:root {{ --ink:#172033; --muted:#5f6b7a; --blue:#2459a9; --pale:#eef4fb;
  --line:#d8e0ea; --good:#177245; --warn:#8a5600; --paper:#ffffff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; color:var(--ink); background:#f4f7fa; font-family:Arial, sans-serif;
  line-height:1.55; }}
main {{ max-width:1180px; margin:0 auto; background:var(--paper); min-height:100vh;
  padding:2.2rem 3rem 4rem; box-shadow:0 0 24px rgba(25,45,75,.08); }}
h1 {{ font-size:2rem; margin:.2rem 0 .4rem; }} h2 {{ margin-top:2.2rem; border-bottom:2px solid
  var(--pale); padding-bottom:.35rem; }} h3 {{ margin-top:1.5rem; }} h4 {{ margin-bottom:.35rem; }}
a {{ color:var(--blue); }} code, pre {{ font-family:Consolas, Menlo, monospace; }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#f7f9fc;
  border:1px solid var(--line);
  border-radius:6px; padding:.9rem; }}
.eyebrow {{ color:var(--blue); font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
.lede {{ font-size:1.08rem; max-width:950px; }} .muted {{ color:var(--muted); }}
.status {{ display:inline-block; padding:.22rem .65rem; color:white; background:var(--good);
  border-radius:999px; font-size:.85rem; font-weight:700; }}
.warning {{ background:#fff7df; border-left:5px solid #d99a19; padding:.75rem 1rem; }}
.synthetic {{ background:#fff0f0; border:2px solid #b42318; padding:.8rem 1rem; font-weight:700; }}
.callout {{ background:var(--pale); border-left:5px solid var(--blue); padding:.9rem 1rem; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:.8rem;
  margin:1rem 0; }}
.card {{ border:1px solid var(--line); border-radius:8px; padding:.9rem; background:#fbfcfe; }}
.card-label {{ color:var(--muted); font-size:.82rem; text-transform:uppercase;
  letter-spacing:.04em; }}
.card-value {{ font-size:1.45rem; font-weight:700; margin:.2rem 0; }}
.card-note {{ font-size:.84rem; }}
.table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:7px; margin:.7rem 0; }}
table {{ width:100%; border-collapse:collapse; font-size:.9rem; }} th {{ background:#edf3fa;
  text-align:left; }} th, td {{ padding:.52rem .62rem; border-bottom:1px solid var(--line);
  vertical-align:top; overflow-wrap:anywhere; }} tr:last-child td {{ border-bottom:0; }}
.chart {{ width:100%; min-height:180px; border:1px solid var(--line); border-radius:7px;
  background:#fff; margin:.7rem 0; }}
.chart-title {{ font-size:16px; font-weight:700; fill:var(--ink); }}
.axis-label, .value-label {{ font-size:12px; fill:#465468; }}
.axis {{ stroke:#8290a3; stroke-width:1; }}
.bar {{ fill:#4b78b8; }} .line {{ fill:none; stroke:#2459a9; stroke-width:2.5; }}
.result {{ border:1px solid var(--line); border-radius:8px; padding:.2rem 1rem 1rem;
  margin:1rem 0; }}
.stage-section {{ border-top:4px solid var(--blue); padding-top:.4rem; margin-top:2.5rem; }}
nav ul {{ columns:2; padding-left:1.2rem; }}
footer {{ margin-top:3rem; border-top:1px solid var(--line);
  padding-top:1rem; color:var(--muted); font-size:.85rem; }}
@media (max-width:720px) {{ main {{ padding:1.2rem; }} nav ul {{ columns:1; }} }}
@media print {{ body {{ background:white; }} main {{ box-shadow:none; max-width:none; }}
  a {{ color:inherit; }} }}
</style>
</head>
<body><main>{body}</main></body>
</html>
"""


def write_stage_report(
    *,
    config: WorkflowConfig,
    stage_name: str,
    stage_root: Path,
    stage_summary: Mapping[str, Any],
    result_summaries: Sequence[Mapping[str, Any]],
    output_inventory: Sequence[Mapping[str, Any]],
) -> Path:
    """Write a verbose HTML report inside a validated temporary stage.

    Args:
        config: Validated workflow configuration.
        stage_name: Stable stage identifier.
        stage_root: Temporary stage directory before atomic publication.
        stage_summary: Provisional manifest content.
        result_summaries: Bounded summaries of declared outputs.
        output_inventory: Checksummed files present before report generation.

    Returns:
        Path to the generated stage HTML report.
    """
    purpose, rationale = stage_purpose(stage_name)
    interpretation, limitation = stage_interpretation(stage_name)
    benchmark = stage_summary.get("benchmark", {})
    if not isinstance(benchmark, dict):
        benchmark = {}
    execution = stage_summary.get("execution", {})
    if not isinstance(execution, dict):
        execution = {}
    points = _timeseries_points(
        stage_root / "benchmark" / "stage_resource_timeseries.tsv.gz",
        _integer(benchmark.get("sample_count")),
    )
    result_html = "".join(_result_html(summary, "../") for summary in result_summaries)
    if not result_html:
        result_html = '<p class="muted">No declared scientific outputs for this optional stage.</p>'
    command = str(execution.get("display_command", ""))
    dependencies = stage_dependencies(stage_name)
    status = str(stage_summary.get("status", "unknown"))
    synthetic_warning = (
        '<p class="synthetic">SYNTHETIC TEST RUN — NOT A SCIENTIFIC RESULT</p>'
        if config.mode == "synthetic"
        else ""
    )
    cards = _cards(
        (
            ("Status", status, "Published only after declared outputs passed validation."),
            ("Wall time", f"{_number(benchmark.get('wall_seconds')):,.2f} s", "Monitored scope."),
            ("CPU time", f"{_number(benchmark.get('total_cpu_seconds')):,.2f} s", "User + system."),
            (
                "Peak RSS",
                f"{_number(benchmark.get('peak_rss_mb')):,.2f} MiB",
                "Sampled process tree.",
            ),
            ("Outputs", str(len(result_summaries)), "Declared result contract."),
            (
                "Published files",
                str(len(output_inventory)),
                "Files present before this report was added.",
            ),
        )
    )
    output_size_items = [
        (str(item.get("path", "")), float(_integer(item.get("size_bytes"))))
        for item in result_summaries
    ]
    log_links = '<a href="../logs/stage.log">stage log</a>'
    if (stage_root / "logs" / "command.log").is_file():
        log_links += ' · <a href="../logs/command.log">unmodified command output</a>'
    identity_table = _key_value_table(
        (
            ("Run name", config.run_name),
            ("Mode", config.mode),
            ("Evidence mode", stage_summary.get("evidence_mode", "")),
            ("Configuration", config.source_path),
            ("Configuration digest", config.digest),
            ("Package version", __version__),
            (
                "Prerequisite stages",
                ", ".join(dependencies) or "controlled input manifests",
            ),
        )
    )
    input_table = _table(
        ("Input role", "Path", "Size", "SHA-256"),
        _input_records(config, stage_name),
    )
    execution_table = _key_value_table(
        (
            ("Implementation", execution.get("implementation", "")),
            ("Working directory", execution.get("working_directory", "")),
            ("Started", stage_summary.get("started_at_utc", "")),
            ("Finished", stage_summary.get("finished_at_utc", "")),
            ("Requested threads", benchmark.get("requested_threads", "")),
            ("Requested memory", f"{benchmark.get('requested_memory_mb', '')} MiB"),
            (
                "Requested runtime",
                f"{benchmark.get('requested_runtime_minutes', '')} min",
            ),
        )
    )
    output_chart = _bar_chart(
        title="Declared output sizes",
        items=output_size_items,
        unit="bytes",
        maximum_items=config.reporting.max_chart_items,
    )
    resource_table = _key_value_table(
        (
            ("Measurement scope", benchmark.get("measurement_scope", "")),
            ("Accounting method", benchmark.get("memory_accounting_method", "")),
            ("Samples", benchmark.get("sample_count", "")),
            ("Mean CPU cores", benchmark.get("mean_cpu_cores", "")),
            (
                "CPU efficiency",
                f"{_number(benchmark.get('cpu_efficiency_percent')):,.2f}%",
            ),
            ("Peak VMS", f"{_number(benchmark.get('peak_vms_mb')):,.2f} MiB"),
            ("Read", _human_bytes(_integer(benchmark.get("read_bytes")))),
            ("Written", _human_bytes(_integer(benchmark.get("write_bytes")))),
            ("Maximum processes", benchmark.get("maximum_process_count", "")),
            ("Maximum threads", benchmark.get("maximum_thread_count", "")),
            ("Scheduler", benchmark.get("scheduler", "")),
            ("Slurm job", benchmark.get("slurm_job_id", "")),
        )
    )
    cpu_chart = _line_chart(
        title="CPU use through the stage",
        points=points["cpu"],
        y_unit="cores",
    )
    rss_chart = _line_chart(
        title="Resident memory through the stage",
        points=points["rss"],
        y_unit="MiB",
    )
    inventory_rows = [
        (
            item.get("path", ""),
            _human_bytes(_integer(item.get("size_bytes"))),
            item.get("sha256", ""),
        )
        for item in output_inventory
    ]
    inventory_table = _table(("Relative path", "Size", "SHA-256"), inventory_rows)
    body = f"""
<p class="eyebrow">ARIA plant E3 workflow · stage report</p>
<h1>{_escape(stage_name)}</h1>
<p><span class="status">{_escape(status)}</span></p>
{synthetic_warning}
<p class="lede">{_escape(purpose)}</p>
{cards}
<nav aria-label="Report sections"><h2>Contents</h2><ul>
<li><a href="#interpretation">Scientific summary</a></li>
<li><a href="#inputs">Inputs and provenance</a></li>
<li><a href="#execution">Computation and command</a></li>
<li><a href="#results">Results</a></li>
<li><a href="#resources">Resource use</a></li>
<li><a href="#outputs">Output inventory</a></li></ul></nav>
<section id="interpretation"><h2>Scientific summary</h2>
<h3>Why this stage exists</h3><p>{_escape(rationale)}</p>
<div class="callout"><strong>Supported interpretation:</strong> {_escape(interpretation)}</div>
<p class="warning"><strong>Limit:</strong> {_escape(limitation)}</p></section>
<section id="inputs"><h2>Inputs and provenance</h2>
<p>Direct prerequisites were checksum-validated before execution. The configuration digest binds
this stage to the complete resolved YAML content.</p>
{identity_table}
{input_table}</section>
<section id="execution"><h2>Computation and command</h2>
<p>The command is recorded as an argument vector and displayed with shell quoting for readability.
The argument-vector representation remains authoritative.</p>
{execution_table}
<pre>{_escape(command or "No external command: validated internal implementation.")}</pre>
<p>Logs: {log_links}</p></section>
"""
    body += f"""
<section id="results"><h2>Results</h2>
<p>Only declared outputs are interpreted here. Previews are deliberately bounded; the linked files
and recorded checksums remain authoritative.</p>{result_html}
{output_chart}</section>
<section id="resources"><h2>Resource use</h2>
{resource_table}
{cpu_chart}
{rss_chart}
<p class="muted">Process-tree values are sampled. Slurm accounting, when available, is reported
independently in the full-run report.</p></section>
<section id="outputs"><h2>Output inventory</h2>{inventory_table}</section>
<footer>Generated {_escape(utc_now())} by e3-end-to-end-workflow {_escape(__version__)}.
This report is descriptive evidence from the recorded run and does not replace the machine-readable
stage manifest.</footer>
"""
    destination = stage_root / "report" / REPORT_FILENAME
    atomic_write_text(destination, _document(title=f"{stage_name} stage report", body=body))
    return destination


def record_workflow_invocation(
    *, config: WorkflowConfig, argv: Sequence[str], working_directory: Path | None = None
) -> dict[str, object]:
    """Append an exact shell-to-Snakemake invocation to run provenance.

    Args:
        config: Validated workflow configuration.
        argv: Non-empty command argument vector.
        working_directory: Directory from which the wrapper launched the command.

    Returns:
        The newly appended invocation record and provenance path.
    """
    arguments = [str(value) for value in argv]
    if arguments and arguments[0] == "--":
        arguments = arguments[1:]
    if not arguments:
        raise WorkflowError("Workflow invocation must contain a command argument vector")
    path = config.run_root / "workflow_logs" / "workflow_invocations.json"
    if path.is_file():
        payload = read_json(path)
        invocations = payload.get("invocations")
        if not isinstance(invocations, list):
            raise WorkflowError(f"Invalid workflow invocation history: {path}")
    else:
        invocations = []
    record = {
        "recorded_at_utc": utc_now(),
        "working_directory": str((working_directory or Path.cwd()).resolve()),
        "configuration": str(config.source_path),
        "configuration_digest": config.digest,
        "package_version": __version__,
        "argv": arguments,
        "display_command": shlex.join(arguments),
    }
    invocations.append(record)
    atomic_write_json(path, {"schema_version": 1, "invocations": invocations})
    return {"status": "recorded", "path": str(path), "invocation": record}


def _load_stage_manifests(config: WorkflowConfig) -> list[dict[str, Any]]:
    """Load and validate all complete stage manifests for final reporting."""
    manifests = []
    for stage_name in STAGE_NAMES:
        path = config.run_root / stage_name / "stage_manifest.json"
        payload = read_json(path)
        if payload.get("stage") != stage_name:
            raise WorkflowError(f"Stage report identity differs: {path}")
        if payload.get("configuration_digest") != config.digest:
            raise WorkflowError(f"Stage report configuration digest differs: {path}")
        if payload.get("status") not in {"complete", "skipped_optional"}:
            raise WorkflowError(f"Stage is not complete for final reporting: {path}")
        manifests.append(payload)
    return manifests


def _workflow_metric_map(config: WorkflowConfig) -> dict[str, dict[str, str]]:
    """Load the completed workflow benchmark metrics by stable metric name."""
    _, rows = read_tsv(config.run_root / "benchmark_summary" / "workflow_resource_summary.tsv")
    return {row["metric"]: row for row in rows}


def _metric_value(metrics: Mapping[str, Mapping[str, str]], name: str) -> str:
    """Return one workflow metric value or an explicit unavailable label."""
    return str(metrics.get(name, {}).get("value", "not available"))


def _stage_section(manifest: Mapping[str, Any]) -> str:
    """Render one stage's concise section in the full-run report."""
    stage_name = str(manifest.get("stage", ""))
    benchmark = manifest.get("benchmark", {})
    if not isinstance(benchmark, dict):
        benchmark = {}
    execution = manifest.get("execution", {})
    if not isinstance(execution, dict):
        execution = {}
    results = manifest.get("result_summaries", [])
    if not isinstance(results, list):
        results = []
    interpretation, limitation = stage_interpretation(stage_name)
    result_rows = [
        (
            result.get("path", ""),
            result.get("kind", ""),
            result.get("summary", ""),
            _human_bytes(_integer(result.get("size_bytes"))),
        )
        for result in results
        if isinstance(result, dict)
    ]
    stage_cards = _cards(
        (
            (
                "Wall time",
                f"{_number(benchmark.get('wall_seconds')):,.2f} s",
                "Monitored scope.",
            ),
            (
                "CPU time",
                f"{_number(benchmark.get('total_cpu_seconds')):,.2f} s",
                "User + system.",
            ),
            (
                "Peak RSS",
                f"{_number(benchmark.get('peak_rss_mb')):,.2f} MiB",
                "Sampled process tree.",
            ),
            ("Declared results", str(len(result_rows)), "Validated output contract."),
        )
    )
    display_command = execution.get(
        "display_command",
        "No external command: validated internal implementation.",
    )
    result_table = _table(("Output", "Type", "Summary", "Size"), result_rows)
    return f"""
<section class="stage-section" id="{_escape(stage_name)}"><h2>{_escape(stage_name)}</h2>
<p><span class="status">{_escape(manifest.get("status", ""))}</span></p>
<p><strong>Evidence mode:</strong> {_escape(manifest.get("evidence_mode", ""))}</p>
<p class="lede">{_escape(manifest.get("purpose", ""))}</p>
<p><strong>Why:</strong> {_escape(manifest.get("rationale", ""))}</p>
<div class="callout"><strong>Supported interpretation:</strong> {_escape(interpretation)}</div>
<p class="warning"><strong>Limit:</strong> {_escape(limitation)}</p>{stage_cards}
<h3>Command</h3><pre>{_escape(display_command)}</pre>
<h3>Result summary</h3>
{result_table}
<p><a href="../{_escape(stage_name)}/report/{REPORT_FILENAME}">Open the verbose stage report</a>
 · <a href="../{_escape(stage_name)}/stage_manifest.json">machine-readable manifest</a></p>
</section>
"""


def generate_run_report(*, config: WorkflowConfig, output_dir: Path) -> dict[str, object]:
    """Atomically publish the consolidated HTML report for a complete run.

    Args:
        config: Validated workflow configuration.
        output_dir: Formal run-report directory.

    Returns:
        Machine-readable report paths and stage count.
    """
    manifests = _load_stage_manifests(config)
    skipped_stages = [
        str(manifest["stage"])
        for manifest in manifests
        if manifest.get("status") == "skipped_optional"
    ]
    application_release_eligible = config.mode == "production" and not skipped_stages
    scope_label = "complete configured run" if skipped_stages else "complete workflow"
    skipped_noun = "stage was" if len(skipped_stages) == 1 else "stages were"
    scope_description = (
        f"{len(skipped_stages)} optional {skipped_noun} explicitly skipped: "
        + ", ".join(skipped_stages)
        if skipped_stages
        else "All twelve scientific stages completed."
    )
    metrics = _workflow_metric_map(config)
    benchmark_manifest_path = config.run_root / "benchmark_summary" / "benchmark_manifest.json"
    benchmark_manifest = read_json(benchmark_manifest_path)
    if benchmark_manifest.get("configuration_digest") != config.digest:
        raise WorkflowError("Benchmark and workflow configuration digests differ")
    invocation_path = config.run_root / "workflow_logs" / "workflow_invocations.json"
    invocation_rows: list[tuple[object, ...]] = []
    if invocation_path.is_file():
        invocation_payload = read_json(invocation_path)
        invocations = invocation_payload.get("invocations", [])
        if not isinstance(invocations, list):
            raise WorkflowError(f"Invalid workflow invocation history: {invocation_path}")
        invocation_rows = [
            (
                item.get("recorded_at_utc", ""),
                item.get("working_directory", ""),
                item.get("display_command", ""),
            )
            for item in invocations
            if isinstance(item, dict)
        ]
    stage_values = []
    for manifest in manifests:
        benchmark = manifest.get("benchmark", {})
        if not isinstance(benchmark, dict):
            benchmark = {}
        stage_values.append(
            {
                "stage": str(manifest["stage"]),
                "wall": _number(benchmark.get("wall_seconds")),
                "cpu": _number(benchmark.get("total_cpu_seconds")),
                "rss": _number(benchmark.get("peak_rss_mb")),
                "bytes": sum(
                    _integer(output.get("size_bytes"))
                    for output in manifest.get("outputs", [])
                    if isinstance(output, dict)
                ),
            }
        )
    metric_rows = [
        (
            row.get("metric", ""),
            row.get("value", ""),
            row.get("unit", ""),
            row.get("interpretation", ""),
        )
        for row in metrics.values()
    ]
    synthetic_warning = (
        '<p class="synthetic">SYNTHETIC TEST RUN — NOT A SCIENTIFIC RESULT</p>'
        if config.mode == "synthetic"
        else ""
    )
    navigation = "".join(
        f'<li><a href="#{_escape(stage_name)}">{_escape(stage_name)}</a></li>'
        for stage_name in STAGE_NAMES
    )
    largest_stage_rss = _number(
        _metric_value(metrics, "maximum_individual_stage_peak_rss_mb")
    )
    summary_cards = _cards(
        (
            (
                "Stages",
                str(len(manifests)),
                f"{len(manifests) - len(skipped_stages)} complete; "
                f"{len(skipped_stages)} explicitly skipped.",
            ),
            (
                "Observed span",
                f"{_number(_metric_value(metrics, 'workflow_observed_span_seconds')):,.2f} s",
                "Includes concurrency and resume gaps.",
            ),
            (
                "Total CPU",
                f"{_number(_metric_value(metrics, 'total_cpu_seconds')):,.2f} s",
                "Summed monitored CPU.",
            ),
            (
                "Largest stage RSS",
                f"{largest_stage_rss:,.2f} MiB",
                "Not workflow-wide concurrent RAM.",
            ),
            (
                "Published data",
                _human_bytes(
                    _integer(_metric_value(metrics, "total_published_output_bytes"))
                ),
                "Summed checksummed stage files.",
            ),
        )
    )
    identity_table = _key_value_table(
        (
            ("Run name", config.run_name),
            ("Mode", config.mode),
            ("Application release eligible", str(application_release_eligible).lower()),
            ("Run scope", scope_label),
            ("Scope detail", scope_description),
            ("Project root", config.project_root),
            ("Run root", config.run_root),
            ("Configuration", config.source_path),
            ("Configuration digest", config.digest),
            ("Package version", __version__),
            ("OrthoFinder policy", "exactly 2.5.5"),
            ("Benchmark manifest SHA-256", sha256_file(benchmark_manifest_path)),
        )
    )
    input_table = _table(
        ("Input role", "Path", "Size", "SHA-256"),
        _input_records(config, "00_inputs"),
    )
    invocation_table = _table(
        ("Recorded at (UTC)", "Working directory", "Command"),
        invocation_rows,
    )
    chart_limit = config.reporting.max_chart_items
    wall_chart = _bar_chart(
        title="Stage wall time",
        items=[(item["stage"], item["wall"]) for item in stage_values],
        unit="s",
        maximum_items=chart_limit,
    )
    cpu_chart = _bar_chart(
        title="Stage CPU time",
        items=[(item["stage"], item["cpu"]) for item in stage_values],
        unit="s",
        maximum_items=chart_limit,
    )
    rss_chart = _bar_chart(
        title="Peak resident memory by stage",
        items=[(item["stage"], item["rss"]) for item in stage_values],
        unit="MiB",
        maximum_items=chart_limit,
    )
    size_chart = _bar_chart(
        title="Checksummed output size by stage",
        items=[(item["stage"], item["bytes"]) for item in stage_values],
        unit="bytes",
        maximum_items=chart_limit,
    )
    metrics_table = _table(("Metric", "Value", "Unit", "Interpretation"), metric_rows)
    body = f"""
<p class="eyebrow">ARIA plant E3 workflow · {_escape(scope_label)} report</p>
<h1>{_escape(config.run_name)}</h1>
<p><span class="status">complete</span></p>{synthetic_warning}
<p class="lede">This self-contained report joins scientific stage summaries, validated inputs and
outputs, exact commands, computation metrics, resource measurements, provenance and interpretation
limits for the configured run. {_escape(scope_description)}</p>
{summary_cards}
<nav aria-label="Stage sections"><h2>Stage index</h2><ul>{navigation}</ul></nav>
<section><h2>Run identity and controlled inputs</h2>
{identity_table}
{input_table}
<h3>Shell-to-Snakemake invocation history</h3>
{invocation_table}
</section>
<section><h2>Computation overview</h2>
{wall_chart}
{cpu_chart}
{rss_chart}
{size_chart}
<h3>Workflow metrics</h3>
{metrics_table}
<p class="muted">Summed stage wall time is not elapsed workflow time when independent branches run
concurrently. Peak RSS is the maximum for one stage, not simultaneous workflow-wide memory.</p>
</section>
<section><h2>Scientific interpretation policy</h2>
<p>Evidence types remain separate. DeepClust clusters are sequence-similarity constructs;
OrthoFinder orthogroups are run-specific phylogenomic constructs; predicted pockets and expression
are supporting evidence. None alone proves E3 function, orthology, ligand binding or efficacy.</p>
</section>
"""
    body += "".join(_stage_section(manifest) for manifest in manifests)
    body += (
        "<footer>Generated "
        + _escape(utc_now())
        + " by e3-end-to-end-workflow "
        + _escape(__version__)
        + ". Machine-readable manifests, TSV summaries and original outputs remain authoritative."
        "</footer>"
    )
    destination = Path(output_dir).resolve()
    staging = config.run_root / ".staging" / f"reports.{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        html_path = staging / RUN_REPORT_FILENAME
        completion_path = staging / "report_complete.tsv"
        manifest_path = staging / "report_manifest.json"
        atomic_write_text(
            html_path,
            _document(title=f"{config.run_name} workflow report", body=body),
        )
        write_tsv(
            completion_path,
            (
                {
                    "status": "complete",
                    "stage_count": len(manifests),
                    "skipped_stage_count": len(skipped_stages),
                    "application_release_eligible": str(application_release_eligible).lower(),
                    "configuration_digest": config.digest,
                    "finished_at_utc": utc_now(),
                },
            ),
            (
                "status",
                "stage_count",
                "skipped_stage_count",
                "application_release_eligible",
                "configuration_digest",
                "finished_at_utc",
            ),
        )
        outputs = inventory_files(staging, frozenset({manifest_path.name}))
        atomic_write_json(
            manifest_path,
            {
                "status": "complete",
                "package_version": __version__,
                "configuration": str(config.source_path),
                "configuration_digest": config.digest,
                "run_root": str(config.run_root),
                "stage_count": len(manifests),
                "skipped_stages": skipped_stages,
                "application_release_eligible": application_release_eligible,
                "benchmark_manifest": str(benchmark_manifest_path),
                "outputs": outputs,
            },
        )
        if destination.exists():
            superseded = config.run_root / "superseded" / f"reports.{uuid.uuid4().hex}"
            superseded.parent.mkdir(parents=True, exist_ok=True)
            os.replace(destination, superseded)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, destination)
    except BaseException:
        failed = config.run_root / "failed" / staging.name
        failed.parent.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            shutil.move(str(staging), str(failed))
        raise
    return {
        "status": "complete",
        "stage_count": len(manifests),
        "skipped_stage_count": len(skipped_stages),
        "application_release_eligible": application_release_eligible,
        "html_report": str(destination / RUN_REPORT_FILENAME),
        "manifest": str(destination / "report_manifest.json"),
    }
