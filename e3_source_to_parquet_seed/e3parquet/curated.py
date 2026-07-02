"""Curated DuckDB view builder for the E3 PROTAC resource.

The functions in this module create a second, query-oriented layer on top of
source-preserving Parquet tables. The goal is not to hide source data. Each
curated view keeps provenance columns whenever possible and the build writes a
verbose debug report describing which sources were found, which were missing,
and which views were created.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from e3parquet.io_utils import normalise_relative_path, safe_name, write_tsv

LOGGER = logging.getLogger(__name__)

ACCESSION_CANDIDATES = (
    "protein_accession",
    "accession",
    "Accession",
    "entry",
    "Entry",
    "From",
    "from",
    "Entry name",
    "Entry_Name",
    "inferred_accession",
    "UniProtKB-AC",
    "UniProtKB AC",
    "uniprot_accession",
    "uniprot_id",
)
GENE_CANDIDATES = ("gene_names", "Gene Names", "Gene names", "gene", "Gene", "gene_id")
ORGANISM_CANDIDATES = ("organism", "Organism", "species", "Species")
ORGANISM_ID_CANDIDATES = ("organism_id", "Organism ID", "Taxon", "taxon_id", "Taxonomic lineage IDs")
SEQUENCE_CANDIDATES = ("sequence", "Sequence")
SEQUENCE_MD5_CANDIDATES = ("sequence_md5", "sequence_md5sum")
POCKET_NAME_CANDIDATES = ("Alt_Pocket_Name", "pocket_name", "Pockets", "name")
DRUGGABILITY_CANDIDATES = ("Druggability_Score", "druggability_score", "druggability")
PROBABILITY_CANDIDATES = ("probability", "Probability")
RANK_CANDIDATES = ("rank", "Rank")
P2RANK_SCORE_CANDIDATES = ("P2Rank_score", "score", "Score")
GO_ID_CANDIDATES = ("go_id", "GO", "GO ID", "Gene Ontology IDs", "Gene ontology IDs")
PAPER_ID_CANDIDATES = ("paper_ids", "Paper", "paper", "PMID", "PubMed", "publication")
HOG_CANDIDATES = ("hog", "HOG", "orthogroup", "Orthogroup", "cluster", "Cluster")

SQLITE_SELECT_PREFIX_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE | re.DOTALL)
SQL_COMMENT_LINE_RE = re.compile(r"^\s*--")


@dataclass
class DebugRecorder:
    """Collect structured debug records and write human-readable reports."""

    records: List[Dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        step: str,
        status: str,
        message: str,
        **details: Any,
    ) -> None:
        """Append a debug record and log it."""
        record: Dict[str, Any] = {
            "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "step": step,
            "status": status,
            "message": message,
        }
        for key, value in details.items():
            if isinstance(value, (list, tuple, dict)):
                record[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            else:
                record[key] = value
        self.records.append(record)
        log_message = "%s | %s | %s", step, status, message
        if status.lower() in {"failed", "error", "missing"}:
            LOGGER.error(*log_message)
        elif status.lower().startswith("warn") or status.lower() == "skipped":
            LOGGER.warning(*log_message)
        else:
            LOGGER.info(*log_message)

    def write(self, output_tsv: Path, output_md: Path) -> None:
        """Write TSV and Markdown debug reports."""
        write_tsv(self.records, output_tsv)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# E3 curated resource build debug report",
            "",
            f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
            "",
            "This report records what the curation script found, what it could not find, and which DuckDB views/tables were created.",
            "It is intended for iterative debugging while the inherited project is being converted into a cleaner query resource.",
            "",
            "## Summary by status",
            "",
        ]
        status_counts: Dict[str, int] = {}
        for record in self.records:
            status = str(record.get("status", ""))
            status_counts[status] = status_counts.get(status, 0) + 1
        for status, count in sorted(status_counts.items()):
            lines.append(f"- `{status}`: {count}")
        lines.extend(["", "## Detailed records", ""])
        for index, record in enumerate(self.records, start=1):
            lines.append(f"### {index}. {record.get('step', '')} — {record.get('status', '')}")
            lines.append("")
            lines.append(str(record.get("message", "")))
            detail_items = [
                (key, value)
                for key, value in record.items()
                if key not in {"timestamp_utc", "step", "status", "message"}
            ]
            if detail_items:
                lines.append("")
                for key, value in detail_items:
                    lines.append(f"- `{key}`: `{value}`")
            lines.append("")
        output_md.write_text("\n".join(lines), encoding="utf-8")


def duckdb_quote_identifier(identifier: str) -> str:
    """Quote a DuckDB identifier."""
    return '"' + identifier.replace('"', '""') + '"'


def duckdb_quote_literal(value: str) -> str:
    """Quote a DuckDB string literal."""
    return "'" + value.replace("'", "''") + "'"


def normalise_column_name(name: str) -> str:
    """Normalise a column name for case-insensitive matching."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def find_column(columns: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    """Return the first matching column from a list of candidates."""
    by_normalised = {normalise_column_name(column): column for column in columns}
    for candidate in candidates:
        found = by_normalised.get(normalise_column_name(candidate))
        if found is not None:
            return found
    return None


def coalesce_columns_sql(
    table_alias: str,
    columns: Sequence[str],
    candidates: Sequence[str],
    default_sql: str = "NULL",
) -> str:
    """Build a SQL coalesce expression over available candidate columns."""
    expressions: List[str] = []
    used: set[str] = set()
    for candidate in candidates:
        column = find_column(columns, [candidate])
        if column is None or column in used:
            continue
        used.add(column)
        expressions.append(
            f"NULLIF(CAST({duckdb_quote_identifier(table_alias)}.{duckdb_quote_identifier(column)} AS VARCHAR), '')"
        )
    if not expressions:
        return default_sql
    if len(expressions) == 1:
        return expressions[0]
    return "COALESCE(" + ", ".join(expressions) + ")"


def try_cast_numeric_sql(expression: str) -> str:
    """Return a DuckDB TRY_CAST expression for numeric fields."""
    return f"TRY_CAST({expression} AS DOUBLE)"


def safe_view_suffix(text: str, max_length: int = 96) -> str:
    """Return a compact suffix for generated helper view names."""
    return safe_name(text.replace("parquet__", "").replace("source_tables__", ""), max_length=max_length)


def list_duckdb_objects(connection: Any) -> List[str]:
    """List DuckDB tables and views in the current database."""
    rows = connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def columns_for_object(connection: Any, object_name: str) -> List[str]:
    """Return column names for a DuckDB table or view."""
    rows = connection.execute(f"DESCRIBE SELECT * FROM {duckdb_quote_identifier(object_name)}").fetchall()
    return [str(row[0]) for row in rows]


def row_count(connection: Any, object_name: str) -> Optional[int]:
    """Return a row count for a DuckDB object, or None on failure."""
    try:
        value = connection.execute(
            f"SELECT COUNT(*) FROM {duckdb_quote_identifier(object_name)}"
        ).fetchone()[0]
        return int(value)
    except Exception:  # pragma: no cover - defensive DB path
        LOGGER.exception("Failed counting rows for %s", object_name)
        return None


def get_view_catalog(connection: Any) -> List[Dict[str, str]]:
    """Return parquet view catalogue records when available."""
    objects = set(list_duckdb_objects(connection))
    if "parquet_view_catalog" not in objects:
        return []
    rows = connection.execute(
        "SELECT view_name, parquet_file, status, error FROM parquet_view_catalog ORDER BY view_name"
    ).fetchall()
    return [
        {
            "view_name": str(row[0]),
            "parquet_file": str(row[1]),
            "status": str(row[2]),
            "error": str(row[3]),
        }
        for row in rows
    ]


def score_catalog_record(
    record: Mapping[str, str],
    include_terms: Sequence[str],
    exclude_terms: Sequence[str] = (),
) -> int:
    """Score a parquet-view catalogue record against search terms."""
    text = " ".join(
        [
            str(record.get("view_name", "")),
            str(record.get("parquet_file", "")),
        ]
    ).lower()
    if any(term.lower() in text for term in exclude_terms):
        return -10_000
    score = 0
    for term in include_terms:
        if term.lower() in text:
            score += 10
    # Prefer the selected curated source over older/benchmark copies.
    if "curated_e3_database" in text or "main_folder_e3_database" in text:
        score += 20
    if "source_tables" in text:
        score += 5
    if "inherited_reports" in text or "january_2026" in text:
        score -= 5
    if "small_test" in text or "benchmark" in text:
        score -= 20
    return score


def select_best_catalog_view(
    catalog: Sequence[Mapping[str, str]],
    include_terms: Sequence[str],
    exclude_terms: Sequence[str] = (),
) -> Optional[str]:
    """Select the best matching view from the parquet catalogue."""
    best_name: Optional[str] = None
    best_score = -1
    for record in catalog:
        if str(record.get("status", "")) not in {"created", ""}:
            continue
        score = score_catalog_record(record, include_terms, exclude_terms)
        if score > best_score:
            best_score = score
            best_name = str(record.get("view_name", ""))
    if best_score <= 0:
        return None
    return best_name


def select_views_by_terms(
    catalog: Sequence[Mapping[str, str]],
    include_any: Sequence[str],
    exclude_any: Sequence[str] = (),
) -> List[str]:
    """Return matching view names from the parquet catalogue."""
    selected: List[str] = []
    for record in catalog:
        text = " ".join(
            [str(record.get("view_name", "")), str(record.get("parquet_file", ""))]
        ).lower()
        if any(term.lower() in text for term in exclude_any):
            continue
        if any(term.lower() in text for term in include_any):
            selected.append(str(record.get("view_name", "")))
    return sorted(set(selected))


def create_or_replace_view(connection: Any, view_name: str, sql: str) -> None:
    """Create or replace a DuckDB view."""
    connection.execute(f"DROP VIEW IF EXISTS {duckdb_quote_identifier(view_name)}")
    connection.execute(f"CREATE VIEW {duckdb_quote_identifier(view_name)} AS {sql}")


def create_empty_view(connection: Any, view_name: str, columns: Mapping[str, str]) -> None:
    """Create an empty typed placeholder view."""
    expressions = [f"CAST(NULL AS {sql_type}) AS {duckdb_quote_identifier(name)}" for name, sql_type in columns.items()]
    create_or_replace_view(connection, view_name, "SELECT " + ", ".join(expressions) + " WHERE FALSE")


def raw_source_column_projection(
    table_alias: str,
    columns: Sequence[str],
    reserved_aliases: Iterable[str] | None = None,
    raw_prefix: str = "_raw_",
) -> str:
    """Return source-column projections with unique raw aliases.

    Curated views expose standardised columns such as ``protein_accession`` or
    ``sequence`` while also preserving all original inherited columns.  Using
    ``t.*`` is unsafe because source tables may already contain columns with the
    same names as the curated aliases.  DuckDB is especially strict when those
    SELECT statements are later combined with ``UNION ALL BY NAME``.

    This helper keeps all source metadata, but renames every inherited column to
    a deterministic ``_raw_*`` alias.
    """
    reserved = {str(alias).lower() for alias in (reserved_aliases or [])}
    used = set(reserved)
    expressions: list[str] = []
    for column in columns:
        base_alias = f"{raw_prefix}{safe_name(str(column))}"
        if not base_alias or base_alias == raw_prefix:
            base_alias = f"{raw_prefix}column"
        alias = base_alias
        counter = 2
        while alias.lower() in used:
            alias = f"{base_alias}_{counter}"
            counter += 1
        used.add(alias.lower())
        expressions.append(
            f"{duckdb_quote_identifier(table_alias)}.{duckdb_quote_identifier(str(column))} "
            f"AS {duckdb_quote_identifier(alias)}"
        )
    if not expressions:
        return "CAST(NULL AS VARCHAR) AS _raw_no_source_columns"
    return ",\n                ".join(expressions)


def create_protein_records_view(
    connection: Any,
    catalog: Sequence[Mapping[str, str]],
    debug: DebugRecorder,
) -> Optional[str]:
    """Create the protein_records view from the best E3 ligase table."""
    source_view = select_best_catalog_view(
        catalog,
        include_terms=("e3_ligases.csv", "e3_ligases"),
        exclude_terms=("small_test", "january_2026", "desktop"),
    )
    if source_view is None:
        create_empty_view(
            connection,
            "protein_records",
            {
                "protein_accession": "VARCHAR",
                "gene_names_standardised": "VARCHAR",
                "organism_standardised": "VARCHAR",
                "organism_id_standardised": "VARCHAR",
            },
        )
        debug.add("protein_records", "missing", "No E3 ligase source table was found; created empty placeholder view.")
        return None

    columns = columns_for_object(connection, source_view)
    accession_sql = coalesce_columns_sql("t", columns, ACCESSION_CANDIDATES)
    gene_sql = coalesce_columns_sql("t", columns, GENE_CANDIDATES)
    organism_sql = coalesce_columns_sql("t", columns, ORGANISM_CANDIDATES)
    organism_id_sql = coalesce_columns_sql("t", columns, ORGANISM_ID_CANDIDATES)
    sequence_sql = coalesce_columns_sql("t", columns, SEQUENCE_CANDIDATES)
    sequence_md5_sql = coalesce_columns_sql("t", columns, SEQUENCE_MD5_CANDIDATES)
    category_sql = coalesce_columns_sql("t", columns, ("category", "Category"))
    reviewed_sql = coalesce_columns_sql("t", columns, ("reviewed", "Reviewed"))
    protein_name_sql = coalesce_columns_sql("t", columns, ("protein_names", "Protein names", "Protein names"))
    length_sql = coalesce_columns_sql("t", columns, ("length", "Length"))

    sql = f"""
        SELECT
            {accession_sql} AS protein_accession,
            {gene_sql} AS gene_names_standardised,
            {organism_sql} AS organism_standardised,
            {organism_id_sql} AS organism_id_standardised,
            {category_sql} AS e3_category_standardised,
            {reviewed_sql} AS reviewed_standardised,
            {protein_name_sql} AS protein_names_standardised,
            TRY_CAST({length_sql} AS BIGINT) AS protein_length_standardised,
            {sequence_sql} AS embedded_sequence,
            {sequence_md5_sql} AS embedded_sequence_md5,
            {duckdb_quote_literal(source_view)} AS _curated_source_view,
            {raw_source_column_projection(
                "t",
                columns,
                reserved_aliases=(
                    "protein_accession",
                    "gene_names_standardised",
                    "organism_standardised",
                    "organism_id_standardised",
                    "e3_category_standardised",
                    "reviewed_standardised",
                    "protein_names_standardised",
                    "protein_length_standardised",
                    "embedded_sequence",
                    "embedded_sequence_md5",
                    "_curated_source_view",
                ),
            )}
        FROM {duckdb_quote_identifier(source_view)} AS t
    """
    create_or_replace_view(connection, "protein_records", sql)
    debug.add(
        "protein_records",
        "created",
        "Created protein_records from the best E3 ligase table.",
        source_view=source_view,
        source_columns=columns,
        rows=row_count(connection, "protein_records"),
    )
    return source_view


def create_union_by_name_view(
    connection: Any,
    view_name: str,
    source_views: Sequence[str],
    standard_select_builder: Any,
    empty_columns: Mapping[str, str],
    debug: DebugRecorder,
    step: str,
    message: str,
) -> None:
    """Create a UNION ALL BY NAME view over heterogeneous source views."""
    if not source_views:
        create_empty_view(connection, view_name, empty_columns)
        debug.add(step, "missing", f"No source views found for {view_name}; created empty placeholder.")
        return

    selects: List[str] = []
    for source_view in source_views:
        columns = columns_for_object(connection, source_view)
        selects.append(standard_select_builder(source_view, columns))
    sql = "\nUNION ALL BY NAME\n".join(selects)
    create_or_replace_view(connection, view_name, sql)
    debug.add(
        step,
        "created",
        message,
        source_views=source_views,
        rows=row_count(connection, view_name),
    )


def create_protein_sequences_view(
    connection: Any,
    catalog: Sequence[Mapping[str, str]],
    debug: DebugRecorder,
) -> None:
    """Create protein_sequences from parsed FASTA and sequence-like tables."""
    fasta_views = select_views_by_terms(
        catalog,
        include_any=("parquet/sequences", "sequences/", "fasta__"),
        exclude_any=("skipped",),
    )

    def builder(source_view: str, columns: Sequence[str]) -> str:
        accession_sql = coalesce_columns_sql("t", columns, ACCESSION_CANDIDATES)
        sequence_sql = coalesce_columns_sql("t", columns, SEQUENCE_CANDIDATES)
        sequence_md5_sql = coalesce_columns_sql("t", columns, SEQUENCE_MD5_CANDIDATES)
        length_sql = coalesce_columns_sql("t", columns, ("sequence_length", "length", "Length"))
        header_sql = coalesce_columns_sql("t", columns, ("fasta_header", "header", "Header"))
        return f"""
            SELECT
                {accession_sql} AS protein_accession,
                {header_sql} AS sequence_header,
                {sequence_sql} AS sequence,
                TRY_CAST({length_sql} AS BIGINT) AS sequence_length,
                {sequence_md5_sql} AS sequence_md5,
                {duckdb_quote_literal(source_view)} AS _curated_source_view,
                {raw_source_column_projection(
                    "t",
                    columns,
                    reserved_aliases=(
                        "protein_accession",
                        "sequence_header",
                        "sequence",
                        "sequence_length",
                        "sequence_md5",
                        "_curated_source_view",
                    ),
                )}
            FROM {duckdb_quote_identifier(source_view)} AS t
        """

    create_union_by_name_view(
        connection,
        "protein_sequences",
        fasta_views,
        builder,
        {
            "protein_accession": "VARCHAR",
            "sequence_header": "VARCHAR",
            "sequence": "VARCHAR",
            "sequence_length": "BIGINT",
            "sequence_md5": "VARCHAR",
        },
        debug,
        "protein_sequences",
        "Created protein_sequences from parsed FASTA/source sequence tables.",
    )


def create_literature_evidence_view(
    connection: Any,
    catalog: Sequence[Mapping[str, str]],
    debug: DebugRecorder,
) -> None:
    """Create a heterogeneous literature_evidence view."""
    views = select_views_by_terms(
        catalog,
        include_any=(
            "other_people_data",
            "literature_reference_datasets",
            "mapped_data",
            "medvar",
            "ciulli",
            "liu",
            "gagne",
            "gange",
            "gingerich",
            "stone",
            "capron",
            "lee",
            "mudgil",
            "downes",
            "paper",
            "publication",
        ),
        exclude_any=("sequences", "fasta"),
    )

    def builder(source_view: str, columns: Sequence[str]) -> str:
        accession_sql = coalesce_columns_sql("t", columns, ACCESSION_CANDIDATES)
        paper_sql = coalesce_columns_sql("t", columns, PAPER_ID_CANDIDATES)
        return f"""
            SELECT
                {accession_sql} AS protein_accession,
                {paper_sql} AS paper_or_publication_id,
                {duckdb_quote_literal(source_view)} AS _curated_source_view,
                t.*
            FROM {duckdb_quote_identifier(source_view)} AS t
        """

    create_union_by_name_view(
        connection,
        "literature_evidence",
        views,
        builder,
        {
            "protein_accession": "VARCHAR",
            "paper_or_publication_id": "VARCHAR",
            "_curated_source_view": "VARCHAR",
        },
        debug,
        "literature_evidence",
        "Created literature_evidence from inherited literature/mapping datasets.",
    )


def create_go_term_evidence_view(
    connection: Any,
    catalog: Sequence[Mapping[str, str]],
    debug: DebugRecorder,
) -> None:
    """Create GO-term evidence view."""
    views = select_views_by_terms(
        catalog,
        include_any=("go_terms", "go_terms", "e3_go", "gene_ontology", "ubiquitin_go"),
        exclude_any=("sqlite",),
    )
    protein_source = select_best_catalog_view(catalog, ("e3_ligases.csv", "e3_ligases"), ("small_test",))
    if protein_source:
        views.append(protein_source)
    views = sorted(set(views))

    def builder(source_view: str, columns: Sequence[str]) -> str:
        accession_sql = coalesce_columns_sql("t", columns, ACCESSION_CANDIDATES)
        go_sql = coalesce_columns_sql("t", columns, GO_ID_CANDIDATES)
        ubiq_sql = coalesce_columns_sql("t", columns, ("ubiquitin_go_term", "ubiquitin", "Ubiquitin"))
        exclusion_sql = coalesce_columns_sql("t", columns, ("exclusion_go_term", "exclusion", "Exclusion"))
        return f"""
            SELECT
                {accession_sql} AS protein_accession,
                {go_sql} AS go_id_or_terms,
                {ubiq_sql} AS ubiquitin_go_term_flag,
                {exclusion_sql} AS exclusion_go_term_flag,
                {duckdb_quote_literal(source_view)} AS _curated_source_view,
                t.*
            FROM {duckdb_quote_identifier(source_view)} AS t
        """

    create_union_by_name_view(
        connection,
        "go_term_evidence",
        views,
        builder,
        {
            "protein_accession": "VARCHAR",
            "go_id_or_terms": "VARCHAR",
            "ubiquitin_go_term_flag": "VARCHAR",
            "exclusion_go_term_flag": "VARCHAR",
        },
        debug,
        "go_term_evidence",
        "Created go_term_evidence from GO and E3 source tables.",
    )


def create_ligandability_pocket_scores_view(
    connection: Any,
    catalog: Sequence[Mapping[str, str]],
    debug: DebugRecorder,
) -> None:
    """Create ligandability/pocket evidence view."""
    views = select_views_by_terms(
        catalog,
        include_any=(
            "pocket",
            "druggability",
            "ligandability",
            "fpocket",
            "p2rank",
            "prank",
            "af2bind",
            "promising_candidates",
            "human_top_candidates",
            "test_query_20260430",
        ),
        exclude_any=("text_lines", "sql_queries"),
    )

    def builder(source_view: str, columns: Sequence[str]) -> str:
        accession_sql = coalesce_columns_sql("t", columns, ACCESSION_CANDIDATES)
        pocket_sql = coalesce_columns_sql("t", columns, POCKET_NAME_CANDIDATES)
        drug_sql = coalesce_columns_sql("t", columns, DRUGGABILITY_CANDIDATES)
        prob_sql = coalesce_columns_sql("t", columns, PROBABILITY_CANDIDATES)
        rank_sql = coalesce_columns_sql("t", columns, RANK_CANDIDATES)
        p2rank_sql = coalesce_columns_sql("t", columns, P2RANK_SCORE_CANDIDATES)
        return f"""
            SELECT
                {accession_sql} AS protein_accession,
                {pocket_sql} AS pocket_name_standardised,
                {try_cast_numeric_sql(drug_sql)} AS druggability_score_numeric,
                {try_cast_numeric_sql(prob_sql)} AS probability_numeric,
                TRY_CAST({rank_sql} AS BIGINT) AS pocket_rank_numeric,
                {try_cast_numeric_sql(p2rank_sql)} AS p2rank_score_numeric,
                {duckdb_quote_literal(source_view)} AS _curated_source_view,
                t.*
            FROM {duckdb_quote_identifier(source_view)} AS t
        """

    create_union_by_name_view(
        connection,
        "ligandability_pocket_scores",
        views,
        builder,
        {
            "protein_accession": "VARCHAR",
            "pocket_name_standardised": "VARCHAR",
            "druggability_score_numeric": "DOUBLE",
            "probability_numeric": "DOUBLE",
            "pocket_rank_numeric": "BIGINT",
            "p2rank_score_numeric": "DOUBLE",
        },
        debug,
        "ligandability_pocket_scores",
        "Created ligandability_pocket_scores from pocket/candidate/ligandability sources.",
    )


def create_deepclust_views(
    connection: Any,
    catalog: Sequence[Mapping[str, str]],
    debug: DebugRecorder,
) -> None:
    """Create exploratory DeepClust views where source files are present."""
    deepclust_views = select_views_by_terms(
        catalog,
        include_any=("deepclust", "concat_db_clustered", "realigned_clusters"),
        exclude_any=("benchmark", "small_test"),
    )

    def builder(source_view: str, columns: Sequence[str]) -> str:
        accession_sql = coalesce_columns_sql("t", columns, ACCESSION_CANDIDATES)
        cluster_sql = coalesce_columns_sql("t", columns, HOG_CANDIDATES)
        return f"""
            SELECT
                {accession_sql} AS protein_accession,
                {cluster_sql} AS cluster_or_orthogroup_id,
                {duckdb_quote_literal(source_view)} AS _curated_source_view,
                t.*
            FROM {duckdb_quote_identifier(source_view)} AS t
        """

    create_union_by_name_view(
        connection,
        "deepclust_cluster_evidence",
        deepclust_views,
        builder,
        {
            "protein_accession": "VARCHAR",
            "cluster_or_orthogroup_id": "VARCHAR",
            "_curated_source_view": "VARCHAR",
        },
        debug,
        "deepclust_cluster_evidence",
        "Created deepclust_cluster_evidence from copied/source DeepClust outputs.",
    )


def create_candidate_e3_summary_view(connection: Any, debug: DebugRecorder) -> None:
    """Create a compact candidate summary view over curated evidence layers."""
    objects = set(list_duckdb_objects(connection))
    if "protein_records" not in objects:
        create_empty_view(
            connection,
            "candidate_e3_summary",
            {
                "protein_accession": "VARCHAR",
                "organism_standardised": "VARCHAR",
                "e3_category_standardised": "VARCHAR",
            },
        )
        debug.add("candidate_e3_summary", "missing", "protein_records missing; created empty candidate summary.")
        return

    # These helper views tolerate empty evidence views and avoid expensive wide joins.
    connection.execute("DROP VIEW IF EXISTS ligandability_by_protein")
    connection.execute(
        """
        CREATE VIEW ligandability_by_protein AS
        SELECT
            protein_accession,
            COUNT(*) AS ligandability_record_count,
            MAX(druggability_score_numeric) AS max_druggability_score,
            MAX(probability_numeric) AS max_pocket_probability,
            MIN(pocket_rank_numeric) AS best_pocket_rank,
            COUNT(DISTINCT _curated_source_view) AS ligandability_source_count
        FROM ligandability_pocket_scores
        WHERE protein_accession IS NOT NULL AND protein_accession <> ''
        GROUP BY protein_accession
        """
    )
    connection.execute("DROP VIEW IF EXISTS literature_by_protein")
    connection.execute(
        """
        CREATE VIEW literature_by_protein AS
        SELECT
            protein_accession,
            COUNT(*) AS literature_record_count,
            COUNT(DISTINCT _curated_source_view) AS literature_source_count
        FROM literature_evidence
        WHERE protein_accession IS NOT NULL AND protein_accession <> ''
        GROUP BY protein_accession
        """
    )
    connection.execute("DROP VIEW IF EXISTS go_by_protein")
    connection.execute(
        """
        CREATE VIEW go_by_protein AS
        SELECT
            protein_accession,
            COUNT(*) AS go_record_count,
            MAX(CASE WHEN LOWER(COALESCE(ubiquitin_go_term_flag, '')) IN ('1', 'true', 'yes') THEN 1 ELSE 0 END) AS has_ubiquitin_go_term,
            MAX(CASE WHEN LOWER(COALESCE(exclusion_go_term_flag, '')) IN ('1', 'true', 'yes') THEN 1 ELSE 0 END) AS has_exclusion_go_term
        FROM go_term_evidence
        WHERE protein_accession IS NOT NULL AND protein_accession <> ''
        GROUP BY protein_accession
        """
    )
    connection.execute("DROP VIEW IF EXISTS sequence_by_protein")
    connection.execute(
        """
        CREATE VIEW sequence_by_protein AS
        SELECT
            protein_accession,
            COUNT(*) AS sequence_record_count,
            MAX(sequence_length) AS max_sequence_length,
            ANY_VALUE(sequence_md5) AS representative_sequence_md5
        FROM protein_sequences
        WHERE protein_accession IS NOT NULL AND protein_accession <> ''
        GROUP BY protein_accession
        """
    )
    connection.execute("DROP VIEW IF EXISTS deepclust_by_protein")
    connection.execute(
        """
        CREATE VIEW deepclust_by_protein AS
        SELECT
            protein_accession,
            COUNT(*) AS deepclust_record_count,
            ANY_VALUE(cluster_or_orthogroup_id) AS example_cluster_or_orthogroup_id
        FROM deepclust_cluster_evidence
        WHERE protein_accession IS NOT NULL AND protein_accession <> ''
        GROUP BY protein_accession
        """
    )
    connection.execute("DROP VIEW IF EXISTS candidate_e3_summary")
    connection.execute(
        """
        CREATE VIEW candidate_e3_summary AS
        SELECT
            p.protein_accession,
            p.gene_names_standardised,
            p.organism_standardised,
            p.organism_id_standardised,
            p.e3_category_standardised,
            p.reviewed_standardised,
            p.protein_names_standardised,
            p.protein_length_standardised,
            COALESCE(s.sequence_record_count, 0) AS sequence_record_count,
            s.max_sequence_length,
            s.representative_sequence_md5,
            COALESCE(l.ligandability_record_count, 0) AS ligandability_record_count,
            l.max_druggability_score,
            l.max_pocket_probability,
            l.best_pocket_rank,
            COALESCE(l.ligandability_source_count, 0) AS ligandability_source_count,
            COALESCE(g.go_record_count, 0) AS go_record_count,
            COALESCE(g.has_ubiquitin_go_term, 0) AS has_ubiquitin_go_term,
            COALESCE(g.has_exclusion_go_term, 0) AS has_exclusion_go_term,
            COALESCE(le.literature_record_count, 0) AS literature_record_count,
            COALESCE(le.literature_source_count, 0) AS literature_source_count,
            COALESCE(d.deepclust_record_count, 0) AS deepclust_record_count,
            d.example_cluster_or_orthogroup_id,
            CASE
                WHEN l.max_druggability_score IS NOT NULL OR l.max_pocket_probability IS NOT NULL THEN 1
                ELSE 0
            END AS has_ligandability_evidence,
            CASE WHEN le.literature_record_count IS NOT NULL THEN 1 ELSE 0 END AS has_literature_evidence,
            CASE WHEN s.sequence_record_count IS NOT NULL THEN 1 ELSE 0 END AS has_sequence_evidence,
            p._curated_source_view AS protein_source_view
        FROM protein_records AS p
        LEFT JOIN sequence_by_protein AS s USING (protein_accession)
        LEFT JOIN ligandability_by_protein AS l USING (protein_accession)
        LEFT JOIN go_by_protein AS g USING (protein_accession)
        LEFT JOIN literature_by_protein AS le USING (protein_accession)
        LEFT JOIN deepclust_by_protein AS d USING (protein_accession)
        """
    )
    debug.add(
        "candidate_e3_summary",
        "created",
        "Created candidate_e3_summary by joining curated evidence aggregates to protein_records.",
        rows=row_count(connection, "candidate_e3_summary"),
    )


def split_sql_statements(sql_text: str) -> List[str]:
    """Split SQL text into top-level semicolon-delimited statements.

    This is deliberately conservative but handles simple quoted strings.
    """
    statements: List[str] = []
    buffer: List[str] = []
    in_single = False
    in_double = False
    previous = ""
    for character in sql_text:
        if character == "'" and not in_double and previous != "\\":
            in_single = not in_single
        elif character == '"' and not in_single and previous != "\\":
            in_double = not in_double
        if character == ";" and not in_single and not in_double:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
        else:
            buffer.append(character)
        previous = character
    statement = "".join(buffer).strip()
    if statement:
        statements.append(statement)
    return statements


def strip_sql_comments(sql_text: str) -> str:
    """Remove whole-line SQL comments while preserving query text."""
    lines = [line for line in sql_text.splitlines() if not SQL_COMMENT_LINE_RE.match(line)]
    return "\n".join(lines).strip()


def extract_select_queries_from_files(sql_files: Sequence[Path], raw_root: Path) -> List[Dict[str, Any]]:
    """Extract SELECT/WITH queries from SQL/TXT files."""
    queries: List[Dict[str, Any]] = []
    for sql_file in sorted(sql_files):
        rel_path = normalise_relative_path(sql_file.relative_to(raw_root))
        text = sql_file.read_text(encoding="utf-8", errors="replace")
        for index, statement in enumerate(split_sql_statements(text), start=1):
            cleaned = strip_sql_comments(statement)
            if not cleaned:
                continue
            if not SQLITE_SELECT_PREFIX_RE.match(cleaned):
                continue
            queries.append(
                {
                    "query_id": f"{safe_name(rel_path)}__query_{index:03d}",
                    "source_file": rel_path,
                    "query_index": index,
                    "sql_text": cleaned,
                }
            )
    return queries


def run_sqlite_regression_queries(
    sqlite_db: Path,
    sql_files: Sequence[Path],
    raw_root: Path,
    max_rows: int = 100_000,
) -> List[Dict[str, Any]]:
    """Run non-destructive SELECT queries against the inherited SQLite DB."""
    queries = extract_select_queries_from_files(sql_files, raw_root)
    results: List[Dict[str, Any]] = []
    executed_at = dt.datetime.now(dt.timezone.utc).isoformat()
    with sqlite3.connect(str(sqlite_db)) as connection:
        for query in queries:
            record: Dict[str, Any] = {
                **query,
                "sqlite_db": normalise_relative_path(sqlite_db.relative_to(raw_root))
                if sqlite_db.is_relative_to(raw_root)
                else str(sqlite_db),
                "sqlite_status": "not_run",
                "sqlite_row_count": "",
                "sqlite_column_count": "",
                "sqlite_columns_json": "[]",
                "sqlite_error": "",
                "duckdb_equivalent_status": "not_started",
                "duckdb_equivalent_view_or_sql": "",
                "executed_at_utc": executed_at,
            }
            try:
                cursor = connection.execute(str(query["sql_text"]))
                columns = [description[0] for description in cursor.description or []]
                count = 0
                while True:
                    rows = cursor.fetchmany(10_000)
                    if not rows:
                        break
                    count += len(rows)
                    if count > max_rows:
                        record["sqlite_status"] = "stopped_after_max_rows"
                        break
                else:  # pragma: no cover - while loop always breaks
                    record["sqlite_status"] = "ok"
                if record["sqlite_status"] == "not_run":
                    record["sqlite_status"] = "ok"
                record["sqlite_row_count"] = count
                record["sqlite_column_count"] = len(columns)
                record["sqlite_columns_json"] = json.dumps(columns, ensure_ascii=False)
            except Exception as exc:  # noqa: BLE001 - keep regression failures as data
                record["sqlite_status"] = "failed"
                record["sqlite_error"] = str(exc)
            results.append(record)
    return results


def source_sql_files(raw_root: Path) -> List[Path]:
    """Return SQL and query-like text files likely containing SQLite examples."""
    files: List[Path] = []
    for path in raw_root.rglob("*"):
        if not path.is_file():
            continue
        lower = path.as_posix().lower()
        if "sql_queries" in lower and path.suffix.lower() in {".sql", ".txt"}:
            files.append(path)
    return sorted(files)


def locate_sqlite_db(raw_root: Path) -> Optional[Path]:
    """Locate the main inherited E3 SQLite database inside the raw copy."""
    candidates = sorted(raw_root.rglob("e3_ligase_sqlite_db.db"))
    if candidates:
        for candidate in candidates:
            if "Main_folder/E3_database" in normalise_relative_path(candidate.relative_to(raw_root)):
                return candidate
        return candidates[0]
    return None


def normalise_records_for_parquet(
    records: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Return records with stable, Arrow-friendly column types.

    The inherited SQL regression records deliberately capture both successful
    and failed queries.  That means fields such as ``sqlite_row_count`` may be
    numeric for successful queries and blank for failed queries.  PyArrow will
    reject those mixed object columns when pandas tries to infer an integer
    schema.  For audit/regression outputs we prefer robustness and readability,
    so optional mixed fields are serialised as strings before writing Parquet.
    """
    normalised: List[Dict[str, Any]] = []
    for record in records:
        clean: Dict[str, Any] = {}
        for key, value in record.items():
            if value is None:
                clean[str(key)] = ""
            elif isinstance(value, (list, tuple, dict)):
                clean[str(key)] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            else:
                clean[str(key)] = str(value)
        normalised.append(clean)
    return normalised


