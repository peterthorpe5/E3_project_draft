"""Final evidence integration, prioritisation and application hand-off."""

from __future__ import annotations

import html
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from e3workflow import __version__
from e3workflow.config import WorkflowConfig
from e3workflow.errors import StageError
from e3workflow.excel_reporting import create_final_results_workbook
from e3workflow.io_utils import (
    atomic_write_json,
    inventory_files,
    sha256_file,
    utc_now,
    write_tsv,
)
from e3workflow.production import find_one, find_orthology_table
from e3workflow.tabular import quote_identifier, quote_literal

LOGGER = logging.getLogger("e3workflow.integration")

FINAL_FIELDS = (
    "final_rank",
    "stringent_rank",
    "structurally_supported_rank",
    "recommendation_status",
    "grant_aligned_prediction_status",
    "cluster_id",
    "primary_group_type",
    "primary_group_id",
    "orthofinder_orthogroup_ids",
    "orthofinder_hierarchical_group_ids",
    "candidate_accessions",
    "prestructure_score",
    "ligandability_score",
    "pocket_conservation_score",
    "three_dimensional_pocket_score",
    "three_dimensional_position_status",
    "three_dimensional_alignment_status",
    "mean_minimum_tm_score",
    "mean_pocket_overlap_fraction",
    "median_centroid_distance_angstrom",
    "mean_structural_residue_match_fraction",
    "mean_structural_residue_identity_fraction",
    "mean_structural_chemical_group_conservation",
    "structural_score",
    "final_score",
    "target_species_fraction",
    "mandatory_species_fraction",
    "domain_species_fraction",
    "expression_species_fraction",
    "structural_species_fraction",
    "minimum_druggability_score",
    "mean_pairwise_region_overlap",
    "mean_chemical_group_conservation",
    "mean_pocket_plddt_fraction",
    "predictor_agreement_fraction",
    "grant_aligned_prestructure_pass",
    "grant_aligned_base_pass",
    "grant_aligned_final_pass",
    "conservation_status",
    "inclusion_reasons",
    "exclusion_reasons",
    "missing_evidence",
    "structural_exclusion_reasons",
    "profile_name",
    "interpretation",
)

MASTER_PARQUET_NAME = "e3_candidate_master_results.parquet"

RESOURCE_SECTIONS = {
    "candidate_evidence": ("candidate_discovery", "candidate"),
    "candidate_orthology": ("orthology", "candidate_group_mapping"),
    "candidate_group_member_sequences": ("orthology", "group_member"),
    "orthogroup_membership": ("orthology", "group_member"),
    "hierarchical_membership": ("orthology", "group_member"),
    "candidate_orthology_summary": ("orthology", "candidate"),
    "domain_hits": ("domains", "member_domain_hit"),
    "domain_summary": ("domains", "candidate_group_member"),
    "candidate_identifier_aliases": ("expression", "candidate_group_member"),
    "candidate_expression_mapping": ("expression", "candidate_group_member"),
    "candidate_expression_summary": ("expression", "candidate_group_member"),
    "candidate_expression_context_summary": (
        "expression",
        "candidate_group_member_context",
    ),
    "prestructure_ranking": ("prioritisation", "candidate"),
    "evolutionary_candidate_group_ranking": (
        "prioritisation",
        "evolutionary_candidate_group",
    ),
    "evolutionary_group_cluster_contributors": (
        "prioritisation",
        "evolutionary_group_cluster_contributor",
    ),
    "structural_analysis_accessions": ("ligandability", "candidate_group_member"),
    "structural_representative_selection_audit": (
        "ligandability",
        "candidate_group_member",
    ),
    "selected_pockets": ("ligandability", "pocket"),
    "ranked_member_pockets": ("ligandability", "ranked_pocket"),
    "structural_prediction_status": ("ligandability", "candidate_group_member"),
    "pocket_conservation_summary": ("pocket_conservation", "candidate"),
    "pocket_conservation_members": ("pocket_conservation", "candidate_group_member"),
    "pocket_sequence_coordinates": ("pocket_conservation", "pocket_residue"),
    "ranked_pocket_sequence_coordinates": (
        "pocket_conservation",
        "ranked_pocket_residue",
    ),
    "structural_alignments": ("structural_alignment", "structure_pair"),
    "structural_pocket_comparisons": ("structural_alignment", "structure_pair"),
    "structural_pocket_residue_matches": ("structural_alignment", "pocket_residue_pair"),
    "structural_alignment_summary": ("structural_alignment", "candidate"),
    "structural_pocket_sensitivity_comparisons": (
        "structural_alignment_sensitivity",
        "structure_pocket_pair",
    ),
    "structural_pocket_sensitivity_residue_matches": (
        "structural_alignment_sensitivity",
        "pocket_residue_pair",
    ),
    "structural_pocket_sensitivity_member_summary": (
        "structural_alignment_sensitivity",
        "candidate_group_member",
    ),
    "structural_pocket_sensitivity_group_summary": (
        "structural_alignment_sensitivity",
        "evolutionary_candidate_group",
    ),
    "final_candidate_prioritisation": ("prioritisation", "candidate"),
    "candidate_master_results": ("prioritisation", "candidate"),
    "final_evolutionary_candidate_prioritisation": (
        "final_recommendations",
        "evolutionary_candidate_group",
    ),
    "top_20_computational_review_shortlist": (
        "final_recommendations",
        "evolutionary_candidate_group",
    ),
    "top_computational_review_shortlist": (
        "final_recommendations",
        "evolutionary_candidate_group",
    ),
    "gate_sensitivity_detail": (
        "final_recommendations",
        "scenario_by_evolutionary_candidate_group",
    ),
    "gate_sensitivity_summary": (
        "final_recommendations",
        "scenario",
    ),
    "grant_aligned_predicted_candidates": (
        "final_recommendations",
        "evolutionary_candidate_group",
    ),
    "final_evolutionary_group_cluster_contributors": (
        "final_recommendations",
        "evolutionary_group_cluster_contributor",
    ),
    "final_candidate_exclusion_audit": (
        "final_recommendations",
        "evolutionary_candidate_group",
    ),
    "resource_metadata": ("provenance", "release"),
    "resource_relation_catalog": ("provenance", "relation"),
}


