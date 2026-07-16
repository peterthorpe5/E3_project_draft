"""Create a validated cluster-level E3 candidate evidence resource.

The completed E3 Discovery Engine DuckDB is attached read-only. The build
creates one row per E3-seeded cluster and publishes a compact DuckDB, TSV,
Parquet, validation report, and provenance manifest. The resulting table is an
evidence summary: sequence clustering does not establish that every member is
an E3 ligase.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import platform
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

from e3parquet import __version__
from e3parquet.io_utils import sha256_file, write_tsv

LOGGER = logging.getLogger(__name__)
TABLE_NAME = "e3_cluster_candidate_evidence"
VALIDATION_TABLE = "e3_cluster_candidate_evidence_validation"
METADATA_TABLE = "e3_cluster_candidate_evidence_build_metadata"
SOURCE_CATALOG = "discovery"
ONEKP_ID = "onekp_dataset"

NAMED_GROUPS: Mapping[str, Tuple[str, ...]] = {
    "cereal": (
        "Hordeum_vulgare",
        "Oryza_sativa",
        "Sorghum_bicolor",
        "Triticum_aestivum",
        "Zea_mays",
    ),
    "solanaceae": ("Solanum_lycopersicum", "Solanum_tuberosum"),
    "legume": ("Glycine_max", "Medicago_truncatula"),
    "brassicaceae": ("Arabidopsis_thaliana",),
}

REQUIRED_COLUMNS: Mapping[str, Set[str]] = {
    "e3_seeded_cluster_summary": {
        "representative_id",
        "known_e3_sequence_count",
        "known_e3_seed_count",
        "known_e3_seed_ids",
        "raw_member_count",
        "strict_member_count",
        "sample_count",
        "species_count",
        "minimum_observed_pident",
        "median_observed_pident",
        "maximum_observed_pident",
        "minimum_member_coverage",
        "median_member_coverage",
        "maximum_member_coverage",
    },
    "sequence_records": {
        "internal_id",
        "source_file_sample_id",
        "source_file_species",
        "sample_id",
        "species",
        "taxon_id",
        "proteome_id",
        "onekp_sample_code",
        "original_id",
        "entry",
        "sequence_length",
        "sequence_md5",
        "source_path",
    },
    "e3_seeded_cluster_members": {
        "representative_id",
        "member_id",
        "source_file_sample_id",
        "sample_id",
        "species",
    },
    "strict_e3_seeded_cluster_members": {
        "representative_id",
        "member_id",
        "source_file_sample_id",
        "sample_id",
        "species",
    },
    "all_matched_e3_seed_sequences": {
        "internal_id",
        "seed_id",
        "representative_id",
        "passes_strict_thresholds",
    },
    "known_e3_seeds": {"seed_id", "seed_metadata_json"},
    "strict_matched_e3_seed_sequences": {
        "internal_id",
        "representative_id",
    },
    "non_strict_matched_e3_seed_sequences": {
        "internal_id",
        "representative_id",
    },
    "strict_nonseed_candidate_members": {"representative_id", "member_id"},
}


class CandidateEvidenceError(RuntimeError):
    """Base exception for candidate evidence failures."""


class SchemaError(CandidateEvidenceError):
    """Raised when the production discovery schema is incomplete."""


class ValidationError(CandidateEvidenceError):
    """Raised when scientific or accounting checks fail."""


@dataclass(frozen=True)
class BuildConfig:
    """Resolved input and output paths for one candidate evidence build."""

    discovery_duckdb: Path
    output_duckdb: Path
    output_tsv: Path
    output_parquet: Path
    validation_tsv: Path
    manifest_json: Path
    log_path: Path
    overwrite: bool = False
    source_sha256: bool = True


@dataclass(frozen=True)
class Check:
    """One formal validation result."""

    name: str
    passed: bool
    observed: str
    expected: str
    details: str


@dataclass(frozen=True)
class BuildResult:
    """Headline values and formal paths from a successful build."""

    row_count: int
    check_count: int
    output_duckdb: Path
    output_tsv: Path
    output_parquet: Path
    validation_tsv: Path
    manifest_json: Path


def quote_literal(*, value: str) -> str:
    """Return a safely quoted DuckDB string literal."""
    return "'" + value.replace("'", "''") + "'"


def identifier(*, value: str) -> str:
    """Validate and quote a controlled DuckDB identifier."""
    if not value or not (value[0].isalpha() or value[0] == "_"):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    if not all(character.isalnum() or character == "_" for character in value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return f'"{value}"'


def table_columns(
    *, connection: Any, catalog: str, table_name: str
) -> Set[str]:
    """Return columns for a table in an attached DuckDB catalogue."""
    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_catalog = ?
          AND table_schema = 'main'
          AND table_name = ?
        ORDER BY ordinal_position
        """,
        [catalog, table_name],
    ).fetchall()
    return {str(row[0]) for row in rows}