def write_regression_results(
    records: Sequence[Mapping[str, Any]],
    out_tsv: Path,
    out_parquet: Path,
) -> None:
    """Write SQLite regression results to TSV and, when available, Parquet."""
    normalised_records = normalise_records_for_parquet(records)
    write_tsv(normalised_records, out_tsv)
    if not normalised_records:
        return
    try:
        import pandas as pd  # type: ignore

        out_parquet.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame.from_records(normalised_records)
        frame.to_parquet(out_parquet, index=False)
    except Exception:  # pragma: no cover - optional dependency path
        LOGGER.exception("Failed writing sqlite regression parquet; TSV was still written")


def create_sqlite_regression_view_if_present(
    connection: Any,
    derived_dir: Path,
    debug: DebugRecorder,
) -> None:
    """Create sqlite_regression_query_results from a regression Parquet/TSV output."""
    parquet_path = derived_dir / "qc" / "sqlite_regression_query_results.parquet"
    tsv_path = derived_dir / "qc" / "sqlite_regression_query_results.tsv"
    if parquet_path.exists():
        sql = f"SELECT * FROM read_parquet({duckdb_quote_literal(str(parquet_path))})"
        create_or_replace_view(connection, "sqlite_regression_query_results", sql)
        debug.add(
            "sqlite_regression_query_results",
            "created",
            "Created sqlite_regression_query_results from Parquet regression results.",
            rows=row_count(connection, "sqlite_regression_query_results"),
        )
    elif tsv_path.exists():
        sql = f"SELECT * FROM read_csv_auto({duckdb_quote_literal(str(tsv_path))}, delim='\t', header=true)"
        create_or_replace_view(connection, "sqlite_regression_query_results", sql)
        debug.add(
            "sqlite_regression_query_results",
            "created",
            "Created sqlite_regression_query_results from TSV regression results.",
            rows=row_count(connection, "sqlite_regression_query_results"),
        )
    else:
        create_empty_view(
            connection,
            "sqlite_regression_query_results",
            {
                "query_id": "VARCHAR",
                "source_file": "VARCHAR",
                "sqlite_status": "VARCHAR",
                "sqlite_row_count": "BIGINT",
                "sqlite_error": "VARCHAR",
            },
        )
        debug.add("sqlite_regression_query_results", "missing", "No SQLite regression output found; created empty placeholder.")


