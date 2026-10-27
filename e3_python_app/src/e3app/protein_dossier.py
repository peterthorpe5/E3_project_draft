"""Resolve protein searches to groups and retain all recorded linked evidence."""

from __future__ import annotations

import logging
import re
from typing import Mapping, Sequence

import duckdb
import pandas as pd

from e3app.complete_exports import iter_query_batches, query_schema
from e3app.data import quote_identifier
from e3app.enriched_hogs import (
    ENRICHED_HOG_MEMBERS,
    ENRICHED_HOG_OVERVIEW,
    enriched_hog_capability,
)
from e3app.errors import AppError
from e3app.human_hogs import RANKING_RELATION_PREFERENCE
from e3app.result_queries import ResourceQuery, build_result_query, resource_schema

LOGGER = logging.getLogger(__name__)
LinkKeys = dict[str, set[str]]
GROUP_COLUMNS = frozenset(
    {
        "group_id",
        "primary_group_id",
        "evolutionary_group_key",
        "hog_id",
        "hog_ids",
        "orthogroup",
        "orthogroup_id",
        "orthogroup_ids",
        "orthofinder_orthogroup_ids",
    }
)
CLUSTER_COLUMNS = frozenset(
    {
        "cluster",
        "cluster_id",
        "clusterid",
        "lead_cluster_id",
        "contributing_cluster_ids",
        "representative_id",
    }
)
PROTEIN_COLUMNS = frozenset(
    {
        "accession",
        "entry",
        "entry_name",
        "protein_accession",
        "candidate_accession",
        "parsed_accession",
        "member_accession",
        "member_identifier",
        "raw_identifier",
        "parsed_entry",
        "internal_id",
        "gene_id",
        "identifier_value",
        "candidate_accessions",
        "candidate_accessions_for_cluster",
        "matched_seed_ids_calculated",
        "discovery_matched_seed_ids_calculated",
        "representative_original_id",
        "seqid",
    }
)
RECORDED_GROUP_RANKINGS = "__recorded_group_rankings__"
PRESTRUCTURE_GROUP_RANKS = ("prestructure_evolutionary_group_rank", "evolutionary_group_rank")
POSTSTRUCTURE_GROUP_RANKS = ("final_evolutionary_rank", "final_rank")
RELEASE_CONTEXT_RELATIONS = frozenset(
    {
        "resource_metadata",
        "resource_relation_catalog",
        "provenance_manifest",
        "source_manifest",
        "run_metadata",
        "software_versions",
    }
)


