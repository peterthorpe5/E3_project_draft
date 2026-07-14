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
    "all_matched_e3_seed_sequences",
    "strict_matched_e3_seed_sequences",
    "non_strict_matched_e3_seed_sequences",
    "strict_nonseed_candidate_members",
    "e3_seeded_cluster_summary",
    "e3_seeded_cross_species_summary",
    "e3_seeded_cluster_size_distribution",
    "sample_e3_summary",
    "realignment_content_summary",
    "workflow_key_metrics",
    "workflow_thresholds",
)


def sql_literal(value: object) -> str:
    """Convert a simple Python value into a safely quoted DuckDB SQL literal.

    Args:
        value: ``None``, Boolean, numeric or string-like value.

    Returns:
        SQL text representing the supplied literal value.
    """

    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _parquet_scan(path: Path) -> str:
    """Build a DuckDB ``read_parquet`` expression for an absolute path.

    Args:
        path: Parquet file path.

    Returns:
        SQL expression with the path safely quoted as a literal.
    """
    return f"read_parquet({sql_literal(str(Path(path).resolve()))})"


def _create_source_tables(
    connection: duckdb.DuckDBPyConnection,
    sequences_parquet: Path,
    seeds_parquet: Path,
    clusters_parquet: Path,
    realignments_parquet: Path,
) -> None:
    """Materialise core workflow Parquet inputs as DuckDB source tables.

    Args:
        connection: Open writable DuckDB connection.
        sequences_parquet: Prepared sequence metadata Parquet file.
        seeds_parquet: Normalised E3 seed Parquet file.
        clusters_parquet: Normalised DeepClust membership Parquet file.
        realignments_parquet: Classified realignment Parquet file.

    Returns:
        None.

    Raises:
        duckdb.Error: If a source file is unreadable or table creation fails.
    """
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
    """Store strict workflow thresholds in a two-column DuckDB table.

    Args:
        connection: Open writable DuckDB connection.
        thresholds: Strict thresholds applied to realignment records.

    Returns:
        None.

    Raises:
        duckdb.Error: If table creation or insertion fails.
    """
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
    """Create derived E3-seed matching, membership and summary tables.

    The SQL identifies sequence records matching supplied seed accessions, finds
    clusters containing at least one match, joins biological metadata and strict
    alignment flags, and summarises each E3-seeded cluster.

    Args:
        connection: DuckDB connection containing all required source tables.

    Returns:
        None.

    Raises:
        duckdb.Error: If required source tables are absent or SQL execution fails.
    """
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
        CREATE TABLE all_matched_e3_seed_sequences AS
        SELECT DISTINCT
            sm.internal_id,
            sm.sample_id,
            sm.species,
            sm.original_id,
            sm.entry,
            sm.seed_id,
            cs.representative_id,
            r.pident,
            r.representative_coverage,
            r.member_coverage,
            r.evalue,
            r.bitscore,
            COALESCE(r.passes_all, FALSE) AS passes_strict_thresholds
        FROM sequence_seed_matches AS sm
        LEFT JOIN raw_cluster_sequences AS cs
            ON sm.internal_id = cs.sequence_id
        LEFT JOIN realigned_membership AS r
            ON cs.representative_id = r.representative_id
            AND sm.internal_id = r.member_id
        """
    )
    connection.execute(
        """
        CREATE TABLE strict_matched_e3_seed_sequences AS
        SELECT *
        FROM all_matched_e3_seed_sequences
        WHERE passes_strict_thresholds
        """
    )
    connection.execute(
        """
        CREATE TABLE non_strict_matched_e3_seed_sequences AS
        SELECT *
        FROM all_matched_e3_seed_sequences
        WHERE NOT passes_strict_thresholds
        """
    )
    connection.execute(
        """
        CREATE TABLE strict_nonseed_candidate_members AS
        SELECT *
        FROM strict_e3_seeded_cluster_members
        WHERE NOT is_known_e3_seed
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
    connection.execute(
        """
        CREATE TABLE e3_seeded_cross_species_summary AS
        SELECT
            species_count,
            COUNT(*) AS cluster_count,
            SUM(raw_member_count) AS raw_member_count,
            SUM(strict_member_count) AS strict_member_count,
            SUM(known_e3_sequence_count) AS known_e3_sequence_count
        FROM e3_seeded_cluster_summary
        GROUP BY species_count
        ORDER BY species_count
        """
    )
    connection.execute(
        """
        CREATE TABLE e3_seeded_cluster_size_distribution AS
        SELECT
            raw_member_count AS raw_cluster_size,
            strict_member_count AS strict_cluster_size,
            COUNT(*) AS cluster_count
        FROM e3_seeded_cluster_summary
        GROUP BY raw_member_count, strict_member_count
        ORDER BY raw_member_count, strict_member_count
        """
    )
    connection.execute(
        """
        CREATE TABLE sample_e3_summary AS
        SELECT
            s.sample_id,
            MAX(s.species) AS species,
            COUNT(DISTINCT s.internal_id) AS input_sequence_count,
            COUNT(DISTINCT a.internal_id) AS matched_e3_seed_count,
            COUNT(DISTINCT st.internal_id) AS strict_matched_e3_seed_count,
            COUNT(DISTINCT ns.internal_id) AS non_strict_matched_e3_seed_count,
            COUNT(DISTINCT c.member_id) AS strict_nonseed_candidate_count,
            COUNT(DISTINCT m.member_id) AS strict_e3_seeded_member_count
        FROM sequence_records AS s
        LEFT JOIN all_matched_e3_seed_sequences AS a
            ON s.internal_id = a.internal_id
        LEFT JOIN strict_matched_e3_seed_sequences AS st
            ON s.internal_id = st.internal_id
        LEFT JOIN non_strict_matched_e3_seed_sequences AS ns
            ON s.internal_id = ns.internal_id
        LEFT JOIN strict_nonseed_candidate_members AS c
            ON s.internal_id = c.member_id
        LEFT JOIN strict_e3_seeded_cluster_members AS m
            ON s.internal_id = m.member_id
        GROUP BY s.sample_id
        ORDER BY s.sample_id
        """
    )
    connection.execute(
        """
        CREATE TABLE realignment_content_summary AS
        SELECT
            COUNT(*) AS data_rows,
            COUNT(*) FILTER (
                WHERE representative_id = member_id
            ) AS representative_self_rows,
            COUNT(*) FILTER (
                WHERE representative_id <> member_id
            ) AS nonself_member_rows,
            COUNT(*) FILTER (
                WHERE representative_id IS NULL
                   OR member_id IS NULL
                   OR pident IS NULL
                   OR representative_coverage IS NULL
                   OR member_coverage IS NULL
                   OR evalue IS NULL
                   OR bitscore IS NULL
            ) AS rows_with_missing_values,
            COUNT(*) FILTER (WHERE passes_all) AS strict_pass_rows,
            MIN(pident) AS minimum_identity,
            MAX(pident) AS maximum_identity,
            MIN(representative_coverage) AS minimum_representative_coverage,
            MIN(member_coverage) AS minimum_member_coverage
        FROM realigned_membership
        """
    )
    connection.execute(
        """
        CREATE TABLE workflow_key_metrics AS
        SELECT 'input_proteins' AS metric, COUNT(*)::BIGINT AS value
        FROM sequence_records
        UNION ALL SELECT 'input_proteomes', COUNT(DISTINCT sample_id)::BIGINT
        FROM sequence_records
        UNION ALL SELECT 'supplied_e3_seed_ids', COUNT(*)::BIGINT
        FROM known_e3_seeds
        UNION ALL SELECT 'matched_input_sequences',
            COUNT(DISTINCT internal_id)::BIGINT FROM sequence_seed_matches
        UNION ALL SELECT 'matched_e3_seed_ids',
            COUNT(DISTINCT seed_id)::BIGINT FROM sequence_seed_matches
        UNION ALL SELECT 'raw_cluster_count',
            COUNT(DISTINCT representative_id)::BIGINT
            FROM raw_deepclust_membership
        UNION ALL SELECT 'raw_cluster_membership_rows', COUNT(*)::BIGINT
            FROM raw_deepclust_membership
        UNION ALL SELECT 'realigned_membership_rows', COUNT(*)::BIGINT
            FROM realigned_membership
        UNION ALL SELECT 'realignment_self_rows', COUNT(*)::BIGINT
            FROM realigned_membership WHERE representative_id = member_id
        UNION ALL SELECT 'realignment_nonself_rows', COUNT(*)::BIGINT
            FROM realigned_membership WHERE representative_id <> member_id
        UNION ALL SELECT 'all_threshold_pass_rows', COUNT(*)::BIGINT
            FROM threshold_pass_membership
        UNION ALL SELECT 'e3_seeded_clusters', COUNT(*)::BIGINT
            FROM e3_seeded_clusters
        UNION ALL SELECT 'e3_seeded_raw_members', COUNT(*)::BIGINT
            FROM e3_seeded_cluster_members
        UNION ALL SELECT 'e3_seeded_strict_members', COUNT(*)::BIGINT
            FROM strict_e3_seeded_cluster_members
        UNION ALL SELECT 'strict_matched_e3_seed_sequences', COUNT(*)::BIGINT
            FROM strict_matched_e3_seed_sequences
        UNION ALL SELECT 'non_strict_matched_e3_seed_sequences', COUNT(*)::BIGINT
            FROM non_strict_matched_e3_seed_sequences
        UNION ALL SELECT 'strict_nonseed_candidate_members', COUNT(*)::BIGINT
            FROM strict_nonseed_candidate_members
        """
    )