def inspect_expression_duckdb(expression_duckdb: Optional[Path]) -> List[Dict[str, Any]]:
    """Inspect an optional Expression Atlas DuckDB resource."""
    records: List[Dict[str, Any]] = []
    checked_at = dt.datetime.now(dt.timezone.utc).isoformat()
    if expression_duckdb is None:
        return [
            {
                "checked_at_utc": checked_at,
                "expression_duckdb": "",
                "status": "not_provided",
                "object_name": "",
                "row_count": "",
                "message": "No --expression-duckdb path was provided. Expression/RNAseq data remain in the separate expression resource, not the source-first E3 resource.",
            }
        ]
    if not expression_duckdb.exists():
        return [
            {
                "checked_at_utc": checked_at,
                "expression_duckdb": str(expression_duckdb),
                "status": "missing_file",
                "object_name": "",
                "row_count": "",
                "message": "Expression DuckDB path does not exist.",
            }
        ]
    try:
        import duckdb  # type: ignore
    except ImportError:
        return [
            {
                "checked_at_utc": checked_at,
                "expression_duckdb": str(expression_duckdb),
                "status": "duckdb_not_installed",
                "object_name": "",
                "row_count": "",
                "message": "Cannot inspect expression DuckDB because python-duckdb is not installed.",
            }
        ]
    try:
        with duckdb.connect(str(expression_duckdb), read_only=True) as connection:
            objects = list_duckdb_objects(connection)
            if not objects:
                records.append(
                    {
                        "checked_at_utc": checked_at,
                        "expression_duckdb": str(expression_duckdb),
                        "status": "no_objects_found",
                        "object_name": "",
                        "row_count": "",
                        "message": "Expression DuckDB opened but no tables/views were found.",
                    }
                )
            for object_name in objects:
                records.append(
                    {
                        "checked_at_utc": checked_at,
                        "expression_duckdb": str(expression_duckdb),
                        "status": "found",
                        "object_name": object_name,
                        "row_count": row_count(connection, object_name) or "",
                        "message": "Expression object found. The Shiny app should use E3_EXPRESSION_DUCKDB for this data unless it is deliberately imported later.",
                    }
                )
    except Exception as exc:  # pragma: no cover - defensive external DB path
        records.append(
            {
                "checked_at_utc": checked_at,
                "expression_duckdb": str(expression_duckdb),
                "status": "failed",
                "object_name": "",
                "row_count": "",
                "message": str(exc),
            }
        )
    return records


