#!/usr/bin/env python3
"""Build and validate the query-only Expression Atlas DuckDB resource.

The scientific parsing authority is the versioned Python-to-Parquet import.
This module creates read-only views over those Parquet files and proves that the
metadata join preserves exactly one row per imported gene/group context.
"""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

try:
    import duckdb
except ImportError:  # pragma: no cover - exercised on user systems
    duckdb = None


EXPRESSION_REQUIRED_COLUMNS = {
    "source_database",
    "experiment_accession",
    "species_column",
    "gene_id",
    "gene_name",
    "sample_or_condition",
    "expression_value",
    "expression_minimum",
    "expression_lower_quartile",
    "expression_median",
    "expression_upper_quartile",
    "expression_maximum",
    "expression_value_statistic",
    "expression_summary_type",
    "expression_unit",
    "source_file",
    "source_file_sha256",
}
METADATA_REQUIRED_COLUMNS = {
    "source_database",
    "experiment_accession",
    "species_column",
    "sample_or_condition",
    "atlas_group_label",
    "assay_ids",
    "assay_count",
    "organism",
    "organism_part",
    "developmental_stage",
    "genotype",
    "cultivar",
    "treatment",
    "condition",
    "assay_name",
    "source_name",
    "sample_name",
    "source_file",
    "source_file_sha256",
    "configuration_file",
    "configuration_file_sha256",
    "expression_file_sha256",
}


@dataclass(frozen=True)
class BuildResult:
    """Validated database-build counts."""

    expression_rows: int
    tpm_rows: int
    fpkm_rows: int
    selected_expression_rows: int
    metadata_rows: int
    expression_rows_with_metadata: int
    mapped_tissue_rows: int


def require_duckdb() -> None:
    """Stop clearly if the Python DuckDB client is unavailable."""
    if duckdb is None:
        raise SystemExit(
            "Missing Python dependency: duckdb. Install it with:\n"
            "  mamba install -c conda-forge python-duckdb"
        )


def quote_literal(value: str | Path) -> str:
    """Return a DuckDB string literal for a trusted local value."""
    return "'" + str(value).replace("'", "''") + "'"


def parquet_files(root: Path, dataset_name: str) -> list[Path]:
    """Return sorted non-empty Parquet files for one named dataset."""
    dataset_root = root / "parquet" / dataset_name
    return sorted(
        path.resolve()
        for path in dataset_root.rglob("*.parquet")
        if path.is_file() and path.stat().st_size > 0
    )


def parquet_relation(paths: Iterable[Path]) -> str:
    """Build one explicit, persistent ``read_parquet`` relation expression."""
    path_list = list(paths)
    if not path_list:
        raise ValueError("Cannot build a Parquet relation from an empty file list")
    values = ", ".join(quote_literal(path) for path in path_list)
    return f"read_parquet([{values}], hive_partitioning = TRUE, union_by_name = TRUE)"


def relation_columns(connection: object, relation_sql: str) -> set[str]:
    """Return lower-case columns exposed by a relation expression."""
    rows = connection.execute(f"DESCRIBE SELECT * FROM {relation_sql}").fetchall()
    return {str(row[0]).lower() for row in rows}


def require_columns(
    connection: object,
    relation_sql: str,
    required: set[str],
    label: str,
) -> None:
    """Fail when a Parquet dataset does not meet its versioned field contract."""
    observed = relation_columns(connection, relation_sql)
    missing = sorted(required - observed)
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing!r}")


def scalar_int(connection: object, query: str) -> int:
    """Execute a scalar count query and return an integer."""
    value = connection.execute(query).fetchone()
    if value is None:
        raise ValueError(f"Validation query returned no row: {query}")
    return int(value[0])