def get_table_row_counts(
    connection: duckdb.DuckDBPyConnection,
    table_names: Iterable[str] = _RESOURCE_TABLES,
) -> Dict[str, int]:
    """Count rows in selected DuckDB resource tables.

    Args:
        connection: Open DuckDB connection containing the requested tables.
        table_names: Iterable of trusted table names to count.

    Returns:
        Mapping from table name to integer row count.

    Raises:
        duckdb.Error: If a requested table does not exist or cannot be queried.
    """

    counts = {}
    for table_name in table_names:
        counts[table_name] = int(
            connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        )
    return counts


def _validation_findings(
    connection: duckdb.DuckDBPyConnection,
) -> List[Dict[str, object]]:
    """Evaluate core integrity checks for a constructed DuckDB resource.

    Args:
        connection: DuckDB connection containing source and curated tables.

    Returns:
        Ordered validation findings with check, status, value and message fields.

    Raises:
        duckdb.Error: If required validation tables cannot be queried.
    """
    findings: List[Dict[str, object]] = []

    def add(check: str, status: str, value: object, message: str) -> None:
        """Append one structured resource-validation finding.

        Args:
            check: Stable machine-readable check name.
            status: ``pass``, ``warning`` or ``fail``.
            value: Observed value supporting the finding.
            message: Human-readable interpretation of the check.

        Returns:
            None.
        """
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

    sequence_count = int(
        connection.execute("SELECT COUNT(*) FROM sequence_records").fetchone()[0]
    )
    realignment_count = int(
        connection.execute("SELECT COUNT(*) FROM realigned_membership").fetchone()[0]
    )
    alignment_status = (
        "warning" if realignment_count == 0
        else "pass" if realignment_count == sequence_count
        else "fail"
    )
    add(
        "realignment_rows_match_sequences",
        alignment_status,
        realignment_count,
        f"Expected one representative-member realignment row per input "
        f"sequence ({sequence_count}).",
    )

    cluster_count = int(
        connection.execute(
            "SELECT COUNT(DISTINCT representative_id) "
            "FROM raw_deepclust_membership"
        ).fetchone()[0]
    )
    self_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM realigned_membership "
            "WHERE representative_id = member_id"
        ).fetchone()[0]
    )
    self_status = (
        "warning" if realignment_count == 0
        else "pass" if self_rows == cluster_count
        else "fail"
    )
    add(
        "representative_self_rows_match_clusters",
        self_status,
        self_rows,
        f"Expected one representative self-alignment per raw cluster "
        f"({cluster_count}).",
    )

    unmatched_realignments = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM realigned_membership AS r
            LEFT JOIN raw_deepclust_membership AS c
              ON r.representative_id = c.representative_id
             AND r.member_id = c.member_id
            WHERE c.representative_id IS NULL
            """
        ).fetchone()[0]
    )
    add(
        "realignments_match_cluster_membership",
        "pass" if unmatched_realignments == 0 else "fail",
        unmatched_realignments,
        "Every realignment row must correspond to a raw cluster assignment.",
    )

    missing_alignment_values = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM realigned_membership
            WHERE representative_id IS NULL
               OR member_id IS NULL
               OR pident IS NULL
               OR representative_coverage IS NULL
               OR member_coverage IS NULL
               OR evalue IS NULL
               OR bitscore IS NULL
            """
        ).fetchone()[0]
    )
    add(
        "missing_realignments_values",
        "pass" if missing_alignment_values == 0 else "fail",
        missing_alignment_values,
        "Realignment identifiers and numeric evidence fields must be complete.",
    )

    matched_seed_count = int(
        connection.execute(
            "SELECT COUNT(DISTINCT internal_id) FROM sequence_seed_matches"
        ).fetchone()[0]
    )
    explicit_seed_count = int(
        connection.execute(
            "SELECT COUNT(DISTINCT internal_id) "
            "FROM all_matched_e3_seed_sequences"
        ).fetchone()[0]
    )
    add(
        "all_matched_seeds_preserved",
        "pass" if explicit_seed_count == matched_seed_count else "fail",
        explicit_seed_count,
        f"All {matched_seed_count} matched E3 seed sequences must remain "
        "explicitly represented regardless of strict-filter status.",
    )

    candidate_violations = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM strict_nonseed_candidate_members
            WHERE is_known_e3_seed OR NOT passes_strict_thresholds
            """
        ).fetchone()[0]
    )
    add(
        "strict_nonseed_candidate_definition",
        "pass" if candidate_violations == 0 else "fail",
        candidate_violations,
        "Candidate-expansion rows must be strict-pass members absent from the "
        "inherited E3 seed list.",
    )

    return findings


def validate_resource(
    connection: duckdb.DuckDBPyConnection,
    findings_tsv: Path,
) -> List[Dict[str, object]]:
    """Run DuckDB resource integrity checks and publish a TSV report.

    Args:
        connection: Open DuckDB connection containing the completed resource.
        findings_tsv: Destination for structured validation findings.

    Returns:
        All validation finding dictionaries when no check has failed.

    Raises:
        DataValidationError: If one or more integrity checks have ``fail`` status.
        duckdb.Error: If validation queries fail.
        OSError: If the findings report cannot be written.
    """

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
    """Stream a two-column DuckDB query result to FASTA.

    Args:
        connection: Open DuckDB connection.
        query: SQL returning identifier and sequence as its first two columns.
        output_path: Destination FASTA path.
        batch_size: Maximum query rows fetched per iteration.

    Returns:
        Number of FASTA records written.

    Raises:
        duckdb.Error: If query execution or result fetching fails.
        DataValidationError: If returned identifiers or sequences are invalid.
        OSError: If the FASTA output cannot be written.
    """
    cursor = connection.execute(query)

    def records() -> Iterable[Tuple[str, str]]:
        """Yield identifier-sequence pairs from the active DuckDB cursor in batches.

        Yields:
            String ``(identifier, sequence)`` pairs in query-result order.

        Raises:
            duckdb.Error: If result fetching fails.
        """
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
    """Export selected DuckDB resource tables as compressed Parquet files.

    Args:
        connection: Open DuckDB connection containing requested tables.
        output_dir: Destination directory for Parquet exports.
        table_names: Trusted table names to export.

    Returns:
        Mapping from table name to exported Parquet path.

    Raises:
        duckdb.Error: If a table is absent or export fails.
        OSError: If the output directory cannot be created.
    """

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
    """Export representative, all-member and strict-member E3-seeded FASTA files.

    Args:
        connection: Open DuckDB connection containing curated resource tables.
        output_dir: Destination directory for FASTA exports.

    Returns:
        Counts of representative, all-member and strict-member sequences written.

    Raises:
        duckdb.Error: If required resource tables cannot be queried.
        DataValidationError: If exported identifiers or sequences are invalid.
        OSError: If the destination directory or FASTA files cannot be written.
    """

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
    all_matched_seeds = _write_fasta_query(
        connection,
        """
        SELECT DISTINCT s.internal_id, s.sequence
        FROM all_matched_e3_seed_sequences AS m
        INNER JOIN sequence_records AS s
            ON m.internal_id = s.internal_id
        ORDER BY s.internal_id
        """,
        destination / "all_matched_e3_seeds.fasta",
    )
    strict_matched_seeds = _write_fasta_query(
        connection,
        """
        SELECT DISTINCT s.internal_id, s.sequence
        FROM strict_matched_e3_seed_sequences AS m
        INNER JOIN sequence_records AS s
            ON m.internal_id = s.internal_id
        ORDER BY s.internal_id
        """,
        destination / "strict_matched_e3_seeds.fasta",
    )
    strict_nonseed_candidates = _write_fasta_query(
        connection,
        """
        SELECT DISTINCT s.internal_id, s.sequence
        FROM strict_nonseed_candidate_members AS m
        INNER JOIN sequence_records AS s
            ON m.member_id = s.internal_id
        ORDER BY s.internal_id
        """,
        destination / "strict_nonseed_candidates.fasta",
    )
    return {
        "representative_sequences": representatives,
        "all_member_sequences": all_members,
        "strict_member_sequences": strict_members,
        "all_matched_e3_seed_sequences": all_matched_seeds,
        "strict_matched_e3_seed_sequences": strict_matched_seeds,
        "strict_nonseed_candidate_sequences": strict_nonseed_candidates,
    }


def export_summary_tables(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
) -> Dict[str, Path]:
    """Export compact scientific and quality-control summary tables as TSV.

    Args:
        connection: Open DuckDB connection containing completed resource tables.
        output_dir: Destination directory for human-readable TSV summaries.

    Returns:
        Mapping from summary table name to its resolved TSV path.

    Raises:
        duckdb.Error: If a summary table is absent or export fails.
        OSError: If the destination directory cannot be created.
    """

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    table_names = (
        "workflow_key_metrics",
        "realignment_content_summary",
        "sample_e3_summary",
        "e3_seeded_cross_species_summary",
        "e3_seeded_cluster_size_distribution",
        "e3_seeded_cluster_summary",
    )
    outputs: Dict[str, Path] = {}
    for table_name in table_names:
        output = destination / f"{table_name}.tsv"
        connection.execute(
            f"COPY (SELECT * FROM {table_name}) TO "
            f"{sql_literal(str(output.resolve()))} "
            "(FORMAT CSV, HEADER TRUE, DELIMITER '\t')"
        )
        outputs[table_name] = output.resolve()
    return outputs


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
    summary_output_dir: Path | None = None,
    metadata: Mapping[str, object] | None = None,
    duckdb_threads: int = 4,
) -> Dict[str, object]:
    """Build, validate and export the production E3-seeded cluster resource.

    A new DuckDB database is assembled atomically from prepared Parquet inputs.
    Source, threshold and curated tables are created, run metadata is stored,
    integrity checks are applied, and portable Parquet and FASTA outputs are
    exported before the database is published.

    Args:
        database_path: Final DuckDB database destination.
        sequences_parquet: Prepared sequence metadata input.
        seeds_parquet: Normalised known-E3 seed input.
        clusters_parquet: Normalised raw DeepClust membership input.
        realignments_parquet: Classified realignment input.
        thresholds: Strict post-realignment thresholds.
        curated_parquet_dir: Destination directory for exported resource tables.
        fasta_output_dir: Destination directory for curated FASTA files.
        validation_tsv: Destination for resource integrity findings.
        summary_output_dir: Optional compact TSV summary directory. Defaults to
            a ``summaries`` sibling below the workflow result root.
        metadata: Optional project, DIAMOND and threshold metadata.
        duckdb_threads: Number of DuckDB execution threads.

    Returns:
        Database path, table counts, validation findings, Parquet paths and FASTA
        record counts.

    Raises:
        ValueError: If thresholds or ``duckdb_threads`` are invalid.
        DataValidationError: If resource integrity checks fail.
        duckdb.Error: If database construction or export SQL fails.
        OSError: If database or export files cannot be created.
    """

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
            database_parent = Path(database_path).resolve().parent
            default_summary_root = (
                database_parent.parent
                if database_parent.name == "duckdb"
                else database_parent
            )
            resolved_summary_dir = (
                Path(summary_output_dir)
                if summary_output_dir is not None
                else default_summary_root / "summaries"
            )
            summary_outputs = export_summary_tables(
                connection,
                resolved_summary_dir,
            )
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
        "summary_outputs": {
            key: str(value) for key, value in summary_outputs.items()
        },
    }
