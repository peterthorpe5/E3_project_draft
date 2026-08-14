"""Defensive multi-item, multi-field search across loaded E3 relations."""

from __future__ import annotations

import logging
import re
from typing import Literal, Sequence

import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError

LOGGER = logging.getLogger(__name__)

SearchMode = Literal["smart", "exact", "contains"]

EXACT_SEARCH_COLUMNS = {
    "accession",
    "entry",
    "entry_name",
    "evolutionary_group_key",
    "primary_group_id",
    "group_id",
    "hog_id",
    "orthogroup_id",
    "cluster_id",
    "lead_cluster_id",
    "representative_id",
    "representative_original_id",
    "protein_accession",
    "candidate_accession",
    "parsed_accession",
    "member_accession",
    "member_identifier",
    "raw_identifier",
    "parsed_entry",
    "gene_id",
    "identifier_value",
    "candidate_accessions",
    "candidate_accessions_for_cluster",
    "matched_seed_ids_calculated",
    "discovery_matched_seed_ids_calculated",
}

TEXT_SEARCH_COLUMNS = {
    "protein_name",
    "protein_names",
    "seed_protein_names",
    "discovery_seed_protein_names",
    "gene_name",
    "gene_names",
    "matched_gene_names",
    "identifier_value",
    "entry_name",
    "category",
    "seed_categories",
    "raw_header",
    "description",
}


def parse_search_terms(*, value: str, maximum_terms: int = 50) -> tuple[str, ...]:
    """Parse a pasted identifier/name list while preserving spaces within names.

    Args:
        value: Terms separated by newlines, commas, semicolons or tabs.
        maximum_terms: Defensive maximum number of unique terms.

    Returns:
        Unique, ordered search terms.

    Raises:
        AppError: If any term or the complete list exceeds safe bounds.
    """
    if not 1 <= maximum_terms <= 500:
        raise AppError("maximum_terms must be between 1 and 500")
    if not isinstance(value, str):
        raise AppError("search input must be text")
    pieces = re.split(r"[\n,;\t]+", value)
    terms: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        term = piece.strip()
        if not term:
            continue
        if len(term) > 200:
            raise AppError("each search term must contain at most 200 characters")
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            terms.append(term)
    if len(terms) > maximum_terms:
        raise AppError(f"search accepts at most {maximum_terms} unique terms")
    return tuple(terms)


def validate_search_mode(*, mode: SearchMode) -> None:
    """Validate a unified-search matching mode."""
    if mode not in {"smart", "exact", "contains"}:
        raise AppError(f"Unsupported search mode: {mode}")


def searchable_columns(*, columns: Sequence[str]) -> tuple[list[str], list[str]]:
    """Classify exact/token and descriptive-text search fields.

    Args:
        columns: Relation column names.

    Returns:
        Exact/token fields and descriptive-text fields, in source order.
    """
    exact: list[str] = []
    text: list[str] = []
    for column in columns:
        lower = column.lower()
        if lower in EXACT_SEARCH_COLUMNS or re.search(
            r"(^|_)(hog|orthogroup|cluster|seed|accession|identifier|gene_id)(_|$)",
            lower,
        ):
            exact.append(column)
        if lower in TEXT_SEARCH_COLUMNS or re.search(
            r"(^|_)(protein|gene|seed).*name(s)?$|(^|_)(description|alias)(_|$)",
            lower,
        ):
            text.append(column)
    return exact, text


def _exact_condition(*, column: str, term_expression: str) -> str:
    """Build a case-insensitive scalar or semicolon-token match."""
    quoted = quote_identifier(column)
    value = f"upper(trim(coalesce(CAST({quoted} AS VARCHAR), '')))"
    term = f"upper(trim({term_expression}))"
    return (
        f"({value} = {term} OR "
        f"instr(';' || replace({value}, '; ', ';') || ';', "
        f"';' || {term} || ';') > 0)"
    )


def _contains_condition(*, column: str, term_expression: str) -> str:
    """Build a case-insensitive literal substring match."""
    quoted = quote_identifier(column)
    return (
        f"instr(lower(coalesce(CAST({quoted} AS VARCHAR), '')), "
        f"lower(trim({term_expression}))) > 0"
    )


