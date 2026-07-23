"""Shared selection and member expansion for exact OrthoFinder group constructs."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import duckdb

from e3workflow.errors import StageError
from e3workflow.tabular import quote_literal


def choose_primary_groups(
    *, mapping_rows: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Choose the best-supported hierarchical group, falling back to an orthogroup.

    Hierarchical orthogroups and orthogroups remain exact OrthoFinder constructs. Selection first
    maximises mapped candidate accessions and then mapped species, with stable lexical tie-breaking.

    Args:
        mapping_rows: Candidate membership mapping records from the orthology component.

    Returns:
        Selected group per candidate cluster and every supplied mapping grouped by cluster.
    """
    by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for supplied_row in mapping_rows:
        by_cluster[str(supplied_row["cluster_id"])].append(dict(supplied_row))
    selected: dict[str, dict[str, Any]] = {}
    for cluster_id, rows in by_cluster.items():
        hierarchical = [
            row for row in rows if row["record_type"] == "HIERARCHICAL_ORTHOGROUP"
        ]
        considered = hierarchical or [
            row for row in rows if row["record_type"] == "ORTHOGROUP"
        ]
        grouped: dict[tuple[str, str], dict[str, set[str]]] = {}
        for row in considered:
            key = (str(row["record_type"]), str(row["group_id"]))
            state = grouped.setdefault(key, {"accessions": set(), "species": set()})
            state["accessions"].add(str(row["candidate_accession"]))
            if row.get("species"):
                state["species"].add(str(row["species"]))
        if not grouped:
            continue
        ordered = sorted(
            grouped.items(),
            key=lambda item: (
                -len(item[1]["accessions"]),
                -len(item[1]["species"]),
                item[0][1],
            ),
        )
        (record_type, group_id), state = ordered[0]
        selected[cluster_id] = {
            "record_type": record_type,
            "group_id": group_id,
            "candidate_accessions": set(state["accessions"]),
            "candidate_species": set(state["species"]),
            "alternative_group_count": len(grouped) - 1,
        }
    return selected, by_cluster


def candidate_mapping_rows(path: Path) -> list[dict[str, Any]]:
    """Read usable candidate-to-group mappings from one Parquet authority."""
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            "SELECT cluster_id, candidate_accession, record_type, group_id, species, "
            "mapping_status, ambiguity_status FROM read_parquet("
            f"{quote_literal(path)}) WHERE mapping_status <> 'NOT_MATCHED' "
            "AND COALESCE(group_id, '') <> ''"
        ).fetchall()
        fields = [str(item[0]) for item in connection.description]
        return [dict(zip(fields, row)) for row in rows]
    except duckdb.Error as exc:
        raise StageError(f"Could not read candidate orthology mappings: {exc}") from exc
    finally:
        connection.close()


def selected_group_members(
    *,
    selected: Mapping[str, Mapping[str, Any]],
    orthogroup_membership: Path,
    hierarchical_membership: Path,
    target_species: Iterable[str],
) -> list[dict[str, Any]]:
    """Expand selected exact groups to their target-species protein members.

    Unparsed identifiers are retained with an empty accession. They later become explicit
    ``ANNOTATION_UNAVAILABLE`` rows rather than disappearing from completeness accounting.
    """
    target = sorted(set(target_species))
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE selected_groups (cluster_id VARCHAR, record_type VARCHAR, "
            "group_id VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO selected_groups VALUES (?, ?, ?)",
            sorted(
                (
                    str(cluster_id),
                    str(record["record_type"]),
                    str(record["group_id"]),
                )
                for cluster_id, record in selected.items()
            ),
        )
        connection.execute("CREATE TABLE target_species (species VARCHAR)")
        connection.executemany(
            "INSERT INTO target_species VALUES (?)", [(item,) for item in target]
        )
        query = (
            "SELECT DISTINCT s.cluster_id, s.record_type AS primary_group_type, "
            "s.group_id AS primary_group_id, m.species AS species_column, "
            "COALESCE(m.parsed_accession, '') AS member_accession, "
            "COALESCE(NULLIF(m.parsed_accession, ''), m.raw_identifier) AS member_identifier, "
            "m.raw_identifier, "
            "COALESCE(m.parsed_entry, '') AS parsed_entry, "
            "m.mapping_status AS identifier_mapping_status, m.mapping_reason "
            "FROM selected_groups s JOIN ("
            "SELECT 'ORTHOGROUP' AS record_type, group_id, species, parsed_accession, "
            "parsed_entry, raw_identifier, mapping_status, mapping_reason FROM read_parquet("
            f"{quote_literal(orthogroup_membership)}) UNION ALL SELECT "
            "'HIERARCHICAL_ORTHOGROUP' AS record_type, group_id, species, parsed_accession, "
            "parsed_entry, raw_identifier, mapping_status, mapping_reason FROM read_parquet("
            f"{quote_literal(hierarchical_membership)})) m USING (record_type, group_id) "
            "JOIN target_species t ON m.species = t.species "
            "ORDER BY s.cluster_id, m.species, member_accession, m.raw_identifier"
        )
        rows = connection.execute(query).fetchall()
        fields = [str(item[0]) for item in connection.description]
        return [dict(zip(fields, row)) for row in rows]
    except duckdb.Error as exc:
        raise StageError(f"Could not expand selected OrthoFinder groups: {exc}") from exc
    finally:
        connection.close()
