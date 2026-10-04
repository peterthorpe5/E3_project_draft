"""Auditable annotations and readable views for C-terminal conservation screens."""

from __future__ import annotations

import logging
from typing import Mapping, Sequence

import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError
from e3app.human_hogs import select_hog_ranking_relation
from e3app.terminal_sequences import GROUP_RECORD_TYPES, MAXIMUM_RESULT_ROWS

LOGGER = logging.getLogger(__name__)

MEMBER_FILTER_LABELS = {
    "all": "All sequence states",
    "match": "Exact matches",
    "non_match": "Assessed non-matches",
    "unavailable": "Unavailable sequences",
}
ROLE_FILTER_LABELS = {
    "all": "All members",
    "plant": "Selected plants",
    "arabidopsis": "Arabidopsis only",
    "human": "Human only",
    "other": "Other comparison members",
}
STATUS_LABELS = {
    "UNAVAILABLE": "Sequences unavailable",
    "NO_MATCH": "No assessed match",
    "SOME_MATCH": "Some assessed members match",
    "ALL_MATCH": "All assessed members match",
}


def _require_columns(*, frame: pd.DataFrame, required: set[str], label: str) -> None:
    """Validate a table contract before constructing a review view.

    Args:
        frame: Source evidence table.
        required: Columns necessary for the operation.
        label: Table name used in an actionable error.

    Raises:
        AppError: If required columns are missing.
    """
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise AppError(f"{label} is missing columns: " + ", ".join(missing))


def _text_tokens(*, values: Sequence[object]) -> tuple[str, ...]:
    """Collect unique semicolon-separated identifiers without inventing null values.

    Args:
        values: Nullable text values from a published annotation table.

    Returns:
        Sorted distinct non-empty tokens.
    """
    tokens: set[str] = set()
    for value in values:
        if pd.isna(value):
            continue
        tokens.update(token.strip() for token in str(value).split(";") if token.strip())
    return tuple(sorted(tokens))


def terminal_species_labels(*, species_taxonomy: pd.DataFrame) -> dict[str, str]:
    """Build species choices from reviewed accepted names and exact source labels.

    Args:
        species_taxonomy: Validated active taxonomy authority.

    Returns:
        Exact source labels mapped to accepted name, NCBI taxon ID and source label.

    Raises:
        AppError: If mappings are incomplete or source labels are duplicated.
    """
    _require_columns(
        frame=species_taxonomy,
        required={"source_species_name", "canonical_species_name", "taxon_id"},
        label="Reviewed taxonomy",
    )
    if species_taxonomy["source_species_name"].duplicated().any():
        raise AppError("Reviewed taxonomy contains duplicate source species labels")
    labels: dict[str, str] = {}
    for row in species_taxonomy.itertuples(index=False):
        if (pd.isna(row.taxon_id) or pd.isna(row.canonical_species_name)
                or pd.isna(row.source_species_name)):
            raise AppError("Reviewed taxonomy contains unavailable accepted names or taxon IDs")
        try:
            if isinstance(row.taxon_id, bool):
                raise ValueError("Boolean taxonomy ID")
            taxon_id = int(row.taxon_id)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AppError("Reviewed taxonomy contains invalid taxon IDs") from exc
        if (taxon_id <= 0 or not str(row.source_species_name).strip()
                or not str(row.canonical_species_name).strip()
                or float(row.taxon_id) != taxon_id):
            raise AppError("Reviewed taxonomy contains invalid species mappings")
        source = str(row.source_species_name)
        labels[source] = f"{row.canonical_species_name} · taxon {taxon_id} · source: {source}"
    return labels


