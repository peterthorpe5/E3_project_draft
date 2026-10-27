"""Complete resource queries, independent of presentation row and column limits."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from numbers import Integral
from typing import Mapping, Sequence

import duckdb
import pandas as pd

from e3app.data import IDENTIFIER_PATTERN, list_relations, quote_identifier, relation_columns
from e3app.enriched_hogs import (
    ENRICHED_HOG_LABELS,
    _build_enriched_hog_query,
    enriched_hog_columns,
)
from e3app.errors import AppError
from e3app.unified_search import (
    SearchMode,
    _contains_condition,
    _exact_condition,
    _relation_search_sql,
    searchable_columns,
    validate_search_mode,
)

LOGGER = logging.getLogger(__name__)


def resource_schema(*, connection: duckdb.DuckDBPyConnection) -> dict[str, tuple[str, ...]]:
    """Read the resource's relation/field catalogue in one metadata query.

    Args:
        connection: Open resource connection.

    Returns:
        Trusted relation names and fields in their published order.
    """
    rows = connection.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'main' ORDER BY lower(table_name), table_name, ordinal_position"
    ).fetchall()
    schema: dict[str, list[str]] = {}
    for relation, column in rows:
        if IDENTIFIER_PATTERN.fullmatch(relation):
            schema.setdefault(relation, []).append(column)
    return {relation: tuple(columns) for relation, columns in schema.items()}


@dataclass(frozen=True, kw_only=True)
class ResourceQuery:
    """One complete, parameter-bound result to preview or export.

    Attributes:
        name: Source relation or virtual result name.
        sql: Read-only SELECT statement without a presentation row limit.
        parameters: Bound query values, kept separate from SQL.
    """

    name: str
    sql: str
    parameters: tuple[object, ...] = ()


def validated_terms(*, terms: Sequence[str]) -> tuple[str, ...]:
    """Validate already separated terms without treating punctuation as a new list.

    Args:
        terms: Explicit identifiers or name fragments.

    Returns:
        Trimmed, case-insensitively unique terms in input order.

    Raises:
        AppError: If the term collection or an individual term is invalid.
    """
    if not isinstance(terms, Sequence) or isinstance(terms, (str, bytes)):
        raise AppError("Search terms must be a sequence of text values")
    if any(not isinstance(term, str) for term in terms):
        raise AppError("Each search term must be text")
    if any(len(term.strip()) > 200 for term in terms):
        raise AppError("Each search term must contain at most 200 characters")
    if any("\x00" in term for term in terms):
        raise AppError("Search terms must not contain null characters")
    unique: dict[str, str] = {}
    for term in terms:
        if term.strip():
            unique.setdefault(term.strip().casefold(), term.strip())
    result = tuple(unique.values())
    if len(result) > 50:
        raise AppError("Search accepts at most 50 unique terms")
    return result


def search_predicate(
    *,
    columns: Sequence[str],
    terms: Sequence[str],
    mode: SearchMode,
) -> tuple[str, tuple[object, ...]]:
    """Build a literal search predicate using bound terms and discovered fields.

    Args:
        columns: Columns available in the complete source.
        terms: Explicit terms; an empty sequence means no filter.
        mode: Smart, exact/token or literal contains matching.

    Returns:
        SQL predicate and corresponding bound values.

    Raises:
        AppError: If the mode or search terms are invalid.
    """
    validate_search_mode(mode=mode)
    clean = validated_terms(terms=terms)
    if not clean:
        return "TRUE", ()
    exact, descriptive = searchable_columns(columns=columns)
    fields = exact if mode == "exact" else list(dict.fromkeys([*exact, *descriptive]))
    conditions: list[str] = []
    parameters: list[object] = []
    for column in fields:
        contains = mode == "contains" or (mode == "smart" and column in descriptive)
        builder = _contains_condition if contains else _exact_condition
        condition = builder(column=column, term_expression="term.value")
        conditions.append(f"EXISTS (SELECT 1 FROM unnest(?) term(value) WHERE {condition})")
        parameters.append(list(clean))
    return " OR ".join(conditions) or "FALSE", tuple(parameters)


def build_result_query(
    *,
    connection: duckdb.DuckDBPyConnection,
    result: str,
    columns: Sequence[str] | None = None,
    terms: Sequence[str] = (),
    mode: SearchMode = "smart",
    hog_ids: Sequence[str] = (),
) -> ResourceQuery:
    """Build a complete raw or enriched query, filtering before any preview limit.

    Args:
        connection: Open resource connection.
        result: Existing relation or enriched result key.
        columns: Output fields, or every field when omitted.
        terms: Optional identifiers or names to match in all source fields.
        mode: Matching method for the optional filter.
        hog_ids: Optional exact HOG scope, applied before joined aggregation.

    Returns:
        Complete query; HOG and member ranks retain their resource-wide meaning.

    Raises:
        AppError: If the source, fields or search request is invalid.
    """
    if result in ENRICHED_HOG_LABELS:
        available = enriched_hog_columns(connection=connection, result=result)
        sql, parameters = _build_enriched_hog_query(
            connection=connection,
            result=result,
            selected_columns=available,
            maximum_rows=None,
            hog_ids=hog_ids,
        )
    else:
        if result not in list_relations(connection=connection):
            raise AppError(f"Unknown resource relation: {result}")
        available = relation_columns(connection=connection, relation=result)
        sql, parameters = f"SELECT * FROM {quote_identifier(result)}", []
    selected = available if columns is None else list(dict.fromkeys(columns))
    if not selected:
        raise AppError("Select at least one result field")
    if set(selected).difference(available):
        raise AppError(
            "Unknown result fields: " + ", ".join(sorted(set(selected) - set(available)))
        )
    predicate, search_parameters = search_predicate(columns=available, terms=terms, mode=mode)
    projection = ", ".join(quote_identifier(column) for column in selected)
    return ResourceQuery(
        name=result,
        sql=f"SELECT {projection} FROM ({sql}) complete_source WHERE ({predicate})",
        parameters=tuple(parameters) + search_parameters,
    )


def build_search_queries(
    *,
    connection: duckdb.DuckDBPyConnection,
    terms: Sequence[str],
    mode: SearchMode = "smart",
    schema: Mapping[str, Sequence[str]] | None = None,
) -> tuple[ResourceQuery, ...]:
    """Build uncapped direct-match queries with term and source provenance.

    Args:
        connection: Open resource connection.
        terms: Explicit identifiers or name fragments.
        mode: Identifier/name matching method.
        schema: Optional previously read catalogue for this same resource.

    Returns:
        One complete query for each searchable relation.

    Raises:
        AppError: If the search is empty or invalid.
    """
    validate_search_mode(mode=mode)
    clean = validated_terms(terms=terms)
    if not clean:
        raise AppError("Enter at least one search term")
    queries = []
    catalogue = resource_schema(connection=connection) if schema is None else schema
    for relation, columns in catalogue.items():
        built = _relation_search_sql(
            relation=relation,
            columns=columns,
            terms=clean,
            mode=mode,
            maximum_rows=None,
        )
        if built is not None:
            sql, parameters = built
            queries.append(ResourceQuery(name=relation, sql=sql, parameters=tuple(parameters)))
    return tuple(queries)


def query_count(*, connection: duckdb.DuckDBPyConnection, query: ResourceQuery) -> int:
    """Count the full result without fetching its rows into pandas.

    Args:
        connection: Open resource connection.
        query: Complete resource query.

    Returns:
        Exact matching row count, including rows beyond the screen preview.

    Raises:
        AppError: If the query cannot be evaluated.
    """
    try:
        return int(
            connection.execute(
                f"SELECT count(*) FROM ({query.sql}) result_count",
                query.parameters,
            ).fetchone()[0]
        )
    except duckdb.Error as exc:
        LOGGER.exception("Could not count complete result %s", query.name)
        raise AppError(f"Could not count complete result {query.name}: {exc}") from exc


def preview_query(
    *,
    connection: duckdb.DuckDBPyConnection,
    query: ResourceQuery,
    maximum_rows: int,
) -> pd.DataFrame:
    """Fetch only a screen preview after all full-resource predicates have run.

    Args:
        connection: Open resource connection.
        query: Complete query, independent of the preview cap.
        maximum_rows: Positive screen limit up to 100,000 rows.

    Returns:
        A bounded preview retaining every requested field.

    Raises:
        AppError: If the limit or query is invalid.
    """
    if (
        not isinstance(maximum_rows, Integral)
        or isinstance(maximum_rows, bool)
        or not 1 <= maximum_rows <= 100_000
    ):
        raise AppError("Preview rows must be between 1 and 100000")
    try:
        return connection.execute(
            f"SELECT * FROM ({query.sql}) preview_source LIMIT {int(maximum_rows)}",
            query.parameters,
        ).fetchdf()
    except duckdb.Error as exc:
        LOGGER.exception("Could not preview complete result %s", query.name)
        raise AppError(f"Could not preview {query.name}: {exc}") from exc


def summarise_search_queries(
    *,
    connection: duckdb.DuckDBPyConnection,
    queries: Sequence[ResourceQuery],
) -> pd.DataFrame:
    """Count every search match by term and relation without preview truncation.

    Args:
        connection: Open resource connection.
        queries: Complete direct-match queries with search provenance.

    Returns:
        Exact term/relation counts; empty sources are omitted.

    Raises:
        AppError: If a source cannot be searched; partial results are never silent.
    """
    frames = []
    for query in queries:
        try:
            frame = connection.execute(
                "SELECT _search_order AS search_order, _search_term AS search_term, "
                f"? AS relation, count(*) AS matched_rows FROM ({query.sql}) matched "
                "GROUP BY _search_order, _search_term ORDER BY _search_order",
                [query.name, *query.parameters],
            ).fetchdf()
        except duckdb.Error as exc:
            LOGGER.exception("Could not search source %s", query.name)
            raise AppError(f"Search could not read {query.name}: {exc}") from exc
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["search_order", "search_term", "relation", "matched_rows"])
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(
            by=["search_order", "relation"],
            kind="stable",
        )
        .reset_index(drop=True)
    )
