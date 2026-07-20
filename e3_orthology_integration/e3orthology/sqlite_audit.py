"""Read-only regression queries against the inherited application SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .errors import InputValidationError
from .io_utils import ensure_readable_file


def connect_readonly(*, path: Path) -> sqlite3.Connection:
    """Open a SQLite database using URI-enforced read-only mode.

    Args:
        path: Existing SQLite database.

    Returns:
        Read-only connection with named-row access.
    """

    database = ensure_readable_file(path=path)
    connection = sqlite3.connect(database=f"{database.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def table_columns(*, connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    """Return SQLite table columns after validating the table name.

    Args:
        connection: Open SQLite connection.
        table_name: Exact table name.

    Returns:
        Ordered column names.

    Raises:
        InputValidationError: If the table does not exist.
    """

    table_row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = :name",
        {"name": table_name},
    ).fetchone()
    if table_row is None:
        raise InputValidationError(f"Required SQLite table does not exist: {table_name}")
    rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return tuple(str(row["name"]) for row in rows)


def lookup_inherited_groups(*, path: Path, accession: str) -> dict[str, str | None]:
    """Retrieve one accession's inherited orthogroup and hierarchical group.

    Args:
        path: Inherited SQLite database.
        accession: Bare accession identifier.

    Returns:
        Mapping containing inherited group identifiers or ``None``.

    Raises:
        InputValidationError: If schemas or accession multiplicity are invalid.
    """

    connection = connect_readonly(path=path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise InputValidationError(f"SQLite integrity check failed: {integrity}")
        expected_columns = {
            "orthogroups": {"accession", "orthogroup"},
            "hogs": {"accession", "hog"},
        }
        for table_name, expected in expected_columns.items():
            observed = set(table_columns(connection=connection, table_name=table_name))
            missing = sorted(expected - observed)
            if missing:
                raise InputValidationError(
                    f"SQLite table {table_name} is missing columns: {', '.join(missing)}"
                )
        orthogroup_rows = connection.execute(
            "SELECT DISTINCT orthogroup FROM orthogroups WHERE accession = :accession",
            {"accession": accession},
        ).fetchall()
        hierarchical_rows = connection.execute(
            "SELECT DISTINCT hog FROM hogs WHERE accession = :accession",
            {"accession": accession},
        ).fetchall()
        if len(orthogroup_rows) > 1 or len(hierarchical_rows) > 1:
            raise InputValidationError(
                f"Inherited SQLite maps accession {accession!r} to multiple group identifiers."
            )
        return {
            "accession": accession,
            "orthogroup": (None if not orthogroup_rows else str(orthogroup_rows[0]["orthogroup"])),
            "hierarchical_orthogroup": (
                None if not hierarchical_rows else str(hierarchical_rows[0]["hog"])
            ),
        }
    finally:
        connection.close()
