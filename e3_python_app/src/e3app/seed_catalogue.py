"""Known-E3 seed catalogue reconstructed from the loaded resource."""

from __future__ import annotations

import logging
import re
from typing import Sequence

import duckdb
import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)

SEED_AUTHORITY_RELATION = "known_e3_seeds"
SEED_SUMMARY_RELATION_PREFERENCE = (
    "candidate_evidence",
    "e3_cluster_candidate_evidence",
)
SEED_ID_COLUMN_PREFERENCE = (
    "matched_seed_ids_calculated",
    "discovery_matched_seed_ids_calculated",
    "known_e3_seed_ids",
    "matched_e3_seeds",
)
SEED_CLUSTER_COLUMN_PREFERENCE = (
    "cluster_id",
    "representative_id",
)
SEED_SEQUENCE_RELATION = "candidate_group_member_sequences"
SEED_ANNOTATION_FIELDS = (
    (
        "associated_seed_protein_names",
        ("seed_protein_names", "discovery_seed_protein_names"),
    ),
    (
        "associated_seed_categories",
        ("seed_categories", "discovery_seed_categories"),
    ),
    (
        "associated_seed_review_statuses",
        ("seed_review_statuses", "discovery_seed_review_statuses"),
    ),
    (
        "associated_seed_ubiquitin_go_statuses",
        (
            "seed_ubiquitin_go_statuses",
            "discovery_seed_ubiquitin_go_statuses",
        ),
    ),
    (
        "associated_seed_organisms",
        ("seed_organisms", "discovery_seed_organisms"),
    ),
)
SEED_EXACT_ANNOTATION_FIELDS = (
    "seed_protein_names",
    "seed_category",
    "seed_review_status",
    "seed_ubiquitin_go_status",
    "seed_exclusion_go_term",
    "seed_organism",
    "seed_taxon_id",
    "seed_sequence_md5",
    "seed_evidence_type",
    "seed_source",
)


def _first_available(
    *,
    available: set[str],
    choices: Sequence[str],
) -> str | None:
    """Return the first available field from an ordered preference list."""
    return next((choice for choice in choices if choice in available), None)


def seed_catalogue_capability(*, connection: object) -> dict[str, object]:
    """Resolve seed-annotation and optional sequence sources.

    Args:
        connection: Open read-only DuckDB connection.

    Returns:
        Availability and source-column metadata.
    """
    relations = set(list_relations(connection))
    summary_relation: str | None = None
    summary_columns: set[str] = set()
    summary_seed_column: str | None = None
    summary_cluster_column: str | None = None
    for relation in SEED_SUMMARY_RELATION_PREFERENCE:
        if relation not in relations:
            continue
        columns = set(relation_columns(connection, relation))
        seed_id_column = _first_available(
            available=columns,
            choices=SEED_ID_COLUMN_PREFERENCE,
        )
        if seed_id_column is None:
            continue
        cluster_column = _first_available(
            available=columns,
            choices=SEED_CLUSTER_COLUMN_PREFERENCE,
        )
        summary_relation = relation
        summary_columns = columns
        summary_seed_column = seed_id_column
        summary_cluster_column = cluster_column
        break
    sequence_columns: set[str] = set()
    if SEED_SEQUENCE_RELATION in relations:
        sequence_columns = set(
            relation_columns(connection, SEED_SEQUENCE_RELATION)
        )
    sequence_available = {
        "raw_identifier",
        "protein_sequence",
    }.issubset(sequence_columns)
    if SEED_AUTHORITY_RELATION in relations:
        authority_columns = set(
            relation_columns(connection, SEED_AUTHORITY_RELATION)
        )
        if "seed_id" in authority_columns:
            return {
                "available": True,
                "mode": "authority",
                "relation": SEED_AUTHORITY_RELATION,
                "columns": tuple(sorted(authority_columns)),
                "seed_id_column": "seed_id",
                "cluster_column": None,
                "summary_relation": summary_relation,
                "summary_columns": tuple(sorted(summary_columns)),
                "summary_seed_column": summary_seed_column,
                "summary_cluster_column": summary_cluster_column,
                "sequence_available": sequence_available,
                "sequence_columns": tuple(sorted(sequence_columns)),
            }
    if summary_relation is not None:
        return {
            "available": True,
            "mode": "cluster_summary",
            "relation": summary_relation,
            "columns": tuple(sorted(summary_columns)),
            "seed_id_column": summary_seed_column,
            "cluster_column": summary_cluster_column,
            "summary_relation": summary_relation,
            "summary_columns": tuple(sorted(summary_columns)),
            "summary_seed_column": summary_seed_column,
            "summary_cluster_column": summary_cluster_column,
            "sequence_available": sequence_available,
            "sequence_columns": tuple(sorted(sequence_columns)),
        }
    return {
        "available": False,
        "mode": None,
        "relation": None,
        "columns": (),
        "seed_id_column": None,
        "cluster_column": None,
        "summary_relation": None,
        "summary_columns": (),
        "summary_seed_column": None,
        "summary_cluster_column": None,
        "sequence_available": False,
        "sequence_columns": (),
    }