def link_columns(*, columns: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Classify explicit relationship identifiers without using descriptive scores.

    Args:
        columns: Actual source fields in their original order.

    Returns:
        Group, cluster and protein fields suitable for exact relationship joins.
    """
    classified: dict[str, list[str]] = {"group": [], "cluster": [], "protein": []}
    for column in columns:
        lower = column.casefold()
        if lower in GROUP_COLUMNS or re.search(r"(^|_)(hog|orthogroup)_ids?$", lower):
            classified["group"].append(column)
        elif lower in CLUSTER_COLUMNS or re.search(r"(^|_)cluster_ids?$", lower):
            classified["cluster"].append(column)
        elif lower in PROTEIN_COLUMNS or re.search(
            r"(^|_)(accessions?|raw_identifiers?|parsed_entries|parsed_entry)$",
            lower,
        ):
            classified["protein"].append(column)
    return {kind: tuple(fields) for kind, fields in classified.items()}


def identifier_tokens(*, value: object, kind: str) -> set[str]:
    """Normalise stored identifier lists while retaining full original identifiers.

    Args:
        value: A stored identifier scalar or list, including nullable fields.
        kind: Group, cluster or protein identifier category.

    Returns:
        Case-normalised exact keys; accessions in pipe FASTA headers are retained.

    Raises:
        AppError: If an unsupported identifier category is requested.
    """
    if kind not in {"group", "cluster", "protein"}:
        raise AppError("Unsupported dossier identifier category")
    if value is None:
        return set()
    if isinstance(value, (list, tuple)):
        return set().union(*(identifier_tokens(value=item, kind=kind) for item in value))
    result: set[str] = set()
    for token in re.split(r"[;,\n\t]+", str(value)):
        token = token.strip()
        if not token:
            continue
        result.add(token.upper())
        if kind == "group":
            # Typed evolutionary keys can coexist with the plain published HOG ID.
            match = re.fullmatch(r"(?:[A-Za-z_]+[:|]+)?((?:N\d+\.)?HOG\d+|OG\d+)", token, re.I)
            if match:
                result.add(match.group(1).upper())
        elif kind == "protein":
            first_token = token.split(maxsplit=1)[0]
            result.add(first_token.upper())
            if "|" in first_token:
                result.update(
                    part.upper()
                    for part in first_token.split("|")
                    if part and part.lower() not in {"sp", "tr", "ref", "gb", "emb", "dbj"}
                )
    return result


def _query_link_keys(
    *,
    connection: duckdb.DuckDBPyConnection,
    query: ResourceQuery,
    columns: Sequence[str] | None = None,
) -> LinkKeys:
    """Read only relationship fields from all matching rows, in bounded batches.

    Args:
        connection: Open resource connection.
        query: Complete matched-row query.
        columns: Known source fields, avoiding repeated DESCRIBE queries.

    Returns:
        Identifier keys grouped by relationship type.
    """
    fields = link_columns(
        columns=(
            columns
            if columns is not None
            else [
                name
                for name, _ in query_schema(
                    connection=connection,
                    query=query,
                )
            ]
        )
    )
    selected = [(kind, field) for kind, columns in fields.items() for field in columns]
    keys: LinkKeys = {"group": set(), "cluster": set(), "protein": set()}
    if not selected:
        return keys
    projection = ", ".join(quote_identifier(field) for _, field in selected)
    narrow_query = ResourceQuery(
        name=query.name,
        sql=f"SELECT {projection} FROM ({query.sql}) matched_keys",
        parameters=query.parameters,
    )
    for batch in iter_query_batches(connection=connection, query=narrow_query):
        for row in batch:
            for (kind, _), value in zip(selected, row, strict=True):
                keys[kind].update(identifier_tokens(value=value, kind=kind))
    return keys


def _link_predicates(
    *,
    columns: Sequence[str],
    keys: Mapping[str, set[str]],
) -> tuple[list[tuple[str, str]], tuple[object, ...]]:
    """Build exact identifier predicates with one bound key array per field.

    Args:
        columns: Existing relation fields.
        keys: Explicit target identifiers for each relationship type.

    Returns:
        Field/predicate pairs and their bound key arrays.
    """
    fields = link_columns(columns=columns)
    predicates: list[tuple[str, str]] = []
    parameters: list[object] = []
    for kind, selected in fields.items():
        values = sorted(keys.get(kind, set()))
        if not values:
            continue
        for column in selected:
            value = f"upper(trim(coalesce(CAST({quote_identifier(column)} AS VARCHAR), '')))"
            tokens = (
                f"list_transform(regexp_split_to_array({value}, '[;|,]'), " "token -> trim(token))"
            )
            candidates = f"list_concat([{value}], {tokens})"
            if kind == "group":
                candidates = (
                    f"list_concat({candidates}, "
                    f"[regexp_replace({value}, '^[A-Za-z_]+[:|]+', '')])"
                )
            predicates.append((column, f"list_has_any({candidates}, ?)"))
            parameters.append(values)
    return predicates, tuple(parameters)


def linked_relation_query(
    *,
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    keys: Mapping[str, set[str]],
    group_id: str = "",
    schema: Mapping[str, Sequence[str]] | None = None,
) -> ResourceQuery | None:
    """Select complete rows through recorded group, cluster or protein links.

    Args:
        connection: Open resource connection.
        relation: Existing relation to inspect.
        keys: Explicit target identifiers, without recursive graph expansion.
        group_id: Optional inspected group for exported row provenance.
        schema: Optional catalogue for this same resource connection.

    Returns:
        Query with linking-column provenance, or None for an incompatible schema.

    Raises:
        AppError: If the requested relation is absent.
    """
    catalogue = resource_schema(connection=connection) if schema is None else schema
    if relation not in catalogue:
        raise AppError(f"Unknown dossier relation: {relation}")
    columns = catalogue[relation]
    conditions, parameters = _link_predicates(columns=columns, keys=keys)
    if not conditions:
        return None
    labels = [f"CASE WHEN {condition} THEN '{field}' END" for field, condition in conditions]
    return ResourceQuery(
        name=relation,
        sql=(
            f"SELECT ? AS _dossier_group, linked.* FROM (SELECT "
            f"concat_ws(';', {', '.join(labels)}) AS _dossier_link_columns, source.* "
            f"FROM {quote_identifier(relation)} source) linked "
            "WHERE length(_dossier_link_columns) > 0"
        ),
        parameters=(group_id, *parameters),
    )


def resolve_search_groups(
    *,
    connection: duckdb.DuckDBPyConnection,
    queries: Sequence[ResourceQuery],
    schema: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, ...]:
    """Resolve direct matches to recorded groups through identifier-bearing rows.

    Args:
        connection: Open resource connection.
        queries: Complete direct-match queries, never preview data frames.
        schema: Optional catalogue already read for the submitted search.

    Returns:
        All discovered group IDs, without a display-derived row limit.
        Matching proteins can belong to more than one recorded group.
    """
    direct: LinkKeys = {"group": set(), "cluster": set(), "protein": set()}
    catalogue = resource_schema(connection=connection) if schema is None else schema
    for query in queries:
        found = _query_link_keys(
            connection=connection, query=query, columns=catalogue.get(query.name)
        )
        for kind in direct:
            direct[kind].update(found[kind])
    groups = set(direct["group"])
    # One explicit bridge from the original hits resolves accession-only and
    # cluster-only evidence. Do not recursively walk shared members into unrelated HOGs.
    for relation, columns in catalogue.items():
        fields = link_columns(columns=columns)
        if not fields["group"]:
            continue
        query = linked_relation_query(
            connection=connection,
            relation=relation,
            keys=direct,
            schema=catalogue,
        )
        if query is not None:
            groups.update(
                _query_link_keys(connection=connection, query=query, columns=columns)["group"]
            )
    # Prefer the actual group field rather than displaying a typed-key duplicate.
    typed_duplicates = {
        value
        for value in groups
        if (identifier_tokens(value=value, kind="group") - {value}).intersection(groups)
    }
    result = tuple(sorted(groups - typed_duplicates))
    LOGGER.info("Resolved complete search to %d recorded groups", len(result))
    return result


def group_ranking_query(
    *,
    connection: duckdb.DuckDBPyConnection,
    group_id: str,
    schema: Mapping[str, Sequence[str]] | None = None,
    canonical_only: bool = False,
) -> ResourceQuery | None:
    """Retain original group-linked ranks from every source, with stage provenance.

    Args:
        connection: Open resource connection.
        group_id: Exact inspected group identifier.
        schema: Optional catalogue for the same resource connection.
        canonical_only: Read only established group-rank sources for a quick profile.

    Returns:
        All original group-linked ranking values, or None if no ranked source
        is available. Only established group-ranking relations and fields are
        labelled as canonical pre/post-structural ranks.
    """
    selects: list[str] = []
    parameters: list[object] = []
    keys = {"group": identifier_tokens(value=group_id, kind="group")}
    catalogue = resource_schema(connection=connection) if schema is None else schema
    for relation, columns in catalogue.items():
        if canonical_only and relation not in RANKING_RELATION_PREFERENCE:
            continue
        conditions, values = _link_predicates(columns=columns, keys=keys)
        ranks = [column for column in columns if re.search(r"(^|_)rank$", column, re.I)]
        if not conditions or not ranks:
            continue
        priority = (
            RANKING_RELATION_PREFERENCE.index(relation)
            if relation in RANKING_RELATION_PREFERENCE
            else len(RANKING_RELATION_PREFERENCE)
        )
        where = " OR ".join(condition for _, condition in conditions)
        for rank in ranks:
            if canonical_only and rank not in (
                *PRESTRUCTURE_GROUP_RANKS,
                *POSTSTRUCTURE_GROUP_RANKS,
            ):
                continue
            stage = "Source-specific rank"
            if relation in RANKING_RELATION_PREFERENCE:
                if rank in PRESTRUCTURE_GROUP_RANKS:
                    stage = "Group rank before structural analysis"
                elif rank in POSTSTRUCTURE_GROUP_RANKS:
                    stage = "Group rank after structural analysis"
            quoted = quote_identifier(rank)
            field_priority = (
                (*PRESTRUCTURE_GROUP_RANKS, *POSTSTRUCTURE_GROUP_RANKS).index(rank)
                if rank in (*PRESTRUCTURE_GROUP_RANKS, *POSTSTRUCTURE_GROUP_RANKS)
                else 99
            )
            selects.append(
                "SELECT ? AS group_id, ? AS source, ? AS rank_field, ? AS rank_stage, "
                f"CAST({quoted} AS VARCHAR) AS recorded_rank, "
                f"TRY_CAST({quoted} AS DOUBLE) AS numeric_rank, "
                f"{priority} AS source_priority, {field_priority} AS rank_field_priority "
                f"FROM {quote_identifier(relation)} "
                f"WHERE ({where}) AND {quoted} IS NOT NULL"
            )
            parameters.extend((group_id, relation, rank, stage, *values))
    if not selects:
        return None
    return ResourceQuery(
        name=RECORDED_GROUP_RANKINGS,
        sql=" UNION ALL ".join(selects)
        + " ORDER BY source_priority, rank_field_priority, source, rank_field, "
        "numeric_rank NULLS LAST, recorded_rank",
        parameters=tuple(parameters),
    )


def canonical_group_ranks(
    *,
    connection: duckdb.DuckDBPyConnection,
    query: ResourceQuery | None,
) -> pd.DataFrame:
    """Select existing ranks independently for each stage, retaining their sources.

    Args:
        connection: Open resource connection.
        query: Complete recorded-group ranking query, or None.

    Returns:
        At most one original rank per structural stage. The strongest available
        source is selected separately for each stage and the inspected group;
        a short final-ranking table cannot hide an earlier full-resource rank.
    """
    if query is None:
        return pd.DataFrame(
            columns=["rank_stage", "recorded_rank", "numeric_rank", "source", "rank_field"]
        )
    return connection.execute(
        "SELECT rank_stage, recorded_rank, numeric_rank, source, rank_field "
        f"FROM ({query.sql}) all_recorded_ranks "
        "WHERE rank_stage IN ('Group rank before structural analysis', "
        "'Group rank after structural analysis') AND numeric_rank > 0 "
        "AND isfinite(numeric_rank) QUALIFY row_number() OVER (PARTITION BY rank_stage "
        "ORDER BY source_priority, rank_field_priority, numeric_rank, source, rank_field) = 1 "
        "ORDER BY rank_stage",
        query.parameters,
    ).fetchdf()


def build_group_dossier(
    *,
    connection: duckdb.DuckDBPyConnection,
    group_id: str,
    schema: Mapping[str, Sequence[str]] | None = None,
) -> tuple[ResourceQuery, ...]:
    """Collect query plans for all evidence linked to one selected group.

    Args:
        connection: Open resource connection.
        group_id: Exact recorded HOG or other group ID selected by the user.
        schema: Optional catalogue read once for the same source.

    Returns:
        Complete overview, member and linked raw-source queries. Empty sources
        remain explicit zero-count entries when the caller exports them.

    Raises:
        AppError: If the group identifier is empty or invalid.
    """
    if not isinstance(group_id, str) or not group_id.strip() or len(group_id.strip()) > 200:
        raise AppError("Select a non-empty group identifier of at most 200 characters")
    if "\x00" in group_id:
        raise AppError("Group identifiers must not contain null characters")
    group_id = group_id.strip()
    group_keys: LinkKeys = {
        "group": identifier_tokens(value=group_id, kind="group"),
        "cluster": set(),
        "protein": set(),
    }
    keys = {kind: set(values) for kind, values in group_keys.items()}
    catalogue = resource_schema(connection=connection) if schema is None else schema
    relations = tuple(catalogue)
    for relation in relations:
        query = linked_relation_query(
            connection=connection,
            relation=relation,
            keys=group_keys,
            schema=catalogue,
        )
        if query is not None:
            found = _query_link_keys(
                connection=connection, query=query, columns=catalogue[relation]
            )
            keys["cluster"].update(found["cluster"])
            keys["protein"].update(found["protein"])
    # Capture protein identifiers present only on contributing-cluster evidence.
    cluster_keys = {"cluster": keys["cluster"]}
    for relation in relations:
        query = linked_relation_query(
            connection=connection,
            relation=relation,
            keys=cluster_keys,
            schema=catalogue,
        )
        if query is not None:
            keys["protein"].update(
                _query_link_keys(
                    connection=connection,
                    query=query,
                    columns=catalogue[relation],
                )["protein"]
            )
    queries: list[ResourceQuery] = []
    capability = enriched_hog_capability(connection=connection)
    if capability["available"]:
        for result in (ENRICHED_HOG_OVERVIEW, ENRICHED_HOG_MEMBERS):
            if result == ENRICHED_HOG_MEMBERS and not capability["membership_available"]:
                continue
            base = build_result_query(
                connection=connection,
                result=result,
                hog_ids=(group_id.upper(),),
            )
            queries.append(
                ResourceQuery(
                    name=result,
                    sql=f"SELECT * FROM ({base.sql}) group_result WHERE upper(trim(hog_id)) = ?",
                    parameters=(*base.parameters, group_id.upper()),
                )
            )
    rank_query = group_ranking_query(connection=connection, group_id=group_id, schema=catalogue)
    if rank_query is not None:
        queries.append(rank_query)
    for relation in relations:
        query = linked_relation_query(
            connection=connection,
            relation=relation,
            keys=keys,
            group_id=group_id,
            schema=catalogue,
        )
        if relation in RELEASE_CONTEXT_RELATIONS:
            query = ResourceQuery(
                name=relation,
                sql=(
                    f"SELECT ? AS _dossier_group, 'RELEASE_CONTEXT' AS _dossier_link_columns, "
                    f"source.* FROM {quote_identifier(relation)} source"
                ),
                parameters=(group_id,),
            )
        if query is not None:
            queries.append(query)
    LOGGER.info("Prepared complete group dossier group=%s sources=%d", group_id, len(queries))
    return tuple(queries)


def dossier_inventory(
    *,
    connection: duckdb.DuckDBPyConnection,
    queries: Sequence[ResourceQuery],
) -> pd.DataFrame:
    """Count complete evidence rows and fields in every planned dossier source.

    Args:
        connection: Open resource connection.
        queries: Complete evidence-source queries.

    Returns:
        Source-level counts, including zero matches, suitable for audit/export.
    """
    from e3app.result_queries import query_count

    return pd.DataFrame(
        [
            {
                "source": query.name,
                "complete_rows": query_count(connection=connection, query=query),
                "complete_fields": len(query_schema(connection=connection, query=query)),
            }
            for query in queries
        ],
        columns=["source", "complete_rows", "complete_fields"],
    )
