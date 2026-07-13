"""DuckDB resource construction, validation, and curated sequence exports."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import duckdb

from e3_discovery.clusters import Thresholds
from e3_discovery.exceptions import DataValidationError
from e3_discovery.fasta import write_fasta_records
from e3_discovery.io_utils import atomic_binary_path, ensure_parent, write_tsv

LOGGER = logging.getLogger(__name__)

_RESOURCE_TABLES = (
    "sequence_records",
    "known_e3_seeds",
    "raw_deepclust_membership",
    "realigned_membership",
    "sequence_seed_matches",
    "raw_cluster_sequences",
    "e3_seeded_clusters",
    "e3_seeded_cluster_members",
    "threshold_pass_membership",
    "strict_e3_seeded_cluster_members",
    "e3_seeded_cluster_summary",
    "workflow_thresholds",
)


def sql_literal(value: object) -> str:
    """Return a safely quoted SQL literal for simple DuckDB statements."""

    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _parquet_scan(path: Path) -> str:
    return f"read_parquet({sql_literal(str(Path(path).resolve()))})"


def _create_source_tables(
    connection: duckdb.DuckDBPyConnection,
    sequences_parquet: Path,
    seeds_parquet: Path,
    clusters_parquet: Path,
    realignments_parquet: Path,
) -> None:
    sources = {
        "sequence_records": sequences_parquet,
        "known_e3_seeds": seeds_parquet,
        "raw_deepclust_membership": clusters_parquet,
        "realigned_membership": realignments_parquet,
    }
    for table_name, path in sources.items():
        connection.execute(
            f"CREATE TABLE {table_name} AS SELECT * FROM {_parquet_scan(path)}"
        )


def _create_threshold_table(
    connection: duckdb.DuckDBPyConnection,
    thresholds: Thresholds,
) -> None:
    records = [
        ("minimum_percent_identity", thresholds.minimum_percent_identity),
        (
            "minimum_representative_coverage",
            thresholds.minimum_representative_coverage,
        ),
        ("minimum_member_coverage", thresholds.minimum_member_coverage),
        ("minimum_bitscore", thresholds.minimum_bitscore),
        ("maximum_evalue", thresholds.maximum_evalue),
    ]
    connection.execute(
        "CREATE TABLE workflow_thresholds "
        "(threshold_name VARCHAR, threshold_value DOUBLE)"
    )
    connection.executemany(
        "INSERT INTO workflow_thresholds VALUES (?, ?)",
        records,
    )


def _create_curated_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE sequence_seed_matches AS
        SELECT DISTINCT
            s.internal_id,
            s.sample_id,
            s.species,
            s.original_id,
            s.entry,
            k.seed_id
        FROM sequence_records AS s
        INNER JOIN known_e3_seeds AS k
            ON s.entry = k.seed_id
            OR s.original_id = k.seed_id
            OR s.internal_id = k.seed_id
        """
    )
    connection.execute(
        """
        CREATE TABLE raw_cluster_sequences AS
        SELECT DISTINCT representative_id, representative_id AS sequence_id
        FROM raw_deepclust_membership
        UNION
        SELECT DISTINCT representative_id, member_id AS sequence_id
        FROM raw_deepclust_membership
        """
    )
    connection.execute(
        """
        CREATE TABLE e3_seeded_clusters AS
        SELECT
            cs.representative_id,
            COUNT(DISTINCT sm.internal_id) AS known_e3_sequence_count,
            COUNT(DISTINCT sm.seed_id) AS known_e3_seed_count,
            STRING_AGG(DISTINCT sm.seed_id, ';' ORDER BY sm.seed_id)
                AS known_e3_seed_ids
        FROM raw_cluster_sequences AS cs
        INNER JOIN sequence_seed_matches AS sm
            ON cs.sequence_id = sm.internal_id
        GROUP BY cs.representative_id
        """
    )
    connection.execute(
        """
        CREATE TABLE threshold_pass_membership AS
        SELECT *
        FROM realigned_membership
        WHERE passes_all
        """
    )
    connection.execute(
        """
        CREATE TABLE e3_seeded_cluster_members AS
        SELECT
            cs.representative_id,
            cs.sequence_id AS member_id,
            s.sample_id,
            s.species,
            s.taxon_id,
            s.proteome_id,
            s.original_id,
            s.entry,
            s.sequence_length,
            s.sequence_md5,
            s.source_path,
            s.sample_metadata_json,
            r.pident,
            r.representative_coverage,
            r.member_coverage,
            r.evalue,
            r.bitscore,
            COALESCE(r.passes_all, FALSE) AS passes_strict_thresholds,
            EXISTS(
                SELECT 1
                FROM sequence_seed_matches AS sm
                WHERE sm.internal_id = cs.sequence_id
            ) AS is_known_e3_seed
        FROM raw_cluster_sequences AS cs
        INNER JOIN e3_seeded_clusters AS ec
            ON cs.representative_id = ec.representative_id
        INNER JOIN sequence_records AS s
            ON cs.sequence_id = s.internal_id
        LEFT JOIN realigned_membership AS r
            ON cs.representative_id = r.representative_id
            AND cs.sequence_id = r.member_id
        """
    )
    connection.execute(
        """
        CREATE TABLE strict_e3_seeded_cluster_members AS
        SELECT *
        FROM e3_seeded_cluster_members
        WHERE passes_strict_thresholds
        """
    )
    connection.execute(
        """
        CREATE TABLE e3_seeded_cluster_summary AS
        SELECT
            m.representative_id,
            MAX(c.known_e3_sequence_count) AS known_e3_sequence_count,
            MAX(c.known_e3_seed_count) AS known_e3_seed_count,
            MAX(c.known_e3_seed_ids) AS known_e3_seed_ids,
            COUNT(DISTINCT m.member_id) AS raw_member_count,
            COUNT(DISTINCT CASE
                WHEN m.passes_strict_thresholds THEN m.member_id
            END) AS strict_member_count,
            COUNT(DISTINCT m.sample_id) AS sample_count,
            COUNT(DISTINCT NULLIF(m.species, '')) AS species_count,
            MIN(m.pident) AS minimum_observed_pident,
            MEDIAN(m.pident) AS median_observed_pident,
            MAX(m.pident) AS maximum_observed_pident,
            MIN(m.member_coverage) AS minimum_member_coverage,
            MEDIAN(m.member_coverage) AS median_member_coverage,
            MAX(m.member_coverage) AS maximum_member_coverage
        FROM e3_seeded_cluster_members AS m
        INNER JOIN e3_seeded_clusters AS c
            ON m.representative_id = c.representative_id
        GROUP BY m.representative_id
        """
    )


