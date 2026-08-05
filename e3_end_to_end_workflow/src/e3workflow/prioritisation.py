"""Transparent grant-aligned pre-structure prioritisation of E3 candidates."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import duckdb

from e3workflow.config import WorkflowConfig
from e3workflow.errors import StageError
from e3workflow.io_utils import write_tsv
from e3workflow.orthology_groups import (
    candidate_mapping_rows,
    choose_primary_groups,
)
from e3workflow.production import find_one, find_orthology_table, split_accessions
from e3workflow.resources import EXPRESSION_RESOURCE_TYPES, read_resource_manifest
from e3workflow.tabular import parquet_columns, quote_literal, write_records

PRESTRUCTURE_FIELDS = (
    "computational_rank",
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "orthofinder_orthogroup_ids",
    "orthofinder_hierarchical_group_ids",
    "alternative_group_count",
    "candidate_accession_count",
    "candidate_accessions",
    "target_species_count",
    "target_species_total",
    "target_species_fraction",
    "target_species_present",
    "target_species_missing",
    "mandatory_species_count",
    "mandatory_species_total",
    "mandatory_species_fraction",
    "mandatory_species_missing",
    "domain_supported_species_count",
    "domain_assessed_species_count",
    "domain_unavailable_species_count",
    "domain_annotation_coverage_fraction",
    "domain_species_fraction",
    "domain_supported_species",
    "domain_annotated_negative_species",
    "domain_unavailable_species",
    "expression_supported_species_count",
    "expression_available_species_count",
    "expression_assessed_species_count",
    "expression_unavailable_species_count",
    "expression_evidence_coverage_fraction",
    "expression_species_fraction",
    "expression_supported_species",
    "expression_assessed_negative_species",
    "expression_unavailable_species",
    "reviewed_seed_fraction",
    "ubiquitin_go_positive_seed_fraction",
    "exclusion_flag_fraction",
    "discovery_score",
    "orthology_score",
    "domain_score",
    "expression_score",
    "prestructure_score",
    "evidence_completeness_fraction",
    "grant_aligned_criteria_status",
    "grant_aligned_stringent_pass",
    "computational_structure_selected",
    "inclusion_reasons",
    "exclusion_reasons",
    "missing_evidence",
    "profile_name",
    "interpretation",
)

STRUCTURE_ACCESSION_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "computational_rank",
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "candidate_accession",
    "species_column",
    "raw_identifier",
    "parsed_entry",
    "review_status",
    "mapping_status",
    "sequence_length",
    "group_reference_length",
    "length_ratio",
    "likely_full_length",
    "alternative_accession_count",
    "prestructure_score",
    "selection_reason",
)

EVOLUTIONARY_GROUP_PREFIX_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "primary_group_type",
    "primary_group_id",
    "lead_cluster_id",
    "lead_computational_rank",
    "contributing_deepclust_cluster_count",
    "contributing_deepclust_cluster_ids",
    "best_prestructure_score",
    "mean_prestructure_score",
    "minimum_prestructure_score",
)

EVOLUTIONARY_GROUP_FIELDS = EVOLUTIONARY_GROUP_PREFIX_FIELDS + tuple(
    f"lead_{field}"
    for field in PRESTRUCTURE_FIELDS
    if field
    not in {
        "cluster_id",
        "primary_group_type",
        "primary_group_id",
        "computational_rank",
        "prestructure_score",
    }
)

EVOLUTIONARY_CONTRIBUTOR_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
) + PRESTRUCTURE_FIELDS

REPRESENTATIVE_AUDIT_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "species_column",
    "candidate_accession",
    "raw_identifier",
    "parsed_entry",
    "review_status",
    "mapping_status",
    "is_input_candidate",
    "sequence_length",
    "group_reference_length",
    "length_ratio",
    "likely_full_length",
    "alternative_accession_count",
    "representative_selected",
    "selection_rank_within_species",
    "selection_status",
    "selection_reason",
)

ALL_MEMBER_STRUCTURE_FIELDS = (
    "evolutionary_group_rank",
    "evolutionary_group_key",
    "computational_rank",
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "candidate_accession",
    "species_column",
    "raw_identifier",
    "parsed_entry",
    "review_status",
    "mapping_status",
    "is_input_candidate",
    "sequence_length",
    "group_reference_length",
    "length_ratio",
    "likely_full_length",
    "prestructure_score",
    "selection_reason",
)

REVIEW_FIELDS = (
    "computational_rank",
    "cluster_id",
    "primary_group_id",
    "prestructure_score",
    "grant_aligned_stringent_pass",
    "computational_structure_selected",
    "review_decision",
    "reviewer",
    "review_date",
    "review_comments",
)


def _evolutionary_group_key(record: Mapping[str, Any]) -> str:
    """Return a stable key that does not conflate DeepClust and OrthoFinder."""
    return f"{record['primary_group_type']}:{record['primary_group_id']}"


def build_evolutionary_group_records(
    records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Aggregate cluster rankings into distinct evolutionary candidate groups.

    The original DeepClust rows remain unchanged in the contributor table. A
    deterministic lead cluster supplies the display-level evidence for each
    distinct primary OrthoFinder group.
    """
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        group_type = str(record.get("primary_group_type", ""))
        group_id = str(record.get("primary_group_id", ""))
        if group_type and group_id:
            grouped[(group_type, group_id)].append(record)
    ordered_groups = sorted(
        grouped.items(),
        key=lambda item: (
            min(int(row["computational_rank"]) for row in item[1]),
            item[0][0],
            item[0][1],
        ),
    )
    groups: list[dict[str, Any]] = []
    contributors: list[dict[str, Any]] = []
    for group_rank, ((group_type, group_id), members) in enumerate(
        ordered_groups,
        start=1,
    ):
        ordered_members = sorted(
            members,
            key=lambda row: (
                int(row["computational_rank"]),
                -float(row["prestructure_score"]),
                str(row["cluster_id"]),
            ),
        )
        lead = ordered_members[0]
        scores = [float(row["prestructure_score"]) for row in ordered_members]
        group_key = _evolutionary_group_key(lead)
        group_record: dict[str, Any] = {
            "evolutionary_group_rank": group_rank,
            "evolutionary_group_key": group_key,
            "primary_group_type": group_type,
            "primary_group_id": group_id,
            "lead_cluster_id": lead["cluster_id"],
            "lead_computational_rank": lead["computational_rank"],
            "contributing_deepclust_cluster_count": len(ordered_members),
            "contributing_deepclust_cluster_ids": ";".join(
                str(row["cluster_id"]) for row in ordered_members
            ),
            "best_prestructure_score": max(scores),
            "mean_prestructure_score": statistics.mean(scores),
            "minimum_prestructure_score": min(scores),
        }
        for field in PRESTRUCTURE_FIELDS:
            if field in {
                "cluster_id",
                "primary_group_type",
                "primary_group_id",
                "computational_rank",
                "prestructure_score",
            }:
                continue
            group_record[f"lead_{field}"] = lead.get(field)
        groups.append(group_record)
        for member in ordered_members:
            contributors.append(
                {
                    "evolutionary_group_rank": group_rank,
                    "evolutionary_group_key": group_key,
                    **{field: member.get(field) for field in PRESTRUCTURE_FIELDS},
                }
            )
    return groups, contributors


