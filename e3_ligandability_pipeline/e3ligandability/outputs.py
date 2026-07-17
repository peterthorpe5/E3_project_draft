"""Publication of TSV, Parquet and DuckDB analytical outputs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from . import __version__
from .io_utils import sha256_file, write_parquet_records, write_tsv_records


_LOGGER = logging.getLogger("e3ligandability.outputs")


_DATASET_TABLES = {
    "accession_status": "accession_status",
    "alphafold_metadata": "alphafold_metadata",
    "asset_manifest": "asset_manifest",
    "model_quality": "model_quality",
    "fpocket_pockets": "fpocket_pockets",
    "p2rank_pockets": "p2rank_pockets",
    "joined_pockets": "joined_pockets",
    "pocket_residue_mappings": "pocket_residue_mappings",
    "pocket_quality": "pocket_quality",
    "external_commands": "external_commands",
    "validation": "validation",
}


def publish_dataset(
    name: str,
    records: Sequence[Mapping[str, Any]],
    output_root: Path,
    write_tsv: bool,
    write_parquet: bool,
) -> list[dict[str, Any]]:
    """Publish one non-empty dataset and return file-manifest records.

    Args:
        name: Logical dataset name.
        records: Table records.
        output_root: Run output root.
        write_tsv: Write a TSV copy.
        write_parquet: Write a Parquet copy.

    Returns:
        File-manifest records. Empty datasets produce no files.
    """

    if not records:
        _LOGGER.info("Dataset %s is empty; no table file written.", name)
        return []
    root = Path(output_root).expanduser().resolve()
    manifests: list[dict[str, Any]] = []
    if write_tsv:
        tsv_path = root / "tables" / "tsv" / f"{name}.tsv"
        write_tsv_records(tsv_path, records)
        manifests.append(
            {
                "dataset": name,
                "format": "tsv",
                "path": str(tsv_path),
                "rows": len(records),
                "bytes": tsv_path.stat().st_size,
                "sha256": sha256_file(tsv_path),
            }
        )
    if write_parquet:
        parquet_path = root / "tables" / "parquet" / f"{name}.parquet"
        write_parquet_records(parquet_path, records)
        manifests.append(
            {
                "dataset": name,
                "format": "parquet",
                "path": str(parquet_path),
                "rows": len(records),
                "bytes": parquet_path.stat().st_size,
                "sha256": sha256_file(parquet_path),
            }
        )
    return manifests


def publish_all_datasets(
    datasets: Mapping[str, Sequence[Mapping[str, Any]]],
    output_root: Path,
    write_tsv: bool,
    write_parquet: bool,
) -> list[dict[str, Any]]:
    """Publish all recognised datasets in a stable order.

    Args:
        datasets: Mapping of logical dataset names to records.
        output_root: Run output root.
        write_tsv: Write TSV copies.
        write_parquet: Write Parquet copies.

    Returns:
        Combined file-manifest records.

    Raises:
        ValueError: If an unrecognised dataset name is supplied.
    """

    unknown = sorted(set(datasets).difference(_DATASET_TABLES))
    if unknown:
        raise ValueError("Unknown output datasets: " + ", ".join(unknown))
    manifests: list[dict[str, Any]] = []
    for name in _DATASET_TABLES:
        manifests.extend(
            publish_dataset(
                name=name,
                records=datasets.get(name, []),
                output_root=output_root,
                write_tsv=write_tsv,
                write_parquet=write_parquet,
            )
        )
    return manifests


def build_duckdb_from_parquet(
    parquet_manifests: Sequence[Mapping[str, Any]],
    database_path: Path,
) -> dict[str, Any]:
    """Materialise published Parquet datasets into a self-contained DuckDB.

    Args:
        parquet_manifests: File-manifest records including Parquet paths.
        database_path: Destination database path.

    Returns:
        Database file-manifest record.
    """

    destination = Path(database_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.unlink(missing_ok=True)
    connection = duckdb.connect(str(temporary))
    try:
        for manifest in parquet_manifests:
            if manifest.get("format") != "parquet":
                continue
            dataset = str(manifest["dataset"])
            if dataset not in _DATASET_TABLES:
                raise ValueError(f"Unrecognised dataset in manifest: {dataset}")
            table_name = _DATASET_TABLES[dataset]
            parquet_path = Path(str(manifest["path"])).resolve()
            quoted_path = str(parquet_path).replace("'", "''")
            connection.execute(
                f'CREATE OR REPLACE TABLE "{table_name}" AS '
                f"SELECT * FROM read_parquet('{quoted_path}')"
            )
        connection.execute(
            "CREATE OR REPLACE TABLE resource_metadata AS "
            "SELECT 'e3_ligandability_pipeline' AS resource_name, "
            f"'{__version__}' AS resource_version"
        )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    temporary.replace(destination)
    return {
        "dataset": "integrated_duckdb",
        "format": "duckdb",
        "path": str(destination),
        "rows": None,
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }


def inspect_duckdb_tables(database_path: Path) -> dict[str, int]:
    """Return materialised table row counts from a generated DuckDB.

    Args:
        database_path: Generated database.

    Returns:
        Mapping of table names to row counts.
    """

    source = Path(database_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"DuckDB does not exist: {source}")
    connection = duckdb.connect(str(source), read_only=True)
    try:
        table_names = [
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            ).fetchall()
        ]
        return {
            table_name: int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{table_name}"'
                ).fetchone()[0]
            )
            for table_name in table_names
        }
    finally:
        connection.close()
