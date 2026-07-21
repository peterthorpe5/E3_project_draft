"""Read-only, bounded DuckDB queries independent of Streamlit."""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

import duckdb
import pandas as pd

from e3app.errors import AppError

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ACCESSION_COLUMNS = (
    "accession",
    "entry",
    "protein_accession",
    "candidate_accession",
    "parsed_accession",
)


def quote_identifier(identifier: str) -> str:
    """Validate and quote a simple DuckDB identifier."""

    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise AppError(f"Unsafe DuckDB identifier: {identifier!r}")
    return f'"{identifier}"'


@contextmanager
def open_read_only(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open and always close a read-only DuckDB connection."""

    source = path.expanduser().resolve()
    if not source.is_file():
        raise AppError(f"DuckDB does not exist: {source}")
    try:
        connection = duckdb.connect(str(source), read_only=True)
    except duckdb.Error as exc:
        raise AppError(f"Could not open DuckDB read-only: {source}: {exc}") from exc
    try:
        yield connection
    finally:
        connection.close()


def list_relations(connection: duckdb.DuckDBPyConnection) -> list[str]:
    """List user tables and views in deterministic order."""

    rows = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY lower(table_name), table_name
        """
    ).fetchall()
    relations = [str(row[0]) for row in rows if IDENTIFIER_PATTERN.fullmatch(str(row[0]))]
    return relations


def relation_columns(connection: duckdb.DuckDBPyConnection, relation: str) -> list[str]:
    """Return columns for a validated relation."""

    quoted = quote_identifier(relation)
    rows = connection.execute(f"DESCRIBE SELECT * FROM {quoted}").fetchall()
    return [str(row[0]) for row in rows]


def relation_count(connection: duckdb.DuckDBPyConnection, relation: str) -> int:
    """Count rows in one validated relation."""

    quoted = quote_identifier(relation)
    return int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])


def preview_relation(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    limit: int,
) -> pd.DataFrame:
    """Return a bounded preview without collecting a whole relation."""

    if limit < 1 or limit > 100_000:
        raise AppError("preview limit must be between 1 and 100000")
    quoted = quote_identifier(relation)
    return connection.execute(f"SELECT * FROM {quoted} LIMIT ?", [limit]).fetchdf()


def resource_overview(
    connection: duckdb.DuckDBPyConnection,
    relations: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Summarise relation names, columns, rows, and inferred capabilities."""

    selected = list_relations(connection) if relations is None else list(relations)
    records = []
    for relation in selected:
        columns = relation_columns(connection, relation)
        records.append(
            {
                "relation": relation,
                "row_count": relation_count(connection, relation),
                "column_count": len(columns),
                "capability": infer_capability(relation, columns),
            }
        )
    return pd.DataFrame.from_records(
        records,
        columns=("relation", "row_count", "column_count", "capability"),
    )


def infer_capability(relation: str, columns: Sequence[str]) -> str:
    """Classify a relation for navigation without changing scientific content."""

    text = " ".join([relation, *columns]).lower()
    for capability, terms in (
        ("orthology", ("orthogroup", "hog")),
        ("ligandability", ("pocket", "fpocket", "p2rank")),
        ("expression", ("expression", "tpm", "fpkm")),
        ("provenance", ("manifest", "provenance", "checksum")),
        ("candidate", ("candidate", "cluster")),
    ):
        if any(term in text for term in terms):
            return capability
    return "resource"


def search_accession(
    connection: duckdb.DuckDBPyConnection,
    accession: str,
    limit_per_relation: int = 100,
) -> pd.DataFrame:
    """Search recognised accession columns using bound SQL parameters."""

    query = accession.strip()
    if not query or len(query) > 200:
        raise AppError("accession query must contain between 1 and 200 characters")
    if limit_per_relation < 1 or limit_per_relation > 10_000:
        raise AppError("limit_per_relation must be between 1 and 10000")
    frames = []
    for relation in list_relations(connection):
        columns = relation_columns(connection, relation)
        case_insensitive_columns = {name.lower(): name for name in columns}
        recognised_columns = (
            case_insensitive_columns[name]
            for name in ACCESSION_COLUMNS
            if name in case_insensitive_columns
        )
        accession_column = next(recognised_columns, None)
        if accession_column is None:
            continue
        sql = (
            f"SELECT ? AS _relation, * FROM {quote_identifier(relation)} "
            f"WHERE upper(CAST({quote_identifier(accession_column)} AS VARCHAR)) = upper(?) LIMIT ?"
        )
        frame = connection.execute(sql, [relation, query, limit_per_relation]).fetchdf()
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["_relation"])
    return pd.concat(frames, ignore_index=True, sort=False)