def validate_schema(*, connection: Any, catalog: str = SOURCE_CATALOG) -> None:
    """Validate all production tables and columns required by the build."""
    identifier(value=catalog)
    failures: List[str] = []
    for table_name, required in REQUIRED_COLUMNS.items():
        observed = table_columns(
            connection=connection,
            catalog=catalog,
            table_name=table_name,
        )
        if not observed:
            failures.append(f"missing table {catalog}.{table_name}")
            continue
        missing = sorted(required - observed)
        if missing:
            failures.append(
                f"missing columns in {catalog}.{table_name}: "
                + ", ".join(missing)
            )
    if failures:
        raise SchemaError("; ".join(failures))


def sql_values(*, values: Sequence[str]) -> str:
    """Return a non-empty comma-separated list of SQL string literals."""
    if not values:
        raise ValueError("At least one SQL value is required.")
    return ", ".join(quote_literal(value=value) for value in values)


def group_count_expression(*, group_name: str, alias: str = "m") -> str:
    """Return SQL counting named-proteome species in one predefined group."""
    if group_name not in NAMED_GROUPS:
        raise ValueError(f"Unknown named group: {group_name}")
    identifier(value=alias)
    values = sql_values(values=NAMED_GROUPS[group_name])
    return (
        "COUNT(DISTINCT CASE WHEN "
        f"{alias}.source_file_sample_id IN ({values}) "
        f"THEN {alias}.source_file_sample_id END)"
    )


def breadth_cte(
    *, table_name: str, cte_name: str, catalog: str = SOURCE_CATALOG
) -> str:
    """Return a CTE summarising sample, species, and named-clade breadth."""
    table_sql = identifier(value=table_name)
    cte_sql = identifier(value=cte_name)
    catalog_sql = identifier(value=catalog)
    group_sql = {
        name: group_count_expression(group_name=name)
        for name in NAMED_GROUPS
    }
    return f"""
{cte_sql} AS (
    SELECT
        m.representative_id,
        COUNT(DISTINCT NULLIF(TRIM(m.sample_id), '')) AS sample_count,
        COUNT(DISTINCT NULLIF(TRIM(m.species), '')) AS species_count,
        COUNT(DISTINCT CASE WHEN m.source_file_sample_id = '{ONEKP_ID}'
            THEN NULLIF(TRIM(m.sample_id), '') END) AS onekp_sample_count,
        COUNT(DISTINCT CASE WHEN m.source_file_sample_id = '{ONEKP_ID}'
            THEN NULLIF(TRIM(m.species), '') END) AS onekp_species_count,
        COUNT(DISTINCT CASE WHEN m.source_file_sample_id <> '{ONEKP_ID}'
            THEN NULLIF(TRIM(m.source_file_sample_id), '') END)
            AS named_proteome_count,
        COUNT(DISTINCT CASE WHEN m.source_file_sample_id <> '{ONEKP_ID}'
            THEN NULLIF(TRIM(m.species), '') END) AS named_species_count,
        STRING_AGG(DISTINCT CASE
            WHEN m.source_file_sample_id <> '{ONEKP_ID}'
            THEN NULLIF(TRIM(m.source_file_sample_id), '') END,
            ';' ORDER BY CASE
            WHEN m.source_file_sample_id <> '{ONEKP_ID}'
            THEN NULLIF(TRIM(m.source_file_sample_id), '') END)
            AS named_proteome_ids,
        {group_sql['cereal']} AS named_cereal_proteome_count,
        {group_sql['solanaceae']} AS named_solanaceae_proteome_count,
        {group_sql['legume']} AS named_legume_proteome_count,
        {group_sql['brassicaceae']} AS named_brassicaceae_proteome_count
    FROM {catalog_sql}.{table_sql} AS m
    GROUP BY m.representative_id
)
""".strip()


