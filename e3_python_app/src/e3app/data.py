"""Read-only, bounded DuckDB queries independent of Streamlit."""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Mapping, Sequence

import duckdb
import pandas as pd

from e3app.errors import AppError

if TYPE_CHECKING:
    from e3app.config import AppConfig

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ACCESSION_COLUMNS = (
    "accession",
    "entry",
    "protein_accession",
    "candidate_accession",
    "parsed_accession",
    "member_accession",
    "candidate_accessions",
    "matched_seed_ids_calculated",
    "discovery_matched_seed_ids_calculated",
)

SECTION_SPECS: Mapping[str, Mapping[str, object]] = {
    "final_recommendations": {
        "title": "Computational recommendations",
        "description": (
            "Which distinct evolutionary candidate groups should be reviewed in "
            "the ordered top 50, which pass every enabled grant-aligned gate, "
            "how sensitive are decisions to named alternatives, and why?"
        ),
        "relations": (
            "top_computational_review_shortlist",
            "top_50_computational_review_shortlist",
            "top_20_computational_review_shortlist",
            "gate_sensitivity_summary",
            "gate_sensitivity_detail",
            "grant_aligned_predicted_candidates",
            "final_evolutionary_candidate_prioritisation",
            "final_evolutionary_group_cluster_contributors",
            "final_candidate_exclusion_audit",
        ),
    },
    "candidates": {
        "title": "Candidate prioritisation",
        "description": (
            "Which candidate E3 groups best satisfy the combined conservation, "
            "domain, expression and structural evidence gates?"
        ),
        "relations": (
            "final_evolutionary_candidate_prioritisation",
            "candidate_master_results",
            "final_candidate_prioritisation",
            "prestructure_ranking",
            "candidate_evidence",
        ),
    },
    "orthology": {
        "title": "Cross-species orthology",
        "description": (
            "Which OrthoFinder groups contain each candidate, which species are "
            "represented and what are the group-member sequences?"
        ),
        "relations": (
            "candidate_orthology",
            "candidate_orthology_summary",
            "candidate_group_member_sequences",
            "orthogroup_membership",
            "hierarchical_membership",
        ),
    },
    "domains": {
        "title": "E3 domain support",
        "description": (
            "Is a catalogued E3-associated domain supported across the assessed "
            "members, and where is annotation unavailable?"
        ),
        "relations": ("domain_summary", "domain_hits", "candidate_master_results"),
    },
    "expression": {
        "title": "Expression support",
        "description": (
            "Which candidate-group members map to Expression Atlas and show broad "
            "plant expression support?"
        ),
        "relations": (
            "candidate_expression_context_summary",
            "candidate_expression_summary",
            "candidate_expression_mapping",
            "candidate_identifier_aliases",
            "candidate_master_results",
        ),
    },
    "ligandability": {
        "title": "Ligandability",
        "description": (
            "Which shortlisted proteins have reusable, high-confidence pockets "
            "supported by fpocket/P2Rank evidence?"
        ),
        "relations": (
            "selected_pockets",
            "ranked_member_pockets",
            "structural_prediction_status",
            "structural_analysis_accessions",
            "candidate_master_results",
        ),
    },
    "pocket_conservation": {
        "title": "Pocket conservation",
        "description": (
            "Is the pocket-bearing region conserved across candidate-group members, "
            "and can pocket residues be traced to FASTA coordinates?"
        ),
        "relations": (
            "pocket_conservation_summary",
            "pocket_conservation_members",
            "pocket_sequence_coordinates",
            "ranked_pocket_sequence_coordinates",
            "candidate_master_results",
        ),
    },
    "structural_alignment": {
        "title": "3D pocket alignment",
        "description": (
            "Do US-align and TM-align support an equivalent 3D pocket position and "
            "stronger local pocket-structure conservation?"
        ),
        "relations": (
            "structural_alignment_summary",
            "structural_pocket_sensitivity_group_summary",
            "structural_pocket_sensitivity_member_summary",
            "structural_pocket_sensitivity_comparisons",
            "structural_pocket_sensitivity_residue_matches",
            "structural_pocket_comparisons",
            "structural_pocket_residue_matches",
            "structural_alignments",
            "candidate_master_results",
        ),
    },
    "provenance": {
        "title": "Provenance and quality control",
        "description": (
            "Which release, files, checksums and evidence limitations underpin the "
            "displayed result?"
        ),
        "relations": (
            "resource_metadata",
            "resource_relation_catalog",
        ),
    },
}