def validate_expression(connection: object) -> tuple[int, int, int]:
    """Validate expression uniqueness, statistics, units, and source provenance."""
    expression_rows = scalar_int(
        connection,
        "SELECT COUNT(*) FROM atlas_expression_long",
    )
    if expression_rows == 0:
        raise ValueError("atlas_expression_long contains zero rows")

    duplicate_keys = scalar_int(
        connection,
        "SELECT COUNT(*) FROM ("
        "SELECT species_column, experiment_accession, gene_id, "
        "sample_or_condition, expression_unit FROM atlas_expression_long "
        "GROUP BY ALL HAVING COUNT(*) <> 1)",
    )
    if duplicate_keys:
        raise ValueError(f"Expression data contain {duplicate_keys} duplicate context keys")

    invalid_rows = scalar_int(
        connection,
        "SELECT COUNT(*) FROM atlas_expression_long WHERE "
        "expression_value IS NULL OR NOT isfinite(expression_value) OR "
        "expression_value < 0 OR expression_unit NOT IN ('TPM', 'FPKM') OR "
        "COALESCE(source_file_sha256, '') !~ '^[0-9a-f]{64}$' OR "
        "CASE WHEN expression_summary_type = 'atlas_five_number_summary' THEN NOT ("
        "expression_minimum <= expression_lower_quartile AND "
        "expression_lower_quartile <= expression_median AND "
        "expression_median <= expression_upper_quartile AND "
        "expression_upper_quartile <= expression_maximum AND "
        "expression_value = expression_median AND "
        "expression_value_statistic = 'median') "
        "WHEN expression_summary_type IN ('single_value', 'atlas_zero_code') THEN NOT ("
        "expression_minimum IS NULL AND expression_lower_quartile IS NULL AND "
        "expression_median IS NULL AND expression_upper_quartile IS NULL AND "
        "expression_maximum IS NULL) ELSE TRUE END",
    )
    if invalid_rows:
        raise ValueError(f"Expression data contain {invalid_rows} invalid semantic rows")

    conflicting_hashes = scalar_int(
        connection,
        "SELECT COUNT(*) FROM (SELECT source_file FROM atlas_expression_long "
        "GROUP BY source_file HAVING COUNT(DISTINCT source_file_sha256) <> 1)",
    )
    if conflicting_hashes:
        raise ValueError(f"Expression data contain {conflicting_hashes} source/hash conflicts")

    tpm_rows = scalar_int(connection, "SELECT COUNT(*) FROM atlas_expression_tpm")
    fpkm_rows = scalar_int(
        connection,
        "SELECT COUNT(*) FROM atlas_expression_fpkm",
    )
    if tpm_rows + fpkm_rows != expression_rows:
        raise ValueError("TPM/FPKM views do not partition all expression rows")
    return expression_rows, tpm_rows, fpkm_rows


def validate_metadata_join(connection: object) -> tuple[int, int, int, int]:
    """Validate metadata keys and prove the left join preserves cardinality."""
    metadata_rows = scalar_int(
        connection,
        "SELECT COUNT(*) FROM atlas_sample_metadata_wide_joinable",
    )
    duplicate_keys = scalar_int(
        connection,
        "SELECT COUNT(*) FROM (SELECT species_column, experiment_accession, "
        "sample_or_condition FROM atlas_sample_metadata_wide_joinable "
        "GROUP BY ALL HAVING COUNT(*) <> 1)",
    )
    if duplicate_keys:
        raise ValueError(f"Sample metadata contain {duplicate_keys} duplicate join keys")
    invalid_hashes = scalar_int(
        connection,
        "SELECT COUNT(*) FROM atlas_sample_metadata_wide_joinable WHERE "
        "COALESCE(source_file_sha256, '') !~ '^[0-9a-f]{64}$' OR "
        "COALESCE(expression_file_sha256, '') !~ '^[0-9a-f]{64}$' OR "
        "(COALESCE(configuration_file, '') <> '' AND "
        "COALESCE(configuration_file_sha256, '') !~ '^[0-9a-f]{64}$')",
    )
    if invalid_hashes:
        raise ValueError(f"Sample metadata contain {invalid_hashes} invalid provenance rows")

    stale_expression_sources = scalar_int(
        connection,
        "SELECT COUNT(*) FROM atlas_sample_metadata_wide_joinable m WHERE "
        "NOT EXISTS (SELECT 1 FROM atlas_expression_long e WHERE "
        "e.species_column = m.species_column AND "
        "e.experiment_accession = m.experiment_accession AND "
        "e.source_file_sha256 = m.expression_file_sha256)",
    )
    if stale_expression_sources:
        raise ValueError(
            "Sample metadata contain "
            f"{stale_expression_sources} rows bound to an unavailable or "
            "changed expression source"
        )

    selected_expression_rows = scalar_int(
        connection,
        "SELECT COUNT(*) FROM atlas_expression_selected",
    )
    joined_rows = scalar_int(
        connection,
        "SELECT COUNT(*) FROM atlas_expression_with_sample_metadata",
    )
    if joined_rows != selected_expression_rows:
        raise ValueError(
            "Expression/metadata join changed row cardinality: "
            f"selected_expression={selected_expression_rows}, "
            f"joined={joined_rows}"
        )
    unmatched_contexts = scalar_int(
        connection,
        "SELECT COUNT(*) FROM atlas_expression_with_sample_metadata "
        "WHERE metadata_source_file IS NULL",
    )
    if unmatched_contexts:
        raise ValueError(
            f"Selected expression data contain {unmatched_contexts} contexts "
            "without configuration-backed sample metadata"
        )
    mapped_tissue_rows = scalar_int(
        connection,
        "SELECT COUNT(*) FROM atlas_expression_with_sample_metadata "
        "WHERE COALESCE(organism_part, '') <> ''",
    )
    return (
        metadata_rows,
        selected_expression_rows,
        joined_rows,
        mapped_tissue_rows,
    )