def apply_evolutionary_group_selection(
    *, records: Sequence[dict[str, Any]], structure_group_limit: int
) -> int:
    """Select distinct evolutionary groups and flag every contributing cluster.

    DeepClust can contribute more than one ranked cluster to the same primary
    OrthoFinder group. Applying ``structure_group_limit`` directly to the
    cluster rows therefore selects fewer evolutionary groups than requested.
    This function derives the authoritative group order first and then
    propagates the group-level decision back to every cluster row.

    Args:
        records: Ranked, mutable DeepClust candidate records.
        structure_group_limit: Maximum number of distinct evolutionary groups.

    Returns:
        Number of distinct evolutionary groups selected.

    Raises:
        StageError: If ``structure_group_limit`` is not positive.
    """
    if structure_group_limit < 1:
        raise StageError("structure_group_limit must be a positive integer")
    groups, _ = build_evolutionary_group_records(records)
    selected_keys = {
        str(group["evolutionary_group_key"])
        for group in groups
        if int(group["evolutionary_group_rank"]) <= structure_group_limit
    }
    for record in records:
        group_type = str(record.get("primary_group_type", ""))
        group_id = str(record.get("primary_group_id", ""))
        key = f"{group_type}:{group_id}" if group_type and group_id else ""
        record["computational_structure_selected"] = key in selected_keys
    return len(selected_keys)