def get_table_row_counts(
    connection: duckdb.DuckDBPyConnection,
    table_names: Iterable[str] = _RESOURCE_TABLES,
) -> Dict[str, int]:
    """Return row counts for named tables."""

    counts = {}
    for table_name in table_names:
        counts[table_name] = int(
            connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        )
    return counts


def _validation_findings(
    connection: duckdb.DuckDBPyConnection,
) -> List[Dict[str, object]]:
    findings: List[Dict[str, object]] = []

    def add(check: str, status: str, value: object, message: str) -> None:
        findings.append(
            {
                "check": check,
                "status": status,
                "value": value,
                "message": message,
            }
        )

    duplicates = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT internal_id
                FROM sequence_records
                GROUP BY internal_id
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
    )
    add(
        "duplicate_internal_ids",
        "pass" if duplicates == 0 else "fail",
        duplicates,
        "Sequence internal identifiers must be unique.",
    )

    missing_cluster_sequences = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM raw_cluster_sequences AS cs
            LEFT JOIN sequence_records AS s
                ON cs.sequence_id = s.internal_id
            WHERE s.internal_id IS NULL
            """
        ).fetchone()[0]
    )
    add(
        "missing_cluster_sequences",
        "pass" if missing_cluster_sequences == 0 else "fail",
        missing_cluster_sequences,
        "Every cluster identifier must map to sequence metadata.",
    )

    seeded_clusters = int(
        connection.execute(
            "SELECT COUNT(*) FROM e3_seeded_clusters"
        ).fetchone()[0]
    )
    add(
        "e3_seeded_clusters_present",
        "pass" if seeded_clusters > 0 else "fail",
        seeded_clusters,
        "At least one cluster must contain a known E3 seed.",
    )

    strict_members = int(
        connection.execute(
            "SELECT COUNT(*) FROM strict_e3_seeded_cluster_members"
        ).fetchone()[0]
    )
    add(
        "strict_members_present",
        "pass" if strict_members > 0 else "warning",
        strict_members,
        "Strict post-realignment membership may legitimately be empty on "
        "small or deliberately relaxed tests.",
    )

    return findings


def validate_resource(
    connection: duckdb.DuckDBPyConnection,
    findings_tsv: Path,
) -> List[Dict[str, object]]:
    """Run resource integrity checks and write a TSV report."""

    findings = _validation_findings(connection)
    write_tsv(findings, findings_tsv)
    failures = [row for row in findings if row["status"] == "fail"]
    if failures:
        messages = "; ".join(str(row["check"]) for row in failures)
        raise DataValidationError(f"Resource validation failed: {messages}")
    return findings


def _write_fasta_query(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    output_path: Path,
    batch_size: int = 10_000,
) -> int:
    cursor = connection.execute(query)

    def records() -> Iterable[Tuple[str, str]]:
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            for identifier, sequence in batch:
                yield str(identifier), str(sequence)

    return write_fasta_records(records(), output_path)


def export_resource_tables(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
    table_names: Sequence[str] = _RESOURCE_TABLES,
) -> Dict[str, Path]:
    """Export curated resource tables as compressed Parquet files."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: Dict[str, Path] = {}
    for table_name in table_names:
        output = destination / f"{table_name}.parquet"
        connection.execute(
            f"COPY {table_name} TO {sql_literal(str(output.resolve()))} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        outputs[table_name] = output
    return outputs


def export_curated_fastas(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
) -> Dict[str, int]:
    """Export representative, all-member, and strict-member FASTA datasets."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    representatives = _write_fasta_query(
        connection,
        """
        SELECT s.internal_id, s.sequence
        FROM e3_seeded_clusters AS c
        INNER JOIN sequence_records AS s
            ON c.representative_id = s.internal_id
        ORDER BY s.internal_id
        """,
        destination / "e3_seeded_representatives.fasta",
    )
    all_members = _write_fasta_query(
        connection,
        """
        SELECT DISTINCT s.internal_id, s.sequence
        FROM e3_seeded_cluster_members AS m
        INNER JOIN sequence_records AS s
            ON m.member_id = s.internal_id
        ORDER BY s.internal_id
        """,
        destination / "e3_seeded_all_members.fasta",
    )
    strict_members = _write_fasta_query(
        connection,
        """
        SELECT DISTINCT s.internal_id, s.sequence
        FROM strict_e3_seeded_cluster_members AS m
        INNER JOIN sequence_records AS s
            ON m.member_id = s.internal_id
        ORDER BY s.internal_id
        """,
        destination / "e3_seeded_strict_members.fasta",
    )
    return {
        "representative_sequences": representatives,
        "all_member_sequences": all_members,
        "strict_member_sequences": strict_members,
    }


def build_duckdb_resource(
    database_path: Path,
    sequences_parquet: Path,
    seeds_parquet: Path,
    clusters_parquet: Path,
    realignments_parquet: Path,
    thresholds: Thresholds,
    curated_parquet_dir: Path,
    fasta_output_dir: Path,
    validation_tsv: Path,
    metadata: Mapping[str, object] | None = None,
    duckdb_threads: int = 4,
) -> Dict[str, object]:
    """Build, validate, and export the production E3-seeded cluster resource."""

    thresholds.validate()
    LOGGER.info("Building curated DuckDB resource: %s", database_path)
    if duckdb_threads < 1:
        raise ValueError("duckdb_threads must be a positive integer")
    output = ensure_parent(Path(database_path))
    with atomic_binary_path(output) as temporary:
        # ``atomic_binary_path`` reserves a unique temporary filename by
        # creating an empty file. DuckDB expects either a valid database or a
        # path that does not yet exist, so remove the empty placeholder before
        # opening the database. The context manager still verifies that DuckDB
        # recreated the file before publishing it atomically.
        temporary.unlink(missing_ok=True)
        connection = duckdb.connect(str(temporary))
        try:
            connection.execute(f"PRAGMA threads={duckdb_threads}")
            LOGGER.info("Loading source Parquet tables into DuckDB")
            _create_source_tables(
                connection,
                sequences_parquet,
                seeds_parquet,
                clusters_parquet,
                realignments_parquet,
            )
            _create_threshold_table(connection, thresholds)
            LOGGER.info("Creating E3-seeded cluster interrogation tables")
            _create_curated_tables(connection)
            connection.execute(
                "CREATE TABLE resource_metadata "
                "(metadata_key VARCHAR, metadata_value VARCHAR)"
            )
            if metadata:
                connection.executemany(
                    "INSERT INTO resource_metadata VALUES (?, ?)",
                    [
                        (str(key), json.dumps(value, sort_keys=True))
                        for key, value in sorted(metadata.items())
                    ],
                )
            findings = validate_resource(connection, validation_tsv)
            counts = get_table_row_counts(connection)
            parquet_outputs = export_resource_tables(
                connection,
                curated_parquet_dir,
            )
            fasta_counts = export_curated_fastas(connection, fasta_output_dir)
            connection.execute("CHECKPOINT")
            LOGGER.info(
                "Curated resource validated: %d seeded clusters, %d strict members",
                counts["e3_seeded_clusters"],
                counts["strict_e3_seeded_cluster_members"],
            )
        finally:
            connection.close()

    return {
        "database_path": str(output),
        "row_counts": counts,
        "validation_findings": findings,
        "parquet_outputs": {
            key: str(value) for key, value in parquet_outputs.items()
        },
        "fasta_counts": fasta_counts,
    }