def create_views(connection: object, output_dir: Path) -> BuildResult:
    """Create validated database views from corrected Parquet datasets."""
    expression_paths = parquet_files(output_dir, "atlas_expression_long")
    if not expression_paths:
        raise ValueError("No expression Parquet files were found")
    expression_sql = parquet_relation(expression_paths)
    require_columns(
        connection,
        expression_sql,
        EXPRESSION_REQUIRED_COLUMNS,
        "Expression Parquet dataset",
    )
    connection.execute(f"CREATE VIEW atlas_expression_long AS SELECT * FROM {expression_sql}")
    connection.execute(
        "CREATE VIEW atlas_expression_tpm AS SELECT * FROM atlas_expression_long "
        "WHERE expression_unit = 'TPM'"
    )
    connection.execute(
        "CREATE VIEW atlas_expression_fpkm AS SELECT * FROM atlas_expression_long "
        "WHERE expression_unit = 'FPKM'"
    )
    expression_rows, tpm_rows, fpkm_rows = validate_expression(connection)
    connection.execute(
        "CREATE VIEW atlas_expression_selected AS "
        "WITH experiment_units AS (SELECT species_column, "
        "experiment_accession, BOOL_OR(expression_unit = 'TPM') AS has_tpm "
        "FROM atlas_expression_long GROUP BY species_column, "
        "experiment_accession) SELECT e.* FROM atlas_expression_long e "
        "JOIN experiment_units u USING (species_column, experiment_accession) "
        "WHERE (u.has_tpm AND e.expression_unit = 'TPM') OR "
        "(NOT u.has_tpm AND e.expression_unit = 'FPKM')"
    )

    alias_paths = parquet_files(output_dir, "gene_identifier_aliases")
    if alias_paths:
        alias_sql = parquet_relation(alias_paths)
        connection.execute(f"CREATE VIEW gene_identifier_aliases AS SELECT * FROM {alias_sql}")

    long_paths = parquet_files(output_dir, "atlas_sample_metadata_long")
    if long_paths:
        long_sql = parquet_relation(long_paths)
        connection.execute(f"CREATE VIEW atlas_sample_metadata_long AS SELECT * FROM {long_sql}")

    wide_paths = parquet_files(output_dir, "atlas_sample_metadata_wide")
    if not wide_paths:
        raise ValueError("No sample-metadata Parquet files were found; tissue mapping is required")
    wide_sql = parquet_relation(wide_paths)
    require_columns(
        connection,
        wide_sql,
        METADATA_REQUIRED_COLUMNS,
        "Sample metadata Parquet dataset",
    )
    connection.execute(f"CREATE VIEW atlas_sample_metadata_wide AS SELECT * FROM {wide_sql}")
    connection.execute(
        "CREATE VIEW atlas_sample_metadata_wide_joinable AS SELECT * FROM "
        "atlas_sample_metadata_wide WHERE COALESCE(sample_or_condition, '') <> ''"
    )
    connection.execute(
        "CREATE VIEW atlas_expression_with_sample_metadata AS SELECT e.*, "
        "m.atlas_group_label, m.assay_ids, m.assay_count, m.organism, "
        "m.organism_part, m.developmental_stage, m.genotype, m.cultivar, "
        "m.treatment, m.condition, m.assay_name, m.source_name, m.sample_name, "
        "m.source_file AS metadata_source_file, "
        "m.source_file_sha256 AS metadata_source_file_sha256, "
        "m.configuration_file, m.configuration_file_sha256, "
        "m.expression_file_sha256 AS metadata_expression_file_sha256 "
        "FROM atlas_expression_selected e LEFT JOIN "
        "atlas_sample_metadata_wide_joinable m ON "
        "e.species_column = m.species_column AND "
        "e.experiment_accession = m.experiment_accession AND "
        "e.sample_or_condition = m.sample_or_condition AND "
        "e.source_file_sha256 = m.expression_file_sha256"
    )
    (
        metadata_rows,
        selected_expression_rows,
        joined_rows,
        mapped_tissue_rows,
    ) = validate_metadata_join(connection)
    return BuildResult(
        expression_rows=expression_rows,
        tpm_rows=tpm_rows,
        fpkm_rows=fpkm_rows,
        selected_expression_rows=selected_expression_rows,
        metadata_rows=metadata_rows,
        expression_rows_with_metadata=joined_rows,
        mapped_tissue_rows=mapped_tissue_rows,
    )