CANONICAL_PARQUET_RELATIONS = {
    "e3_candidate_master_results": "candidate_master_results",
    "final_candidate_prioritisation": "final_candidate_prioritisation",
    "top_20_computational_review_shortlist": (
        "top_20_computational_review_shortlist"
    ),
    "top_computational_review_shortlist": (
        "top_computational_review_shortlist"
    ),
    "top_50_computational_review_shortlist": (
        "top_50_computational_review_shortlist"
    ),
    "gate_sensitivity_detail": "gate_sensitivity_detail",
    "gate_sensitivity_summary": "gate_sensitivity_summary",
    "grant_aligned_predicted_candidates": "grant_aligned_predicted_candidates",
    "final_evolutionary_candidate_prioritisation": (
        "final_evolutionary_candidate_prioritisation"
    ),
    "final_evolutionary_group_cluster_contributors": (
        "final_evolutionary_group_cluster_contributors"
    ),
    "final_candidate_exclusion_audit": "final_candidate_exclusion_audit",
    "computational_prestructure_ranking": "prestructure_ranking",
    "evolutionary_candidate_group_ranking": (
        "evolutionary_candidate_group_ranking"
    ),
    "evolutionary_group_cluster_contributors": (
        "evolutionary_group_cluster_contributors"
    ),
    "e3_cluster_candidate_evidence": "candidate_evidence",
    "candidate_membership_mapping": "candidate_orthology",
    "candidate_cluster_orthology_summary": "candidate_orthology_summary",
    "candidate_group_member_sequences": "candidate_group_member_sequences",
    "orthogroup_membership": "orthogroup_membership",
    "hierarchical_membership": "hierarchical_membership",
    "domain_summary": "domain_summary",
    "domain_hits": "domain_hits",
    "candidate_identifier_aliases": "candidate_identifier_aliases",
    "candidate_expression_mapping": "candidate_expression_mapping",
    "candidate_expression_summary": "candidate_expression_summary",
    "candidate_expression_context_summary": "candidate_expression_context_summary",
    "structural_analysis_accessions": "structural_analysis_accessions",
    "structural_representative_selection_audit": (
        "structural_representative_selection_audit"
    ),
    "selected_pockets": "selected_pockets",
    "ranked_member_pockets": "ranked_member_pockets",
    "structural_prediction_status": "structural_prediction_status",
    "pocket_conservation_summary": "pocket_conservation_summary",
    "pocket_conservation_members": "pocket_conservation_members",
    "pocket_sequence_coordinates": "pocket_sequence_coordinates",
    "ranked_pocket_sequence_coordinates": (
        "ranked_pocket_sequence_coordinates"
    ),
    "structural_alignments": "structural_alignments",
    "pocket_comparisons": "structural_pocket_comparisons",
    "pocket_residue_matches": "structural_pocket_residue_matches",
    "structural_alignment_summary": "structural_alignment_summary",
    "structural_pocket_sensitivity_comparisons": (
        "structural_pocket_sensitivity_comparisons"
    ),
    "structural_pocket_sensitivity_residue_matches": (
        "structural_pocket_sensitivity_residue_matches"
    ),
    "structural_pocket_sensitivity_member_summary": (
        "structural_pocket_sensitivity_member_summary"
    ),
    "structural_pocket_sensitivity_group_summary": (
        "structural_pocket_sensitivity_group_summary"
    ),
}


def quote_identifier(identifier: str) -> str:
    """Validate and quote a simple DuckDB identifier."""
    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise AppError(f"Unsafe DuckDB identifier: {identifier!r}")
    return f'"{identifier}"'


def quote_literal(value: str | Path) -> str:
    """Quote one trusted local path as a DuckDB string literal."""
    return "'" + str(value).replace("'", "''") + "'"