def _representative_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return a conservative deterministic full-length representative order."""
    ratio = float(record["length_ratio"])
    reviewed = "reviewed" in str(record.get("review_status", "")).lower()
    mapped = "mapped" in str(record.get("mapping_status", "")).lower()
    return (
        not bool(record["likely_full_length"]),
        not reviewed,
        not bool(record.get("is_input_candidate", False)),
        not mapped,
        abs(math.log(ratio)) if ratio > 0 else math.inf,
        -int(record["sequence_length"]),
        str(record["candidate_accession"]),
        str(record["raw_identifier"]),
    )


def derive_structural_representatives(
    *,
    config: WorkflowConfig,
    stage_root: Path,
) -> dict[str, int]:
    """Derive one auditable representative per target species and group.

    Returns:
        Counts for the evolutionary-group, all-member and representative
        selection authorities.
    """
    tables = stage_root / "tables"
    ranking_path = tables / "computational_prestructure_ranking.parquet"
    member_path = find_orthology_table(
        root=config.run_root / "05_orthology",
        name="candidate_group_member_sequences.parquet",
    )
    available_member_columns = set(parquet_columns(member_path))
    required_member_columns = {
        "cluster_id",
        "record_type",
        "group_id",
        "species",
        "parsed_accession",
        "sequence_length",
    }
    missing_member_columns = sorted(
        required_member_columns.difference(available_member_columns)
    )
    if missing_member_columns:
        raise StageError(
            "Candidate-group member table is missing required representative "
            f"selection columns: {', '.join(missing_member_columns)}"
        )
    optional_expressions = {
        "raw_identifier": (
            "raw_identifier"
            if "raw_identifier" in available_member_columns
            else "CAST(parsed_accession AS VARCHAR) AS raw_identifier"
        ),
        "parsed_entry": (
            "parsed_entry"
            if "parsed_entry" in available_member_columns
            else "''::VARCHAR AS parsed_entry"
        ),
        "review_status": (
            "review_status"
            if "review_status" in available_member_columns
            else "''::VARCHAR AS review_status"
        ),
        "mapping_status": (
            "mapping_status"
            if "mapping_status" in available_member_columns
            else "''::VARCHAR AS mapping_status"
        ),
        "is_input_candidate": (
            "is_input_candidate"
            if "is_input_candidate" in available_member_columns
            else "FALSE::BOOLEAN AS is_input_candidate"
        ),
    }
    connection = duckdb.connect(":memory:")
    try:
        ranked = _records_from_query(
            connection=connection,
            query=(
                "SELECT * FROM read_parquet("
                f"{quote_literal(ranking_path)}) ORDER BY computational_rank"
            ),
        )
        member_rows = _records_from_query(
            connection=connection,
            query=(
                "SELECT cluster_id, record_type, group_id, species, "
                f"{optional_expressions['raw_identifier']}, parsed_accession, "
                f"{optional_expressions['parsed_entry']}, "
                f"{optional_expressions['review_status']}, "
                f"{optional_expressions['mapping_status']}, "
                f"{optional_expressions['is_input_candidate']}, "
                "sequence_length FROM read_parquet("
                f"{quote_literal(member_path)})"
            ),
        )
    except duckdb.Error as exc:
        raise StageError(f"Could not derive structural representatives: {exc}") from exc
    finally:
        connection.close()
    groups, contributors = build_evolutionary_group_records(ranked)
    selected_groups = {
        (str(row["primary_group_type"]), str(row["primary_group_id"])): row
        for row in groups
        if int(row["evolutionary_group_rank"])
        <= config.analysis.prioritisation.structure_group_limit
    }
    candidates_by_group_species: dict[
        tuple[str, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    target_species = set(config.analysis.prioritisation.target_species)
    for member in member_rows:
        group_key = (str(member["record_type"]), str(member["group_id"]))
        species = str(member["species"])
        accession = str(member.get("parsed_accession", "")).strip()
        if group_key not in selected_groups or species not in target_species:
            continue
        if not accession:
            continue
        candidates_by_group_species[(group_key[0], group_key[1], species)].append(
            dict(member)
        )
    reference_lengths: dict[tuple[str, str], float] = {}
    for group_key in selected_groups:
        species_maxima = [
            max(
                int(row["sequence_length"])
                for row in candidates
            )
            for (record_type, group_id, _species), candidates in
            candidates_by_group_species.items()
            if (record_type, group_id) == group_key and candidates
        ]
        reference_lengths[group_key] = (
            float(statistics.median(species_maxima)) if species_maxima else 0.0
        )
    audit_rows: list[dict[str, Any]] = []
    all_member_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    for (group_type, group_id, species), raw_candidates in sorted(
        candidates_by_group_species.items()
    ):
        group = selected_groups[(group_type, group_id)]
        reference_length = reference_lengths[(group_type, group_id)]
        deduplicated: dict[str, dict[str, Any]] = {}
        for candidate in raw_candidates:
            accession = str(candidate["parsed_accession"])
            existing = deduplicated.get(accession)
            if existing is None or int(candidate["sequence_length"]) > int(
                existing["sequence_length"]
            ):
                deduplicated[accession] = candidate
        prepared: list[dict[str, Any]] = []
        for candidate in deduplicated.values():
            sequence_length = int(candidate["sequence_length"])
            ratio = (
                sequence_length / reference_length if reference_length > 0 else 0.0
            )
            prepared.append(
                {
                    **candidate,
                    "candidate_accession": candidate["parsed_accession"],
                    "species_column": species,
                    "group_reference_length": reference_length,
                    "length_ratio": ratio,
                    "likely_full_length": 0.75 <= ratio <= 1.35,
                }
            )
        ordered = sorted(prepared, key=_representative_sort_key)
        alternative_count = max(0, len(ordered) - 1)
        for selection_rank, candidate in enumerate(ordered, start=1):
            selected = selection_rank == 1
            status = (
                "SELECTED_PRIMARY_REPRESENTATIVE"
                if selected
                else "RETAINED_ALTERNATIVE_NOT_SELECTED"
            )
            reason = (
                "one deterministic likely-full-length representative per target "
                "species and evolutionary candidate group"
                if candidate["likely_full_length"]
                else (
                    "best available accession selected but its length is outside "
                    "the conservative group-relative full-length interval"
                )
            )
            audit = {
                "evolutionary_group_rank": group["evolutionary_group_rank"],
                "evolutionary_group_key": group["evolutionary_group_key"],
                "cluster_id": group["lead_cluster_id"],
                "primary_group_type": group_type,
                "primary_group_id": group_id,
                "species_column": species,
                "candidate_accession": candidate["candidate_accession"],
                "raw_identifier": candidate.get("raw_identifier", ""),
                "parsed_entry": candidate.get("parsed_entry", ""),
                "review_status": candidate.get("review_status", ""),
                "mapping_status": candidate.get("mapping_status", ""),
                "is_input_candidate": candidate.get("is_input_candidate", False),
                "sequence_length": candidate["sequence_length"],
                "group_reference_length": reference_length,
                "length_ratio": candidate["length_ratio"],
                "likely_full_length": candidate["likely_full_length"],
                "alternative_accession_count": alternative_count,
                "representative_selected": selected,
                "selection_rank_within_species": selection_rank,
                "selection_status": status,
                "selection_reason": reason,
            }
            audit_rows.append(audit)
            all_member_rows.append(
                {
                    "evolutionary_group_rank": group["evolutionary_group_rank"],
                    "evolutionary_group_key": group["evolutionary_group_key"],
                    "computational_rank": group["lead_computational_rank"],
                    "cluster_id": group["lead_cluster_id"],
                    "primary_group_type": group_type,
                    "primary_group_id": group_id,
                    "candidate_accession": candidate["candidate_accession"],
                    "species_column": species,
                    "raw_identifier": candidate.get("raw_identifier", ""),
                    "parsed_entry": candidate.get("parsed_entry", ""),
                    "review_status": candidate.get("review_status", ""),
                    "mapping_status": candidate.get("mapping_status", ""),
                    "is_input_candidate": candidate.get("is_input_candidate", False),
                    "sequence_length": candidate["sequence_length"],
                    "group_reference_length": reference_length,
                    "length_ratio": candidate["length_ratio"],
                    "likely_full_length": candidate["likely_full_length"],
                    "prestructure_score": group["best_prestructure_score"],
                    "selection_reason": (
                        "target-species member of a computationally selected "
                        "evolutionary candidate group"
                    ),
                }
            )
            if selected:
                selected_rows.append(
                    {
                        field: (
                            group["lead_computational_rank"]
                            if field == "computational_rank"
                            else group["best_prestructure_score"]
                            if field == "prestructure_score"
                            else audit.get(field, "")
                        )
                        for field in STRUCTURE_ACCESSION_FIELDS
                    }
                )
    write_records(
        tsv_path=tables / "evolutionary_candidate_group_ranking.tsv",
        parquet_path=tables / "evolutionary_candidate_group_ranking.parquet",
        fieldnames=EVOLUTIONARY_GROUP_FIELDS,
        records=groups,
    )
    write_records(
        tsv_path=tables / "evolutionary_group_cluster_contributors.tsv",
        parquet_path=tables / "evolutionary_group_cluster_contributors.parquet",
        fieldnames=EVOLUTIONARY_CONTRIBUTOR_FIELDS,
        records=contributors,
    )
    write_records(
        tsv_path=tables / "structural_analysis_accessions_all_members.tsv",
        parquet_path=tables / "structural_analysis_accessions_all_members.parquet",
        fieldnames=ALL_MEMBER_STRUCTURE_FIELDS,
        records=all_member_rows,
    )
    write_records(
        tsv_path=tables / "structural_representative_selection_audit.tsv",
        parquet_path=tables / "structural_representative_selection_audit.parquet",
        fieldnames=REPRESENTATIVE_AUDIT_FIELDS,
        records=audit_rows,
    )
    write_records(
        tsv_path=tables / "structural_analysis_accessions.tsv",
        parquet_path=tables / "structural_analysis_accessions.parquet",
        fieldnames=STRUCTURE_ACCESSION_FIELDS,
        records=selected_rows,
    )
    write_tsv(
        tables / "ligandability_accessions.tsv",
        [
            {
                "accession": row["candidate_accession"],
                "evolutionary_group_rank": row["evolutionary_group_rank"],
                "evolutionary_group_key": row["evolutionary_group_key"],
                "cluster_id": row["cluster_id"],
                "primary_group_type": row["primary_group_type"],
                "primary_group_id": row["primary_group_id"],
                "species_column": row["species_column"],
                "sequence_length": row["sequence_length"],
            }
            for row in selected_rows
        ],
        (
            "accession",
            "evolutionary_group_rank",
            "evolutionary_group_key",
            "cluster_id",
            "primary_group_type",
            "primary_group_id",
            "species_column",
            "sequence_length",
        ),
    )
    return {
        "distinct_evolutionary_group_count": len(groups),
        "selected_evolutionary_group_count": len(selected_groups),
        "all_member_structural_accession_count": len(all_member_rows),
        "selected_structural_representative_count": len(selected_rows),
    }


def safe_fraction(numerator: float, denominator: float) -> float:
    """Return a bounded fraction, using zero for an unavailable denominator."""
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def _records_from_query(
    *, connection: duckdb.DuckDBPyConnection, query: str, parameters: Sequence[Any] = ()
) -> list[dict[str, Any]]:
    """Return one bounded DuckDB query as dictionaries."""
    rows = connection.execute(query, list(parameters)).fetchall()
    fields = [str(item[0]) for item in connection.description]
    return [dict(zip(fields, row)) for row in rows]


def _candidate_rows(path: Path) -> list[dict[str, Any]]:
    """Read the compact candidate evidence fields required for scoring."""
    connection = duckdb.connect(":memory:")
    try:
        return _records_from_query(
            connection=connection,
            query=(
                "SELECT representative_id AS cluster_id, matched_seed_ids_calculated, "
                "matched_seed_id_count, reviewed_seed_count, ubiquitin_go_positive_seed_count, "
                "seed_with_exclusion_go_term_count, strict_member_count, "
                "strict_named_species_count, strict_named_proteome_count, "
                "strict_onekp_species_count, seed_categories, seed_protein_names "
                f"FROM read_parquet({quote_literal(path)})"
            ),
        )
    except duckdb.Error as exc:
        raise StageError(f"Could not read candidate evidence for ranking: {exc}") from exc
    finally:
        connection.close()


def _full_group_species(
    *,
    selected: Mapping[str, Mapping[str, Any]],
    orthogroup_membership: Path,
    hierarchical_membership: Path,
) -> dict[tuple[str, str], set[str]]:
    """Retrieve species coverage for only the chosen OrthoFinder groups."""
    requested = {
        (str(record["record_type"]), str(record["group_id"])) for record in selected.values()
    }
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE selected_groups (record_type VARCHAR, group_id VARCHAR)")
        connection.executemany("INSERT INTO selected_groups VALUES (?, ?)", sorted(requested))
        query = (
            "SELECT s.record_type, s.group_id, m.species FROM selected_groups s JOIN ("
            "SELECT 'ORTHOGROUP' AS record_type, group_id, species FROM read_parquet("
            f"{quote_literal(orthogroup_membership)}) UNION ALL SELECT "
            "'HIERARCHICAL_ORTHOGROUP' AS record_type, group_id, species FROM read_parquet("
            f"{quote_literal(hierarchical_membership)})) m USING (record_type, group_id) "
            "WHERE COALESCE(m.species, '') <> ''"
        )
        rows = connection.execute(query).fetchall()
    except duckdb.Error as exc:
        raise StageError(f"Could not calculate full group species coverage: {exc}") from exc
    finally:
        connection.close()
    result: dict[tuple[str, str], set[str]] = defaultdict(set)
    for record_type, group_id, species in rows:
        result[(str(record_type), str(group_id))].add(str(species))
    return result


def _expression_rows_by_cluster(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Read group-member expression summaries into a candidate-cluster index."""
    connection = duckdb.connect(":memory:")
    try:
        query = (
            "SELECT cluster_id, member_accession, member_identifier, species_column, "
            "mapping_status, broad_expression_supported, evidence_status FROM read_parquet("
            f"{quote_literal(path)})"
        )
        rows = _records_from_query(connection=connection, query=query)
    except duckdb.Error as exc:
        raise StageError(f"Could not read expression summary: {exc}") from exc
    finally:
        connection.close()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["cluster_id"])].append(row)
    return grouped