def evidence_sql(*, catalog: str = SOURCE_CATALOG) -> str:
    """Return SQL that creates one evidence row per E3-seeded cluster."""
    catalog_sql = identifier(value=catalog)
    raw_breadth = breadth_cte(
        table_name="e3_seeded_cluster_members",
        cte_name="raw_breadth",
        catalog=catalog,
    )
    strict_breadth = breadth_cte(
        table_name="strict_e3_seeded_cluster_members",
        cte_name="strict_breadth",
        catalog=catalog,
    )
    return f"""
WITH
{raw_breadth},
{strict_breadth},
representatives AS (
    SELECT internal_id AS representative_id,
        source_file_sample_id AS representative_source_file_sample_id,
        source_file_species AS representative_source_file_species,
        sample_id AS representative_sample_id,
        species AS representative_species,
        taxon_id AS representative_taxon_id,
        proteome_id AS representative_proteome_id,
        onekp_sample_code AS representative_onekp_sample_code,
        original_id AS representative_original_id,
        entry AS representative_entry,
        sequence_length AS representative_sequence_length,
        sequence_md5 AS representative_sequence_md5,
        source_path AS representative_source_path
    FROM {catalog_sql}.sequence_records
),
seed_counts AS (
    SELECT representative_id,
        COUNT(DISTINCT internal_id) AS matched_seed_sequence_count,
        COUNT(DISTINCT seed_id) AS matched_seed_id_count,
        STRING_AGG(DISTINCT seed_id, ';' ORDER BY seed_id)
            AS matched_seed_ids_calculated,
        COUNT(DISTINCT internal_id) FILTER (
            WHERE passes_strict_thresholds IS TRUE)
            AS strict_matched_seed_sequence_count,
        COUNT(DISTINCT internal_id) FILTER (
            WHERE passes_strict_thresholds IS NOT TRUE)
            AS non_strict_matched_seed_sequence_count
    FROM {catalog_sql}.all_matched_e3_seed_sequences
    GROUP BY representative_id
),
nonseed_counts AS (
    SELECT representative_id,
        COUNT(DISTINCT member_id) AS strict_nonseed_candidate_count
    FROM {catalog_sql}.strict_nonseed_candidate_members
    GROUP BY representative_id
),
seed_annotation AS (
    SELECT links.representative_id,
        COUNT(DISTINCT links.seed_id) AS annotated_seed_id_count,
        COUNT(DISTINCT NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.category')), ''))
            AS seed_category_count,
        STRING_AGG(DISTINCT NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.category')), ''), ';' ORDER BY
            NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.category')), '')) AS seed_categories,
        STRING_AGG(DISTINCT NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.reviewed')), ''), ';' ORDER BY
            NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.reviewed')), ''))
            AS seed_review_statuses,
        STRING_AGG(DISTINCT NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.ubiquitin_go_term')), ''), ';'
            ORDER BY NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.ubiquitin_go_term')), ''))
            AS seed_ubiquitin_go_statuses,
        STRING_AGG(DISTINCT NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.organism')), ''), ';' ORDER BY
            NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.organism')), '')) AS seed_organisms,
        STRING_AGG(DISTINCT NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.protein_names')), ''), ' | '
            ORDER BY NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.protein_names')), ''))
            AS seed_protein_names,
        COUNT(*) FILTER (WHERE LOWER(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.reviewed')) = 'reviewed')
            AS reviewed_seed_count,
        COUNT(*) FILTER (WHERE LOWER(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.ubiquitin_go_term')) =
            'ubiquitin go term') AS ubiquitin_go_positive_seed_count,
        COUNT(*) FILTER (WHERE NULLIF(TRIM(JSON_EXTRACT_STRING(
            seeds.seed_metadata_json, '$.exclusion_go_term')), '')
            IS NOT NULL) AS seed_with_exclusion_go_term_count
    FROM (SELECT DISTINCT representative_id, seed_id
          FROM {catalog_sql}.all_matched_e3_seed_sequences) AS links
    LEFT JOIN {catalog_sql}.known_e3_seeds AS seeds
        ON seeds.seed_id = links.seed_id
    GROUP BY links.representative_id
)
SELECT c.representative_id,
    r.representative_source_file_sample_id,
    r.representative_source_file_species,
    r.representative_sample_id,
    r.representative_species,
    r.representative_taxon_id,
    r.representative_proteome_id,
    r.representative_onekp_sample_code,
    r.representative_original_id,
    r.representative_entry,
    r.representative_sequence_length,
    r.representative_sequence_md5,
    r.representative_source_path,
    c.known_e3_sequence_count,
    c.known_e3_seed_count,
    c.known_e3_seed_ids,
    COALESCE(sc.matched_seed_sequence_count, 0)
        AS matched_seed_sequence_count,
    COALESCE(sc.matched_seed_id_count, 0) AS matched_seed_id_count,
    sc.matched_seed_ids_calculated,
    COALESCE(sc.strict_matched_seed_sequence_count, 0)
        AS strict_matched_seed_sequence_count,
    COALESCE(sc.non_strict_matched_seed_sequence_count, 0)
        AS non_strict_matched_seed_sequence_count,
    COALESCE(sa.annotated_seed_id_count, 0) AS annotated_seed_id_count,
    COALESCE(sa.seed_category_count, 0) AS seed_category_count,
    sa.seed_categories,
    sa.seed_review_statuses,
    sa.seed_ubiquitin_go_statuses,
    sa.seed_organisms,
    sa.seed_protein_names,
    COALESCE(sa.reviewed_seed_count, 0) AS reviewed_seed_count,
    COALESCE(sa.ubiquitin_go_positive_seed_count, 0)
        AS ubiquitin_go_positive_seed_count,
    COALESCE(sa.seed_with_exclusion_go_term_count, 0)
        AS seed_with_exclusion_go_term_count,
    c.raw_member_count,
    c.strict_member_count,
    COALESCE(ns.strict_nonseed_candidate_count, 0)
        AS strict_nonseed_candidate_count,
    CAST(c.strict_member_count AS DOUBLE) / NULLIF(c.raw_member_count, 0)
        AS strict_member_fraction,
    CAST(COALESCE(ns.strict_nonseed_candidate_count, 0) AS DOUBLE)
        / NULLIF(c.strict_member_count, 0) AS strict_nonseed_fraction,
    c.sample_count AS raw_sample_count_reported,
    c.species_count AS raw_species_count_reported,
    COALESCE(rb.sample_count, 0) AS raw_sample_count_calculated,
    COALESCE(rb.species_count, 0) AS raw_species_count_calculated,
    COALESCE(rb.onekp_sample_count, 0) AS raw_onekp_sample_count,
    COALESCE(rb.onekp_species_count, 0) AS raw_onekp_species_count,
    COALESCE(rb.named_proteome_count, 0) AS raw_named_proteome_count,
    COALESCE(rb.named_species_count, 0) AS raw_named_species_count,
    rb.named_proteome_ids AS raw_named_proteome_ids,
    COALESCE(rb.named_cereal_proteome_count, 0)
        AS raw_named_cereal_proteome_count,
    COALESCE(rb.named_solanaceae_proteome_count, 0)
        AS raw_named_solanaceae_proteome_count,
    COALESCE(rb.named_legume_proteome_count, 0)
        AS raw_named_legume_proteome_count,
    COALESCE(rb.named_brassicaceae_proteome_count, 0)
        AS raw_named_brassicaceae_proteome_count,
    COALESCE(sb.sample_count, 0) AS strict_sample_count,
    COALESCE(sb.species_count, 0) AS strict_species_count,
    COALESCE(sb.onekp_sample_count, 0) AS strict_onekp_sample_count,
    COALESCE(sb.onekp_species_count, 0) AS strict_onekp_species_count,
    COALESCE(sb.named_proteome_count, 0) AS strict_named_proteome_count,
    COALESCE(sb.named_species_count, 0) AS strict_named_species_count,
    sb.named_proteome_ids AS strict_named_proteome_ids,
    COALESCE(sb.named_cereal_proteome_count, 0)
        AS strict_named_cereal_proteome_count,
    COALESCE(sb.named_solanaceae_proteome_count, 0)
        AS strict_named_solanaceae_proteome_count,
    COALESCE(sb.named_legume_proteome_count, 0)
        AS strict_named_legume_proteome_count,
    COALESCE(sb.named_brassicaceae_proteome_count, 0)
        AS strict_named_brassicaceae_proteome_count,
    c.minimum_observed_pident,
    c.median_observed_pident,
    c.maximum_observed_pident,
    c.minimum_member_coverage,
    c.median_member_coverage,
    c.maximum_member_coverage
FROM {catalog_sql}.e3_seeded_cluster_summary AS c
LEFT JOIN representatives AS r USING (representative_id)
LEFT JOIN seed_counts AS sc USING (representative_id)
LEFT JOIN nonseed_counts AS ns USING (representative_id)
LEFT JOIN raw_breadth AS rb USING (representative_id)
LEFT JOIN strict_breadth AS sb USING (representative_id)
LEFT JOIN seed_annotation AS sa USING (representative_id)
""".strip()