def _relation_search_sql(
    *,
    relation: str,
    columns: Sequence[str],
    terms: Sequence[str],
    mode: SearchMode,
    maximum_rows: int,
) -> tuple[str, list[object]] | None:
    """Build one bound search query for a single relation."""
    exact_columns, text_columns = searchable_columns(columns=columns)
    if mode == "exact":
        selected = [(column, "exact") for column in exact_columns]
    elif mode == "contains":
        selected = [
            (column, "contains")
            for column in dict.fromkeys([*exact_columns, *text_columns])
        ]
    else:
        selected = [
            (
                column,
                "contains" if column in text_columns else "exact",
            )
            for column in dict.fromkeys([*exact_columns, *text_columns])
        ]
    if not selected:
        return None
    values = ", ".join("(?, ?)" for _ in terms)
    parameters: list[object] = []
    for order, term in enumerate(terms, start=1):
        parameters.extend((order, term))
    conditions: list[str] = []
    labels: list[str] = []
    for column, match_type in selected:
        condition = (
            _exact_condition(column=column, term_expression="t.search_term")
            if match_type == "exact"
            else _contains_condition(column=column, term_expression="t.search_term")
        )
        conditions.append(condition)
        labels.append(f"CASE WHEN {condition} THEN '{column}' END")
    sql = (
        f"WITH search_terms(search_order, search_term) AS (VALUES {values}) "
        f"SELECT t.search_order AS _search_order, t.search_term AS _search_term, "
        f"'{relation}' AS _relation, "
        f"concat_ws(';', {', '.join(labels)}) AS _matched_columns, source.* "
        f"FROM {quote_identifier(relation)} source CROSS JOIN search_terms t "
        f"WHERE {' OR '.join(conditions)} "
        "ORDER BY t.search_order "
        f"LIMIT {int(maximum_rows)}"
    )
    return sql, parameters


def collect_unified_search(
    *,
    connection: object,
    search_terms: Sequence[str],
    mode: SearchMode = "smart",
    maximum_rows_per_relation: int = 250,
    maximum_total_rows: int = 10_000,
) -> pd.DataFrame:
    """Search identifiers and names across every compatible loaded relation.

    Args:
        connection: Open read-only DuckDB connection.
        search_terms: One or several exact identifiers or name fragments.
        mode: Smart, exact/token or contains matching.
        maximum_rows_per_relation: Bound applied within each source relation.
        maximum_total_rows: Bound applied after combining relation results.

    Returns:
        Combined matches retaining relation, search-term and field provenance.
    """
    validate_search_mode(mode=mode)
    terms = tuple(dict.fromkeys(term.strip() for term in search_terms if term.strip()))
    if not terms:
        raise AppError("Enter at least one search term")
    if len(terms) > 50:
        raise AppError("search accepts at most 50 unique terms")
    if not 1 <= maximum_rows_per_relation <= 10_000:
        raise AppError("maximum_rows_per_relation must be between 1 and 10000")
    if not 1 <= maximum_total_rows <= 100_000:
        raise AppError("maximum_total_rows must be between 1 and 100000")
    frames: list[pd.DataFrame] = []
    for relation in list_relations(connection):
        columns = relation_columns(connection, relation)
        built = _relation_search_sql(
            relation=relation,
            columns=columns,
            terms=terms,
            mode=mode,
            maximum_rows=maximum_rows_per_relation,
        )
        if built is None:
            continue
        sql, parameters = built
        try:
            frame = connection.execute(sql, parameters).fetchdf()
        except Exception as exc:  # pragma: no cover - defensive per-relation isolation
            LOGGER.warning("Search skipped relation %s: %s", relation, exc)
            continue
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(
            columns=("_search_order", "_search_term", "_relation", "_matched_columns")
        )
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.sort_values(
        by=["_search_order", "_relation"],
        kind="stable",
    )
    return combined.head(maximum_total_rows).reset_index(drop=True)


def summarise_unified_search(*, matches: pd.DataFrame) -> pd.DataFrame:
    """Summarise match counts by pasted term and source relation."""
    required = {"_search_order", "_search_term", "_relation"}
    missing = sorted(required.difference(matches.columns))
    if missing:
        raise AppError("search results are missing columns: " + ", ".join(missing))
    if matches.empty:
        return pd.DataFrame(
            columns=("search_order", "search_term", "relation", "matched_rows")
        )
    summary = (
        matches.groupby(
            ["_search_order", "_search_term", "_relation"],
            dropna=False,
            sort=True,
        )
        .size()
        .rename("matched_rows")
        .reset_index()
        .rename(
            columns={
                "_search_order": "search_order",
                "_search_term": "search_term",
                "_relation": "relation",
            }
        )
    )
    return summary
