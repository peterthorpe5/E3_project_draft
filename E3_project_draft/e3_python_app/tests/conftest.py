"""Shared application tests and a representative tiny DuckDB resource."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest


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
            "CREATE TABLE orthogroup_membership(parsed_accession VARCHAR, orthogroup VARCHAR)"
        )
        connection.execute("INSERT INTO orthogroup_membership VALUES ('Q9SA03', 'OG0001686')")
        connection.execute("CREATE TABLE pocket_scores(accession VARCHAR, p2rank_score DOUBLE)")
        connection.execute("INSERT INTO pocket_scores VALUES ('Q9SA03', 4.2)")
        connection.execute("CREATE TABLE provenance_manifest(path VARCHAR, checksum VARCHAR)")
        connection.execute("INSERT INTO provenance_manifest VALUES ('source', 'abc')")
        connection.execute("CREATE VIEW candidate_view AS SELECT * FROM candidates")
        connection.execute(
            "CREATE TABLE candidate_master_results("
            "final_rank INTEGER, recommendation_status VARCHAR, cluster_id VARCHAR, "
            "primary_group_id VARCHAR, orthofinder_orthogroup_ids VARCHAR, "
            "candidate_accessions VARCHAR, final_score DOUBLE, "
            "target_species_fraction DOUBLE, domain_species_fraction DOUBLE, "
            "expression_species_fraction DOUBLE, structural_species_fraction DOUBLE, "
            "grant_aligned_prestructure_pass BOOLEAN, grant_aligned_final_pass BOOLEAN, "
            "three_dimensional_alignment_status VARCHAR, missing_evidence VARCHAR)"
        )
        connection.execute(
            "INSERT INTO candidate_master_results VALUES "
            "(1, 'PRIORITY_RECOMMENDATION', 'cluster_1', 'N0.HOG0001', "
            "'OG0001686', 'Q9SA03;Q00002', 0.91, 1.0, 1.0, 1.0, 1.0, "
            "true, true, 'CONSERVED_3D_POCKET_SUPPORTED', '')"
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
            "mean_minimum_tm_score DOUBLE)"
        )
        connection.execute(
            "INSERT INTO structural_alignment_summary VALUES "
            "('cluster_1', 'N0.HOG0001', 'SAME_3D_POCKET_POSITION_SUPPORTED', "
            "'CONSERVED_3D_POCKET_SUPPORTED', 0.9)"
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
def master_parquet(resource_db: Path, tmp_path: Path) -> Path:
    """Export the representative candidate master relation to Parquet."""
    path = tmp_path / "e3_candidate_master_results.parquet"
    with duckdb.connect(str(resource_db), read_only=True) as connection:
        connection.execute(
            "COPY candidate_master_results TO ? (FORMAT PARQUET)",
            [str(path)],
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