def _final_query(
    config: WorkflowConfig,
    prestructure: Path,
    conservation: Path,
    alignment_summary: Path | None,
) -> str:
    """Return the final transparent scoring query."""
    settings = config.analysis.prioritisation
    ligandability = config.analysis.ligandability
    structural_alignment = config.analysis.structural_alignment
    alignment_relation = (
        f"read_parquet({quote_literal(alignment_summary)})"
        if alignment_summary is not None
        else (
            "(SELECT NULL::VARCHAR AS cluster_id, NULL::VARCHAR AS primary_group_type, "
            "NULL::VARCHAR AS primary_group_id, NULL::VARCHAR AS alignment_status, "
            "NULL::VARCHAR AS position_alignment_status, "
            "NULL::DOUBLE AS three_dimensional_pocket_score, "
            "NULL::DOUBLE AS mean_minimum_tm_score, "
            "NULL::DOUBLE AS mean_pocket_overlap_fraction, "
            "NULL::DOUBLE AS median_centroid_distance_angstrom, "
            "NULL::DOUBLE AS mean_structural_residue_match_fraction, "
            "NULL::DOUBLE AS mean_structural_residue_identity_fraction, "
            "NULL::DOUBLE AS mean_structural_chemical_group_conservation WHERE false)"
        )
    )
    use_alignment = "true" if structural_alignment.use_for_prioritisation else "false"
    require_alignment = (
        "true"
        if structural_alignment.require_for_final_recommendation
        else "false"
    )
    return (
        "WITH pre AS (SELECT * FROM read_parquet("
        f"{quote_literal(prestructure)})), pockets AS (SELECT * FROM read_parquet("
        f"{quote_literal(conservation)})), alignments AS (SELECT * FROM "
        f"{alignment_relation}), joined AS (SELECT p.*, "
        "COALESCE(CAST(c.structured_species_count AS BIGINT), 0::BIGINT) AS "
        "structured_species_count, "
        "COALESCE(CAST(c.conserved_component_species_count AS BIGINT), 0::BIGINT) AS "
        "conserved_component_species_count, "
        "COALESCE(CAST(c.conserved_component_fraction AS DOUBLE), 0.0::DOUBLE) AS "
        "conserved_component_fraction, "
        "COALESCE(CAST(c.mean_pairwise_region_overlap AS DOUBLE), 0.0::DOUBLE) AS "
        "mean_pairwise_region_overlap, "
        "COALESCE(CAST(c.mean_chemical_group_conservation AS DOUBLE), 0.0::DOUBLE) AS "
        "mean_chemical_group_conservation, "
        "COALESCE(CAST(c.minimum_druggability_score AS DOUBLE), 0.0::DOUBLE) AS "
        "minimum_druggability_score, "
        "COALESCE(CAST(c.mean_druggability_score AS DOUBLE), 0.0::DOUBLE) AS "
        "mean_druggability_score, "
        "COALESCE(CAST(c.mean_pocket_plddt_fraction AS DOUBLE), 0.0::DOUBLE) AS "
        "mean_pocket_plddt_fraction, "
        "COALESCE(CAST(c.predictor_agreement_fraction AS DOUBLE), 0.0::DOUBLE) AS "
        "predictor_agreement_fraction, "
        "COALESCE(CAST(c.conserved_pocket_score AS DOUBLE), 0.0::DOUBLE) AS "
        "pocket_conservation_score, COALESCE(CAST(c.conservation_status AS VARCHAR), "
        "'NO_STRUCTURAL_EVIDENCE') AS conservation_status, "
        "COALESCE(CAST(a.three_dimensional_pocket_score AS DOUBLE), 0.0::DOUBLE) AS "
        "three_dimensional_pocket_score, "
        "COALESCE(CAST(a.alignment_status AS VARCHAR), 'NOT_ASSESSED') AS "
        "three_dimensional_alignment_status, "
        "COALESCE(CAST(a.position_alignment_status AS VARCHAR), 'NOT_ASSESSED') AS "
        "three_dimensional_position_status, "
        "COALESCE(CAST(a.mean_minimum_tm_score AS DOUBLE), 0.0::DOUBLE) AS "
        "mean_minimum_tm_score, "
        "COALESCE(CAST(a.mean_pocket_overlap_fraction AS DOUBLE), 0.0::DOUBLE) AS "
        "mean_pocket_overlap_fraction, "
        "CAST(a.median_centroid_distance_angstrom AS DOUBLE) AS "
        "median_centroid_distance_angstrom, "
        "CAST(a.mean_structural_residue_match_fraction AS DOUBLE) AS "
        "mean_structural_residue_match_fraction, "
        "CAST(a.mean_structural_residue_identity_fraction AS DOUBLE) AS "
        "mean_structural_residue_identity_fraction, "
        "CAST(a.mean_structural_chemical_group_conservation AS DOUBLE) AS "
        "mean_structural_chemical_group_conservation, "
        "COALESCE(CAST(c.all_assessed_members_pass_druggability AS BOOLEAN), false) AS "
        "all_assessed_members_pass_druggability, "
        "COALESCE(CAST(c.all_assessed_members_pass_mapping AS BOOLEAN), false) AS "
        "all_assessed_members_pass_mapping FROM pre p LEFT JOIN pockets c "
        "USING (cluster_id, primary_group_type, primary_group_id) LEFT JOIN alignments a "
        "USING (cluster_id, primary_group_type, primary_group_id)), components AS (SELECT *, "
        "(minimum_druggability_score + mean_pocket_plddt_fraction + "
        "CAST(all_assessed_members_pass_mapping AS INTEGER) + predictor_agreement_fraction) / 4.0 "
        "AS ligandability_score, conserved_component_species_count::DOUBLE / "
        "NULLIF(target_species_total, 0) AS structural_species_fraction FROM joined), scores AS ("
        "SELECT *, ligandability_score * "
        f"{settings.ligandability_weight} + pocket_conservation_score * "
        f"{settings.pocket_conservation_weight} AS base_structural_score FROM components), "
        "refined_scores AS (SELECT *, CASE WHEN "
        f"{use_alignment} AND three_dimensional_alignment_status <> 'NOT_ASSESSED' THEN "
        "base_structural_score * "
        f"{1.0 - structural_alignment.prioritisation_weight} + "
        "three_dimensional_pocket_score * "
        f"{structural_alignment.prioritisation_weight} ELSE base_structural_score END AS "
        "structural_score FROM scores), base_decisions AS (SELECT *, prestructure_score * "
        f"{settings.prestructure_final_weight} + structural_score * "
        f"{settings.structural_final_weight} AS final_score, "
        "CAST(grant_aligned_stringent_pass AS BOOLEAN) AS grant_aligned_prestructure_pass, "
        "CASE WHEN CAST(grant_aligned_stringent_pass AS BOOLEAN) AND conservation_status = "
        "'CONSERVED_REGION_SUPPORTED' AND minimum_druggability_score >= "
        f"{ligandability.minimum_druggability_score} AND all_assessed_members_pass_druggability "
        "AND all_assessed_members_pass_mapping AND structural_species_fraction >= "
        f"{settings.minimum_structural_species_fraction} THEN true ELSE false END AS "
        "grant_aligned_base_pass FROM refined_scores), decisions AS (SELECT *, "
        "CASE WHEN grant_aligned_base_pass AND (NOT "
        f"{require_alignment} OR three_dimensional_alignment_status = "
        "'CONSERVED_3D_POCKET_SUPPORTED') THEN true ELSE false END AS "
        "grant_aligned_final_pass, concat_ws(';', CASE WHEN conservation_status <> "
        "'CONSERVED_REGION_SUPPORTED' THEN 'conserved_pocket_region_not_supported' END, CASE "
        "WHEN minimum_druggability_score < "
        f"{ligandability.minimum_druggability_score} THEN 'minimum_druggability_below_threshold' "
        "END, CASE WHEN NOT all_assessed_members_pass_druggability THEN "
        "'not_all_assessed_members_pass_druggability' END, CASE WHEN NOT "
        "all_assessed_members_pass_mapping THEN 'not_all_assessed_members_pass_mapping' END, "
        "CASE WHEN structural_species_fraction < "
        f"{settings.minimum_structural_species_fraction} THEN "
        "'structural_species_fraction_below_threshold' END, CASE WHEN "
        f"{require_alignment} AND three_dimensional_alignment_status <> "
        "'CONSERVED_3D_POCKET_SUPPORTED' THEN 'three_dimensional_pocket_not_supported' END) AS "
        "structural_exclusion_reasons FROM base_decisions), ranked AS (SELECT *, "
        "row_number() OVER (ORDER BY "
        "grant_aligned_base_pass DESC, final_score DESC, evidence_completeness_fraction DESC, "
        "cluster_id) AS final_rank, CASE WHEN grant_aligned_base_pass THEN row_number() OVER "
        "(PARTITION BY grant_aligned_base_pass ORDER BY final_score DESC, cluster_id) END AS "
        "stringent_rank, CASE WHEN grant_aligned_final_pass THEN row_number() OVER "
        "(PARTITION BY grant_aligned_final_pass ORDER BY final_score DESC, cluster_id) END AS "
        "structurally_supported_rank FROM decisions) SELECT final_rank, stringent_rank, "
        "structurally_supported_rank, CASE WHEN "
        "grant_aligned_final_pass AND structurally_supported_rank <= "
        f"{settings.final_candidate_limit} THEN 'PRIORITY_RECOMMENDATION' WHEN "
        "grant_aligned_final_pass THEN 'STRINGENT_PASS_OUTSIDE_TOP_LIMIT' ELSE "
        "'FURTHER_EVIDENCE_OR_REVIEW_REQUIRED' END AS recommendation_status, CASE WHEN "
        "grant_aligned_final_pass THEN 'GRANT_ALIGNED_PREDICTED_CANDIDATE' WHEN "
        "three_dimensional_alignment_status = 'NOT_ASSESSED' THEN "
        "'STRUCTURAL_EVIDENCE_NOT_ASSESSED' ELSE 'NOT_GRANT_ALIGNED_PREDICTED_CANDIDATE' END AS "
        "grant_aligned_prediction_status, cluster_id, "
        "primary_group_type, primary_group_id, orthofinder_orthogroup_ids, "
        "orthofinder_hierarchical_group_ids, candidate_accessions, prestructure_score, "
        "ligandability_score, pocket_conservation_score, three_dimensional_pocket_score, "
        "three_dimensional_position_status, three_dimensional_alignment_status, "
        "mean_minimum_tm_score, mean_pocket_overlap_fraction, "
        "median_centroid_distance_angstrom, mean_structural_residue_match_fraction, "
        "mean_structural_residue_identity_fraction, "
        "mean_structural_chemical_group_conservation, structural_score, "
        "final_score, "
        "target_species_fraction, mandatory_species_fraction, domain_species_fraction, "
        "expression_species_fraction, structural_species_fraction, minimum_druggability_score, "
        "mean_pairwise_region_overlap, mean_chemical_group_conservation, "
        "mean_pocket_plddt_fraction, predictor_agreement_fraction, "
        "all_assessed_members_pass_druggability, "
        "all_assessed_members_pass_mapping, "
        "grant_aligned_prestructure_pass, "
        "grant_aligned_base_pass, grant_aligned_final_pass, conservation_status, "
        "inclusion_reasons, exclusion_reasons, "
        "missing_evidence, structural_exclusion_reasons, profile_name, "
        "'computational evidence prioritisation; experimental E3 activity, binding and "
        "degradation remain unvalidated' AS interpretation FROM ranked ORDER BY final_rank"
    )