def write_expression_status(records: Sequence[Mapping[str, Any]], out_tsv: Path, out_parquet: Path) -> None:
    """Write expression resource status records."""
    write_tsv(records, out_tsv)
    if not records:
        return
    try:
        import pandas as pd  # type: ignore

        out_parquet.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame.from_records(records).to_parquet(out_parquet, index=False)
    except Exception:  # pragma: no cover
        LOGGER.exception("Failed writing expression status parquet; TSV was still written")


def create_expression_status_view_if_present(
    connection: Any,
    derived_dir: Path,
    debug: DebugRecorder,
) -> None:
    """Create expression_resource_status view from QC output."""
    parquet_path = derived_dir / "qc" / "expression_resource_status.parquet"
    tsv_path = derived_dir / "qc" / "expression_resource_status.tsv"
    if parquet_path.exists():
        create_or_replace_view(
            connection,
            "expression_resource_status",
            f"SELECT * FROM read_parquet({duckdb_quote_literal(str(parquet_path))})",
        )
    elif tsv_path.exists():
        create_or_replace_view(
            connection,
            "expression_resource_status",
            f"SELECT * FROM read_csv_auto({duckdb_quote_literal(str(tsv_path))}, delim='\t', header=true)",
        )
    else:
        create_empty_view(
            connection,
            "expression_resource_status",
            {
                "checked_at_utc": "VARCHAR",
                "expression_duckdb": "VARCHAR",
                "status": "VARCHAR",
                "object_name": "VARCHAR",
                "row_count": "VARCHAR",
                "message": "VARCHAR",
            },
        )
    debug.add(
        "expression_resource_status",
        "created",
        "Created expression_resource_status. This diagnoses whether RNAseq/expression data were supplied as a separate DuckDB resource.",
        rows=row_count(connection, "expression_resource_status"),
    )