def _aggregate_optional_text(
    *,
    available: set[str],
    choices: Sequence[str],
    alias: str,
) -> str:
    """Return one distinct text aggregation or a typed blank field."""
    column = _first_available(available=available, choices=choices)
    if column is None:
        return f"CAST('' AS VARCHAR) AS {quote_identifier(alias)}"
    expression = f"nullif(trim(CAST({quote_identifier(column)} AS VARCHAR)), '')"
    return (
        f"coalesce(string_agg(DISTINCT {expression}, ';' "
        f"ORDER BY {expression}) FILTER (WHERE {expression} IS NOT NULL), '') "
        f"AS {quote_identifier(alias)}"
    )


def _sequence_cte(*, capability: dict[str, object]) -> str:
    """Return optional exact seed-sequence aggregation SQL."""
    if not capability["sequence_available"]:
        return (
            "seed_sequences AS (SELECT CAST(NULL AS VARCHAR) AS seed_id, "
            "CAST(NULL AS BIGINT) AS sequence_match_count, "
            "CAST(NULL AS BIGINT) AS distinct_sequence_count, "
            "CAST(NULL AS VARCHAR) AS sequence_species, "
            "CAST(NULL AS VARCHAR) AS sequence_identifiers, "
            "CAST(NULL AS VARCHAR) AS protein_sequence WHERE FALSE)"
        )
    columns = set(capability["sequence_columns"])
    accession = (
        "CAST(parsed_accession AS VARCHAR)"
        if "parsed_accession" in columns
        else "CAST(NULL AS VARCHAR)"
    )
    species = (
        "CAST(species AS VARCHAR)"
        if "species" in columns
        else "CAST('' AS VARCHAR)"
    )
    return (
        "sequence_rows AS (SELECT coalesce(nullif(trim("
        f"{accession}), ''), nullif(trim(CAST(raw_identifier AS VARCHAR)), '')) "
        f"AS seed_id, {species} AS species, CAST(raw_identifier AS VARCHAR) "
        "AS raw_identifier, nullif(trim(CAST(protein_sequence AS VARCHAR)), '') "
        f"AS protein_sequence FROM {quote_identifier(SEED_SEQUENCE_RELATION)} "
        "), seed_sequences AS (SELECT seed_id, count(*) "
        "AS sequence_match_count, count(DISTINCT protein_sequence) FILTER "
        "(WHERE protein_sequence IS NOT NULL) AS distinct_sequence_count, "
        "coalesce(string_agg(DISTINCT species, ';' ORDER BY species) FILTER "
        "(WHERE nullif(trim(species), '') IS NOT NULL), '') AS sequence_species, "
        "coalesce(string_agg(DISTINCT raw_identifier, ';' ORDER BY raw_identifier) "
        "FILTER (WHERE nullif(trim(raw_identifier), '') IS NOT NULL), '') "
        "AS sequence_identifiers, min(protein_sequence) FILTER "
        "(WHERE protein_sequence IS NOT NULL) AS protein_sequence FROM "
        "sequence_rows WHERE seed_id IS NOT NULL GROUP BY seed_id)"
    )