def _copy_query_tsv(
    *, connection: duckdb.DuckDBPyConnection, query: str, path: Path
) -> None:
    """Atomically publish a DuckDB query as tab-separated text."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.unlink(missing_ok=True)
    try:
        connection.execute(
            f"COPY ({query}) TO {quote_literal(temporary)} "
            "(FORMAT CSV, DELIMITER '\t', HEADER TRUE, QUOTE '" + '"' + "')"
        )
        temporary.replace(destination)
    except duckdb.Error as exc:
        temporary.unlink(missing_ok=True)
        raise StageError(f"Could not publish TSV query {destination}: {exc}") from exc


def _copy_query_parquet(
    *,
    connection: duckdb.DuckDBPyConnection,
    query: str,
    path: Path,
) -> None:
    """Atomically publish a DuckDB query as compressed Parquet."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.unlink(missing_ok=True)
    try:
        connection.execute(
            f"COPY ({query}) TO {quote_literal(temporary)} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        temporary.replace(destination)
    except duckdb.Error as exc:
        temporary.unlink(missing_ok=True)
        raise StageError(f"Could not publish Parquet query {destination}: {exc}") from exc


def _create_table_from_parquet(
    *,
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    path: Path,
) -> None:
    """Materialise one Parquet authority in the integrated DuckDB."""
    connection.execute(
        f"CREATE TABLE {quote_identifier(table_name)} AS SELECT * FROM read_parquet("
        f"{quote_literal(path)})"
    )


def _relation_columns(
    *,
    connection: duckdb.DuckDBPyConnection,
    relation: str,
) -> list[str]:
    """Return validated columns for one materialised DuckDB relation."""
    rows = connection.execute(
        f"DESCRIBE SELECT * FROM {quote_identifier(relation)}"
    ).fetchall()
    columns = [str(row[0]) for row in rows]
    for column in columns:
        quote_identifier(column)
    return columns


def _relation_exists(
    *,
    connection: duckdb.DuckDBPyConnection,
    relation: str,
) -> bool:
    """Return whether one table or view exists in the current DuckDB."""
    row = connection.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = ?",
        [relation],
    ).fetchone()
    return bool(row and int(row[0]) == 1)


def _candidate_master_query(
    *,
    connection: duckdb.DuckDBPyConnection,
) -> str:
    """Build one wide, candidate-level result without flattening detail tables.

    The master relation contains every final prioritisation field, all additional
    candidate-level pre-structure fields and every discovery-evidence column.
    Discovery fields are prefixed to make schema growth collision-safe. Detailed
    one-to-many evidence remains in the normalised DuckDB relations.
    """
    final_columns = set(
        _relation_columns(
            connection=connection,
            relation="final_candidate_prioritisation",
        )
    )
    prestructure_columns = _relation_columns(
        connection=connection,
        relation="prestructure_ranking",
    )
    discovery_columns = _relation_columns(
        connection=connection,
        relation="candidate_evidence",
    )
    additional_prestructure = [
        column
        for column in prestructure_columns
        if column not in final_columns and column != "cluster_id"
    ]
    discovery_evidence = [
        column for column in discovery_columns if column != "representative_id"
    ]
    selections = ["final.*"]
    selections.extend(
        f"pre.{quote_identifier(column)} AS {quote_identifier(column)}"
        for column in additional_prestructure
    )
    selections.extend(
        "discovery."
        f"{quote_identifier(column)} AS {quote_identifier(f'discovery_{column}')}"
        for column in discovery_evidence
    )
    selections.extend(
        (
            "members.orthofinder_group_member_count",
            "members.orthofinder_group_species_count",
            "domains.domain_evidence_row_count",
            "expression.expression_evidence_row_count",
            "pockets.selected_pocket_count",
            "pocket_members.pocket_conservation_member_count",
        )
    )
    return (
        "SELECT "
        + ", ".join(selections)
        + " FROM final_candidate_prioritisation AS final "
        "LEFT JOIN prestructure_ranking AS pre USING (cluster_id) "
        "LEFT JOIN candidate_evidence AS discovery "
        "ON discovery.representative_id = final.cluster_id "
        "LEFT JOIN (SELECT cluster_id, COUNT(*) AS orthofinder_group_member_count, "
        "COUNT(DISTINCT species) AS orthofinder_group_species_count "
        "FROM candidate_group_member_sequences GROUP BY cluster_id) AS members "
        "USING (cluster_id) "
        "LEFT JOIN (SELECT cluster_id, COUNT(*) AS domain_evidence_row_count "
        "FROM domain_summary GROUP BY cluster_id) AS domains USING (cluster_id) "
        "LEFT JOIN (SELECT cluster_id, COUNT(*) AS expression_evidence_row_count "
        "FROM candidate_expression_summary GROUP BY cluster_id) AS expression "
        "USING (cluster_id) "
        "LEFT JOIN (SELECT cluster_id, COUNT(*) AS selected_pocket_count "
        "FROM selected_pockets GROUP BY cluster_id) AS pockets USING (cluster_id) "
        "LEFT JOIN (SELECT cluster_id, COUNT(*) AS pocket_conservation_member_count "
        "FROM pocket_conservation_members GROUP BY cluster_id) AS pocket_members "
        "USING (cluster_id) ORDER BY final.final_rank"
    )