def export_curated_views_to_parquet(
    connection: Any,
    derived_dir: Path,
    view_names: Sequence[str],
    debug: DebugRecorder,
) -> None:
    """Materialise curated views to Parquet files for reproducibility."""
    out_dir = derived_dir / "curated_parquet"
    out_dir.mkdir(parents=True, exist_ok=True)
    for view_name in view_names:
        out_path = out_dir / f"{safe_name(view_name)}.parquet"
        try:
            connection.execute(
                f"COPY (SELECT * FROM {duckdb_quote_identifier(view_name)}) TO {duckdb_quote_literal(str(out_path))} (FORMAT PARQUET)"
            )
            debug.add(
                "export_curated_parquet",
                "written",
                f"Exported {view_name} to curated Parquet.",
                view_name=view_name,
                output_parquet=normalise_relative_path(out_path.relative_to(derived_dir)),
            )
        except Exception as exc:  # pragma: no cover - external DB path
            debug.add(
                "export_curated_parquet",
                "failed",
                f"Failed exporting {view_name} to Parquet.",
                view_name=view_name,
                error=str(exc),
            )


def create_curated_views(
    duckdb_path: Path,
    derived_dir: Path,
    debug: DebugRecorder,
    materialise_parquet: bool = True,
) -> List[str]:
    """Create all curated views in the DuckDB resource."""
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "duckdb is required for curated view creation. Install with: "
            "conda install -c conda-forge duckdb python-duckdb"
        ) from exc

    curated_view_names = [
        "protein_records",
        "protein_sequences",
        "literature_evidence",
        "go_term_evidence",
        "ligandability_pocket_scores",
        "deepclust_cluster_evidence",
        "sqlite_regression_query_results",
        "expression_resource_status",
        "candidate_e3_summary",
    ]

    with duckdb.connect(str(duckdb_path)) as connection:
        catalog = get_view_catalog(connection)
        if not catalog:
            debug.add(
                "parquet_view_catalog",
                "missing",
                "No parquet_view_catalog was found. Run e3_create_duckdb_views.py before e3_build_curated_resource.py.",
            )
        else:
            debug.add(
                "parquet_view_catalog",
                "found",
                "Found source Parquet views for curation.",
                count=len(catalog),
            )

        create_protein_records_view(connection, catalog, debug)
        create_protein_sequences_view(connection, catalog, debug)
        create_literature_evidence_view(connection, catalog, debug)
        create_go_term_evidence_view(connection, catalog, debug)
        create_ligandability_pocket_scores_view(connection, catalog, debug)
        create_deepclust_views(connection, catalog, debug)
        create_sqlite_regression_view_if_present(connection, derived_dir, debug)
        create_expression_status_view_if_present(connection, derived_dir, debug)
        create_candidate_e3_summary_view(connection, debug)

        connection.execute("DROP TABLE IF EXISTS curated_view_catalog")
        connection.execute(
            "CREATE TABLE curated_view_catalog(view_name VARCHAR, row_count BIGINT, created_at_utc VARCHAR)"
        )
        rows = [
            (view_name, row_count(connection, view_name) or 0, dt.datetime.now(dt.timezone.utc).isoformat())
            for view_name in curated_view_names
        ]
        connection.executemany("INSERT INTO curated_view_catalog VALUES (?, ?, ?)", rows)

        if materialise_parquet:
            export_curated_views_to_parquet(connection, derived_dir, curated_view_names, debug)

    return curated_view_names
