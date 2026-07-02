"""DuckDB view creation for the E3 PROTAC Parquet resource."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from e3parquet.io_utils import (
    is_probable_parquet_file,
    normalise_relative_path,
    path_has_hidden_or_macos_sidecar_part,
    safe_name,
)

LOGGER = logging.getLogger(__name__)


def parquet_paths(root: Path, validate_magic: bool = True) -> List[Path]:
    """Return usable Parquet files under a directory.

    macOS AppleDouble sidecar files often look like ``._name.parquet`` but are
    not real Parquet files. These are always skipped. When ``validate_magic`` is
    true, files must also have the expected PAR1 header/footer before they are
    handed to DuckDB.
    """
    if not root.exists():
        return []

    paths: List[Path] = []
    for path in sorted(root.rglob("*.parquet")):
        if not path.is_file():
            continue
        if path_has_hidden_or_macos_sidecar_part(path):
            LOGGER.warning("Skipping hidden/macOS sidecar file: %s", path)
            continue
        if validate_magic and not is_probable_parquet_file(path):
            LOGGER.warning("Skipping invalid Parquet-like file: %s", path)
            continue
        paths.append(path)
    return paths


def duckdb_quote(value: str) -> str:
    """Quote a string literal for DuckDB SQL."""
    return "'" + value.replace("'", "''") + "'"


def view_name_for_parquet(parquet_path: Path, derived_dir: Path) -> str:
    """Create a stable DuckDB view name for a Parquet file."""
    relative = parquet_path.relative_to(derived_dir).as_posix()
    if relative.endswith(".parquet"):
        relative = relative[: -len(".parquet")]
    return safe_name(relative.replace("/", "__"))


def create_views_for_parquets(
    derived_dir: Path,
    duckdb_path: Path,
    overwrite: bool = True,
    validate_magic: bool = True,
) -> List[Dict[str, str]]:
    """Create one DuckDB view per usable Parquet file.

    Parameters
    ----------
    derived_dir:
        Directory containing Parquet outputs.
    duckdb_path:
        Destination DuckDB file.
    overwrite:
        Whether to replace existing views with the same names.
    validate_magic:
        Check Parquet magic bytes before creating views. This protects against
        macOS AppleDouble files and truncated/corrupt inherited Parquet files.

    Returns
    -------
    list of dict
        Catalog records for created views.
    """
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "duckdb is required for view creation. Install with: "
            "conda install -c conda-forge duckdb python-duckdb"
        ) from exc

    derived_dir = derived_dir.resolve()
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    catalog: List[Dict[str, str]] = []
    LOGGER.info("Creating DuckDB views in %s", duckdb_path)

    with duckdb.connect(str(duckdb_path)) as connection:
        for path in parquet_paths(derived_dir, validate_magic=validate_magic):
            view_name = view_name_for_parquet(path, derived_dir)
            relative_path = normalise_relative_path(path.relative_to(derived_dir))
            if overwrite:
                connection.execute(f'DROP VIEW IF EXISTS "{view_name}"')
            sql = (
                f'CREATE VIEW "{view_name}" AS '
                f"SELECT * FROM read_parquet({duckdb_quote(str(path))})"
            )

            try:
                connection.execute(sql)
            except Exception as exc:
                LOGGER.exception("Failed creating view for %s", path)
                catalog.append(
                    {
                        "view_name": view_name,
                        "parquet_file": relative_path,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                continue

            catalog.append(
                {
                    "view_name": view_name,
                    "parquet_file": relative_path,
                    "status": "created",
                    "error": "",
                }
            )
            LOGGER.debug("Created view %s for %s", view_name, path)

        connection.execute("DROP TABLE IF EXISTS parquet_view_catalog")
        connection.execute(
            "CREATE TABLE parquet_view_catalog("
            "view_name VARCHAR, parquet_file VARCHAR, "
            "status VARCHAR, error VARCHAR)"
        )
        if catalog:
            rows = [
                (
                    record["view_name"],
                    record["parquet_file"],
                    record["status"],
                    record["error"],
                )
                for record in catalog
            ]
            connection.executemany(
                "INSERT INTO parquet_view_catalog VALUES (?, ?, ?, ?)",
                rows,
            )

    created_count = sum(1 for record in catalog if record["status"] == "created")
    LOGGER.info("Created %d DuckDB views", created_count)
    return catalog
