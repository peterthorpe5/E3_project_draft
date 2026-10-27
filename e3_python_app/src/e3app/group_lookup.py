"""Small, explicit group lookups that do not build the complete evidence graph."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Mapping, Sequence

import duckdb
import pandas as pd

from e3app.data import quote_identifier
from e3app.errors import AppError
from e3app.human_hogs import RANKING_RELATION_PREFERENCE
from e3app.protein_dossier import (
    _link_predicates,
    canonical_group_ranks,
    group_ranking_query,
    link_columns,
)
from e3app.result_queries import ResourceQuery, preview_query, resource_schema, validated_terms
from e3app.unified_search import SearchMode, validate_search_mode

LOGGER = logging.getLogger(__name__)
GROUP_PATTERN = re.compile(r"(?:N\d+\.HOG\d+|HOG\d+|OG\d+)\Z", re.IGNORECASE)
GROUP_LOOKUP_PREFERENCE = (
    "hierarchical_membership",
    "orthogroup_membership",
    "candidate_group_member_sequences",
    *RANKING_RELATION_PREFERENCE,
    "candidate_orthology",
    "candidate_orthology_summary",
)


def exact_group_terms(*, terms: Sequence[str], mode: SearchMode) -> tuple[str, ...]:
    """Recognise complete HOG/OG IDs without changing contains/name searches.

    Args:
        terms: Separated user terms, including possible surrounding whitespace.
        mode: Requested matching semantics.

    Returns:
        Normalised IDs if every term is a complete group ID; otherwise empty.

    Raises:
        AppError: If input terms or the matching mode are invalid.
    """
    validate_search_mode(mode=mode)
    clean = validated_terms(terms=terms)
    if mode == "contains" or not clean or not all(GROUP_PATTERN.fullmatch(term) for term in clean):
        return ()
    return tuple(term.upper() for term in clean)


def find_exact_groups(
    *,
    connection: duckdb.DuckDBPyConnection,
    terms: Sequence[str],
    schema: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, ...]:
    """Confirm group IDs in authoritative sources, stopping once each is found.

    Args:
        connection: Open resource connection.
        terms: Exact group identifiers, including supported generic group IDs.
        schema: Optional previously read source catalogue.

    Returns:
        Existing IDs in input order. A missing preferred source triggers a
        group-field-only fallback, not a scan through names and sequences.

    Raises:
        AppError: If an input or lookup source is invalid.
    """
    requested = tuple(term.upper() for term in validated_terms(terms=terms))
    catalogue = resource_schema(connection=connection) if schema is None else schema
    ordered = tuple(dict.fromkeys([*GROUP_LOOKUP_PREFERENCE, *catalogue]))
    remaining = set(requested)
    start = perf_counter()
    inspected = 0
    for relation in ordered:
        if not remaining:
            break
        fields = link_columns(columns=catalogue.get(relation, ()))["group"]
        if not fields:
            continue
        for term in tuple(remaining):
            predicates, parameters = _link_predicates(columns=fields, keys={"group": {term}})
            where = " OR ".join(condition for _, condition in predicates)
            try:
                found = connection.execute(
                    f"SELECT EXISTS (SELECT 1 FROM {quote_identifier(relation)} "
                    f"WHERE {where} LIMIT 1)",
                    parameters,
                ).fetchone()[0]
            except duckdb.Error as exc:
                LOGGER.exception("Exact group lookup could not read %s", relation)
                raise AppError(f"Exact group lookup could not read {relation}: {exc}") from exc
            inspected += 1
            if found:
                remaining.remove(term)
    result = tuple(term for term in requested if term not in remaining)
    LOGGER.info(
        "Exact group lookup requested=%d found=%d source_checks=%d elapsed_seconds=%.3f",
        len(requested),
        len(result),
        inspected,
        perf_counter() - start,
    )
    return result


def group_match_queries(
    *,
    connection: duckdb.DuckDBPyConnection,
    terms: Sequence[str],
    schema: Mapping[str, Sequence[str]] | None = None,
) -> tuple[ResourceQuery, ...]:
    """Build complete direct matches restricted to recorded group identifier fields.

    Args:
        connection: Open resource connection.
        terms: Exact group identifiers selected by the user.
        schema: Optional catalogue for this same resource.

    Returns:
        Uncapped per-source queries retaining every source field and match provenance.

    Raises:
        AppError: If the input contains no valid search terms.
    """
    clean = validated_terms(terms=terms)
    if not clean:
        raise AppError("Enter at least one group identifier")
    catalogue = resource_schema(connection=connection) if schema is None else schema
    queries = []
    for relation, columns in catalogue.items():
        fields = link_columns(columns=columns)["group"]
        if not fields:
            continue
        selects = []
        parameters: list[object] = []
        for order, term in enumerate(clean, start=1):
            predicates, values = _link_predicates(columns=fields, keys={"group": {term.upper()}})
            labels = [
                f"CASE WHEN {condition} THEN '{field}' END" for field, condition in predicates
            ]
            selects.append(
                "SELECT * FROM (SELECT ? AS _search_order, ? AS _search_term, ? AS _relation, "
                f"concat_ws(';', {', '.join(labels)}) AS _matched_columns, source.* "
                f"FROM {quote_identifier(relation)} source) matches "
                "WHERE length(_matched_columns) > 0"
            )
            parameters.extend((order, term, relation, *values))
        sql = " UNION ALL ".join(selects) + " ORDER BY _search_order"
        queries.append(ResourceQuery(name=relation, sql=sql, parameters=tuple(parameters)))
    return tuple(queries)


def quick_group_profile(
    *,
    connection: duckdb.DuckDBPyConnection,
    group_id: str,
    maximum_rows: int = 100,
    schema: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, object]:
    """Read stored ranks and one scoped membership summary before loading a dossier.

    Args:
        connection: Open resource connection.
        group_id: Exact existing group selected by the user.
        maximum_rows: Bound on the lightweight member preview.
        schema: Optional catalogue for the same source.

    Returns:
        Original rank values/provenance, membership counts and a small metadata
        preview. Full source inventories and enriched all-HOG joins are deferred.

    Raises:
        AppError: If the group identifier, preview bound or source is invalid.
    """
    clean = validated_terms(terms=(group_id,))
    if not clean:
        raise AppError("Choose a group identifier")
    if (
        isinstance(maximum_rows, bool)
        or not isinstance(maximum_rows, int)
        or not 1 <= maximum_rows <= 100_000
    ):
        raise AppError("Preview rows must be between 1 and 100000")
    group_id = clean[0].upper()
    catalogue = resource_schema(connection=connection) if schema is None else schema
    start = perf_counter()
    ranking = group_ranking_query(
        connection=connection,
        group_id=group_id,
        schema=catalogue,
        canonical_only=True,
    )
    ranks = canonical_group_ranks(connection=connection, query=ranking)
    result: dict[str, object] = {
        "group_id": group_id,
        "ranks": ranks,
        "member_count": None,
        "species_count": None,
        "membership_source": None,
        "members": pd.DataFrame(),
    }
    sources = [
        "hierarchical_membership",
        "orthogroup_membership",
        "candidate_group_member_sequences",
    ]
    if group_id.startswith("OG"):
        sources[0], sources[1] = sources[1], sources[0]
    for relation in sources:
        columns = catalogue.get(relation, ())
        fields = link_columns(columns=columns)["group"]
        if not fields:
            continue
        group_field = next(
            (field for field in ("group_id", "hog_id", "primary_group_id") if field in fields),
            fields[0],
        )
        conditions, parameters = _link_predicates(
            columns=(group_field,), keys={"group": {group_id}}
        )
        where = conditions[0][1]
        species = next((field for field in ("species", "species_column") if field in columns), None)
        species_count = f"count(DISTINCT {quote_identifier(species)})" if species else "NULL"
        count, represented = connection.execute(
            f"SELECT count(*), {species_count} FROM {quote_identifier(relation)} WHERE {where}",
            parameters,
        ).fetchone()
        if not count:
            continue
        metadata = [
            field
            for field in (
                group_field,
                "species",
                "species_column",
                "parsed_accession",
                "parsed_entry",
                "raw_identifier",
                "member_accession",
                "sequence_length",
                "mapping_status",
                "review_status",
            )
            if field in columns
        ]
        projection = ", ".join(quote_identifier(field) for field in dict.fromkeys(metadata))
        query = ResourceQuery(
            name=relation,
            sql=f"SELECT {projection} FROM {quote_identifier(relation)} WHERE {where}",
            parameters=parameters,
        )
        result.update(
            {
                "member_count": int(count),
                "species_count": represented,
                "membership_source": relation,
                "members": preview_query(
                    connection=connection, query=query, maximum_rows=maximum_rows
                ),
            }
        )
        break
    LOGGER.info(
        "Loaded quick group profile group=%s elapsed_seconds=%.3f", group_id, perf_counter() - start
    )
    return result
