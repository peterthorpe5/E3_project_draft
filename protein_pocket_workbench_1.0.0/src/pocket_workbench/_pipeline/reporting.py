"""Consistent TSV, materialised DuckDB, Excel and self-contained HTML exports."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import duckdb

from .excel import create_workbook
from .io import write_tsv
from .schema import DEFINITIONS, PRIMARY_KEYS, SCHEMAS, TABLE_FIELDS


def create_database(*, path: Path, tables: dict) -> None:
    """Write typed, self-contained tables with primary keys and useful views.

    Args:
        path: DuckDB destination, replaceable atomically.
        tables: Explicit-schema records, including empty tables.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.duckdb")
    temporary.unlink(missing_ok=True)
    with duckdb.connect(database=str(temporary)) as connection:
        connection.begin()
        for name, schema in SCHEMAS.items():
            fields = ", ".join(f'"{column}" {kind}' for column, kind in schema)
            keys = ", ".join(f'"{key}"' for key in PRIMARY_KEYS[name])
            connection.execute(
                query=f'CREATE TABLE "{name}" ({fields}, PRIMARY KEY ({keys}))'
            )
            if tables[name]:
                placeholders = ",".join("?" for _ in schema)
                connection.executemany(
                    query=f'INSERT INTO "{name}" VALUES ({placeholders})',
                    parameters=[
                        [row.get(column) for column, _ in schema]
                        for row in tables[name]
                    ],
                )
        connection.execute(
            query="""
            CREATE VIEW v_best_pocket_per_model AS
            SELECT * FROM ranked_pockets WHERE review_rank = 1;
            CREATE VIEW v_locally_confident_pockets AS
            SELECT * FROM ranked_pockets
            WHERE confidence_status = 'meets_local_confidence_rule';
            CREATE VIEW v_independent_p2rank AS
            SELECT * FROM pockets WHERE method = 'p2rank';
            CREATE VIEW v_model_summary AS
            SELECT s.*, COALESCE(r.cavity_count, 0) AS cavity_count,
              COALESCE(p.prediction_count, 0) AS independent_prediction_count
            FROM samples s
            LEFT JOIN (SELECT sample_id, COUNT(*) AS cavity_count
                       FROM ranked_pockets GROUP BY sample_id) r USING (sample_id)
            LEFT JOIN (SELECT sample_id, COUNT(*) AS prediction_count
                       FROM pockets WHERE method = 'p2rank'
                       GROUP BY sample_id) p USING (sample_id);
        """
        )
        connection.commit()
    temporary.replace(target=path)


def create_html(*, path: Path, tables: dict, manifest: dict) -> None:
    """Embed results safely in a dependency-free, offline HTML browser.

    Args:
        path: Report destination at the run root.
        tables: Normalised data, shared with the other exports.
        manifest: Status, timestamp and settings.
    """
    payload = {
        "samples": tables["samples"],
        "ranked": tables["ranked_pockets"],
        "pockets": tables["pockets"],
        "methods": tables["method_runs"],
        "manifest": {
            key: manifest[key]
            for key in ("status", "finished_utc", "settings", "pipeline_version")
        },
    }
    serialised = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    for character, replacement in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        serialised = serialised.replace(character, replacement)
    template = (
        files(__package__)
        .joinpath("resources/report.html")
        .read_text(encoding="utf-8")
    )
    temporary = path.with_suffix(".tmp.html")
    temporary.write_text(
        data=template.replace("__REPORT_DATA__", serialised), encoding="utf-8"
    )
    temporary.replace(target=path)


def export_results(*, root: Path, tables: dict, manifest: dict) -> None:
    """Produce all user-facing formats from the same in-memory records.

    Args:
        root: Run directory.
        tables: Complete results with every input accounted for.
        manifest: Completed run provenance.
    """
    for name, columns in TABLE_FIELDS.items():
        write_tsv(
            path=root / "tables" / f"{name}.tsv", rows=tables[name], columns=columns
        )
    dictionary = [
        {
            "table": name,
            "column": column,
            "type": kind,
            "description": "Run metadata value as JSON text"
            if name == "run_info" and column == "value"
            else DEFINITIONS[column][1],
        }
        for name, schema in SCHEMAS.items()
        for column, kind in schema
    ]
    write_tsv(
        path=root / "tables" / "field_dictionary.tsv",
        rows=dictionary,
        columns=["table", "column", "type", "description"],
    )
    create_database(path=root / "database" / "protein_pockets.duckdb", tables=tables)
    create_workbook(
        path=root / "excel" / "protein_pockets.xlsx", tables=tables, manifest=manifest
    )
    for sample in tables["samples"]:
        identifier = sample["sample_id"]
        subset = {
            name: rows
            if name == "run_info"
            else [row for row in rows if row["sample_id"] == identifier]
            for name, rows in tables.items()
        }
        create_workbook(
            path=root / "excel" / "models" / f"{identifier}.xlsx",
            tables=subset,
            manifest=manifest,
        )
    create_html(path=root / "report.html", tables=tables, manifest=manifest)