def create_evidence_table(*, connection: Any) -> int:
    """Validate the source and create the materialised evidence table."""
    validate_schema(connection=connection)
    table_sql = identifier(value=TABLE_NAME)
    connection.execute(f"DROP TABLE IF EXISTS {table_sql}")
    connection.execute(f"CREATE TABLE {table_sql} AS {evidence_sql()}")
    return int(connection.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()[0])


def scalar(*, connection: Any, sql: str) -> int:
    """Execute SQL expected to return one non-null integer value."""
    row = connection.execute(sql).fetchone()
    if row is None or row[0] is None:
        raise ValidationError(f"No integer result returned by: {sql}")
    return int(row[0])


def equality_check(
    *, name: str, observed: int, expected: int, details: str
) -> Check:
    """Create one equality-based validation result."""
    return Check(
        name=name,
        passed=observed == expected,
        observed=str(observed),
        expected=str(expected),
        details=details,
    )


def validate_evidence(*, connection: Any) -> List[Check]:
    """Run complete cluster, member, seed, breadth, and join validation."""
    table_sql = identifier(value=TABLE_NAME)
    source_sql = identifier(value=SOURCE_CATALOG)
    checks: List[Check] = []

    simple_checks = (
        (
            "candidate_row_count",
            f"SELECT COUNT(*) FROM {table_sql}",
            f"SELECT COUNT(*) FROM {source_sql}.e3_seeded_cluster_summary",
            "One evidence row is required per E3-seeded cluster.",
        ),
        (
            "raw_member_accounting",
            f"SELECT SUM(raw_member_count) FROM {table_sql}",
            f"SELECT COUNT(*) FROM {source_sql}.e3_seeded_cluster_members",
            "Raw E3-seeded members must reconcile exactly.",
        ),
        (
            "strict_member_accounting",
            f"SELECT SUM(strict_member_count) FROM {table_sql}",
            (
                f"SELECT COUNT(*) FROM {source_sql}."
                "strict_e3_seeded_cluster_members"
            ),
            "Strict E3-seeded members must reconcile exactly.",
        ),
        (
            "matched_seed_accounting",
            f"SELECT SUM(matched_seed_sequence_count) FROM {table_sql}",
            (
                f"SELECT COUNT(*) FROM {source_sql}."
                "all_matched_e3_seed_sequences"
            ),
            "All matched inherited E3 seed sequences must be retained.",
        ),
        (
            "strict_seed_accounting",
            (
                "SELECT SUM(strict_matched_seed_sequence_count) "
                f"FROM {table_sql}"
            ),
            (
                f"SELECT COUNT(*) FROM {source_sql}."
                "strict_matched_e3_seed_sequences"
            ),
            "Strict matched E3 seed sequences must reconcile exactly.",
        ),
        (
            "non_strict_seed_accounting",
            (
                "SELECT SUM(non_strict_matched_seed_sequence_count) "
                f"FROM {table_sql}"
            ),
            (
                f"SELECT COUNT(*) FROM {source_sql}."
                "non_strict_matched_e3_seed_sequences"
            ),
            "Non-strict matched E3 seeds must reconcile exactly.",
        ),
        (
            "strict_nonseed_accounting",
            f"SELECT SUM(strict_nonseed_candidate_count) FROM {table_sql}",
            (
                f"SELECT COUNT(*) FROM {source_sql}."
                "strict_nonseed_candidate_members"
            ),
            "Strict non-seed candidates must reconcile exactly.",
        ),
    )
    for name, observed_sql, expected_sql, details in simple_checks:
        checks.append(
            equality_check(
                name=name,
                observed=scalar(connection=connection, sql=observed_sql),
                expected=scalar(connection=connection, sql=expected_sql),
                details=details,
            )
        )

    zero_checks = (
        (
            "representatives_unique",
            (
                "SELECT COUNT(*) FROM (SELECT representative_id FROM "
                f"{table_sql} GROUP BY representative_id HAVING COUNT(*) > 1)"
            ),
            "Representative identifiers must be unique.",
        ),
        (
            "representatives_non_null",
            f"SELECT COUNT(*) FROM {table_sql} WHERE representative_id IS NULL",
            "Representative identifiers must not be null.",
        ),
        (
            "representative_metadata_complete",
            (
                f"SELECT COUNT(*) FROM {table_sql} WHERE "
                "representative_source_file_sample_id IS NULL"
            ),
            "Every representative must join to sequence_records.",
        ),
        (
            "strict_components_reconcile_per_cluster",
            (
                f"SELECT COUNT(*) FROM {table_sql} WHERE strict_member_count <> "
                "strict_matched_seed_sequence_count + "
                "strict_nonseed_candidate_count"
            ),
            "Strict members must equal strict seeds plus strict non-seeds.",
        ),
        (
            "seed_components_reconcile_per_cluster",
            (
                f"SELECT COUNT(*) FROM {table_sql} WHERE "
                "matched_seed_sequence_count <> "
                "strict_matched_seed_sequence_count + "
                "non_strict_matched_seed_sequence_count"
            ),
            "Matched seeds must equal strict plus non-strict seed sequences.",
        ),
        (
            "raw_breadth_matches_production_summary",
            (
                f"SELECT COUNT(*) FROM {table_sql} WHERE "
                "raw_sample_count_reported <> raw_sample_count_calculated OR "
                "raw_species_count_reported <> raw_species_count_calculated"
            ),
            "Recalculated raw breadth must match the production summary.",
        ),
        (
            "strict_counts_are_raw_subsets",
            (
                f"SELECT COUNT(*) FROM {table_sql} WHERE "
                "strict_member_count > raw_member_count OR "
                "strict_sample_count > raw_sample_count_calculated OR "
                "strict_species_count > raw_species_count_calculated"
            ),
            "Strict evidence must remain a subset of raw evidence.",
        ),
        (
            "production_seed_counts_match_direct_counts",
            (
                f"SELECT COUNT(*) FROM {table_sql} WHERE "
                "known_e3_sequence_count <> matched_seed_sequence_count OR "
                "known_e3_seed_count <> matched_seed_id_count"
            ),
            "Production summary seed counts must match direct seed links.",
        ),
        (
            "production_seed_ids_match_direct_ids",
            (
                f"SELECT COUNT(*) FROM {table_sql} WHERE "
                "COALESCE(known_e3_seed_ids, '') <> "
                "COALESCE(matched_seed_ids_calculated, '')"
            ),
            "Production summary seed identifiers must match direct links.",
        ),
        (
            "matched_seed_metadata_complete",
            (
                f"SELECT COUNT(*) FROM {table_sql} WHERE "
                "annotated_seed_id_count <> matched_seed_id_count"
            ),
            "Every matched seed identifier must join to seed metadata.",
        ),
    )
    for name, sql, details in zero_checks:
        checks.append(
            equality_check(
                name=name,
                observed=scalar(connection=connection, sql=sql),
                expected=0,
                details=details,
            )
        )

    failed = [check.name for check in checks if not check.passed]
    if failed:
        raise ValidationError("Validation failed: " + ", ".join(failed))
    return checks