def _final_evolutionary_query(
    *,
    connection: duckdb.DuckDBPyConnection,
) -> str:
    """Build one decision row per distinct evolutionary candidate group."""
    group_columns = _relation_columns(
        connection=connection,
        relation="evolutionary_candidate_group_ranking",
    )
    master_columns = _relation_columns(
        connection=connection,
        relation="candidate_master_results",
    )
    selections = [
        "row_number() OVER (ORDER BY master.final_rank, "
        "groups.evolutionary_group_rank, groups.evolutionary_group_key) "
        "AS final_evolutionary_rank"
    ]
    has_sensitivity = _relation_exists(
        connection=connection,
        relation="structural_pocket_sensitivity_group_summary",
    )
    if has_sensitivity:
        selections.extend(
            (
                "sensitivity.member_pocket_top_k",
                "sensitivity.sensitivity_group_position_support_fraction",
                "sensitivity.sensitivity_group_support_fraction",
                "sensitivity.position_rescued_accession_count",
                "sensitivity.conservation_rescued_accession_count",
                "sensitivity.sensitivity_position_alignment_status",
                "sensitivity.sensitivity_alignment_status",
            )
        )
    else:
        selections.extend(
            (
                "CAST(NULL AS BIGINT) AS member_pocket_top_k",
                "CAST(NULL AS DOUBLE) AS "
                "sensitivity_group_position_support_fraction",
                "CAST(NULL AS DOUBLE) AS sensitivity_group_support_fraction",
                "CAST(0 AS BIGINT) AS position_rescued_accession_count",
                "CAST(0 AS BIGINT) AS conservation_rescued_accession_count",
                "'NOT_ASSESSED' AS sensitivity_position_alignment_status",
                "'NOT_ASSESSED' AS sensitivity_alignment_status",
            )
        )
    for column in group_columns:
        output_name = (
            "prestructure_evolutionary_group_rank"
            if column == "evolutionary_group_rank"
            else column
        )
        selections.append(
            f"groups.{quote_identifier(column)} AS {quote_identifier(output_name)}"
        )
    excluded_master = {
        "cluster_id",
        "primary_group_type",
        "primary_group_id",
    }
    group_output_names = {
        (
            "prestructure_evolutionary_group_rank"
            if column == "evolutionary_group_rank"
            else column
        )
        for column in group_columns
    }
    for column in master_columns:
        if column in excluded_master or column in group_output_names:
            continue
        selections.append(f"master.{quote_identifier(column)}")
    sensitivity_join = (
        " LEFT JOIN structural_pocket_sensitivity_group_summary AS sensitivity "
        "ON sensitivity.cluster_id = groups.lead_cluster_id "
        "AND sensitivity.primary_group_type = groups.primary_group_type "
        "AND sensitivity.primary_group_id = groups.primary_group_id "
        if has_sensitivity
        else ""
    )
    return (
        "SELECT "
        + ", ".join(selections)
        + " FROM evolutionary_candidate_group_ranking AS groups "
        + "JOIN candidate_master_results AS master "
        + "ON master.cluster_id = groups.lead_cluster_id "
        + sensitivity_join
        + "ORDER BY final_evolutionary_rank"
    )


def _final_contributor_query(
    *,
    connection: duckdb.DuckDBPyConnection,
) -> str:
    """Build final cluster detail without conflating contributor and group rows."""
    contributor_columns = _relation_columns(
        connection=connection,
        relation="evolutionary_group_cluster_contributors",
    )
    master_columns = _relation_columns(
        connection=connection,
        relation="candidate_master_results",
    )
    selections = [
        f"contributors.{quote_identifier(column)}"
        for column in contributor_columns
    ]
    contributor_set = set(contributor_columns)
    for column in master_columns:
        if column in contributor_set:
            continue
        selections.append(
            f"master.{quote_identifier(column)} AS "
            f"{quote_identifier(f'final_{column}')}"
        )
    return (
        "SELECT "
        + ", ".join(selections)
        + " FROM evolutionary_group_cluster_contributors AS contributors "
        "LEFT JOIN candidate_master_results AS master USING (cluster_id) "
        "ORDER BY contributors.evolutionary_group_rank, "
        "contributors.computational_rank, contributors.cluster_id"
    )


def _create_gate_sensitivity_tables(
    *,
    connection: duckdb.DuckDBPyConnection,
    config: WorkflowConfig,
) -> None:
    """Materialise named exploratory alternatives to the immutable strict gates.

    Args:
        connection: Open integrated-resource DuckDB connection.
        config: Validated workflow configuration supplying release thresholds.
    """
    species_threshold = (
        config.analysis.prioritisation.minimum_structural_species_fraction
    )
    connection.execute(
        "CREATE TEMP TABLE pocket_druggability_fraction AS SELECT "
        "cluster_id, primary_group_type, primary_group_id, "
        "AVG(CAST(passes_druggability_threshold AS INTEGER)) "
        "AS druggability_pass_fraction "
        "FROM selected_pockets GROUP BY ALL"
    )
    common_relaxed = (
        "final.grant_aligned_prestructure_pass "
        "AND final.conservation_status = 'CONSERVED_REGION_SUPPORTED' "
        "AND final.all_assessed_members_pass_mapping "
        f"AND final.structural_species_fraction >= {species_threshold} "
        "AND pockets.druggability_pass_fraction >= 0.75"
    )
    connection.execute(
        "CREATE TABLE gate_sensitivity_detail AS "
        "SELECT 'STRICT_PRIMARY' AS scenario_id, "
        "'Published gates: all assessed members pass druggability and rank-one "
        "pockets pass the 3D conservation test' AS scenario_definition, "
        "final.final_evolutionary_rank, final.evolutionary_group_key, "
        "final.primary_group_type, final.primary_group_id, "
        "pockets.druggability_pass_fraction, "
        "final.three_dimensional_alignment_status AS structural_status, "
        "final.grant_aligned_final_pass AS scenario_pass "
        "FROM final_evolutionary_candidate_prioritisation AS final "
        "LEFT JOIN pocket_druggability_fraction AS pockets "
        "ON pockets.cluster_id = final.lead_cluster_id "
        "AND pockets.primary_group_type = final.primary_group_type "
        "AND pockets.primary_group_id = final.primary_group_id "
        "UNION ALL SELECT 'DRUGGABILITY_75_PERCENT', "
        "'At least 75% of assessed members pass druggability; strict rank-one "
        "3D conservation retained', final.final_evolutionary_rank, "
        "final.evolutionary_group_key, final.primary_group_type, "
        "final.primary_group_id, pockets.druggability_pass_fraction, "
        "final.three_dimensional_alignment_status, "
        f"COALESCE(({common_relaxed} AND "
        "final.three_dimensional_alignment_status = "
        "'CONSERVED_3D_POCKET_SUPPORTED'), false) "
        "FROM final_evolutionary_candidate_prioritisation AS final "
        "LEFT JOIN pocket_druggability_fraction AS pockets "
        "ON pockets.cluster_id = final.lead_cluster_id "
        "AND pockets.primary_group_type = final.primary_group_type "
        "AND pockets.primary_group_id = final.primary_group_id "
        "UNION ALL SELECT 'TOP_K_POCKET', "
        "'Published druggability gates retained; both aligners must support the "
        "same top-k member pocket', final.final_evolutionary_rank, "
        "final.evolutionary_group_key, final.primary_group_type, "
        "final.primary_group_id, pockets.druggability_pass_fraction, "
        "final.sensitivity_alignment_status, "
        "COALESCE((final.grant_aligned_base_pass AND "
        "final.sensitivity_alignment_status = "
        "'CONSERVED_3D_POCKET_SUPPORTED'), false) "
        "FROM final_evolutionary_candidate_prioritisation AS final "
        "LEFT JOIN pocket_druggability_fraction AS pockets "
        "ON pockets.cluster_id = final.lead_cluster_id "
        "AND pockets.primary_group_type = final.primary_group_type "
        "AND pockets.primary_group_id = final.primary_group_id "
        "UNION ALL SELECT 'DRUGGABILITY_75_PERCENT_PLUS_TOP_K', "
        "'At least 75% pass druggability and both aligners support the same top-k "
        "member pocket', final.final_evolutionary_rank, "
        "final.evolutionary_group_key, final.primary_group_type, "
        "final.primary_group_id, pockets.druggability_pass_fraction, "
        "final.sensitivity_alignment_status, "
        f"COALESCE(({common_relaxed} AND "
        "final.sensitivity_alignment_status = "
        "'CONSERVED_3D_POCKET_SUPPORTED'), false) "
        "FROM final_evolutionary_candidate_prioritisation AS final "
        "LEFT JOIN pocket_druggability_fraction AS pockets "
        "ON pockets.cluster_id = final.lead_cluster_id "
        "AND pockets.primary_group_type = final.primary_group_type "
        "AND pockets.primary_group_id = final.primary_group_id"
    )
    connection.execute(
        "CREATE TABLE gate_sensitivity_summary AS SELECT scenario_id, "
        "MIN(scenario_definition) AS scenario_definition, "
        "COUNT(*) AS evolutionary_group_count, "
        "SUM(CAST(scenario_pass AS INTEGER)) AS passing_group_count "
        "FROM gate_sensitivity_detail GROUP BY scenario_id ORDER BY scenario_id"
    )


