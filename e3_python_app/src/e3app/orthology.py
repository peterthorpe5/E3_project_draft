"""Bounded OrthoFinder and seed-group queries independent of Streamlit."""

from __future__ import annotations

from importlib.resources import files
from typing import Literal, Sequence

import pandas as pd

from e3app.data import list_relations, quote_identifier, relation_columns
from e3app.errors import AppError

GroupType = Literal["orthogroup", "hierarchical_orthogroup"]
MatchMode = Literal["any", "all"]

ORTHOLOGY_RELATIONS: dict[GroupType, str] = {
    "orthogroup": "orthogroup_membership",
    "hierarchical_orthogroup": "hierarchical_membership",
}
ORTHOLOGY_RECORD_TYPES: dict[GroupType, str] = {
    "orthogroup": "ORTHOGROUP",
    "hierarchical_orthogroup": "HIERARCHICAL_ORTHOGROUP",
}
MEMBERSHIP_COLUMNS = {"group_id", "species", "raw_identifier"}
SEED_MEMBER_COLUMNS = {
    "cluster_id",
    "record_type",
    "group_id",
    "species",
    "internal_id",
    "raw_identifier",
    "parsed_accession",
    "parsed_entry",
    "review_status",
    "mapping_status",
    "is_input_candidate",
    "candidate_accessions_for_cluster",
    "sequence_length",
    "protein_sequence",
}


def select_orthology_relation(
    *, relation_names: Sequence[str], group_type: GroupType
) -> str | None:
    """Return the membership relation for a requested OrthoFinder group type.

    Args:
        relation_names: Available DuckDB relation names.
        group_type: ``orthogroup`` or ``hierarchical_orthogroup``.

    Returns:
        Relation name when available, otherwise ``None``.
    """
    if group_type not in ORTHOLOGY_RELATIONS:
        raise AppError(f"Unsupported OrthoFinder group type: {group_type}")
    relation = ORTHOLOGY_RELATIONS[group_type]
    return relation if relation in set(relation_names) else None


def _require_columns(
    *, connection: object, relation: str, required: set[str]
) -> None:
    """Require a relation to contain a documented column contract."""
    available = set(relation_columns(connection, relation))
    missing = sorted(required.difference(available))
    if missing:
        raise AppError(
            f"{relation} is missing required columns: {', '.join(missing)}"
        )


def collect_orthology_species(
    *, connection: object, relation: str
) -> list[str]:
    """Return exact non-empty species labels represented in a membership table."""
    _require_columns(
        connection=connection,
        relation=relation,
        required=MEMBERSHIP_COLUMNS,
    )
    query = (
        f"SELECT DISTINCT trim(species) AS species FROM {quote_identifier(relation)} "
        "WHERE species IS NOT NULL AND trim(species) != '' "
        "ORDER BY lower(species), species"
    )
    return [str(row[0]) for row in connection.execute(query).fetchall()]


def collect_orthology_metrics(
    *, connection: object, relation: str
) -> dict[str, int | str]:
    """Calculate release-level membership and OrthoFinder-group metrics.

    Metrics are computed in DuckDB and therefore do not collect the member-level
    relation into application memory.
    """
    _require_columns(
        connection=connection,
        relation=relation,
        required=MEMBERSHIP_COLUMNS,
    )
    available = set(list_relations(connection))
    seeded_sql = "FALSE"
    if "candidate_group_member_sequences" in available:
        _require_columns(
            connection=connection,
            relation="candidate_group_member_sequences",
            required=SEED_MEMBER_COLUMNS,
        )
        seeded_sql = (
            "EXISTS (SELECT 1 FROM candidate_group_member_sequences seeds "
            "WHERE seeds.group_id = grouped.group_id)"
        )
    query = f"""
        WITH source AS (
            SELECT group_id, species
            FROM {quote_identifier(relation)}
            WHERE group_id IS NOT NULL AND trim(group_id) != ''
        ),
        totals AS (
            SELECT COUNT(*) AS input_sequences,
                   COUNT(DISTINCT species) AS input_species
            FROM source
        ),
        grouped AS (
            SELECT group_id,
                   COUNT(*) AS member_count,
                   COUNT(DISTINCT species) AS species_count
            FROM source
            GROUP BY group_id
        )
        SELECT totals.input_sequences,
               totals.input_species,
               COUNT(*) AS group_count,
               SUM(CASE WHEN {seeded_sql} THEN 1 ELSE 0 END) AS seeded_group_count,
               SUM(CASE WHEN grouped.species_count = totals.input_species
                        THEN 1 ELSE 0 END) AS all_species_group_count,
               COALESCE(MAX(grouped.member_count), 0) AS largest_group_size,
               COALESCE(arg_max(grouped.group_id, grouped.member_count), '')
                   AS largest_group_id
        FROM grouped CROSS JOIN totals
        GROUP BY totals.input_sequences, totals.input_species
    """
    row = connection.execute(query).fetchone()
    if row is None:
        return {
            "input_sequences": 0,
            "input_species": 0,
            "group_count": 0,
            "seeded_group_count": 0,
            "all_species_group_count": 0,
            "largest_group_size": 0,
            "largest_group_id": "",
        }
    names = (
        "input_sequences",
        "input_species",
        "group_count",
        "seeded_group_count",
        "all_species_group_count",
        "largest_group_size",
        "largest_group_id",
    )
    result = dict(zip(names, row, strict=True))
    for name in names[:-1]:
        result[name] = int(result[name] or 0)
    result["largest_group_id"] = str(result["largest_group_id"] or "")
    return result