def _json_text_expression(*, keys: Sequence[str], available: set[str]) -> str:
    """Return a null-safe exact metadata value from known-seed JSON."""
    if "seed_metadata_json" not in available:
        return "CAST('' AS VARCHAR)"
    candidates = [
        "nullif(trim(json_extract_string("
        "TRY_CAST(seed_metadata_json AS JSON), "
        f"'$.{key}')), '')"
        for key in keys
    ]
    return "coalesce(" + ", ".join(candidates) + ", '')"


def _authority_source_expression(*, column: str, available: set[str]) -> str:
    """Return one optional exact authority/provenance field."""
    if column not in available:
        return "CAST('' AS VARCHAR)"
    return f"coalesce(CAST({quote_identifier(column)} AS VARCHAR), '')"


def _cluster_summary_cte(*, capability: dict[str, object]) -> str:
    """Return exact seed-to-cluster links where cluster summaries exist."""
    relation = capability.get("summary_relation")
    seed_column = capability.get("summary_seed_column")
    cluster_column = capability.get("summary_cluster_column")
    if relation is None or seed_column is None or cluster_column is None:
        return (
            "cluster_summary AS (SELECT CAST(NULL AS VARCHAR) AS seed_id, "
            "CAST(NULL AS BIGINT) AS source_cluster_count, "
            "CAST(NULL AS VARCHAR) AS source_cluster_ids WHERE FALSE)"
        )
    return (
        "cluster_links AS (SELECT DISTINCT trim(seed_id) AS seed_id, "
        f"CAST({quote_identifier(str(cluster_column))} AS VARCHAR) "
        f"AS source_cluster_id FROM {quote_identifier(str(relation))}, "
        "UNNEST(string_split(coalesce(CAST("
        f"{quote_identifier(str(seed_column))} AS VARCHAR), ''), ';')) "
        "AS seeds(seed_id) WHERE trim(seed_id) != ''), "
        "cluster_summary AS (SELECT seed_id, count(DISTINCT "
        "nullif(trim(source_cluster_id), '')) AS source_cluster_count, "
        "coalesce(string_agg(DISTINCT source_cluster_id, ';' ORDER BY "
        "source_cluster_id) FILTER (WHERE nullif(trim(source_cluster_id), '') "
        "IS NOT NULL), '') AS source_cluster_ids FROM cluster_links "
        "GROUP BY seed_id)"
    )