def check_records(*, checks: Sequence[Check]) -> List[Dict[str, str]]:
    """Convert validation checks to records for TSV and DuckDB storage."""
    return [
        {
            "check_name": check.name,
            "status": "PASS" if check.passed else "FAIL",
            "observed_value": check.observed,
            "expected_value": check.expected,
            "details": check.details,
        }
        for check in checks
    ]


def temporary_path(*, formal_path: Path) -> Path:
    """Return a unique hidden temporary path beside a formal output."""
    return formal_path.with_name(
        f".{formal_path.name}.tmp.{uuid.uuid4().hex}"
    )


def validate_paths(*, config: BuildConfig) -> None:
    """Validate source and formal output paths before expensive work."""
    source = config.discovery_duckdb.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Discovery DuckDB not found: {source}")
    outputs = (
        config.output_duckdb,
        config.output_tsv,
        config.output_parquet,
        config.validation_tsv,
        config.manifest_json,
    )
    resolved = [path.resolve() for path in outputs]
    if source in resolved:
        raise CandidateEvidenceError("The source DuckDB cannot be an output.")
    if len(set(resolved)) != len(resolved):
        raise CandidateEvidenceError("Formal output paths must be distinct.")
    existing = [path for path in outputs if path.exists()]
    if existing and not config.overwrite:
        raise FileExistsError(
            "Outputs exist; pass --overwrite: "
            + ", ".join(str(path) for path in existing)
        )
    for path in (*outputs, config.log_path):
        path.parent.mkdir(parents=True, exist_ok=True)