def _normalise_values(*, values: Sequence[str]) -> list[str]:
    """Return unique, non-empty strings while preserving selection order."""
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def collect_orthology_group_summary(
    *,
    connection: object,
    relation: str,
    required_species: Sequence[str] = (),
    taxonomy_species: Sequence[str] = (),
    breadth: str = "all",
    seeded_only: bool = False,
    maximum_rows: int = 5000,
) -> pd.DataFrame:
    """Collect a bounded, filterable one-row-per-OrthoFinder-group summary.

    Args:
        connection: Open DuckDB connection.
        relation: Membership relation selected for the group type.
        required_species: Exact species labels which must all occur in a group.
        taxonomy_species: Curated species labels; a group must contain at least one.
        breadth: ``all``, ``one_species``, ``multiple_species`` or ``all_species``.
        seeded_only: Retain only groups linked to inherited E3 seed evidence.
        maximum_rows: Defensive maximum number of summary rows.

    Returns:
        A bounded summary ordered by group size and identifier.
    """
    if breadth not in {"all", "one_species", "multiple_species", "all_species"}:
        raise AppError(f"Unsupported species-breadth filter: {breadth}")
    if not 1 <= maximum_rows <= 100_000:
        raise AppError("maximum orthology rows must be between 1 and 100000")
    _require_columns(
        connection=connection,
        relation=relation,
        required=MEMBERSHIP_COLUMNS,
    )
    required = _normalise_values(values=required_species)
    taxonomy = _normalise_values(values=taxonomy_species)
    parameters: list[object] = []
    filters: list[str] = []
    if required:
        placeholders = ", ".join("?" for _ in required)
        filters.append(
            f"matched_required_species = {len(required)}"
        )
        parameters.extend(required)
        required_expression = (
            f"COUNT(DISTINCT CASE WHEN species IN ({placeholders}) "
            "THEN species END)"
        )
    else:
        required_expression = "0"
    if taxonomy:
        placeholders = ", ".join("?" for _ in taxonomy)
        filters.append("matched_taxonomy_species > 0")
        parameters.extend(taxonomy)
        taxonomy_expression = (
            f"COUNT(DISTINCT CASE WHEN species IN ({placeholders}) "
            "THEN species END)"
        )
    else:
        taxonomy_expression = "0"
    if breadth == "one_species":
        filters.append("species_count = 1")
    elif breadth == "multiple_species":
        filters.append("species_count > 1 AND species_count < input_species")
    elif breadth == "all_species":
        filters.append("species_count = input_species")
    available = set(list_relations(connection))
    has_seeds = "candidate_group_member_sequences" in available
    seeded_expression = (
        "EXISTS (SELECT 1 FROM candidate_group_member_sequences seeds "
        "WHERE seeds.group_id = grouped.group_id)"
        if has_seeds
        else "FALSE"
    )
    if seeded_only:
        if not has_seeds:
            return pd.DataFrame(
                columns=(
                    "group_id",
                    "member_count",
                    "species_count",
                    "species_breadth",
                    "contains_e3_seed_evidence",
                    "species_present",
                )
            )
        filters.append("contains_e3_seed_evidence")
    where_sql = " WHERE " + " AND ".join(filters) if filters else ""
    query = f"""
        WITH source AS (
            SELECT group_id, trim(species) AS species
            FROM {quote_identifier(relation)}
            WHERE group_id IS NOT NULL AND trim(group_id) != ''
        ),
        totals AS (
            SELECT COUNT(DISTINCT species) AS input_species FROM source
        ),
        grouped AS (
            SELECT group_id,
                   COUNT(*) AS member_count,
                   COUNT(DISTINCT species) AS species_count,
                   string_agg(DISTINCT species, ';' ORDER BY species)
                       AS species_present,
                   {required_expression} AS matched_required_species,
                   {taxonomy_expression} AS matched_taxonomy_species
            FROM source
            GROUP BY group_id
        ),
        labelled AS (
            SELECT grouped.*,
                   totals.input_species,
                   CASE
                     WHEN species_count = 1 THEN 'One species only'
                     WHEN species_count = input_species THEN 'All input species'
                     ELSE 'Multiple species (not all)'
                   END AS species_breadth,
                   {seeded_expression} AS contains_e3_seed_evidence
            FROM grouped CROSS JOIN totals
        )
        SELECT group_id, member_count, species_count, input_species,
               species_breadth, contains_e3_seed_evidence, species_present
        FROM labelled{where_sql}
        ORDER BY member_count DESC, lower(group_id), group_id
        LIMIT {int(maximum_rows)}
    """
    return connection.execute(query, parameters).fetchdf()