def _collect_cluster_annotations(
    *,
    connection: object,
    relation: str,
    key_column: str,
    fields: Mapping[str, str],
    clusters: Sequence[str],
) -> dict[str, dict[str, object]]:
    """Read bounded, aggregated annotations for explicitly linked source clusters.

    Args:
        connection: Open read-only DuckDB connection.
        relation: Internally selected annotation relation.
        key_column: Published cluster identifier column.
        fields: Source fields mapped to explicit provenance-labelled output fields.
        clusters: Exact source cluster identifiers linked to returned groups.

    Returns:
        Nullable annotation values by exact cluster identifier. Unsupported
        optional relations return no annotations.

    Raises:
        AppError: If an available relation cannot be queried.
    """
    if not clusters or relation not in list_relations(connection=connection):
        return {}
    columns = set(relation_columns(connection=connection, relation=relation))
    if key_column not in columns:
        LOGGER.warning("Optional annotation relation %s has no %s", relation, key_column)
        return {}
    expressions: list[str] = []
    for source, output in fields.items():
        text = (
            f"nullif(trim(CAST({quote_identifier(source)} AS VARCHAR)), '')"
            if source in columns else "CAST(NULL AS VARCHAR)"
        )
        expressions.append(
            f"string_agg(DISTINCT {text}, ';' ORDER BY {text}) AS {quote_identifier(output)}"
        )
    key = f"trim(CAST({quote_identifier(key_column)} AS VARCHAR))"
    sql = (
        f"SELECT {key} AS cluster_key, " + ", ".join(expressions)
        + f" FROM {quote_identifier(relation)} WHERE {key} IN (SELECT unnest(?)) "
        + f"GROUP BY {key}"
    )
    try:
        table = connection.execute(sql, [list(clusters)]).fetchdf()
    except Exception as exc:
        LOGGER.exception("Could not query C-terminal annotations from %s", relation)
        raise AppError(f"Could not query optional C-terminal annotations from {relation}") from exc
    return {
        str(row["cluster_key"]): row
        for row in table.to_dict(orient="records")
    }