def _write_resource_relation_catalog(
    *,
    connection: duckdb.DuckDBPyConnection,
    sources: Sequence[tuple[str, Path]],
) -> None:
    """Materialise relation purpose, granularity and source provenance."""
    connection.execute(
        "CREATE TABLE resource_relation_catalog ("
        "relation_name VARCHAR, app_section VARCHAR, row_granularity VARCHAR, "
        "source_parquet VARCHAR)"
    )
    records = []
    for relation_name, source_path in sources:
        section, granularity = RESOURCE_SECTIONS.get(
            relation_name,
            ("other", "unspecified"),
        )
        records.append(
            (
                relation_name,
                section,
                granularity,
                str(source_path),
            )
        )
    for relation_name in (
        "final_candidate_prioritisation",
        "candidate_master_results",
        "final_evolutionary_candidate_prioritisation",
        "top_20_computational_review_shortlist",
        "top_computational_review_shortlist",
        "gate_sensitivity_detail",
        "gate_sensitivity_summary",
        "grant_aligned_predicted_candidates",
        "final_evolutionary_group_cluster_contributors",
        "final_candidate_exclusion_audit",
        "resource_metadata",
        "resource_relation_catalog",
    ):
        section, granularity = RESOURCE_SECTIONS[relation_name]
        records.append((relation_name, section, granularity, "generated_in_stage_10"))
    connection.executemany(
        "INSERT INTO resource_relation_catalog VALUES (?, ?, ?, ?)",
        records,
    )


def _resource_tables(config: WorkflowConfig) -> list[tuple[str, Path]]:
    """Resolve the completed workflow authorities included in the final database."""
    roots_and_names = (
        ("candidate_evidence", "03_candidate_evidence", "e3_cluster_candidate_evidence.parquet"),
        ("candidate_orthology", "05_orthology", "candidate_membership_mapping.parquet"),
        (
            "candidate_group_member_sequences",
            "05_orthology",
            "candidate_group_member_sequences.parquet",
        ),
        ("orthogroup_membership", "05_orthology", "orthogroup_membership.parquet"),
        ("hierarchical_membership", "05_orthology", "hierarchical_membership.parquet"),
        (
            "candidate_orthology_summary",
            "05_orthology",
            "candidate_cluster_orthology_summary.parquet",
        ),
        ("domain_hits", "06_domains", "domain_hits.parquet"),
        ("domain_summary", "06_domains", "domain_summary.parquet"),
        ("candidate_identifier_aliases", "07_expression", "candidate_identifier_aliases.parquet"),
        ("candidate_expression_mapping", "07_expression", "candidate_expression_mapping.parquet"),
        ("candidate_expression_summary", "07_expression", "candidate_expression_summary.parquet"),
        (
            "candidate_expression_context_summary",
            "07_expression",
            "candidate_expression_context_summary.parquet",
        ),
        ("prestructure_ranking", "08_shortlist_gate", "computational_prestructure_ranking.parquet"),
        (
            "evolutionary_candidate_group_ranking",
            "08_shortlist_gate",
            "evolutionary_candidate_group_ranking.parquet",
        ),
        (
            "evolutionary_group_cluster_contributors",
            "08_shortlist_gate",
            "evolutionary_group_cluster_contributors.parquet",
        ),
        (
            "structural_analysis_accessions",
            "08_shortlist_gate",
            "structural_analysis_accessions.parquet",
        ),
        (
            "structural_representative_selection_audit",
            "08_shortlist_gate",
            "structural_representative_selection_audit.parquet",
        ),
        ("selected_pockets", "09_ligandability", "selected_pockets.parquet"),
        (
            "ranked_member_pockets",
            "09_ligandability",
            "ranked_member_pockets.parquet",
        ),
        (
            "structural_prediction_status",
            "09_ligandability",
            "structural_prediction_status.parquet",
        ),
        ("pocket_conservation_summary", "09_ligandability", "pocket_conservation_summary.parquet"),
        ("pocket_conservation_members", "09_ligandability", "pocket_conservation_members.parquet"),
        (
            "pocket_sequence_coordinates",
            "09_ligandability",
            "pocket_sequence_coordinates.parquet",
        ),
        (
            "ranked_pocket_sequence_coordinates",
            "09_ligandability",
            "ranked_pocket_sequence_coordinates.parquet",
        ),
    )
    tables = []
    optional_legacy_relations = {
        "ranked_member_pockets",
        "ranked_pocket_sequence_coordinates",
        "candidate_expression_context_summary",
    }
    for table_name, stage_name, filename in roots_and_names:
        stage_root = config.run_root / stage_name
        try:
            source = (
                find_orthology_table(root=stage_root, name=filename)
                if stage_name == "05_orthology"
                else find_one(root=stage_root, name=filename)
            )
        except StageError:
            if table_name not in optional_legacy_relations:
                raise
            LOGGER.warning(
                "Optional relation is unavailable in a legacy result: %s",
                table_name,
            )
            continue
        tables.append((table_name, source))
    if config.stage("09b_structural_alignment").enabled:
        structural_root = config.run_root / "09b_structural_alignment"
        required_structural = (
            ("structural_alignments", "structural_alignments.parquet"),
            ("structural_pocket_comparisons", "pocket_comparisons.parquet"),
            (
                "structural_pocket_residue_matches",
                "pocket_residue_matches.parquet",
            ),
            (
                "structural_alignment_summary",
                "structural_alignment_summary.parquet",
            ),
        )
        for table_name, filename in required_structural:
            tables.append(
                (
                    table_name,
                    find_one(root=structural_root, name=filename),
                )
            )
        optional_structural = (
            "structural_pocket_sensitivity_comparisons",
            "structural_pocket_sensitivity_residue_matches",
            "structural_pocket_sensitivity_member_summary",
            "structural_pocket_sensitivity_group_summary",
        )
        for table_name in optional_structural:
            filename = table_name + ".parquet"
            matches = sorted(structural_root.rglob(filename))
            if len(matches) > 1:
                raise StageError(
                    f"Expected at most one {filename!r} below "
                    f"{structural_root}; observed {len(matches)}"
                )
            if matches:
                tables.append((table_name, matches[0]))
            else:
                LOGGER.warning(
                    "Optional v0.11 structural sensitivity relation is "
                    "unavailable in a legacy result: %s",
                    table_name,
                )
    return tables