def _build_authority_seed_catalogue_query(
    *,
    capability: dict[str, object],
    maximum_rows: int,
) -> str:
    """Build a catalogue from the exact normalised known-seed authority."""
    available = set(capability["columns"])
    metadata = {
        "seed_protein_names": ("protein_names", "protein_name", "name"),
        "seed_category": ("category", "e3_category"),
        "seed_review_status": ("reviewed", "review_status"),
        "seed_ubiquitin_go_status": ("ubiquitin_go_term",),
        "seed_exclusion_go_term": ("exclusion_go_term",),
        "seed_organism": ("organism",),
        "seed_taxon_id": ("organism_id", "taxon_id"),
        "seed_sequence_md5": ("sequence_md5",),
        "seed_evidence_type": ("evidence_type",),
        "seed_source": ("source",),
    }
    annotations = ", ".join(
        f"{_json_text_expression(keys=keys, available=available)} "
        f"AS {quote_identifier(alias)}"
        for alias, keys in metadata.items()
    )
    provenance = ", ".join(
        f"{_authority_source_expression(column=column, available=available)} "
        f"AS {quote_identifier(column)}"
        for column in (
            "source_value",
            "source_column",
            "source_row",
            "source_path",
            "seed_metadata_json",
        )
    )
    cluster_summary = _cluster_summary_cte(capability=capability)
    sequence_cte = _sequence_cte(capability=capability)
    blank_associations = ", ".join(
        f"CAST('' AS VARCHAR) AS {quote_identifier(alias)}"
        for alias, _ in SEED_ANNOTATION_FIELDS
    )
    exact_projection = ", ".join(
        f"authority.{quote_identifier(column)}"
        for column in SEED_EXACT_ANNOTATION_FIELDS
    )
    return f"""
        WITH authority_rows AS (
            SELECT trim(CAST(seed_id AS VARCHAR)) AS seed_id,
                   {annotations},
                   {provenance},
                   ROW_NUMBER() OVER (
                       PARTITION BY trim(CAST(seed_id AS VARCHAR))
                       ORDER BY trim(CAST(seed_id AS VARCHAR))
                   ) AS seed_row
            FROM {quote_identifier(SEED_AUTHORITY_RELATION)}
            WHERE nullif(trim(CAST(seed_id AS VARCHAR)), '') IS NOT NULL
        ), authority AS (
            SELECT * EXCLUDE (seed_row) FROM authority_rows WHERE seed_row = 1
        ), {cluster_summary}, {sequence_cte}
        SELECT authority.seed_id,
               {exact_projection},
               {blank_associations},
               coalesce(clusters.source_cluster_count, 0)
                   AS source_cluster_count,
               coalesce(clusters.source_cluster_ids, '') AS source_cluster_ids,
               coalesce(sequences.distinct_sequence_count, 0) > 0
                   AS sequence_available,
               coalesce(sequences.sequence_match_count, 0)
                   AS sequence_match_count,
               coalesce(sequences.distinct_sequence_count, 0)
                   AS distinct_sequence_count,
               coalesce(sequences.sequence_species, '') AS sequence_species,
               coalesce(sequences.sequence_identifiers, '')
                   AS sequence_identifiers,
               coalesce(sequences.protein_sequence, '') AS protein_sequence,
               length(coalesce(sequences.protein_sequence, ''))
                   AS protein_sequence_length,
               authority.source_value,
               authority.source_column,
               authority.source_row,
               authority.source_path,
               authority.seed_metadata_json,
               'exact seed authority row' AS annotation_scope,
               '{SEED_AUTHORITY_RELATION}' AS catalogue_source
        FROM authority
        LEFT JOIN cluster_summary clusters USING (seed_id)
        LEFT JOIN seed_sequences sequences USING (seed_id)
        ORDER BY lower(authority.seed_id), authority.seed_id
        LIMIT {int(maximum_rows)}
    """