def write_validation(path: Path, result: BuildResult) -> None:
    """Write one-row database validation authority as TSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "expression_rows": result.expression_rows,
        "tpm_rows": result.tpm_rows,
        "fpkm_rows": result.fpkm_rows,
        "selected_expression_rows": result.selected_expression_rows,
        "metadata_rows": result.metadata_rows,
        "expression_rows_with_metadata": result.expression_rows_with_metadata,
        "mapped_tissue_rows": result.mapped_tissue_rows,
        "expression_join_cardinality_preserved": "true",
        "scientific_parser": "python_atlas_five_number_v3_1",
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(values),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(values)


def build_database(
    output_dir: Path,
    duckdb_path: Path,
    force: bool = False,
) -> BuildResult:
    """Build the database atomically and preserve an existing file on failure."""
    require_duckdb()
    output_dir = output_dir.resolve()
    duckdb_path = duckdb_path.resolve()
    if duckdb_path.exists() and not force:
        raise FileExistsError(
            f"DuckDB already exists; pass --force true to replace it: {duckdb_path}"
        )
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{duckdb_path.name}.",
        suffix=".partial",
        dir=str(duckdb_path.parent),
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    temporary_path.unlink()
    connection = None
    try:
        connection = duckdb.connect(str(temporary_path))
        result = create_views(connection, output_dir)
        connection.close()
        connection = None
        os.replace(temporary_path, duckdb_path)
    except Exception:
        if connection is not None:
            connection.close()
        temporary_path.unlink(missing_ok=True)
        raise
    write_validation(
        output_dir / "manifests" / "atlas_duckdb_validation.tsv",
        result,
    )
    return result


def parse_bool(value: str) -> bool:
    """Parse a strict command-line Boolean."""
    normalised = value.strip().lower()
    if normalised in {"true", "1", "yes"}:
        return True
    if normalised in {"false", "0", "no"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse named command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build validated DuckDB views over corrected Atlas Parquet."
    )
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--duckdb_path", required=True)
    parser.add_argument("--force", type=parse_bool, default=False)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Run the validated database builder."""
    args = parse_args(argv)
    result = build_database(
        Path(args.output_dir),
        Path(args.duckdb_path),
        force=args.force,
    )
    print(
        "Created validated Expression Atlas DuckDB: "
        f"{args.duckdb_path} ({result.expression_rows} expression rows)",
        flush=True,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
