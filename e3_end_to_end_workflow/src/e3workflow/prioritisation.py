"""Transparent grant-aligned pre-structure prioritisation of E3 candidates."""

from __future__ import annotations

import math
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
    selected_group_members,
)
from e3workflow.production import find_one, split_accessions
from e3workflow.resources import EXPRESSION_RESOURCE_TYPES, read_resource_manifest
from e3workflow.tabular import quote_literal, write_records

PRESTRUCTURE_FIELDS = (
    "computational_rank",
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
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
    "computational_rank",
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "candidate_accession",
    "species_column",
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
    }
    domain_supported_species = {
        str(row["species_column"])
        for row in domain_rows
        if row.get("domain_support_status") == "SUPPORTED" and row.get("species_column")
    }
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


def rank_records(
    *, records: Sequence[dict[str, Any]], structure_group_limit: int
) -> list[dict[str, Any]]:
    """Sort, rank and select pre-structure records deterministically."""
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
        row["computational_structure_selected"] = rank <= structure_group_limit
    return ordered


def run_prestructure_stage(*, config: WorkflowConfig, stage_root: Path) -> None:
    """Integrate discovery, orthology, domain and expression evidence for ranking."""
    candidate_path = find_one(
        root=config.run_root / "03_candidate_evidence",
        name="e3_cluster_candidate_evidence.parquet",
    )
    orthology_root = config.run_root / "05_orthology"
    candidate_mapping = find_one(
        root=orthology_root, name="candidate_membership_mapping.parquet"
    )
    orthogroup_membership = find_one(root=orthology_root, name="orthogroup_membership.parquet")
    hierarchical_membership = find_one(
        root=orthology_root, name="hierarchical_membership.parquet"
    )
    domain_summary = find_one(root=config.run_root / "06_domains", name="domain_summary.parquet")
    expression_summary = find_one(
        root=config.run_root / "07_expression", name="candidate_expression_summary.parquet"
    )
    mapping_rows = candidate_mapping_rows(path=candidate_mapping)
    primary_by_cluster, _ = choose_primary_groups(mapping_rows=mapping_rows)
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
        scored.append(
            score_candidate(
                config=config,
                candidate=candidate,
                primary=primary,
                full_species=species,
                domain_rows=domain_by_cluster.get(cluster_id, []),
                expression_rows=expression_by_cluster.get(cluster_id, []),
                expression_available_species=expression_available_species,
            )
        )
    ranked = rank_records(
        records=scored,
        structure_group_limit=config.analysis.prioritisation.structure_group_limit,
    )
    selected_members = selected_group_members(
        selected=primary_by_cluster,
        orthogroup_membership=orthogroup_membership,
        hierarchical_membership=hierarchical_membership,
        target_species=config.analysis.prioritisation.target_species,
    )
    members_by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for member in selected_members:
        members_by_cluster[str(member["cluster_id"])].append(member)
    tables = stage_root / "tables"
    write_records(
        tsv_path=tables / "computational_prestructure_ranking.tsv",
        parquet_path=tables / "computational_prestructure_ranking.parquet",
        fieldnames=PRESTRUCTURE_FIELDS,
        records=ranked,
    )
    structural_rows = []
    for row in ranked:
        if not row["computational_structure_selected"]:
            continue
        cluster_id = str(row["cluster_id"])
        primary = primary_by_cluster.get(cluster_id)
        if primary is None:
            continue
        relevant = [
            member
            for member in members_by_cluster.get(cluster_id, [])
            if str(member.get("member_accession", "")).strip()
        ]
        for mapping in sorted(
            relevant,
            key=lambda item: (
                str(item.get("species_column", "")),
                str(item["member_accession"]),
            ),
        ):
            structural_rows.append(
                {
                    "computational_rank": row["computational_rank"],
                    "cluster_id": cluster_id,
                    "primary_group_type": primary["record_type"],
                    "primary_group_id": primary["group_id"],
                    "candidate_accession": mapping["member_accession"],
                    "species_column": mapping.get("species_column", ""),
                    "prestructure_score": row["prestructure_score"],
                    "selection_reason": (
                        "target_species_member_of_computationally_selected_primary_group"
                    ),
                }
            )
    unique_structural = {
        (row["cluster_id"], row["candidate_accession"]): row for row in structural_rows
    }
    write_records(
        tsv_path=tables / "structural_analysis_accessions.tsv",
        parquet_path=tables / "structural_analysis_accessions.parquet",
        fieldnames=STRUCTURE_ACCESSION_FIELDS,
        records=[unique_structural[key] for key in sorted(unique_structural)],
    )
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
                "grant_aligned_stringent_pass_count": sum(
                    bool(row["grant_aligned_stringent_pass"]) for row in ranked
                ),
                "computational_structure_group_count": sum(
                    bool(row["computational_structure_selected"]) for row in ranked
                ),
                "structural_accession_count": len(unique_structural),
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
            "grant_aligned_stringent_pass_count",
            "computational_structure_group_count",
            "structural_accession_count",
            "score_minimum",
            "score_maximum",
            "profile_name",
            "interpretation",
        ),
    )
