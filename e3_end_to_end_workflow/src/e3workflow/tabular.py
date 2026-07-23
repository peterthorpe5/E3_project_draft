"""Small, bounded DuckDB helpers for TSV, Parquet and integrated resources."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import duckdb

from e3workflow.errors import StageError
from e3workflow.io_utils import write_tsv


def quote_identifier(value: str) -> str:
    """Quote one controlled SQL identifier."""
    if not value or not (value[0].isalpha() or value[0] == "_"):
        raise StageError(f"Unsafe SQL identifier: {value!r}")
    if any(not (character.isalnum() or character == "_") for character in value):
        raise StageError(f"Unsafe SQL identifier: {value!r}")
    return f'"{value}"'


def quote_literal(value: str | Path) -> str:
    """Quote one SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def parquet_columns(path: Path) -> tuple[str, ...]:
    """Return the ordered columns of one readable Parquet file."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise StageError(f"Parquet file does not exist: {source}")
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet({quote_literal(source)})"
        ).fetchall()
        return tuple(str(row[0]) for row in rows)
    except duckdb.Error as exc:
        raise StageError(f"Could not inspect Parquet file {source}: {exc}") from exc
    finally:
        connection.close()


def parquet_row_count(path: Path) -> int:
    """Count one Parquet dataset without loading it into Python memory."""
    source = Path(path).expanduser().resolve()
    connection = duckdb.connect(":memory:")
    try:
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM read_parquet({quote_literal(source)})"
            ).fetchone()[0]
        )
    except duckdb.Error as exc:
        raise StageError(f"Could not count Parquet file {source}: {exc}") from exc
    finally:
        connection.close()


def write_records(
    *,
    tsv_path: Path,
    parquet_path: Path,
    fieldnames: Sequence[str],
    records: Iterable[Mapping[str, Any]],
    column_types: Mapping[str, str] | None = None,
) -> int:
    """Write one record stream to matching TSV and Parquet authorities.

    Args:
        tsv_path: Human-auditable TSV destination.
        parquet_path: Analytical Parquet destination.
        fieldnames: Stable output column order.
        records: Record iterable, consumed once.
        column_types: Optional DuckDB types used when there are no data rows.

    Returns:
        Number of records written.
    """
    materialised = list(records)
    write_tsv(Path(tsv_path), materialised, fieldnames)
    destination = Path(parquet_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.unlink(missing_ok=True)
    source = Path(tsv_path).expanduser().resolve()
    connection = duckdb.connect(":memory:")
    try:
        if materialised:
            sql = (
                "COPY (SELECT * FROM read_csv("
                f"{quote_literal(source)}, delim='\\t', header=true, auto_detect=true, "
                "sample_size=-1, null_padding=true)) TO "
                f"{quote_literal(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            connection.execute(sql)
        else:
            types = dict(column_types or {})
            expressions = [
                f"CAST(NULL AS {types.get(field, 'VARCHAR')}) AS {quote_identifier(field)}"
                for field in fieldnames
            ]
            connection.execute(
                "COPY (SELECT "
                + ", ".join(expressions)
                + " WHERE FALSE) TO "
                + quote_literal(temporary)
                + " (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        temporary.replace(destination)
    except duckdb.Error as exc:
        temporary.unlink(missing_ok=True)
        raise StageError(f"Could not publish Parquet table {destination}: {exc}") from exc
    finally:
        connection.close()
    return len(materialised)


def copy_query_to_parquet(
    *, connection: duckdb.DuckDBPyConnection, query: str, path: Path
) -> None:
    """Atomically write one DuckDB query to compressed Parquet."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.unlink(missing_ok=True)
    try:
        connection.execute(
            f"COPY ({query}) TO {quote_literal(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        temporary.replace(destination)
    except duckdb.Error as exc:
        temporary.unlink(missing_ok=True)
        raise StageError(f"Could not publish query as {destination}: {exc}") from exc