def _bar_chart(records: Sequence[Mapping[str, Any]], width: int = 900) -> str:
    """Return an embedded SVG chart for the highest-ranked final scores."""
    selected = list(records[:20])
    if not selected:
        return "<p>No prioritisation rows were available.</p>"
    row_height = 30
    left = 190
    chart_width = width - left - 80
    height = 35 + row_height * len(selected)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Final candidate score chart">'
    ]
    for index, record in enumerate(selected):
        y = 25 + index * row_height
        score = max(0.0, min(1.0, float(record["final_score"])))
        colour = "#216e39" if record["grant_aligned_final_pass"] else "#7a5b16"
        parts.append(
            f'<text x="0" y="{y + 15}" font-size="13">'
            f'{html.escape(str(record["cluster_id"]))}</text>'
        )
        parts.append(
            f'<rect x="{left}" y="{y}" width="{score * chart_width:.2f}" height="19" '
            f'fill="{colour}" rx="3" />'
        )
        parts.append(
            f'<text x="{left + score * chart_width + 7:.2f}" y="{y + 15}" '
            f'font-size="12">{score:.3f}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _table(records: Sequence[Mapping[str, Any]]) -> str:
    """Return a bounded HTML table of final candidate results."""
    columns = (
        "final_rank",
        "recommendation_status",
        "cluster_id",
        "primary_group_id",
        "final_score",
        "target_species_fraction",
        "expression_species_fraction",
        "structural_species_fraction",
        "conservation_status",
        "three_dimensional_alignment_status",
    )
    header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = []
    for record in records[:25]:
        cells = []
        for column in columns:
            value = record.get(column, "")
            if isinstance(value, float):
                value = f"{value:.4f}"
            cells.append(f"<td>{html.escape(str(value))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def write_prioritisation_report(
    *, config: WorkflowConfig, records: Sequence[Mapping[str, Any]], path: Path
) -> None:
    """Write a self-contained verbose scientific prioritisation report."""
    stringent = [record for record in records if record["grant_aligned_final_pass"]]
    recommendations = [
        record for record in records if record["recommendation_status"] == "PRIORITY_RECOMMENDATION"
    ]
    prestructure = [record for record in records if record["grant_aligned_prestructure_pass"]]
    no_conserved_structure = [
        record
        for record in records
        if record["conservation_status"] != "CONSERVED_REGION_SUPPORTED"
    ]
    missing_evidence = [record for record in records if record.get("missing_evidence")]
    body = f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<title>ARIA E3 computational prioritisation</title><style>
body{{font-family:system-ui,sans-serif;max-width:1180px;margin:2rem auto;
padding:0 1rem;color:#17202a}}
h1,h2{{color:#173f5f}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}}
.card{{border:1px solid #ccd6dd;border-radius:8px;padding:1rem;background:#f8fafb}}
.number{{font-size:2rem;font-weight:700}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}}
th,td{{border:1px solid #d5dde3;padding:.45rem;text-align:left;vertical-align:top}}
th{{background:#edf3f7}}
.warning{{border-left:5px solid #a66a00;background:#fff7e6;padding:1rem}}
code{{word-break:break-all}}
svg{{width:100%;height:auto}}
@media(max-width:800px){{.cards{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<h1>ARIA plant E3 computational prioritisation</h1>
<p><strong>Run:</strong> {html.escape(config.run_name)}<br><strong>Profile:</strong>
{html.escape(config.analysis.prioritisation.profile_name)}<br><strong>Generated:</strong>
{html.escape(utc_now())}</p>
<div class="cards">
<div class="card"><div class="number">{len(records)}</div>candidate groups ranked</div>
<div class="card"><div class="number">{len(prestructure)}</div>
grant-aligned pre-structure passes</div>
<div class="card"><div class="number">{len(stringent)}</div>final stringent passes</div>
<div class="card"><div class="number">{len(recommendations)}</div>
priority recommendations</div></div>
<h2>Direct result</h2><p>The workflow ranked {len(records)} candidate groups and identified
{len(recommendations)} candidates within the configured
top-{config.analysis.prioritisation.final_candidate_limit} priority recommendation limit.
A recommendation requires broad target and mandatory-crop coverage,
broad mapped Expression Atlas support, conserved E3-domain support,
reusable high-quality pocket evidence
and a pocket-bearing aligned region supported across the configured structural species fraction.</p>
<div class="warning"><strong>Interpretation boundary.</strong>
These are computational recommendations. Neither AlphaFold confidence, domain annotation,
OrthoFinder grouping, RNA expression, fpocket/P2Rank scores nor aligned pocket-region
conservation proves E3 activity, compound binding or target degradation.
Human structural, biological and chemistry review remains required.</div>
<h2>Top final scores</h2>{_bar_chart(records)}
<h2>Top candidate table</h2>{_table(records)}
<h2>Evidence and thresholds</h2><ul>
<li>Target plants:
{html.escape('; '.join(config.analysis.prioritisation.target_species))}</li>
<li>Mandatory crop panel:
{html.escape('; '.join(config.analysis.prioritisation.mandatory_species))}</li>
<li>Minimum target-species fraction:
{config.analysis.prioritisation.minimum_target_species_fraction:.3f}</li>
<li>Minimum expression-species fraction:
{config.analysis.prioritisation.minimum_expression_species_fraction:.3f}</li>
<li>Minimum domain-species fraction:
{config.analysis.prioritisation.minimum_domain_species_fraction:.3f}</li>
<li>Minimum structural-species fraction:
{config.analysis.prioritisation.minimum_structural_species_fraction:.3f}</li>
<li>Minimum fpocket/P2Rank druggability score:
{config.analysis.ligandability.minimum_druggability_score:.3f}</li>
</ul>
<h2>Coverage limitations</h2><p>{len(no_conserved_structure)} ranked groups lacked a supported
multi-member conserved-pocket region, and {len(missing_evidence)} ranked groups had at least one
explicit missing-evidence state. A configured species without a compatible domain annotation or
Expression Atlas resource remains unavailable rather than becoming a biological negative.</p>
<h2>Authoritative outputs</h2><p>The complete row-level evidence, scores,
inclusion/exclusion reasons, missing-data states, provenance and source tables are stored in
<code>duckdb/e3_integrated_resource.duckdb</code>
and the matching TSV/Parquet final ranking.</p></body></html>"""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.partial")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(destination)


def run_integrated_stage(*, config: WorkflowConfig, stage_root: Path) -> None:
    """Build the portable integrated DuckDB, final ranking and scientific HTML report."""
    prestructure = find_one(
        root=config.run_root / "08_shortlist_gate",
        name="computational_prestructure_ranking.parquet",
    )
    conservation = find_one(
        root=config.run_root / "09_ligandability", name="pocket_conservation_summary.parquet"
    )
    alignment_summary = (
        find_one(
            root=config.run_root / "09b_structural_alignment",
            name="structural_alignment_summary.parquet",
        )
        if config.stage("09b_structural_alignment").enabled
        else None
    )
    final_query = _final_query(
        config=config,
        prestructure=prestructure,
        conservation=conservation,
        alignment_summary=alignment_summary,
    )
    database_path = stage_root / "duckdb" / "e3_integrated_resource.duckdb"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_database = database_path.with_name(f".{database_path.name}.partial")
    temporary_database.unlink(missing_ok=True)
    connection = duckdb.connect(str(temporary_database))
    try:
        resource_tables = _resource_tables(config=config)
        for table_name, source_path in resource_tables:
            _create_table_from_parquet(
                connection=connection, table_name=table_name, path=source_path
            )
        connection.execute(
            f"CREATE TABLE final_candidate_prioritisation AS {final_query}"
        )
        connection.execute(
            "CREATE TABLE candidate_master_results AS "
            + _candidate_master_query(connection=connection)
        )
        connection.execute(
            "CREATE TABLE final_evolutionary_candidate_prioritisation AS "
            + _final_evolutionary_query(connection=connection)
        )
        connection.execute(
            "CREATE TABLE final_evolutionary_group_cluster_contributors AS "
            + _final_contributor_query(connection=connection)
        )
        top_limit = config.analysis.prioritisation.final_candidate_limit
        dynamic_top_relation = (
            f"top_{top_limit}_computational_review_shortlist"
        )
        connection.execute(
            "CREATE TABLE top_computational_review_shortlist AS SELECT *, "
            "CASE WHEN grant_aligned_final_pass THEN "
            "'STRUCTURALLY_SUPPORTED_FOR_BOSS_REVIEW' ELSE "
            "'BOSS_REVIEW_WITH_EXPLICIT_EVIDENCE_GAPS' END AS boss_review_status "
            "FROM final_evolutionary_candidate_prioritisation "
            "ORDER BY final_evolutionary_rank LIMIT ?",
            [top_limit],
        )
        connection.execute(
            f"CREATE TABLE {quote_identifier(dynamic_top_relation)} AS "
            "SELECT * FROM top_computational_review_shortlist "
            "ORDER BY final_evolutionary_rank"
        )
        if dynamic_top_relation != "top_20_computational_review_shortlist":
            connection.execute(
                "CREATE TABLE top_20_computational_review_shortlist AS "
                "SELECT * FROM top_computational_review_shortlist "
                "ORDER BY final_evolutionary_rank LIMIT 20"
            )
        _create_gate_sensitivity_tables(
            connection=connection,
            config=config,
        )
        connection.execute(
            "CREATE TABLE grant_aligned_predicted_candidates AS SELECT * "
            "FROM final_evolutionary_candidate_prioritisation "
            "WHERE grant_aligned_final_pass "
            "ORDER BY final_evolutionary_rank LIMIT ?",
            [config.analysis.prioritisation.final_candidate_limit],
        )
        connection.execute(
            "CREATE TABLE final_candidate_exclusion_audit AS SELECT "
            "final_evolutionary_rank, evolutionary_group_key, primary_group_type, "
            "primary_group_id, lead_cluster_id, contributing_deepclust_cluster_count, "
            "contributing_deepclust_cluster_ids, grant_aligned_prediction_status, "
            "grant_aligned_prestructure_pass, grant_aligned_base_pass, "
            "grant_aligned_final_pass, conservation_status, "
            "three_dimensional_position_status, three_dimensional_alignment_status, "
            "inclusion_reasons, exclusion_reasons, missing_evidence, "
            "structural_exclusion_reasons FROM "
            "final_evolutionary_candidate_prioritisation "
            "WHERE NOT grant_aligned_final_pass ORDER BY final_evolutionary_rank"
        )
        connection.execute(
            "CREATE TABLE resource_metadata AS SELECT ? AS resource_name, ? AS package_version, "
            "? AS run_name, ? AS configuration_digest, ? AS scoring_profile, ? AS created_at",
            [
                "ARIA E3 integrated prioritisation resource",
                __version__,
                config.run_name,
                config.digest,
                config.analysis.prioritisation.profile_name,
                utc_now(),
            ],
        )
        _write_resource_relation_catalog(
            connection=connection,
            sources=resource_tables,
        )
        final_rows = connection.execute(
            "SELECT * FROM final_candidate_prioritisation ORDER BY final_rank"
        ).fetchall()
        final_columns = [str(item[0]) for item in connection.description]
        evolutionary_group_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM final_evolutionary_candidate_prioritisation"
            ).fetchone()[0]
        )
        top_review_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM top_computational_review_shortlist"
            ).fetchone()[0]
        )
        _copy_query_tsv(
            connection=connection,
            query="SELECT * FROM final_candidate_prioritisation ORDER BY final_rank",
            path=stage_root / "tables" / "final_candidate_prioritisation.tsv",
        )
        _copy_query_parquet(
            connection=connection,
            query="SELECT * FROM final_candidate_prioritisation",
            path=stage_root / "tables" / "final_candidate_prioritisation.parquet",
        )
        master_parquet = stage_root / "tables" / MASTER_PARQUET_NAME
        _copy_query_parquet(
            connection=connection,
            query="SELECT * FROM candidate_master_results",
            path=master_parquet,
        )
        final_root = stage_root / "final_results"
        final_queries = {
            "final_evolutionary_candidate_prioritisation": (
                "SELECT * FROM final_evolutionary_candidate_prioritisation "
                "ORDER BY final_evolutionary_rank"
            ),
            "top_computational_review_shortlist": (
                "SELECT * FROM top_computational_review_shortlist "
                "ORDER BY final_evolutionary_rank"
            ),
            dynamic_top_relation: (
                f"SELECT * FROM {quote_identifier(dynamic_top_relation)} "
                "ORDER BY final_evolutionary_rank"
            ),
            "top_20_computational_review_shortlist": (
                "SELECT * FROM top_20_computational_review_shortlist "
                "ORDER BY final_evolutionary_rank"
            ),
            "grant_aligned_predicted_candidates": (
                "SELECT * FROM grant_aligned_predicted_candidates "
                "ORDER BY final_evolutionary_rank"
            ),
            "final_evolutionary_group_cluster_contributors": (
                "SELECT * FROM final_evolutionary_group_cluster_contributors "
                "ORDER BY evolutionary_group_rank, computational_rank, cluster_id"
            ),
            "final_candidate_exclusion_audit": (
                "SELECT * FROM final_candidate_exclusion_audit "
                "ORDER BY final_evolutionary_rank"
            ),
            "gate_sensitivity_detail": (
                "SELECT * FROM gate_sensitivity_detail "
                "ORDER BY scenario_id, final_evolutionary_rank"
            ),
            "gate_sensitivity_summary": (
                "SELECT * FROM gate_sensitivity_summary ORDER BY scenario_id"
            ),
        }
        for basename, query in final_queries.items():
            _copy_query_tsv(
                connection=connection,
                query=query,
                path=final_root / f"{basename}.tsv",
            )
            _copy_query_parquet(
                connection=connection,
                query=query,
                path=final_root / f"{basename}.parquet",
            )
        workbook_path = create_final_results_workbook(
            connection=connection,
            config=config,
            output_path=final_root / "final_candidate_recommendations.xlsx",
        )
        connection.execute("CHECKPOINT")
    except duckdb.Error as exc:
        connection.close()
        temporary_database.unlink(missing_ok=True)
        raise StageError(f"Could not build integrated DuckDB: {exc}") from exc
    finally:
        try:
            connection.close()
        except duckdb.Error:
            pass
    temporary_database.replace(database_path)
    records = [dict(zip(final_columns, row)) for row in final_rows]
    if not records:
        raise StageError("Final integrated prioritisation contains no candidate rows")
    report_path = stage_root / "reports" / "final_computational_prioritisation.html"
    write_prioritisation_report(config=config, records=records, path=report_path)
    final_report = stage_root / "final_results" / "final_computational_prioritisation.html"
    shutil.copy2(report_path, final_report)
    final_readme = stage_root / "final_results" / "README.txt"
    final_readme.write_text(
        (
            "ARIA plant E3 final structural-completion results\n\n"
            "Start with final_candidate_recommendations.xlsx or "
            "final_computational_prioritisation.html.\n"
            f"The ordered top-{top_limit} review table is intended to let project "
            "leads select up to ten "
            "experimental priorities. A row is a distinct evolutionary candidate "
            "group; contributing DeepClust clusters remain in the separate contributor "
            "table. These are computational predictions and do not establish E3 "
            "activity, binding or degradation.\n"
        ),
        encoding="utf-8",
    )
    summary = {
        "run_name": config.run_name,
        "profile_name": config.analysis.prioritisation.profile_name,
        "candidate_count": len(records),
        "prestructure_pass_count": sum(
            bool(record["grant_aligned_prestructure_pass"]) for record in records
        ),
        "final_stringent_pass_count": sum(
            bool(record["grant_aligned_final_pass"]) for record in records
        ),
        "priority_recommendation_count": sum(
            record["recommendation_status"] == "PRIORITY_RECOMMENDATION"
            for record in records
        ),
        "evolutionary_candidate_group_count": evolutionary_group_count,
        "top_review_count": top_review_count,
        "top_review_limit": top_limit,
        "database_sha256": sha256_file(database_path),
        "master_parquet_sha256": sha256_file(
            stage_root / "tables" / MASTER_PARQUET_NAME
        ),
        "report_sha256": sha256_file(report_path),
        "excel_sha256": sha256_file(workbook_path),
        "interpretation": (
            "computational recommendations requiring human and experimental validation"
        ),
    }
    atomic_write_json(
        stage_root / "final_results" / "final_results_manifest.json",
        {
            "status": "complete",
            "run_name": config.run_name,
            "configuration_digest": config.digest,
            "generated_at_utc": utc_now(),
            "top_review_limit": top_limit,
            "row_granularity": "distinct evolutionary candidate group",
            "outputs": inventory_files(
                stage_root / "final_results",
                frozenset({"final_results_manifest.json"}),
            ),
            "interpretation": summary["interpretation"],
        },
    )
    atomic_write_json(stage_root / "provenance" / "integrated_resource_manifest.json", summary)
    write_tsv(
        stage_root / "qc" / "integrated_resource_validation.tsv",
        [summary],
        (
            "run_name",
            "profile_name",
            "candidate_count",
            "prestructure_pass_count",
            "final_stringent_pass_count",
            "priority_recommendation_count",
            "evolutionary_candidate_group_count",
            "top_review_count",
            "top_review_limit",
            "database_sha256",
            "master_parquet_sha256",
            "report_sha256",
            "excel_sha256",
            "interpretation",
        ),
    )


def run_app_ready_stage(*, config: WorkflowConfig, stage_root: Path) -> None:
    """Publish stable configuration hand-offs for the R Shiny and Python applications."""
    integrated_stage = config.run_root / "10_integrated_resource"
    database = integrated_stage / "duckdb" / "e3_integrated_resource.duckdb"
    report = integrated_stage / "reports" / "final_computational_prioritisation.html"
    final_table = integrated_stage / "tables" / "final_candidate_prioritisation.parquet"
    master_table = integrated_stage / "tables" / MASTER_PARQUET_NAME
    final_results = integrated_stage / "final_results"
    top_review_table = (
        final_results / "top_computational_review_shortlist.parquet"
    )
    gate_sensitivity = final_results / "gate_sensitivity_summary.parquet"
    final_workbook = final_results / "final_candidate_recommendations.xlsx"
    for path in (
        database,
        report,
        final_table,
        master_table,
        top_review_table,
        gate_sensitivity,
        final_workbook,
    ):
        if not path.is_file() or path.stat().st_size == 0:
            raise StageError(f"Application hand-off input is missing or empty: {path}")
    rows = [
        {
            "run_name": config.run_name,
            "mode": config.mode,
            "production_eligible": "true",
            "resource_duckdb": database,
            "resource_duckdb_sha256": sha256_file(database),
            "final_ranking_parquet": final_table,
            "candidate_master_parquet": master_table,
            "candidate_master_parquet_sha256": sha256_file(master_table),
            "final_report_html": report,
            "final_results_directory": final_results,
            "top_review_parquet": top_review_table,
            "gate_sensitivity_parquet": gate_sensitivity,
            "final_excel_workbook": final_workbook,
            "python_app_root": config.project_root / "e3_python_app",
            "r_shiny_app_root": config.project_root / "E3_shiny_app",
            "read_only_required": "true",
        }
    ]
    write_tsv(
        stage_root / "app_handoff.tsv",
        rows,
        (
            "run_name",
            "mode",
            "production_eligible",
            "resource_duckdb",
            "resource_duckdb_sha256",
            "final_ranking_parquet",
            "candidate_master_parquet",
            "candidate_master_parquet_sha256",
            "final_report_html",
            "final_results_directory",
            "top_review_parquet",
            "gate_sensitivity_parquet",
            "final_excel_workbook",
            "python_app_root",
            "r_shiny_app_root",
            "read_only_required",
        ),
    )
    (stage_root / "config").mkdir(parents=True, exist_ok=True)
    (stage_root / "config" / "python_app.env").write_text(
        (
            f"E3_RESOURCE_DUCKDB={database}\n"
            f"E3_FINAL_RESULTS_DIR={final_results}\n"
            "E3_MAX_TABLE_ROWS=10000\n"
        ),
        encoding="utf-8",
    )
    (stage_root / "config" / "python_app_master_parquet.env").write_text(
        f"E3_RESOURCE_PARQUET={master_table}\nE3_MAX_TABLE_ROWS=10000\n",
        encoding="utf-8",
    )
    (stage_root / "config" / "shiny_app.env").write_text(
        (
            f"E3_RESOURCE_DUCKDB={database}\n"
            f"E3_FINAL_RESULTS_DIR={final_results}\n"
            "E3_MAX_TABLE_ROWS=10000\n"
        ),
        encoding="utf-8",
    )
    (stage_root / "config" / "shiny_app_master_parquet.env").write_text(
        f"E3_RESOURCE_PARQUET={master_table}\nE3_MAX_TABLE_ROWS=10000\n",
        encoding="utf-8",
    )
    write_tsv(
        stage_root / "config" / "shiny_app_config.tsv",
        [
            {"setting": "resource_duckdb", "value": database},
            {"setting": "resource_parquet", "value": ""},
            {"setting": "resource_run_dir", "value": ""},
            {"setting": "expression_duckdb", "value": ""},
            {"setting": "max_preview_rows", "value": 10000},
        ],
        ("setting", "value"),
    )
    write_tsv(
        stage_root / "config" / "shiny_app_master_parquet_config.tsv",
        [
            {"setting": "resource_duckdb", "value": ""},
            {"setting": "resource_parquet", "value": master_table},
            {"setting": "resource_run_dir", "value": ""},
            {"setting": "expression_duckdb", "value": ""},
            {"setting": "max_preview_rows", "value": 10000},
        ],
        ("setting", "value"),
    )
    atomic_write_json(
        stage_root / "app_release_manifest.json",
        {
            "run_name": config.run_name,
            "resource_duckdb": str(database),
            "resource_duckdb_sha256": sha256_file(database),
            "candidate_master_parquet": str(master_table),
            "candidate_master_parquet_sha256": sha256_file(master_table),
            "final_report_html": str(report),
            "created_at": utc_now(),
            "status": "READY_FOR_READ_ONLY_APPLICATIONS",
        },
    )