def _domain_rows_by_cluster(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Read tri-state domain summaries grouped by candidate cluster."""
    connection = duckdb.connect(":memory:")
    try:
        query = (
            "SELECT cluster_id, member_accession, species_column, "
            "annotation_availability_status, domain_support_status, e3_families "
            f"FROM read_parquet({quote_literal(path)})"
        )
        rows = _records_from_query(connection=connection, query=query)
    except duckdb.Error as exc:
        raise StageError(f"Could not read domain summary: {exc}") from exc
    finally:
        connection.close()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["cluster_id"])].append(row)
    return grouped


def _string_set(values: Iterable[str]) -> str:
    """Serialise a deterministic set as semicolon-delimited text."""
    return ";".join(sorted({value for value in values if value}))


def score_candidate(
    *,
    config: WorkflowConfig,
    candidate: Mapping[str, Any],
    primary: Mapping[str, Any] | None,
    full_species: set[str],
    domain_rows: Sequence[Mapping[str, Any]],
    expression_rows: Sequence[Mapping[str, Any]],
    expression_available_species: set[str],
) -> dict[str, Any]:
    """Score one candidate cluster while retaining every denominator and reason."""
    settings = config.analysis.prioritisation
    accessions = split_accessions(candidate.get("matched_seed_ids_calculated"))
    target_species = set(settings.target_species)
    mandatory_species = set(settings.mandatory_species)
    target_present = full_species.intersection(target_species)
    target_fraction = safe_fraction(len(target_present), len(target_species))
    mandatory_present = full_species.intersection(mandatory_species)
    mandatory_fraction = safe_fraction(len(mandatory_present), len(mandatory_species))
    domain_assessed_species = {
        str(row["species_column"])
        for row in domain_rows
        if row.get("species_column")
        and row.get("domain_support_status")
        in {"SUPPORTED", "ANNOTATED_NO_CATALOGUED_E3_DOMAIN"}
    }.intersection(target_present)
    domain_supported_species = {
        str(row["species_column"])
        for row in domain_rows
        if row.get("domain_support_status") == "SUPPORTED" and row.get("species_column")
    }.intersection(domain_assessed_species)
    domain_fraction = safe_fraction(
        len(domain_supported_species), len(domain_assessed_species)
    )
    domain_annotated_negative_species = domain_assessed_species.difference(
        domain_supported_species
    )
    domain_unavailable_species = target_present.difference(domain_assessed_species)
    domain_annotation_coverage = safe_fraction(
        len(domain_assessed_species), len(target_present)
    )
    expression_available = expression_available_species.intersection(target_present)
    expression_assessed_species = {
        str(row["species_column"])
        for row in expression_rows
        if row.get("species_column")
        and row.get("mapping_status") == "MAPPED_UNIQUE"
        and (
            not row.get("evidence_status")
            or row.get("evidence_status")
            in {"BROAD_EXPRESSION_SUPPORTED", "LIMITED_OR_ZERO_EXPRESSION"}
        )
    }.intersection(expression_available)
    expression_supported_species = {
        str(row["species_column"])
        for row in expression_rows
        if bool(row.get("broad_expression_supported")) and row.get("species_column")
    }.intersection(expression_assessed_species)
    expression_assessed_negative_species = expression_assessed_species.difference(
        expression_supported_species
    )
    expression_unavailable_species = target_present.difference(
        expression_assessed_species
    )
    expression_fraction = safe_fraction(
        len(expression_supported_species), len(expression_assessed_species)
    )
    expression_evidence_coverage = safe_fraction(
        len(expression_assessed_species), len(target_present)
    )
    seed_count = float(candidate.get("matched_seed_id_count") or 0)
    reviewed_fraction = safe_fraction(float(candidate.get("reviewed_seed_count") or 0), seed_count)
    go_fraction = safe_fraction(
        float(candidate.get("ubiquitin_go_positive_seed_count") or 0), seed_count
    )
    exclusion_fraction = safe_fraction(
        float(candidate.get("seed_with_exclusion_go_term_count") or 0), seed_count
    )
    discovery_score = (reviewed_fraction + go_fraction + (1.0 - exclusion_fraction)) / 3.0
    orthology_score = target_fraction * (0.8 + 0.2 * mandatory_fraction)
    domain_score = domain_fraction if domain_assessed_species else 0.5
    expression_score = expression_fraction if expression_assessed_species else 0.5
    prestructure_score = (
        discovery_score * settings.discovery_weight
        + orthology_score * settings.orthology_weight
        + domain_score * settings.domain_weight
        + expression_score * settings.expression_weight
    )
    evidence_completeness = [
        1.0 if seed_count > 0 else 0.0,
        1.0 if primary is not None else 0.0,
        domain_annotation_coverage,
        expression_evidence_coverage,
    ]
    missing_evidence = []
    if seed_count <= 0:
        missing_evidence.append("discovery_seed_evidence_unavailable")
    if primary is None:
        missing_evidence.append("orthofinder_group_unavailable")
    if not domain_assessed_species:
        missing_evidence.append("domain_evidence_unavailable")
    elif domain_unavailable_species:
        missing_evidence.append(
            "domain_annotation_unavailable_for_species="
            + _string_set(domain_unavailable_species)
        )
    if not expression_assessed_species:
        missing_evidence.append("expression_resource_unavailable")
    elif expression_unavailable_species:
        missing_evidence.append(
            "expression_evidence_unavailable_for_species="
            + _string_set(expression_unavailable_species)
        )
    exclusion_reasons = []
    if target_fraction < settings.minimum_target_species_fraction:
        exclusion_reasons.append("target_species_fraction_below_threshold")
    if mandatory_fraction < 1.0:
        exclusion_reasons.append("mandatory_species_missing")
    if (
        domain_assessed_species
        and domain_fraction < settings.minimum_domain_species_fraction
    ):
        exclusion_reasons.append("domain_species_fraction_below_threshold")
    if (
        expression_assessed_species
        and expression_fraction < settings.minimum_expression_species_fraction
    ):
        exclusion_reasons.append("expression_species_fraction_below_threshold")
    if exclusion_reasons:
        criteria_status = "FAIL"
    elif not domain_assessed_species or not expression_assessed_species:
        criteria_status = "PENDING_MISSING_EVIDENCE"
    elif missing_evidence:
        criteria_status = "PASS_WITH_MISSING_EVIDENCE"
    else:
        criteria_status = "PASS"
    stringent_pass = criteria_status in {"PASS", "PASS_WITH_MISSING_EVIDENCE"}
    inclusion_reasons = []
    if target_fraction >= settings.minimum_target_species_fraction:
        inclusion_reasons.append("broad_target_species_coverage")
    if mandatory_fraction == 1.0:
        inclusion_reasons.append("all_mandatory_crop_species_present")
    if domain_fraction >= settings.minimum_domain_species_fraction:
        inclusion_reasons.append("broad_catalogued_e3_domain_support")
    if expression_fraction >= settings.minimum_expression_species_fraction:
        inclusion_reasons.append("broad_expression_support")
    return {
        "computational_rank": 0,
        "cluster_id": candidate["cluster_id"],
        "primary_group_type": "" if primary is None else primary["record_type"],
        "primary_group_id": "" if primary is None else primary["group_id"],
        "alternative_group_count": 0 if primary is None else primary["alternative_group_count"],
        "candidate_accession_count": len(accessions),
        "candidate_accessions": ";".join(accessions),
        "target_species_count": len(target_present),
        "target_species_total": len(target_species),
        "target_species_fraction": target_fraction,
        "target_species_present": _string_set(target_present),
        "target_species_missing": _string_set(target_species.difference(target_present)),
        "mandatory_species_count": len(mandatory_present),
        "mandatory_species_total": len(mandatory_species),
        "mandatory_species_fraction": mandatory_fraction,
        "mandatory_species_missing": _string_set(mandatory_species.difference(mandatory_present)),
        "domain_supported_species_count": len(domain_supported_species),
        "domain_assessed_species_count": len(domain_assessed_species),
        "domain_unavailable_species_count": len(domain_unavailable_species),
        "domain_annotation_coverage_fraction": domain_annotation_coverage,
        "domain_species_fraction": domain_fraction,
        "domain_supported_species": _string_set(domain_supported_species),
        "domain_annotated_negative_species": _string_set(
            domain_annotated_negative_species
        ),
        "domain_unavailable_species": _string_set(domain_unavailable_species),
        "expression_supported_species_count": len(expression_supported_species),
        "expression_available_species_count": len(expression_available),
        "expression_assessed_species_count": len(expression_assessed_species),
        "expression_unavailable_species_count": len(expression_unavailable_species),
        "expression_evidence_coverage_fraction": expression_evidence_coverage,
        "expression_species_fraction": expression_fraction,
        "expression_supported_species": _string_set(expression_supported_species),
        "expression_assessed_negative_species": _string_set(
            expression_assessed_negative_species
        ),
        "expression_unavailable_species": _string_set(expression_unavailable_species),
        "reviewed_seed_fraction": reviewed_fraction,
        "ubiquitin_go_positive_seed_fraction": go_fraction,
        "exclusion_flag_fraction": exclusion_fraction,
        "discovery_score": discovery_score,
        "orthology_score": orthology_score,
        "domain_score": domain_score,
        "expression_score": expression_score,
        "prestructure_score": prestructure_score,
        "evidence_completeness_fraction": safe_fraction(
            sum(evidence_completeness), len(evidence_completeness)
        ),
        "grant_aligned_criteria_status": criteria_status,
        "grant_aligned_stringent_pass": stringent_pass,
        "computational_structure_selected": False,
        "inclusion_reasons": ";".join(inclusion_reasons),
        "exclusion_reasons": ";".join(exclusion_reasons),
        "missing_evidence": ";".join(missing_evidence),
        "profile_name": settings.profile_name,
        "interpretation": (
            "computational prioritisation only; requires structural, biological "
            "and chemistry review"
        ),
    }


def rank_records(*, records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort and rank pre-structure cluster records deterministically."""
    ordered = sorted(
        records,
        key=lambda row: (
            not bool(row["grant_aligned_stringent_pass"]),
            -float(row["prestructure_score"]),
            -float(row["evidence_completeness_fraction"]),
            str(row["cluster_id"]),
        ),
    )
    for rank, row in enumerate(ordered, start=1):
        row["computational_rank"] = rank
        row["computational_structure_selected"] = False
    return ordered


def run_prestructure_stage(*, config: WorkflowConfig, stage_root: Path) -> None:
    """Integrate discovery, orthology, domain and expression evidence for ranking."""
    candidate_path = find_one(
        root=config.run_root / "03_candidate_evidence",
        name="e3_cluster_candidate_evidence.parquet",
    )
    orthology_root = config.run_root / "05_orthology"
    candidate_mapping = find_orthology_table(
        root=orthology_root,
        name="candidate_membership_mapping.parquet",
    )
    orthogroup_membership = find_orthology_table(
        root=orthology_root,
        name="orthogroup_membership.parquet",
    )
    hierarchical_membership = find_orthology_table(
        root=orthology_root,
        name="hierarchical_membership.parquet",
    )
    domain_summary = find_one(root=config.run_root / "06_domains", name="domain_summary.parquet")
    expression_summary = find_one(
        root=config.run_root / "07_expression", name="candidate_expression_summary.parquet"
    )
    mapping_rows = candidate_mapping_rows(path=candidate_mapping)
    primary_by_cluster, mappings_by_cluster = choose_primary_groups(
        mapping_rows=mapping_rows
    )
    group_species = _full_group_species(
        selected=primary_by_cluster,
        orthogroup_membership=orthogroup_membership,
        hierarchical_membership=hierarchical_membership,
    )
    domain_by_cluster = _domain_rows_by_cluster(path=domain_summary)
    expression_by_cluster = _expression_rows_by_cluster(path=expression_summary)
    expression_manifest = config.resources.expression_manifest
    if expression_manifest is None:
        raise StageError("inputs.expression_manifest is required for prioritisation")
    expression_resources = read_resource_manifest(
        path=expression_manifest,
        allowed_resource_types=EXPRESSION_RESOURCE_TYPES,
        verify_checksums=True,
    )
    expression_available_species = {
        record["species_column"]
        for record in expression_resources
        if record["resource_type"] == "atlas_expression_long"
    }
    scored = []
    for candidate in _candidate_rows(path=candidate_path):
        cluster_id = str(candidate["cluster_id"])
        primary = primary_by_cluster.get(cluster_id)
        species = (
            set()
            if primary is None
            else group_species.get((primary["record_type"], primary["group_id"]), set())
        )
        scored_record = score_candidate(
            config=config,
            candidate=candidate,
            primary=primary,
            full_species=species,
            domain_rows=domain_by_cluster.get(cluster_id, []),
            expression_rows=expression_by_cluster.get(cluster_id, []),
            expression_available_species=expression_available_species,
        )
        cluster_mappings = mappings_by_cluster.get(cluster_id, [])
        scored_record["orthofinder_orthogroup_ids"] = _string_set(
            str(record["group_id"])
            for record in cluster_mappings
            if record.get("record_type") == "ORTHOGROUP"
        )
        scored_record["orthofinder_hierarchical_group_ids"] = _string_set(
            str(record["group_id"])
            for record in cluster_mappings
            if record.get("record_type") == "HIERARCHICAL_ORTHOGROUP"
        )
        scored.append(scored_record)
    ranked = rank_records(records=scored)
    selected_evolutionary_group_count = apply_evolutionary_group_selection(
        records=ranked,
        structure_group_limit=config.analysis.prioritisation.structure_group_limit,
    )
    tables = stage_root / "tables"
    write_records(
        tsv_path=tables / "computational_prestructure_ranking.tsv",
        parquet_path=tables / "computational_prestructure_ranking.parquet",
        fieldnames=PRESTRUCTURE_FIELDS,
        records=ranked,
    )
    selection_counts = derive_structural_representatives(
        config=config,
        stage_root=stage_root,
    )
    evolutionary_groups, _ = build_evolutionary_group_records(ranked)
    review_rows = [
        {
            "computational_rank": row["computational_rank"],
            "cluster_id": row["cluster_id"],
            "primary_group_id": row["primary_group_id"],
            "prestructure_score": row["prestructure_score"],
            "grant_aligned_stringent_pass": row["grant_aligned_stringent_pass"],
            "computational_structure_selected": row["computational_structure_selected"],
            "review_decision": "PENDING",
            "reviewer": "",
            "review_date": "",
            "review_comments": "",
        }
        for row in ranked
    ]
    write_tsv(tables / "human_review_template.tsv", review_rows, REVIEW_FIELDS)
    write_tsv(
        stage_root / "qc" / "prioritisation_validation.tsv",
        [
            {
                "candidate_cluster_count": len(ranked),
                "mapped_primary_group_count": sum(bool(row["primary_group_id"]) for row in ranked),
                "grant_aligned_stringent_cluster_count": sum(
                    bool(row["grant_aligned_stringent_pass"]) for row in ranked
                ),
                "grant_aligned_stringent_evolutionary_group_count": sum(
                    bool(row["lead_grant_aligned_stringent_pass"])
                    for row in evolutionary_groups
                ),
                "distinct_evolutionary_group_count": selection_counts[
                    "distinct_evolutionary_group_count"
                ],
                "computational_structure_evolutionary_group_count": (
                    selected_evolutionary_group_count
                ),
                "computational_structure_contributing_cluster_count": sum(
                    bool(row["computational_structure_selected"]) for row in ranked
                ),
                "all_member_structural_accession_count": selection_counts[
                    "all_member_structural_accession_count"
                ],
                "selected_structural_representative_count": selection_counts[
                    "selected_structural_representative_count"
                ],
                "score_minimum": min(
                    (float(row["prestructure_score"]) for row in ranked),
                    default=math.nan,
                ),
                "score_maximum": max(
                    (float(row["prestructure_score"]) for row in ranked),
                    default=math.nan,
                ),
                "profile_name": config.analysis.prioritisation.profile_name,
                "interpretation": (
                    "computational recommendation; human review remains pending and is not "
                    "represented as biological approval"
                ),
            }
        ],
        (
            "candidate_cluster_count",
            "mapped_primary_group_count",
            "grant_aligned_stringent_cluster_count",
            "grant_aligned_stringent_evolutionary_group_count",
            "distinct_evolutionary_group_count",
            "computational_structure_evolutionary_group_count",
            "computational_structure_contributing_cluster_count",
            "all_member_structural_accession_count",
            "selected_structural_representative_count",
            "score_minimum",
            "score_maximum",
            "profile_name",
            "interpretation",
        ),
    )