def export_outputs(
    *, connection: Any, tsv_path: Path, parquet_path: Path
) -> Tuple[Path, Path]:
    """Export the evidence table to temporary TSV and Parquet files."""
    temp_tsv = temporary_path(formal_path=tsv_path)
    temp_parquet = temporary_path(formal_path=parquet_path)
    table_sql = identifier(value=TABLE_NAME)
    query = f"SELECT * FROM {table_sql} ORDER BY representative_id"
    connection.execute(
        f"COPY ({query}) TO {quote_literal(value=str(temp_tsv))} "
        "(FORMAT CSV, DELIMITER '\t', HEADER TRUE, NULL '')"
    )
    connection.execute(
        f"COPY ({query}) TO {quote_literal(value=str(temp_parquet))} "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    return temp_tsv, temp_parquet


def relation_columns(*, connection: Any, relation_sql: str) -> List[str]:
    """Return ordered column names for a queryable DuckDB relation."""
    cursor = connection.execute(f"SELECT * FROM {relation_sql} LIMIT 0")
    if cursor.description is None:
        raise ValidationError(
            f"Could not resolve relation columns for: {relation_sql}"
        )
    return [str(column[0]) for column in cursor.description]


def validate_exported_outputs(
    *,
    connection: Any,
    tsv_path: Path,
    parquet_path: Path,
    expected_row_count: int,
) -> List[Check]:
    """Validate staged TSV and Parquet row counts, schemas, and file sizes."""
    for path in (tsv_path, parquet_path):
        if not path.is_file():
            raise ValidationError(f"Expected staged export is missing: {path}")
        if path.stat().st_size <= 0:
            raise ValidationError(f"Expected staged export is empty: {path}")

    tsv_relation = (
        "read_csv("
        f"{quote_literal(value=str(tsv_path))}, "
        "delim='\t', header=true, all_varchar=true, sample_size=-1)"
    )
    parquet_relation = (
        f"read_parquet({quote_literal(value=str(parquet_path))})"
    )
    table_columns_ordered = relation_columns(
        connection=connection,
        relation_sql=identifier(value=TABLE_NAME),
    )
    tsv_columns = relation_columns(
        connection=connection,
        relation_sql=tsv_relation,
    )
    parquet_columns = relation_columns(
        connection=connection,
        relation_sql=parquet_relation,
    )
    checks = [
        equality_check(
            name="tsv_export_row_count",
            observed=scalar(
                connection=connection,
                sql=f"SELECT COUNT(*) FROM {tsv_relation}",
            ),
            expected=expected_row_count,
            details="The staged TSV must contain one row per candidate cluster.",
        ),
        equality_check(
            name="parquet_export_row_count",
            observed=scalar(
                connection=connection,
                sql=f"SELECT COUNT(*) FROM {parquet_relation}",
            ),
            expected=expected_row_count,
            details=(
                "The staged Parquet file must contain one row per candidate "
                "cluster."
            ),
        ),
        Check(
            name="tsv_export_schema",
            passed=tsv_columns == table_columns_ordered,
            observed=json.dumps(tsv_columns),
            expected=json.dumps(table_columns_ordered),
            details="The staged TSV column order must match the DuckDB table.",
        ),
        Check(
            name="parquet_export_schema",
            passed=parquet_columns == table_columns_ordered,
            observed=json.dumps(parquet_columns),
            expected=json.dumps(table_columns_ordered),
            details=(
                "The staged Parquet column order must match the DuckDB table."
            ),
        ),
    ]
    failed = [check.name for check in checks if not check.passed]
    if failed:
        raise ValidationError(
            "Export validation failed: " + ", ".join(failed)
        )
    return checks


def manifest_record(
    *,
    config: BuildConfig,
    row_count: int,
    checks: Sequence[Check],
    started_at: str,
    finished_at: str,
    source_hash: str,
) -> Dict[str, object]:
    """Return the deterministic build provenance manifest."""
    import duckdb  # type: ignore

    stat = config.discovery_duckdb.stat()
    return {
        "resource_name": "E3 cluster candidate evidence",
        "resource_version": __version__,
        "scientific_interpretation": (
            "Each row is an E3-seeded sequence cluster. Cluster membership "
            "and strict sequence evidence do not prove that every member is "
            "an E3 ligase."
        ),
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "duckdb_version": str(duckdb.__version__),
        "source_duckdb": str(config.discovery_duckdb.resolve()),
        "source_duckdb_bytes": int(stat.st_size),
        "source_duckdb_mtime_utc": dt.datetime.fromtimestamp(
            stat.st_mtime, tz=dt.timezone.utc
        ).isoformat(),
        "source_duckdb_sha256": source_hash,
        "candidate_row_count": row_count,
        "validation_check_count": len(checks),
        "validation_pass_count": sum(check.passed for check in checks),
        "outputs": {
            "duckdb": str(config.output_duckdb.resolve()),
            "tsv": str(config.output_tsv.resolve()),
            "parquet": str(config.output_parquet.resolve()),
            "validation_tsv": str(config.validation_tsv.resolve()),
        },
        "named_group_definitions": {
            key: list(value) for key, value in NAMED_GROUPS.items()
        },
        "source_sha256_calculated": config.source_sha256,
    }


def write_json_temp(*, value: Mapping[str, object], formal_path: Path) -> Path:
    """Write JSON to a temporary path and return the staged path."""
    staged = temporary_path(formal_path=formal_path)
    staged.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return staged


def store_internal_tables(
    *, connection: Any, checks: Sequence[Check], manifest: Mapping[str, object]
) -> None:
    """Store validation and provenance inside the output DuckDB."""
    validation_sql = identifier(value=VALIDATION_TABLE)
    metadata_sql = identifier(value=METADATA_TABLE)
    connection.execute(f"DROP TABLE IF EXISTS {validation_sql}")
    connection.execute(
        f"CREATE TABLE {validation_sql} (check_name VARCHAR, status VARCHAR, "
        "observed_value VARCHAR, expected_value VARCHAR, details VARCHAR)"
    )
    connection.executemany(
        f"INSERT INTO {validation_sql} VALUES (?, ?, ?, ?, ?)",
        [
            (
                record["check_name"],
                record["status"],
                record["observed_value"],
                record["expected_value"],
                record["details"],
            )
            for record in check_records(checks=checks)
        ],
    )
    connection.execute(f"DROP TABLE IF EXISTS {metadata_sql}")
    connection.execute(
        f"CREATE TABLE {metadata_sql} (metadata_json VARCHAR NOT NULL)"
    )
    connection.execute(
        f"INSERT INTO {metadata_sql} VALUES (?)",
        [json.dumps(manifest, sort_keys=True, ensure_ascii=False)],
    )


def cleanup(*, paths: Sequence[Path]) -> None:
    """Best-effort removal of staged files after a failed build."""
    for path in paths:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        except OSError:
            LOGGER.exception("Could not remove staged path: %s", path)


def publish(*, staged: Path, formal: Path) -> None:
    """Atomically publish one staged file to its formal path."""
    if not staged.is_file():
        raise CandidateEvidenceError(f"Staged file missing: {staged}")
    os.replace(staged, formal)


def build(*, config: BuildConfig) -> BuildResult:
    """Build, validate, export, and atomically publish candidate evidence."""
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise CandidateEvidenceError("duckdb is required.") from exc

    validate_paths(config=config)
    LOGGER.info("Candidate evidence build started")
    LOGGER.info("Source DuckDB: %s", config.discovery_duckdb.resolve())
    LOGGER.info("Output DuckDB: %s", config.output_duckdb.resolve())
    LOGGER.info("Output TSV: %s", config.output_tsv.resolve())
    LOGGER.info("Output Parquet: %s", config.output_parquet.resolve())
    LOGGER.info("Overwrite enabled: %s", config.overwrite)
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    LOGGER.info("Calculating source SHA-256: %s", config.source_sha256)
    source_hash = (
        sha256_file(config.discovery_duckdb)
        if config.source_sha256
        else "not_calculated"
    )
    temp_db = temporary_path(formal_path=config.output_duckdb)
    staged: List[Path] = [temp_db]
    connection = None
    try:
        LOGGER.info("Opening staged output DuckDB: %s", temp_db)
        connection = duckdb.connect(str(temp_db))
        LOGGER.info("Attaching source DuckDB read-only")
        connection.execute(
            f"ATTACH {quote_literal(value=str(config.discovery_duckdb.resolve()))} "
            f"AS {identifier(value=SOURCE_CATALOG)} (READ_ONLY)"
        )
        LOGGER.info("Creating cluster-level evidence table")
        row_count = create_evidence_table(connection=connection)
        LOGGER.info("Created %d cluster evidence rows", row_count)
        LOGGER.info("Running scientific and accounting validation")
        checks = validate_evidence(connection=connection)
        LOGGER.info("Core validation checks passed: %d", len(checks))
        LOGGER.info("Exporting staged TSV and Parquet outputs")
        temp_tsv, temp_parquet = export_outputs(
            connection=connection,
            tsv_path=config.output_tsv,
            parquet_path=config.output_parquet,
        )
        staged.extend((temp_tsv, temp_parquet))
        LOGGER.info("Validating staged TSV and Parquet outputs")
        checks.extend(
            validate_exported_outputs(
                connection=connection,
                tsv_path=temp_tsv,
                parquet_path=temp_parquet,
                expected_row_count=row_count,
            )
        )
        LOGGER.info("All validation checks passed: %d", len(checks))
        temp_validation = temporary_path(formal_path=config.validation_tsv)
        write_tsv(check_records(checks=checks), temp_validation)
        staged.append(temp_validation)
        finished_at = dt.datetime.now(dt.timezone.utc).isoformat()
        manifest = manifest_record(
            config=config,
            row_count=row_count,
            checks=checks,
            started_at=started_at,
            finished_at=finished_at,
            source_hash=source_hash,
        )
        LOGGER.info("Storing validation and provenance inside output DuckDB")
        store_internal_tables(
            connection=connection,
            checks=checks,
            manifest=manifest,
        )
        connection.execute(f"DETACH {identifier(value=SOURCE_CATALOG)}")
        connection.close()
        connection = None
        temp_manifest = write_json_temp(
            value=manifest,
            formal_path=config.manifest_json,
        )
        staged.append(temp_manifest)
        LOGGER.info("Publishing validated formal outputs atomically")
        for source, destination in (
            (temp_db, config.output_duckdb),
            (temp_tsv, config.output_tsv),
            (temp_parquet, config.output_parquet),
            (temp_validation, config.validation_tsv),
            (temp_manifest, config.manifest_json),
        ):
            publish(staged=source, formal=destination)
        LOGGER.info("Published %d candidate evidence rows", row_count)
        return BuildResult(
            row_count=row_count,
            check_count=len(checks),
            output_duckdb=config.output_duckdb,
            output_tsv=config.output_tsv,
            output_parquet=config.output_parquet,
            validation_tsv=config.validation_tsv,
            manifest_json=config.manifest_json,
        )
    except Exception:
        LOGGER.exception("Candidate evidence build failed")
        if connection is not None:
            connection.close()
        cleanup(paths=staged)
        raise


def result_dict(*, result: BuildResult) -> Dict[str, object]:
    """Return a JSON-serialisable dictionary for a build result."""
    values = asdict(result)
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in values.items()
    }