def collect_orthology_size_distribution(
    *, connection: object, relation: str
) -> pd.DataFrame:
    """Return full group-size frequencies without returning individual groups."""
    _require_columns(
        connection=connection,
        relation=relation,
        required=MEMBERSHIP_COLUMNS,
    )
    query = f"""
        WITH source AS (
            SELECT group_id, species
            FROM {quote_identifier(relation)}
            WHERE group_id IS NOT NULL AND trim(group_id) != ''
        ),
        totals AS (
            SELECT COUNT(DISTINCT species) AS input_species FROM source
        ),
        grouped AS (
            SELECT group_id, COUNT(*) AS member_count,
                   COUNT(DISTINCT species) AS species_count
            FROM source GROUP BY group_id
        ),
        labelled AS (
            SELECT member_count,
                   CASE
                     WHEN species_count = 1 THEN 'One species only'
                     WHEN species_count = input_species THEN 'All input species'
                     ELSE 'Multiple species (not all)'
                   END AS species_breadth
            FROM grouped CROSS JOIN totals
        )
        SELECT member_count, species_breadth, COUNT(*) AS group_count
        FROM labelled
        GROUP BY member_count, species_breadth
        ORDER BY member_count, species_breadth
    """
    return connection.execute(query).fetchdf()


def collect_seed_identifiers(*, connection: object) -> list[str]:
    """Return inherited E3 seed identifiers encoded in seeded member groups."""
    if "candidate_group_member_sequences" not in set(list_relations(connection)):
        return []
    _require_columns(
        connection=connection,
        relation="candidate_group_member_sequences",
        required=SEED_MEMBER_COLUMNS,
    )
    query = """
        SELECT DISTINCT trim(seed_id) AS seed_id
        FROM candidate_group_member_sequences,
             UNNEST(string_split(
                 coalesce(candidate_accessions_for_cluster, ''), ';'
             )) AS seeds(seed_id)
        WHERE trim(seed_id) != ''
        ORDER BY lower(seed_id), seed_id
    """
    return [str(row[0]) for row in connection.execute(query).fetchall()]