@contextmanager
def open_read_only(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open and always close a read-only DuckDB connection."""
    source = path.expanduser().resolve()
    if not source.is_file():
        raise AppError(f"DuckDB does not exist: {source}")
    try:
        connection = duckdb.connect(str(source), read_only=True)
    except duckdb.Error as exc:
        raise AppError(f"Could not open DuckDB read-only: {source}: {exc}") from exc
    try:
        yield connection
    finally:
        connection.close()


def _safe_relation_name(path: Path, root: Path) -> str:
    """Return a deterministic relation name for an otherwise unknown Parquet."""
    relative = path.relative_to(root).with_suffix("")
    raw = "_".join(relative.parts[-3:])
    normalised = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    normalised = re.sub(r"_+", "_", normalised).strip("_").lower()
    if not normalised or not normalised[0].isalpha():
        normalised = f"result_{normalised}"
    return normalised


def discover_run_parquets(run_dir: Path) -> dict[str, Path]:
    """Discover current-run Parquets while excluding hidden and superseded data."""
    root = run_dir.expanduser().resolve()
    if not root.is_dir():
        raise AppError(f"Resource run directory does not exist: {root}")
    discovered: dict[str, Path] = {}
    for path in sorted(root.rglob("*.parquet")):
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") or part == "superseded" for part in relative_parts):
            continue
        relation = CANONICAL_PARQUET_RELATIONS.get(path.stem)
        if relation is None:
            relation = _safe_relation_name(path, root)
        if relation in discovered:
            relation = _safe_relation_name(path, root)
        suffix = 2
        base = relation
        while relation in discovered:
            relation = f"{base}_{suffix}"
            suffix += 1
        if IDENTIFIER_PATTERN.fullmatch(relation):
            discovered[relation] = path.resolve()
    if not discovered:
        raise AppError(f"Resource run directory contains no usable Parquet results: {root}")
    return discovered


def _register_parquet_views(
    connection: duckdb.DuckDBPyConnection,
    relations: Mapping[str, Path],
) -> None:
    """Register local Parquet files as read-only in-memory DuckDB views."""
    for relation, path in relations.items():
        connection.execute(
            f"CREATE VIEW {quote_identifier(relation)} AS "
            f"SELECT * FROM read_parquet({quote_literal(path)})"
        )
    connection.execute(
        "CREATE TABLE resource_relation_catalog ("
        "relation_name VARCHAR, app_section VARCHAR, row_granularity VARCHAR, "
        "source_parquet VARCHAR)"
    )
    records = [
        (
            relation,
            infer_capability(relation, []),
            "source_defined",
            str(path),
        )
        for relation, path in relations.items()
    ]
    connection.executemany(
        "INSERT INTO resource_relation_catalog VALUES (?, ?, ?, ?)",
        records,
    )


@contextmanager
def open_resource(config: AppConfig) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open DuckDB, one master Parquet or all current-run Parquets uniformly."""
    if config.resource_duckdb is not None:
        with open_read_only(config.resource_duckdb) as connection:
            yield connection
        return
    connection = duckdb.connect(":memory:")
    try:
        if config.resource_parquet is not None:
            _register_parquet_views(
                connection,
                {"candidate_master_results": config.resource_parquet.resolve()},
            )
        elif config.resource_run_dir is not None:
            _register_parquet_views(
                connection,
                discover_run_parquets(config.resource_run_dir),
            )
        else:
            raise AppError("No resource source was configured")
        yield connection
    except duckdb.Error as exc:
        raise AppError(f"Could not open resource source: {config.source_path}: {exc}") from exc
    finally:
        connection.close()


def list_relations(connection: duckdb.DuckDBPyConnection) -> list[str]:
    """List user tables and views in deterministic order."""
    rows = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY lower(table_name), table_name
        """
    ).fetchall()
    relations = [str(row[0]) for row in rows if IDENTIFIER_PATTERN.fullmatch(str(row[0]))]
    return relations


def relation_columns(connection: duckdb.DuckDBPyConnection, relation: str) -> list[str]:
    """Return columns for a validated relation."""
    quoted = quote_identifier(relation)
    rows = connection.execute(f"DESCRIBE SELECT * FROM {quoted}").fetchall()
    return [str(row[0]) for row in rows]


def relation_count(connection: duckdb.DuckDBPyConnection, relation: str) -> int:
    """Count rows in one validated relation."""
    quoted = quote_identifier(relation)
    return int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])


def preview_relation(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    limit: int,
) -> pd.DataFrame:
    """Return a bounded preview without collecting a whole relation."""
    if limit < 1 or limit > 100_000:
        raise AppError("preview limit must be between 1 and 100000")
    quoted = quote_identifier(relation)
    return connection.execute(f"SELECT * FROM {quoted} LIMIT ?", [limit]).fetchdf()


def preview_selected_columns(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    columns: Sequence[str],
    limit: int,
) -> pd.DataFrame:
    """Return a bounded preview containing only explicitly selected columns."""
    available = relation_columns(connection, relation)
    selected = list(dict.fromkeys(columns))
    if not selected:
        raise AppError("Select at least one result column")
    unknown = sorted(set(selected).difference(available))
    if unknown:
        raise AppError(f"Unknown columns for {relation}: {', '.join(unknown)}")
    if limit < 1 or limit > 100_000:
        raise AppError("preview limit must be between 1 and 100000")
    selected_sql = ", ".join(quote_identifier(column) for column in selected)
    return connection.execute(
        f"SELECT {selected_sql} FROM {quote_identifier(relation)} LIMIT ?",
        [limit],
    ).fetchdf()


def distinct_text_values(
    *,
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    column: str,
    maximum_values: int = 500,
) -> list[str]:
    """Return bounded distinct non-empty values for one filter control.

    Args:
        connection: Open read-only DuckDB connection.
        relation: Existing relation name.
        column: Existing text-compatible column.
        maximum_values: Maximum values collected into the app.

    Returns:
        Sorted values, or an empty list when the column is unavailable.

    Raises:
        AppError: If the limit is invalid.
    """
    if not 1 <= maximum_values <= 10_000:
        raise AppError("maximum distinct values must be between 1 and 10000")
    available = relation_columns(connection, relation)
    if column not in available:
        return []
    quoted_column = quote_identifier(column)
    query = (
        f"SELECT DISTINCT CAST({quoted_column} AS VARCHAR) AS value "
        f"FROM {quote_identifier(relation)} WHERE {quoted_column} IS NOT NULL "
        f"AND trim(CAST({quoted_column} AS VARCHAR)) <> '' "
        f"ORDER BY value LIMIT {int(maximum_values)}"
    )
    return [str(row[0]) for row in connection.execute(query).fetchall()]


def filter_expression_context(
    *,
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    selected_columns: Sequence[str],
    species: str = "All",
    organism_part: str = "All",
    metadata_status: str = "All",
    expression_positive: str = "All",
    search_text: str = "",
    maximum_rows: int = 1000,
) -> pd.DataFrame:
    """Query a bounded candidate-by-tissue expression relation.

    Args:
        connection: Open read-only DuckDB connection.
        relation: Candidate expression-context relation.
        selected_columns: Columns returned to the app.
        species: Exact species filter or ``All``.
        organism_part: Exact tissue/organism-part filter or ``All``.
        metadata_status: Exact metadata-availability state or ``All``.
        expression_positive: ``Positive``, ``Below threshold`` or ``All``.
        search_text: Case-insensitive partial identifier search.
        maximum_rows: Hard result limit.

    Returns:
        Filtered expression-context rows.

    Raises:
        AppError: If requested fields or limits are invalid.
    """
    if not 1 <= maximum_rows <= 10_000:
        raise AppError("maximum expression rows must be between 1 and 10000")
    available = relation_columns(connection, relation)
    if not selected_columns:
        raise AppError("At least one expression column must be selected")
    missing = sorted(set(selected_columns).difference(available))
    if missing:
        raise AppError("Unknown expression columns: " + ", ".join(missing))
    conditions: list[str] = []
    parameters: list[object] = []
    if species != "All" and "species_column" in available:
        conditions.append("CAST(species_column AS VARCHAR) = ?")
        parameters.append(species)
    if organism_part != "All" and "organism_part" in available:
        conditions.append("CAST(organism_part AS VARCHAR) = ?")
        parameters.append(organism_part)
    if metadata_status != "All" and "metadata_status" in available:
        conditions.append("CAST(metadata_status AS VARCHAR) = ?")
        parameters.append(metadata_status)
    if expression_positive not in {"All", "Positive", "Below threshold"}:
        raise AppError(f"Unknown expression support filter: {expression_positive}")
    if expression_positive != "All" and "expression_positive" in available:
        conditions.append("CAST(expression_positive AS BOOLEAN) = ?")
        parameters.append(expression_positive == "Positive")
    cleaned_search = search_text.strip().lower()
    search_columns = [
        column
        for column in (
            "gene_id",
            "gene_name",
            "member_accession",
            "member_identifier",
            "primary_group_id",
            "cluster_id",
        )
        if column in available
    ]
    if cleaned_search and search_columns:
        conditions.append(
            "("
            + " OR ".join(
                "contains(lower(COALESCE(CAST("
                f"{quote_identifier(column)} AS VARCHAR), '')), ?)"
                for column in search_columns
            )
            + ")"
        )
        parameters.extend([cleaned_search] * len(search_columns))
    selected_sql = ", ".join(
        quote_identifier(column) for column in selected_columns
    )
    where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""
    order_columns = [
        column
        for column in (
            "primary_group_id",
            "species_column",
            "member_accession",
            "organism_part",
            "experiment_accession",
            "sample_or_condition",
        )
        if column in available
    ]
    order_sql = (
        " ORDER BY "
        + ", ".join(quote_identifier(column) for column in order_columns)
        if order_columns
        else ""
    )
    query = (
        f"SELECT {selected_sql} FROM {quote_identifier(relation)}"
        f"{where_sql}{order_sql} LIMIT {int(maximum_rows)}"
    )
    return connection.execute(query, parameters).fetchdf()


def resource_overview(
    connection: duckdb.DuckDBPyConnection,
    relations: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Summarise relation names, columns, rows, and inferred capabilities."""
    selected = list_relations(connection) if relations is None else list(relations)
    records = []
    for relation in selected:
        columns = relation_columns(connection, relation)
        records.append(
            {
                "relation": relation,
                "row_count": relation_count(connection, relation),
                "column_count": len(columns),
                "capability": infer_capability(relation, columns),
            }
        )
    return pd.DataFrame.from_records(
        records,
        columns=("relation", "row_count", "column_count", "capability"),
    )


def infer_capability(relation: str, columns: Sequence[str]) -> str:
    """Classify a relation for navigation without changing scientific content."""
    text = " ".join([relation, *columns]).lower()
    for capability, terms in (
        (
            "final_recommendations",
            (
                "top_computational_review_shortlist",
                "top_50_computational_review_shortlist",
                "top_20_computational_review_shortlist",
                "gate_sensitivity",
                "grant_aligned_predicted_candidates",
                "final_evolutionary_candidate_prioritisation",
                "final_candidate_exclusion_audit",
            ),
        ),
        ("structural_alignment", ("structural_alignment", "tm_score", "centroid_distance")),
        ("pocket_conservation", ("pocket_conservation", "pocket_sequence_coordinate")),
        ("orthology", ("orthogroup", "hog")),
        ("ligandability", ("pocket", "fpocket", "p2rank")),
        ("expression", ("expression", "tpm", "fpkm")),
        ("provenance", ("manifest", "provenance", "checksum")),
        ("candidate", ("candidate", "cluster")),
    ):
        if any(term in text for term in terms):
            return capability
    return "resource"


def relations_for_section(
    connection: duckdb.DuckDBPyConnection,
    section: str,
) -> list[str]:
    """Return available relations relevant to one grant-facing section."""
    if section not in SECTION_SPECS:
        raise AppError(f"Unknown result section: {section}")
    available = list_relations(connection)
    preferred = list(SECTION_SPECS[section]["relations"])
    selected = [relation for relation in preferred if relation in available]
    if (
        section == "final_recommendations"
        and not selected
        and "candidate_master_results" in available
    ):
        selected.append("candidate_master_results")
    if section == "provenance":
        selected.extend(
            relation
            for relation in available
            if relation not in selected
            and infer_capability(relation, relation_columns(connection, relation))
            == "provenance"
        )
    return selected


def default_columns(section: str, available: Sequence[str]) -> list[str]:
    """Choose concise grant-facing defaults while keeping every column selectable."""
    preferences = {
        "final_recommendations": (
            "final_evolutionary_rank",
            "structurally_supported_rank",
            "boss_review_status",
            "grant_aligned_prediction_status",
            "evolutionary_group_key",
            "primary_group_type",
            "primary_group_id",
            "contributing_deepclust_cluster_count",
            "contributing_deepclust_cluster_ids",
            "lead_cluster_id",
            "final_score",
            "target_species_fraction",
            "domain_species_fraction",
            "expression_species_fraction",
            "selected_pocket_count",
            "structural_species_fraction",
            "inclusion_reasons",
            "exclusion_reasons",
            "missing_evidence",
        ),
        "candidates": (
            "final_rank",
            "recommendation_status",
            "cluster_id",
            "primary_group_id",
            "orthofinder_orthogroup_ids",
            "candidate_accessions",
            "final_score",
            "target_species_fraction",
            "domain_species_fraction",
            "expression_species_fraction",
            "structural_species_fraction",
            "missing_evidence",
        ),
        "orthology": (
            "cluster_id",
            "record_type",
            "group_id",
            "orthogroup_id",
            "species",
            "parsed_accession",
            "member_accession",
            "sequence_length",
            "orthofinder_orthogroup_ids",
            "orthofinder_hierarchical_group_ids",
            "orthofinder_group_member_count",
            "orthofinder_group_species_count",
        ),
        "domains": (
            "cluster_id",
            "member_accession",
            "species_column",
            "domain_support_status",
            "e3_families",
            "annotation_availability_status",
            "domain_species_fraction",
            "domain_annotation_coverage_fraction",
            "domain_supported_species",
            "domain_unavailable_species",
        ),
        "expression": (
            "cluster_id",
            "member_accession",
            "species_column",
            "mapping_status",
            "gene_id",
            "experiment_accession",
            "sample_or_condition",
            "atlas_group_label",
            "organism_part",
            "developmental_stage",
            "condition",
            "expression_context",
            "metadata_status",
            "expression_unit",
            "expression_value",
            "expression_positive",
            "expression_minimum",
            "expression_lower_quartile",
            "expression_median",
            "expression_upper_quartile",
            "expression_maximum",
            "context_count",
            "positive_context_fraction",
            "broad_expression_supported",
            "evidence_status",
            "expression_species_fraction",
            "expression_evidence_coverage_fraction",
            "expression_supported_species",
            "expression_unavailable_species",
        ),
        "ligandability": (
            "cluster_id",
            "candidate_accession",
            "species_column",
            "pocket_number",
            "druggability_score",
            "p2rank_score",
            "mapping_fraction",
            "structural_evidence_status",
            "ligandability_score",
            "minimum_druggability_score",
            "mean_pocket_plddt_fraction",
            "predictor_agreement_fraction",
            "selected_pocket_count",
        ),
        "pocket_conservation": (
            "cluster_id",
            "primary_group_id",
            "candidate_accession",
            "species_column",
            "conservation_status",
            "conserved_pocket_score",
            "fasta_position",
            "sequence_coordinate_status",
            "pocket_conservation_score",
            "mean_pairwise_region_overlap",
            "mean_chemical_group_conservation",
            "pocket_conservation_member_count",
        ),
        "structural_alignment": (
            "cluster_id",
            "primary_group_id",
            "alignment_tool",
            "position_alignment_status",
            "alignment_status",
            "mean_minimum_tm_score",
            "mean_pocket_overlap_fraction",
            "median_centroid_distance_angstrom",
            "three_dimensional_position_status",
            "three_dimensional_alignment_status",
            "mean_structural_residue_match_fraction",
            "mean_structural_chemical_group_conservation",
        ),
        "provenance": (
            "relation_name",
            "app_section",
            "row_granularity",
            "source_parquet",
            "resource_name",
            "package_version",
            "run_name",
            "configuration_digest",
        ),
    }
    selected = [column for column in preferences[section] if column in available]
    return selected or list(available[: min(12, len(available))])


def grant_overview(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Calculate group-level Milestone 1/2 counts from the best relation.

    Compatibility relations are deduplicated by evolutionary-group identifier
    before any card is calculated. This prevents DeepClust contributor rows
    from being reported as distinct biological candidate groups.
    """
    relations = list_relations(connection)
    relation = next(
        (
            name
            for name in (
                "final_evolutionary_candidate_prioritisation",
                "candidate_master_results",
                "final_candidate_prioritisation",
                "prestructure_ranking",
                "candidate_evidence",
            )
            if name in relations
        ),
        None,
    )
    if relation is None:
        return {
            "candidate_count": 0,
            "prestructure_pass_count": 0,
            "final_pass_count": 0,
            "structural_assessed_count": 0,
        }
    relation_column_list = relation_columns(connection, relation)
    columns = set(relation_column_list)
    source = quote_identifier(relation)
    if (
        relation != "final_evolutionary_candidate_prioritisation"
        and "primary_group_id" in columns
    ):
        partition = ["primary_group_id"]
        if "primary_group_type" in columns:
            partition.insert(0, "primary_group_type")
        order_columns = [
            column
            for column in (
                "final_evolutionary_rank",
                "final_rank",
                "computational_rank",
                "prestructure_evolutionary_group_rank",
                "cluster_id",
            )
            if column in columns
        ] or ["primary_group_id"]
        partition_sql = ", ".join(
            quote_identifier(column) for column in partition
        )
        order_sql = ", ".join(
            quote_identifier(column) for column in order_columns
        )
        source = (
            "(SELECT * EXCLUDE (_e3_group_row) FROM (SELECT *, "
            f"ROW_NUMBER() OVER (PARTITION BY {partition_sql} ORDER BY "
            f"{order_sql}) AS _e3_group_row FROM {source} WHERE "
            "COALESCE(CAST(primary_group_id AS VARCHAR), '') <> '') "
            "WHERE _e3_group_row = 1)"
        )

    def count_true(column: str) -> int:
        if column not in columns:
            return 0
        return int(
            connection.execute(
                f"SELECT COUNT(*) FROM {source} "
                f"WHERE COALESCE(CAST({quote_identifier(column)} AS BOOLEAN), false)"
            ).fetchone()[0]
        )

    structural_status = 0
    if "three_dimensional_alignment_status" in columns:
        structural_status = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {source} "
                "WHERE COALESCE(three_dimensional_alignment_status, 'NOT_ASSESSED') "
                "<> 'NOT_ASSESSED'"
            ).fetchone()[0]
        )
    return {
        "candidate_count": int(
            connection.execute(f"SELECT COUNT(*) FROM {source}").fetchone()[0]
        ),
        "prestructure_pass_count": count_true("grant_aligned_prestructure_pass")
        or count_true("grant_aligned_stringent_pass"),
        "final_pass_count": count_true("grant_aligned_final_pass"),
        "structural_assessed_count": structural_status,
    }


def search_accession(
    connection: duckdb.DuckDBPyConnection,
    accession: str,
    limit_per_relation: int = 100,
) -> pd.DataFrame:
    """Search recognised accession columns using bound SQL parameters."""
    query = accession.strip()
    if not query or len(query) > 200:
        raise AppError("accession query must contain between 1 and 200 characters")
    if limit_per_relation < 1 or limit_per_relation > 10_000:
        raise AppError("limit_per_relation must be between 1 and 10000")
    frames = []
    for relation in list_relations(connection):
        columns = relation_columns(connection, relation)
        case_insensitive_columns = {name.lower(): name for name in columns}
        recognised_columns = [
            case_insensitive_columns[name]
            for name in ACCESSION_COLUMNS
            if name in case_insensitive_columns
        ]
        if not recognised_columns:
            continue
        conditions = []
        parameters: list[object] = [relation]
        for accession_column in recognised_columns:
            quoted_column = quote_identifier(accession_column)
            conditions.append(
                f"(upper(CAST({quoted_column} AS VARCHAR)) = upper(?) OR "
                f"instr(';' || upper(CAST({quoted_column} AS VARCHAR)) || ';', "
                "';' || upper(?) || ';') > 0)"
            )
            parameters.extend((query, query))
        sql = (
            f"SELECT ? AS _relation, * FROM {quote_identifier(relation)} "
            f"WHERE {' OR '.join(conditions)} LIMIT ?"
        )
        parameters.append(limit_per_relation)
        frame = connection.execute(sql, parameters).fetchdf()
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["_relation"])
    return pd.concat(frames, ignore_index=True, sort=False)