def enrich_terminal_group_summary(
    *, connection: object, summary: pd.DataFrame, group_type: str,
) -> pd.DataFrame:
    """Attach existing HOG ranks and explicitly linked E3 seed/domain context.

    Args:
        connection: Open read-only DuckDB connection.
        summary: Bounded terminal-screen summary, including source cluster links.
        group_type: Exact grouping selector used for the terminal screen.

    Returns:
        Same rows and order with nullable rank, seed description, seed category,
        domain support and E3-family fields. Linked-cluster annotations describe
        the source E3 neighbourhood; they are not annotations of every HOG member.
        Screen counts in DataFrame attributes are retained.

    Raises:
        AppError: If group inputs or available optional annotations are invalid.
    """
    _require_columns(frame=summary, required={"group_id", "source_cluster_ids"}, label="Summary")
    if group_type not in GROUP_RECORD_TYPES:
        raise AppError("Unsupported OrthoFinder grouping level")
    if len(summary) > MAXIMUM_RESULT_ROWS or summary["group_id"].duplicated().any():
        raise AppError("Terminal summary must contain bounded, unique group identifiers")
    result = summary.copy()
    result["hog_prestructure_rank"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result["hog_poststructure_rank"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result["ranking_source"] = pd.NA
    result["ranking_source_row_count"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    rank_relation = select_hog_ranking_relation(connection=connection)
    if rank_relation is not None and not result.empty:
        columns = set(relation_columns(connection=connection, relation=rank_relation))
        expressions: list[str] = []
        for output, candidates in (
            ("hog_prestructure_rank", ("prestructure_evolutionary_group_rank",
                                       "evolutionary_group_rank", "computational_rank")),
            ("hog_poststructure_rank", ("final_evolutionary_rank", "final_rank")),
        ):
            source = next((name for name in candidates if name in columns), None)
            value = f"TRY_CAST({quote_identifier(source)} AS BIGINT)" if source else "NULL"
            expressions.append(f"min({value}) AS {output}")
        parameters: list[object] = [result["group_id"].astype(str).tolist()]
        group_filter = ""
        if "primary_group_type" in columns:
            group_filter = " AND upper(trim(CAST(primary_group_type AS VARCHAR))) = ?"
            parameters.append(GROUP_RECORD_TYPES[group_type])
        sql = (
            "SELECT trim(CAST(primary_group_id AS VARCHAR)) AS group_id, "
            + ", ".join(expressions) + ", count(*) AS ranking_source_row_count "
            + f"FROM {quote_identifier(rank_relation)} "
            + "WHERE trim(CAST(primary_group_id AS VARCHAR)) IN (SELECT unnest(?))"
            + group_filter + " GROUP BY trim(CAST(primary_group_id AS VARCHAR))"
        )
        try:
            ranks = connection.execute(sql, parameters).fetchdf().set_index(keys="group_id")
        except Exception as exc:
            LOGGER.exception("Could not query terminal-screen group ranks")
            raise AppError("Could not query C-terminal group ranking context") from exc
        for name in ("hog_prestructure_rank", "hog_poststructure_rank", "ranking_source_row_count"):
            result[name] = result["group_id"].map(arg=ranks[name]).astype("Int64")
        result.loc[result["group_id"].isin(values=ranks.index), "ranking_source"] = rank_relation
    clusters = _text_tokens(values=result["source_cluster_ids"].tolist())
    for relation, key_column, fields in (
        ("candidate_evidence", "representative_id", {
            "seed_protein_names": "linked_seed_protein_descriptions",
            "seed_categories": "linked_seed_categories",
            "matched_seed_ids_calculated": "linked_seed_identifiers",
        }),
        ("domain_summary", "cluster_id", {
            "domain_support_status": "linked_cluster_domain_support_status",
            "e3_families": "linked_cluster_e3_families",
            "e3_domain_accessions": "linked_cluster_e3_domain_accessions",
        }),
    ):
        annotations = _collect_cluster_annotations(
            connection=connection, relation=relation, key_column=key_column,
            fields=fields, clusters=clusters,
        )
        for output in fields.values():
            values: list[object] = []
            for links in result["source_cluster_ids"]:
                tokens = _text_tokens(values=[
                    annotations.get(cluster, {}).get(output, pd.NA)
                    for cluster in _text_tokens(values=[links])
                ])
                values.append(";".join(tokens) if tokens else pd.NA)
            result[output] = pd.Series(values, index=result.index, dtype="string")
    LOGGER.info("Enriched %d C-terminal groups using rank source %s", len(result), rank_relation)
    return result


def annotate_terminal_members(
    *,
    connection: object,
    members: pd.DataFrame,
    species_taxonomy: pd.DataFrame,
    group_type: str,
) -> pd.DataFrame:
    """Attach reviewed taxonomy and exact member-specific published domain evidence.

    Args:
        connection: Open read-only DuckDB connection.
        members: Bounded member evidence for one selected group.
        species_taxonomy: Active reviewed source-label mapping.
        group_type: Group selector used to obtain the members.

    Returns:
        Same members with accepted name, NCBI taxon ID and nullable domain fields.
        Domain joins use exact accession, source species and source cluster links,
        plus group ID/type when published. No external annotation is guessed.

    Raises:
        AppError: If contracts, group scope or available annotations are invalid.
    """
    _require_columns(
        frame=members, required={"group_id", "species", "parsed_accession", "source_cluster_ids"},
        label="Member evidence",
    )
    terminal_species_labels(species_taxonomy=species_taxonomy)
    if group_type not in GROUP_RECORD_TYPES or members["group_id"].nunique() > 1:
        raise AppError("Member annotations require one supported orthology group")
    if len(members) > MAXIMUM_RESULT_ROWS:
        raise AppError("Member annotations exceed the bounded result limit")
    result = members.copy()
    mappings = species_taxonomy.set_index(keys="source_species_name")
    result["accepted_species_name"] = result["species"].map(arg=mappings["canonical_species_name"])
    result["ncbi_taxon_id"] = result["species"].map(arg=mappings["taxon_id"]).astype("Int64")
    result["taxonomy_mapping_status"] = "UNRESOLVED"
    result.loc[result["ncbi_taxon_id"].notna(), "taxonomy_mapping_status"] = "REVIEWED"
    domain_fields = ("domain_support_status", "e3_families", "e3_domain_accessions")
    for name in (*domain_fields, "domain_annotation_source"):
        result[name] = pd.NA
    if result.empty or "domain_summary" not in list_relations(connection=connection):
        return result
    columns = set(relation_columns(connection=connection, relation="domain_summary"))
    if not {"cluster_id", "species_column", "member_accession"}.issubset(columns):
        LOGGER.warning("Optional domain_summary lacks exact member join identifiers")
        return result
    clusters = _text_tokens(values=result["source_cluster_ids"].tolist())
    if not clusters:
        return result
    expressions: list[str] = []
    for name in domain_fields:
        value = (
            f"nullif(trim(CAST({quote_identifier(name)} AS VARCHAR)), '')"
            if name in columns else "CAST(NULL AS VARCHAR)"
        )
        expressions.append(f"string_agg(DISTINCT {value}, ';' ORDER BY {value}) AS {name}")
    parameters: list[object] = [
        list(clusters), result["species"].astype(str).unique().tolist(),
        result["parsed_accession"].dropna().astype(str).unique().tolist(),
    ]
    scope_filter = ""
    for field, value in (
        ("primary_group_id", str(result["group_id"].iloc[0])),
        ("primary_group_type", GROUP_RECORD_TYPES[group_type]),
    ):
        if field in columns:
            scope_filter += f" AND trim(CAST({quote_identifier(field)} AS VARCHAR)) = ?"
            parameters.append(value)
    sql = (
        "SELECT trim(CAST(cluster_id AS VARCHAR)) AS cluster_id, "
        "trim(CAST(species_column AS VARCHAR)) AS species, "
        "trim(CAST(member_accession AS VARCHAR)) AS parsed_accession, "
        + ", ".join(expressions) + " FROM domain_summary "
        "WHERE trim(CAST(cluster_id AS VARCHAR)) IN (SELECT unnest(?)) "
        "AND trim(CAST(species_column AS VARCHAR)) IN (SELECT unnest(?)) "
        "AND trim(CAST(member_accession AS VARCHAR)) IN (SELECT unnest(?)) "
        + scope_filter + " GROUP BY ALL"
    )
    try:
        domains = connection.execute(sql, parameters).fetchdf()
    except Exception as exc:
        LOGGER.exception("Could not query exact C-terminal member domains")
        raise AppError("Could not query C-terminal member domain annotations") from exc
    lookup = {
        (row["cluster_id"], row["species"], row["parsed_accession"]): row
        for row in domains.to_dict(orient="records")
    }
    for index, row in result.iterrows():
        annotations = [
            lookup[key]
            for cluster in _text_tokens(values=[row["source_cluster_ids"]])
            if (key := (cluster, row["species"], row["parsed_accession"])) in lookup
        ]
        for name in domain_fields:
            tokens = _text_tokens(values=[record[name] for record in annotations])
            if tokens:
                result.at[index, name] = ";".join(tokens)
        if annotations:
            result.at[index, "domain_annotation_source"] = "domain_summary"
    LOGGER.info("Annotated %d C-terminal members without changing sequence evidence", len(result))
    return result


def _fraction_label(*, numerator: object, denominator: object) -> str:
    """Format an evidence fraction without treating an unavailable denominator as zero.

    Args:
        numerator: Assessed matching or available member count.
        denominator: Exact evidence denominator.

    Returns:
        Readable count fraction and percentage, or an explicit unavailable label.
    """
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return "Unavailable"
    return f"{int(numerator):,}/{int(denominator):,} ({100 * numerator / denominator:.1f}%)"


def terminal_summary_display(*, summary: pd.DataFrame) -> pd.DataFrame:
    """Construct a compact prioritisation table with exact denominator labels.

    Args:
        summary: Raw or enriched group summary from the terminal screen.

    Returns:
        Readable display fields; raw downloadable evidence is left untouched.

    Raises:
        AppError: If the conservation count contract is incomplete.
    """
    _require_columns(
        frame=summary,
        required={"group_id", "matching_plant_member_count", "assessed_plant_member_count",
                  "plant_member_count", "matching_plant_species_count",
                  "assessed_plant_species_count",
                  "human_member_count", "human_comparison_status"},
        label="Terminal summary",
    )
    rows: list[dict[str, object]] = []
    for record in summary.to_dict(orient="records"):
        rows.append({
            "Group": record["group_id"],
            "Plant proteins matching / assessed": _fraction_label(
                numerator=record["matching_plant_member_count"],
                denominator=record["assessed_plant_member_count"],
            ),
            "Plant species matching / assessed": _fraction_label(
                numerator=record["matching_plant_species_count"],
                denominator=record["assessed_plant_species_count"],
            ),
            "Plant sequences available / published": _fraction_label(
                numerator=record["assessed_plant_member_count"],
                denominator=record["plant_member_count"],
            ),
            "Arabidopsis matching IDs": record.get("arabidopsis_matching_identifiers", pd.NA),
            "Human IDs": record.get("human_identifiers", pd.NA),
            "Human comparison": (
                STATUS_LABELS.get(record["human_comparison_status"], "Unavailable")
                if record["human_member_count"] else "No published member"
            ),
            "Group rank after structure": record.get("hog_poststructure_rank", pd.NA),
            "Linked E3 families": record.get("linked_cluster_e3_families", pd.NA),
        })
    return pd.DataFrame(data=rows)


def filter_terminal_members(
    *, members: pd.DataFrame, match_filter: str = "all", role_filter: str = "all",
    species: Sequence[str] = (),
) -> pd.DataFrame:
    """Filter a member preview without altering the conservation calculation.

    Args:
        members: Selected-group evidence with nullable sequence match states.
        match_filter: All, exact matches, assessed non-matches or unavailable.
        role_filter: All, plants, Arabidopsis, human or other comparison members.
        species: Optional exact source labels; no selection means all species.

    Returns:
        Matching evidence rows in their existing order, preserving nullable states.

    Raises:
        AppError: If a filter or required evidence field is unsupported.
    """
    _require_columns(
        frame=members,
        required={"species", "taxonomic_role", "terminal_match", "sequence_available",
                  "is_arabidopsis", "is_human"},
        label="Member preview",
    )
    if match_filter not in MEMBER_FILTER_LABELS or role_filter not in ROLE_FILTER_LABELS:
        raise AppError("Unsupported C-terminal member filter")
    mask = pd.Series(True, index=members.index)
    if match_filter == "match":
        mask &= members["terminal_match"].eq(other=True).fillna(False)
    elif match_filter == "non_match":
        mask &= members["sequence_available"].eq(other=True).fillna(False)
        mask &= members["terminal_match"].eq(other=False).fillna(False)
    elif match_filter == "unavailable":
        mask &= members["sequence_available"].eq(other=False).fillna(False)
    role_columns = {"arabidopsis": "is_arabidopsis", "human": "is_human"}
    if role_filter in role_columns:
        mask &= members[role_columns[role_filter]].eq(other=True).fillna(False)
    elif role_filter in {"plant", "other"}:
        role = "TARGET_PLANT" if role_filter == "plant" else "OTHER_COMPARISON"
        mask &= members["taxonomic_role"].eq(other=role)
    if species:
        unknown = set(species).difference(members["species"].astype(str))
        if unknown:
            raise AppError("Member filter contains species outside the selected group")
        mask &= members["species"].isin(values=list(species))
    return members.loc[mask].copy().reset_index(drop=True)


def terminal_member_display(*, members: pd.DataFrame) -> pd.DataFrame:
    """Prepare readable member fields with explicit missing sequence states.

    Args:
        members: Annotated member evidence or a filtered subset.

    Returns:
        Compact member view with accepted names, original IDs and terminal context.
    """
    _require_columns(
        frame=members,
        required={"sequence_available", "terminal_match", "species", "raw_identifier"},
        label="Member display",
    )
    result = members.copy()
    result["Match state"] = "Sequence unavailable"
    assessed = result["sequence_available"].eq(other=True)
    result.loc[assessed & result["terminal_match"].eq(other=False).fillna(False), "Match state"] = (
        "Assessed non-match"
    )
    result.loc[assessed & result["terminal_match"].eq(other=True).fillna(False), "Match state"] = (
        "Exact match"
    )
    fields = {
        "accepted_species_name": "Accepted species", "species": "Source species",
        "ncbi_taxon_id": "NCBI taxon ID", "parsed_accession": "Accession",
        "raw_identifier": "Source protein ID", "protein_description": "Protein description",
        "taxonomic_role": "Comparison role", "Match state": "Match state",
        "c_terminal_context": "C-terminal context", "observed_sequence_length": "Length (aa)",
        "domain_support_status": "Member domain evidence", "e3_families": "Member E3 families",
    }
    columns = [name for name in fields if name in result.columns]
    return result.loc[:, columns].rename(columns=fields)


def terminal_species_summary(
    *, members: pd.DataFrame, plant_species: Sequence[str], species_taxonomy: pd.DataFrame,
) -> pd.DataFrame:
    """Audit assessed, missing and non-represented species in one selected group.

    Args:
        members: Complete selected-group evidence, before preview filtering.
        plant_species: Exact source labels in the active conservation denominator.
        species_taxonomy: Active reviewed source-label mappings.

    Returns:
        One row per selected plant, reviewed human label or represented comparison
        species. An unrepresented taxon means no published member in this relation;
        it is not a claim of biological absence. Fractions without evidence are null.

    Raises:
        AppError: If member evidence or reviewed taxonomy is incomplete.
    """
    _require_columns(
        frame=members,
        required={"group_id", "species", "sequence_available", "terminal_match"},
        label="Species evidence",
    )
    terminal_species_labels(species_taxonomy=species_taxonomy)
    if members["group_id"].nunique() != 1:
        raise AppError("Species audit requires complete evidence for one selected group")
    mappings = species_taxonomy.set_index(keys="source_species_name")
    human = set(mappings.index[mappings["taxon_id"].astype(int) == 9606])
    species_values = set(plant_species) | human | set(members["species"].astype(str))
    rows: list[dict[str, object]] = []
    for species in sorted(species_values):
        selected = members.loc[members["species"].eq(other=species)]
        published = len(selected)
        assessed = int(selected["sequence_available"].eq(other=True).sum())
        matched = int(selected["terminal_match"].eq(other=True).fillna(False).sum())
        state = "NOT_REPRESENTED" if published == 0 else "UNAVAILABLE"
        if assessed:
            state = "ALL_MATCH" if matched == assessed else "SOME_MATCH" if matched else "NO_MATCH"
        role = "HUMAN_COMPARISON" if species in human else "OTHER_COMPARISON"
        if species in plant_species and species not in human:
            role = "TARGET_PLANT"
        rows.append({
            "group_id": str(members["group_id"].iloc[0]),
            "species": species,
            "accepted_species_name": mappings["canonical_species_name"].get(species, pd.NA),
            "ncbi_taxon_id": mappings["taxon_id"].get(species, pd.NA),
            "taxonomic_role": role,
            "published_member_count": published,
            "assessed_member_count": assessed,
            "matching_member_count": matched,
            "non_matching_member_count": assessed - matched,
            "unavailable_sequence_count": published - assessed,
            "member_match_fraction": matched / assessed if assessed else pd.NA,
            "sequence_coverage_fraction": assessed / published if published else pd.NA,
            "match_status": state,
        })
    result = pd.DataFrame(data=rows)
    result["ncbi_taxon_id"] = result["ncbi_taxon_id"].astype("Int64")
    return result


def terminal_screen_provenance(
    *, summary: pd.DataFrame, settings: Mapping[str, object],
) -> pd.DataFrame:
    """Serialise active settings and unlimited screen counts for an auditable export.

    Args:
        summary: Screen summary retaining its ``screen_audit`` attributes.
        settings: Active sequence, grouping, taxonomy, species and threshold settings.

    Returns:
        Two-column settings and count table suitable for TSV and Excel export.

    Raises:
        AppError: If source screen counts were lost before export.
    """
    audit = summary.attrs.get("screen_audit")
    if not isinstance(audit, dict) or "qualifying_group_count" not in audit:
        raise AppError("C-terminal screen audit counts are unavailable")
    rows: list[dict[str, str]] = []
    for field, value in {**settings, **audit}.items():
        text = ";".join(map(str, value)) if isinstance(value, (tuple, list)) else str(value)
        rows.append({"setting": field, "value": text})
    return pd.DataFrame(data=rows)