def collect_seed_group_members(
    *,
    connection: object,
    seed_identifiers: Sequence[str],
    group_type: GroupType,
    match_mode: MatchMode = "any",
    species: Sequence[str] = (),
    maximum_rows: int = 10_000,
) -> pd.DataFrame:
    """Return full sequence-bearing members of groups matching selected seeds."""
    seeds = _normalise_values(values=seed_identifiers)
    selected_species = _normalise_values(values=species)
    if not seeds:
        raise AppError("Select at least one E3 seed identifier")
    if match_mode not in {"any", "all"}:
        raise AppError("Seed matching must be 'any' or 'all'")
    if group_type not in ORTHOLOGY_RECORD_TYPES:
        raise AppError(f"Unsupported OrthoFinder group type: {group_type}")
    if not 1 <= maximum_rows <= 100_000:
        raise AppError("maximum seed-group rows must be between 1 and 100000")
    if "candidate_group_member_sequences" not in set(list_relations(connection)):
        raise AppError("This release has no sequence-bearing seeded-group relation")
    _require_columns(
        connection=connection,
        relation="candidate_group_member_sequences",
        required=SEED_MEMBER_COLUMNS,
    )
    seed_placeholders = ", ".join("?" for _ in seeds)
    parameters: list[object] = [ORTHOLOGY_RECORD_TYPES[group_type], *seeds]
    having = (
        f"COUNT(DISTINCT seed_id) = {len(seeds)}"
        if match_mode == "all"
        else "COUNT(DISTINCT seed_id) >= 1"
    )
    species_filter = ""
    if selected_species:
        placeholders = ", ".join("?" for _ in selected_species)
        species_filter = f" AND members.species IN ({placeholders})"
        parameters.extend(selected_species)
    query = f"""
        WITH exploded AS (
            SELECT DISTINCT record_type, group_id, trim(seed_id) AS seed_id
            FROM candidate_group_member_sequences,
                 UNNEST(string_split(
                     coalesce(candidate_accessions_for_cluster, ''), ';'
                 )) AS seeds(seed_id)
            WHERE record_type = ? AND trim(seed_id) IN ({seed_placeholders})
        ),
        matched_groups AS (
            SELECT record_type, group_id,
                   string_agg(DISTINCT seed_id, ';' ORDER BY seed_id)
                       AS matched_seed_identifiers
            FROM exploded
            GROUP BY record_type, group_id
            HAVING {having}
        )
        SELECT members.record_type AS primary_group_type,
               members.group_id AS primary_group_id,
               matched.matched_seed_identifiers,
               string_agg(DISTINCT members.cluster_id, ';'
                          ORDER BY members.cluster_id) AS linked_deepclust_clusters,
               members.species,
               members.internal_id,
               members.raw_identifier,
               members.parsed_accession,
               members.parsed_entry,
               members.review_status,
               members.mapping_status,
               bool_or(coalesce(members.is_input_candidate, FALSE))
                   AS is_input_seed_member,
               max(members.sequence_length) AS sequence_length,
               any_value(members.protein_sequence) AS protein_sequence
        FROM candidate_group_member_sequences members
        INNER JOIN matched_groups matched
          ON members.record_type = matched.record_type
         AND members.group_id = matched.group_id
        WHERE TRUE{species_filter}
        GROUP BY members.record_type, members.group_id,
                 matched.matched_seed_identifiers, members.species,
                 members.internal_id, members.raw_identifier,
                 members.parsed_accession, members.parsed_entry,
                 members.review_status, members.mapping_status
        ORDER BY lower(members.group_id), members.group_id,
                 lower(members.species), members.species,
                 lower(members.raw_identifier), members.raw_identifier
        LIMIT {int(maximum_rows)}
    """
    return connection.execute(query, parameters).fetchdf()


def summarise_seed_groups(*, members: pd.DataFrame) -> pd.DataFrame:
    """Summarise one seed-search member result without losing source rows."""
    required = {
        "primary_group_type",
        "primary_group_id",
        "matched_seed_identifiers",
        "species",
        "raw_identifier",
    }
    missing = sorted(required.difference(members.columns))
    if missing:
        raise AppError("Seed member result is missing columns: " + ", ".join(missing))
    if members.empty:
        return pd.DataFrame(
            columns=(
                "primary_group_type",
                "primary_group_id",
                "matched_seed_identifiers",
                "member_count",
                "species_count",
                "species_present",
            )
        )
    grouped = members.groupby(
        ["primary_group_type", "primary_group_id", "matched_seed_identifiers"],
        dropna=False,
        sort=True,
    )
    summary = grouped.agg(
        member_count=("raw_identifier", "nunique"),
        species_count=("species", "nunique"),
        species_present=(
            "species",
            lambda values: ";".join(sorted(set(values.dropna().astype(str)))),
        ),
    )
    return summary.reset_index()


def load_species_taxonomy() -> pd.DataFrame:
    """Load the small curated species manifest shipped with the application."""
    resource = files("e3app").joinpath("resources", "species_taxonomy.tsv")
    with resource.open(mode="r", encoding="utf-8", newline="") as handle:
        return pd.read_csv(handle, sep="\t", dtype_backend="numpy_nullable")