def build_seed_catalogue_query(
    *,
    capability: dict[str, object],
    maximum_rows: int,
) -> str:
    """Build a bounded seed catalogue query.

    Args:
        capability: Metadata returned by :func:`seed_catalogue_capability`.
        maximum_rows: Hard row limit from 1 to 100,000.

    Returns:
        Executable DuckDB SQL.

    Raises:
        AppError: If source metadata or the row bound is invalid.
    """
    if not capability.get("available"):
        raise AppError("No E3 seed evidence relation is available")
    if not 1 <= maximum_rows <= 100_000:
        raise AppError("maximum seed rows must be between 1 and 100000")
    if capability.get("mode") == "authority":
        return _build_authority_seed_catalogue_query(
            capability=capability,
            maximum_rows=maximum_rows,
        )
    relation = str(capability["relation"])
    available = set(capability["columns"])
    seed_column = str(capability["seed_id_column"])
    cluster_column = capability["cluster_column"]
    cluster_expression = (
        f"CAST({quote_identifier(str(cluster_column))} AS VARCHAR)"
        if cluster_column is not None
        else "CAST('' AS VARCHAR)"
    )
    annotation_sql = ", ".join(
        _aggregate_optional_text(
            available=available,
            choices=choices,
            alias=alias,
        )
        for alias, choices in SEED_ANNOTATION_FIELDS
    )
    sequence_cte = _sequence_cte(capability=capability)
    blank_exact = ", ".join(
        f"CAST('' AS VARCHAR) AS {quote_identifier(column)}"
        for column in SEED_EXACT_ANNOTATION_FIELDS
    )
    return f"""
        WITH exploded AS (
            SELECT DISTINCT
                   trim(seed_id) AS seed_id,
                   {cluster_expression} AS source_cluster_id,
                   * EXCLUDE ({quote_identifier(seed_column)})
            FROM {quote_identifier(relation)},
                 UNNEST(string_split(
                     coalesce(CAST({quote_identifier(seed_column)} AS VARCHAR), ''),
                     ';'
                 )) AS seeds(seed_id)
            WHERE trim(seed_id) != ''
        ), seed_annotations AS (
            SELECT seed_id,
                   count(DISTINCT nullif(trim(source_cluster_id), ''))
                       AS source_cluster_count,
                   coalesce(string_agg(DISTINCT source_cluster_id, ';'
                       ORDER BY source_cluster_id) FILTER (
                           WHERE nullif(trim(source_cluster_id), '') IS NOT NULL
                       ), '') AS source_cluster_ids,
                   {annotation_sql}
            FROM exploded
            GROUP BY seed_id
        ), {sequence_cte}
        SELECT annotations.seed_id,
               {blank_exact},
               annotations.associated_seed_protein_names,
               annotations.associated_seed_categories,
               annotations.associated_seed_review_statuses,
               annotations.associated_seed_ubiquitin_go_statuses,
               annotations.associated_seed_organisms,
               annotations.source_cluster_count,
               annotations.source_cluster_ids,
               coalesce(sequences.distinct_sequence_count, 0) > 0
                   AS sequence_available,
               coalesce(sequences.sequence_match_count, 0)
                   AS sequence_match_count,
               coalesce(sequences.distinct_sequence_count, 0)
                   AS distinct_sequence_count,
               coalesce(sequences.sequence_species, '') AS sequence_species,
               coalesce(sequences.sequence_identifiers, '')
                   AS sequence_identifiers,
               coalesce(sequences.protein_sequence, '') AS protein_sequence,
               length(coalesce(sequences.protein_sequence, ''))
                   AS protein_sequence_length,
               CAST('' AS VARCHAR) AS source_value,
               CAST('' AS VARCHAR) AS source_column,
               CAST('' AS VARCHAR) AS source_row,
               CAST('' AS VARCHAR) AS source_path,
               CAST('' AS VARCHAR) AS seed_metadata_json,
               'cluster-associated annotation; exact per-seed linkage retained '
               'only where published by the source' AS annotation_scope,
               '{relation}' AS catalogue_source
        FROM seed_annotations annotations
        LEFT JOIN seed_sequences sequences USING (seed_id)
        ORDER BY lower(annotations.seed_id), annotations.seed_id
        LIMIT {int(maximum_rows)}
    """


def collect_seed_catalogue(
    *,
    connection: duckdb.DuckDBPyConnection,
    maximum_rows: int = 10_000,
) -> pd.DataFrame:
    """Collect the bounded seed catalogue and available exact sequences."""
    capability = seed_catalogue_capability(connection=connection)
    query = build_seed_catalogue_query(
        capability=capability,
        maximum_rows=maximum_rows,
    )
    try:
        result = connection.execute(query).fetchdf()
    except duckdb.Error as exc:
        LOGGER.exception("Could not collect the E3 seed catalogue")
        raise AppError(f"Could not collect the E3 seed catalogue: {exc}") from exc
    LOGGER.info("Collected %s E3 seed catalogue rows", len(result))
    return result


def filter_seed_catalogue(*, frame: pd.DataFrame, query: str) -> pd.DataFrame:
    """Filter seeds using one or several literal pasted terms."""
    terms = tuple(
        dict.fromkeys(
            token.strip().casefold()
            for token in re.split(r"[\n\r\t,;]+", str(query or ""))
            if token.strip()
        )
    )
    if not terms or frame.empty:
        return frame
    searchable = [
        column
        for column in frame.columns
        if column != "protein_sequence"
    ]
    combined = frame[searchable].fillna("").astype(str).agg(" ".join, axis=1)
    folded = combined.str.casefold()
    mask = pd.Series(False, index=frame.index)
    for term in terms:
        mask |= folded.str.contains(term, regex=False)
    return frame.loc[mask].copy()
