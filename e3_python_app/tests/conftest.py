"""Shared application tests and a representative tiny DuckDB resource."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from e3app.data import quote_literal


@pytest.fixture
def resource_db(tmp_path: Path) -> Path:
    """Create candidate, orthology, pocket and provenance relations."""
    path = tmp_path / "resource.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE candidates(accession VARCHAR, organism VARCHAR, score DOUBLE)"
        )
        connection.execute(
            "INSERT INTO candidates VALUES ('Q9SA03', 'Arabidopsis thaliana', 0.95), "
            "('P38398', 'Homo sapiens', 0.80)"
        )
        connection.execute(
            "CREATE TABLE orthogroup_membership("
            "group_id VARCHAR, species VARCHAR, raw_identifier VARCHAR, "
            "parsed_accession VARCHAR, orthogroup VARCHAR)"
        )
        connection.execute(
            "INSERT INTO orthogroup_membership VALUES "
            "('OG0001686', 'Arabidopsis_thaliana', 'sp|Q9SA03|FB27_ARATH', "
            "'Q9SA03', 'OG0001686')"
        )
        connection.execute(
            "CREATE TABLE hierarchical_membership("
            "group_id VARCHAR, species VARCHAR, raw_identifier VARCHAR)"
        )
        connection.execute(
            "INSERT INTO hierarchical_membership VALUES "
            "('N0.HOG0001', 'Arabidopsis_thaliana', 'sp|Q9SA03|FB27_ARATH'), "
            "('N0.HOG0001', 'Homo_sapiens', 'sp|P38398|BRCA1_HUMAN')"
        )
        connection.execute(
            "CREATE TABLE candidate_group_member_sequences("
            "cluster_id VARCHAR, record_type VARCHAR, group_id VARCHAR, "
            "species VARCHAR, internal_id VARCHAR, raw_identifier VARCHAR, "
            "parsed_accession VARCHAR, parsed_entry VARCHAR, review_status VARCHAR, "
            "mapping_status VARCHAR, is_input_candidate BOOLEAN, "
            "candidate_accessions_for_cluster VARCHAR, sequence_length INTEGER, "
            "protein_sequence VARCHAR)"
        )
        connection.execute(
            "INSERT INTO candidate_group_member_sequences VALUES "
            "('cluster_1', 'HIERARCHICAL_ORTHOGROUP', 'N0.HOG0001', "
            "'Arabidopsis_thaliana', '0_0', 'sp|Q9SA03|FB27_ARATH', "
            "'Q9SA03', 'FB27_ARATH', 'REVIEWED', 'MAPPED', true, "
            "'Q9SA03', 8, 'MSTNPKPQ'), "
            "('cluster_1', 'ORTHOGROUP', 'OG0001686', "
            "'Arabidopsis_thaliana', '0_0', 'sp|Q9SA03|FB27_ARATH', "
            "'Q9SA03', 'FB27_ARATH', 'REVIEWED', 'MAPPED', true, "
            "'Q9SA03', 8, 'MSTNPKPQ')"
        )
        connection.execute("CREATE TABLE pocket_scores(accession VARCHAR, p2rank_score DOUBLE)")
        connection.execute("INSERT INTO pocket_scores VALUES ('Q9SA03', 4.2)")
        connection.execute("CREATE TABLE provenance_manifest(path VARCHAR, checksum VARCHAR)")
        connection.execute("INSERT INTO provenance_manifest VALUES ('source', 'abc')")
        connection.execute("CREATE VIEW candidate_view AS SELECT * FROM candidates")
        connection.execute(
            "CREATE TABLE candidate_master_results("
            "final_rank INTEGER, prestructure_evolutionary_group_rank INTEGER, "
            "recommendation_status VARCHAR, cluster_id VARCHAR, "
            "primary_group_id VARCHAR, orthofinder_orthogroup_ids VARCHAR, "
            "candidate_accessions VARCHAR, final_score DOUBLE, "
            "target_species_fraction DOUBLE, domain_species_fraction DOUBLE, "
            "expression_species_fraction DOUBLE, structural_species_fraction DOUBLE, "
            "grant_aligned_prestructure_pass BOOLEAN, grant_aligned_final_pass BOOLEAN, "
            "three_dimensional_alignment_status VARCHAR, missing_evidence VARCHAR)"
        )
        connection.execute(
            "INSERT INTO candidate_master_results VALUES "
            "(1, 1, 'PRIORITY_RECOMMENDATION', 'cluster_1', 'N0.HOG0001', "
            "'OG0001686', 'Q9SA03;Q00002', 0.91, 1.0, 1.0, 1.0, 1.0, "
            "true, true, 'CONSERVED_3D_POCKET_SUPPORTED', '')"
        )
        connection.execute(
            "CREATE TABLE candidate_evidence("
            "representative_id VARCHAR, representative_original_id VARCHAR, "
            "matched_seed_ids_calculated VARCHAR, raw_member_count INTEGER, "
            "strict_member_count INTEGER, strict_member_fraction DOUBLE, "
            "raw_onekp_sample_count INTEGER, raw_onekp_species_count INTEGER, "
            "strict_onekp_sample_count INTEGER, strict_onekp_species_count INTEGER, "
            "strict_named_proteome_count INTEGER, strict_named_species_count INTEGER)"
        )
        connection.execute(
            "INSERT INTO candidate_evidence VALUES "
            "('cluster_1', 'onekp_dataset@@scaffold-AAAA-1', 'Q9SA03', "
            "12, 10, 0.833, 7, 6, 5, 4, 3, 3)"
        )
        connection.execute(
            "CREATE TABLE domain_summary("
            "cluster_id VARCHAR, member_accession VARCHAR, species_column VARCHAR, "
            "domain_support_status VARCHAR)"
        )
        connection.execute(
            "INSERT INTO domain_summary VALUES "
            "('cluster_1', 'Q9SA03', 'Arabidopsis_thaliana', 'SUPPORTED')"
        )
        connection.execute(
            "CREATE TABLE candidate_expression_summary("
            "cluster_id VARCHAR, member_accession VARCHAR, species_column VARCHAR, "
            "mapping_status VARCHAR, broad_expression_supported BOOLEAN)"
        )
        connection.execute(
            "INSERT INTO candidate_expression_summary VALUES "
            "('cluster_1', 'Q9SA03', 'Arabidopsis_thaliana', 'MAPPED_UNIQUE', true)"
        )
        connection.execute(
            "CREATE TABLE candidate_expression_context_summary("
            "cluster_id VARCHAR, primary_group_id VARCHAR, member_accession VARCHAR, "
            "member_identifier VARCHAR, species_column VARCHAR, gene_id VARCHAR, "
            "gene_name VARCHAR, experiment_accession VARCHAR, expression_unit VARCHAR, "
            "sample_or_condition VARCHAR, atlas_group_label VARCHAR, assay_ids VARCHAR, "
            "assay_count INTEGER, organism_part VARCHAR, developmental_stage VARCHAR, "
            "condition VARCHAR, expression_context VARCHAR, metadata_status VARCHAR, "
            "expression_value_statistic VARCHAR, expression_value DOUBLE, "
            "expression_minimum DOUBLE, expression_lower_quartile DOUBLE, "
            "expression_median DOUBLE, expression_upper_quartile DOUBLE, "
            "expression_maximum DOUBLE, expression_positive BOOLEAN)"
        )
        connection.execute(
            "INSERT INTO candidate_expression_context_summary VALUES "
            "('cluster_1', 'N0.HOG0001', 'Q9SA03', 'Q9SA03', "
            "'Arabidopsis_thaliana', 'AT1G31090', 'FB27', 'E-MTAB-1', 'TPM', "
            "'g1', 'leaf control', 'SRR1;SRR2', 2, 'leaf', 'adult', 'control', "
            "'leaf', 'MAPPED_WITH_TISSUE', 'median', 4.0, 3.0, 3.5, 4.0, "
            "4.5, 5.0, true), "
            "('cluster_1', 'N0.HOG0001', 'Q9SA03', 'Q9SA03', "
            "'Arabidopsis_thaliana', 'AT1G31090', 'FB27', 'E-MTAB-2', 'TPM', "
            "'g2', 'root control', 'SRR3', 1, 'root', 'adult', 'control', "
            "'root', 'MAPPED_WITH_TISSUE', 'median', 0.4, 0.1, 0.2, 0.4, "
            "0.5, 0.7, false)"
        )
        connection.execute(
            "CREATE TABLE selected_pockets("
            "cluster_id VARCHAR, candidate_accession VARCHAR, pocket_number INTEGER, "
            "druggability_score DOUBLE)"
        )
        connection.execute(
            "INSERT INTO selected_pockets VALUES ('cluster_1', 'Q9SA03', 1, 0.9)"
        )
        connection.execute(
            "CREATE TABLE pocket_conservation_summary("
            "cluster_id VARCHAR, primary_group_id VARCHAR, conservation_status VARCHAR, "
            "conserved_pocket_score DOUBLE)"
        )
        connection.execute(
            "INSERT INTO pocket_conservation_summary VALUES "
            "('cluster_1', 'N0.HOG0001', 'CONSERVED_REGION_SUPPORTED', 0.88)"
        )
        connection.execute(
            "CREATE TABLE structural_alignment_summary("
            "cluster_id VARCHAR, primary_group_id VARCHAR, "
            "position_alignment_status VARCHAR, alignment_status VARCHAR, "
            "mean_minimum_tm_score DOUBLE, "
            "mean_pocket_overlap_fraction DOUBLE, "
            "median_centroid_distance_angstrom DOUBLE)"
        )
        connection.execute(
            "INSERT INTO structural_alignment_summary VALUES "
            "('cluster_1', 'N0.HOG0001', 'SAME_3D_POCKET_POSITION_SUPPORTED', "
            "'CONSERVED_3D_POCKET_SUPPORTED', 0.9, 0.8, 1.2)"
        )
        connection.execute(
            "CREATE TABLE top_computational_review_shortlist AS "
            "SELECT * FROM candidate_master_results ORDER BY final_rank"
        )
        connection.execute(
            "CREATE TABLE top_50_computational_review_shortlist AS "
            "SELECT * FROM candidate_master_results ORDER BY final_rank"
        )
        connection.execute(
            "CREATE TABLE gate_sensitivity_summary("
            "scenario_id VARCHAR, evolutionary_group_count INTEGER, "
            "passing_group_count INTEGER)"
        )
        connection.execute(
            "INSERT INTO gate_sensitivity_summary VALUES "
            "('STRICT_PRIMARY', 1, 1), ('TOP_K_POCKET', 1, 1)"
        )
        connection.execute(
            "CREATE TABLE resource_metadata("
            "resource_name VARCHAR, package_version VARCHAR, run_name VARCHAR)"
        )
        connection.execute(
            "INSERT INTO resource_metadata VALUES "
            "('ARIA E3 resource', '0.7.2', 'fixture')"
        )
    return path


@pytest.fixture
def recommendation_threshold_db(resource_db: Path) -> Path:
    """Add a complete two-group final-gate relation for headless UI tests."""
    with duckdb.connect(str(resource_db)) as connection:
        connection.execute(
            "CREATE TABLE final_evolutionary_candidate_prioritisation("
            "final_evolutionary_rank INTEGER, primary_group_type VARCHAR, "
            "primary_group_id VARCHAR, lead_cluster_id VARCHAR, "
            "target_species_fraction DOUBLE, mandatory_species_fraction DOUBLE, "
            "domain_assessed_species_count INTEGER, domain_species_fraction DOUBLE, "
            "expression_assessed_species_count INTEGER, "
            "expression_species_fraction DOUBLE, structural_species_fraction DOUBLE, "
            "minimum_druggability_score DOUBLE, "
            "all_assessed_members_pass_druggability BOOLEAN, "
            "all_assessed_members_pass_mapping BOOLEAN, conservation_status VARCHAR, "
            "three_dimensional_alignment_status VARCHAR, "
            "prestructure_score DOUBLE, final_score DOUBLE, "
            "candidate_accessions VARCHAR)"
        )
        connection.execute(
            "INSERT INTO final_evolutionary_candidate_prioritisation VALUES "
            "(1, 'HIERARCHICAL_ORTHOGROUP', 'N0.HOG0001', 'cluster_1', "
            "1, 1, 12, 1, 10, 1, 1, 0.7, true, true, "
            "'CONSERVED_REGION_SUPPORTED', 'CONSERVED_3D_POCKET_SUPPORTED', "
            "0.9, 0.9, 'P1;P2'), "
            "(2, 'HIERARCHICAL_ORTHOGROUP', 'N0.HOG0002', 'cluster_2', "
            "1, 1, 12, 1, 10, 1, 1, 0.325, false, true, "
            "'CONSERVED_REGION_SUPPORTED', 'CONSERVED_3D_POCKET_SUPPORTED', "
            "0.85, 0.8, 'P3;P4')"
        )
        connection.execute(
            "INSERT INTO selected_pockets VALUES "
            "('cluster_1', 'P2', 1, 0.7), "
            "('cluster_2', 'P3', 1, 0.8), "
            "('cluster_2', 'P4', 1, 0.325)"
        )
    return resource_db


@pytest.fixture
def master_parquet(resource_db: Path, tmp_path: Path) -> Path:
    """Export the representative candidate master relation to Parquet."""
    path = tmp_path / "e3_candidate_master_results.parquet"
    with duckdb.connect(str(resource_db), read_only=True) as connection:
        connection.execute(
            "COPY candidate_master_results TO "
            f"{quote_literal(path)} (FORMAT PARQUET)"
        )
    return path


@pytest.fixture
def run_results_dir(master_parquet: Path, tmp_path: Path) -> Path:
    """Create a minimal current-run directory containing several Parquets."""
    root = tmp_path / "workflow_run"
    stage = root / "10_integrated_resource" / "tables"
    stage.mkdir(parents=True)
    target = stage / master_parquet.name
    target.write_bytes(master_parquet.read_bytes())
    return root
