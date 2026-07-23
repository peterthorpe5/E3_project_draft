"""Compact integration proof for downloaded evidence through app-ready release."""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

import duckdb

from e3workflow.config import load_config
from e3workflow.integration import run_app_ready_stage, run_integrated_stage
from e3workflow.ligandability import run_ligandability_stage
from e3workflow.prioritisation import run_prestructure_stage
from e3workflow.production import run_domain_stage, run_expression_stage
from e3workflow.resources import (
    build_domain_cache_manifest,
    build_expression_manifest,
    build_ligandability_manifest,
)


def _write_parquet(
    path: Path, schema: str, rows: Sequence[Sequence[Any]]
) -> None:
    """Write a typed Parquet fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"CREATE TABLE fixture ({schema})")
        if rows:
            placeholders = ", ".join("?" for _ in rows[0])
            connection.executemany(
                f"INSERT INTO fixture VALUES ({placeholders})", rows
            )
        escaped = str(path).replace("'", "''")
        connection.execute(f"COPY fixture TO '{escaped}' (FORMAT PARQUET)")
    finally:
        connection.close()


def _membership_row(
    species: str, raw_identifier: str, accession: str, entry: str
) -> tuple[Any, ...]:
    """Return one hierarchical-membership row."""
    return (
        "HIERARCHICAL_ORTHOGROUP",
        "N0.HOG0001",
        "OG0001",
        "",
        species,
        raw_identifier,
        accession,
        entry,
        "reviewed",
        "fixture",
        "PARSED",
        "fixture",
        "fixture.tsv",
        2,
    )


def _annotation(accession: str) -> dict[str, Any]:
    """Return one terminal InterPro cache payload with F-box support."""
    return {
        "schema_version": 1,
        "requested_accession": accession,
        "retrieval_status": "ANNOTATED",
        "retrieved_at_utc": "2026-07-22T00:00:00Z",
        "api_base_url": "https://www.ebi.ac.uk/interpro/api",
        "release": {"interpro_version": "109.0"},
        "protein_metadata": None,
        "results": [
            {
                "metadata": {
                    "accession": "PF00646",
                    "name": "F-box domain",
                    "source_database": "pfam",
                    "type": "domain",
                    "integrated": "IPR001810",
                },
                "proteins": [
                    {
                        "accession": accession.lower(),
                        "protein_length": 8,
                        "source_database": "reviewed",
                        "organism": "fixture",
                        "in_alphafold": True,
                        "entry_protein_locations": [
                            {
                                "fragments": [
                                    {
                                        "start": 2,
                                        "end": 6,
                                        "dc-status": "CONTINUOUS",
                                    }
                                ],
                                "representative": False,
                                "model": "PF00646",
                                "score": 1e-8,
                            }
                        ],
                    }
                ],
            }
        ],
        "error": "",
    }


def test_downloaded_evidence_to_app_ready_release(
    synthetic_config: Path,
    package_root: Path,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """All scientific adapters share one flexible two-species schema."""
    base = load_config(synthetic_config)
    candidate_root = base.run_root / "03_candidate_evidence" / "candidate_evidence"
    candidate_schema = (
        "representative_id VARCHAR, matched_seed_ids_calculated VARCHAR, "
        "matched_seed_id_count INTEGER, reviewed_seed_count INTEGER, "
        "ubiquitin_go_positive_seed_count INTEGER, "
        "seed_with_exclusion_go_term_count INTEGER, strict_member_count INTEGER, "
        "strict_named_species_count INTEGER, strict_named_proteome_count INTEGER, "
        "strict_onekp_species_count INTEGER, seed_categories VARCHAR, "
        "seed_protein_names VARCHAR"
    )
    _write_parquet(
        candidate_root / "e3_cluster_candidate_evidence.parquet",
        candidate_schema,
        [("cluster_1", "Q9SA03;Q00002", 2, 2, 2, 0, 10, 2, 2, 0, "F-box", "fixture")],
    )

    orthology = base.run_root / "05_orthology" / "orthology" / "tables"
    _write_parquet(
        orthology / "candidate_membership_mapping.parquet",
        (
            "cluster_id VARCHAR, candidate_accession VARCHAR, record_type VARCHAR, "
            "group_id VARCHAR, species VARCHAR, mapping_status VARCHAR, "
            "ambiguity_status VARCHAR"
        ),
        [
            (
                "cluster_1",
                "Q9SA03",
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0001",
                "Arabidopsis_thaliana",
                "MATCHED",
                "UNAMBIGUOUS",
            ),
            (
                "cluster_1",
                "Q00002",
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0001",
                "Oryza_sativa",
                "MATCHED",
                "UNAMBIGUOUS",
            ),
        ],
    )
    membership_schema = (
        "record_type VARCHAR, group_id VARCHAR, orthogroup_id VARCHAR, "
        "gene_tree_parent_clade VARCHAR, species VARCHAR, raw_identifier VARCHAR, "
        "parsed_accession VARCHAR, parsed_entry VARCHAR, review_status VARCHAR, "
        "identifier_format VARCHAR, mapping_status VARCHAR, mapping_reason VARCHAR, "
        "source_file VARCHAR, source_row INTEGER"
    )
    _write_parquet(orthology / "orthogroup_membership.parquet", membership_schema, [])
    _write_parquet(
        orthology / "hierarchical_membership.parquet",
        membership_schema,
        [
            _membership_row(
                "Arabidopsis_thaliana", "sp|Q9SA03|FB27_ARATH", "Q9SA03", "FB27_ARATH"
            ),
            _membership_row(
                "Oryza_sativa", "tr|Q00002|ENTRY_RICE", "Q00002", "ENTRY_RICE"
            ),
        ],
    )
    _write_parquet(
        orthology / "candidate_cluster_orthology_summary.parquet",
        "cluster_id VARCHAR, mapped_candidate_count INTEGER",
        [("cluster_1", 2)],
    )

    cache_root = tmp_path / "interpro_cache"
    cache_root.mkdir()
    for accession in ("Q9SA03", "Q00002"):
        (cache_root / f"{accession}.json").write_text(
            json.dumps(_annotation(accession)), encoding="utf-8"
        )
    domain_manifest = build_domain_cache_manifest(
        cache_root=cache_root,
        output_path=tmp_path / "domain_manifest.tsv",
    )

    sqlite_path = tmp_path / "e3.db"
    sqlite_connection = sqlite3.connect(sqlite_path)
    sqlite_connection.execute(
        "CREATE TABLE e3 (entry TEXT, gene_names TEXT, organism TEXT, entry_name TEXT)"
    )
    sqlite_connection.executemany(
        "INSERT INTO e3 VALUES (?, ?, ?, ?)",
        [
            ("Q9SA03", "AT1G31090", "Arabidopsis thaliana", "FB27_ARATH"),
            ("Q00002", "LOC_Os01g01010", "Oryza sativa", "ENTRY_RICE"),
        ],
    )
    sqlite_connection.commit()
    sqlite_connection.close()

    expression_root = tmp_path / "expression"
    expression_schema = (
        "experiment_accession VARCHAR, species_column VARCHAR, gene_id VARCHAR, "
        "gene_name VARCHAR, sample_or_condition VARCHAR, expression_value DOUBLE, "
        "expression_unit VARCHAR, source_file VARCHAR"
    )
    for species, gene in (
        ("Arabidopsis_thaliana", "AT1G31090"),
        ("Oryza_sativa", "LOC_Os01g01010"),
    ):
        _write_parquet(
            expression_root
            / "atlas_expression_long"
            / f"species_column={species}"
            / "part.parquet",
            expression_schema,
            [("E-MTAB-1", species, gene, gene, "leaf", 5.0, "TPM", "fixture")],
        )
    expression_manifest = build_expression_manifest(
        expression_root=expression_root,
        output_path=tmp_path / "expression_manifest.tsv",
    )

    ligand_root = tmp_path / "ligandability" / "tables" / "parquet"
    _write_parquet(
        ligand_root / "joined_pockets.parquet",
        (
            "accession VARCHAR, pocket_number INTEGER, druggability_score DOUBLE, "
            "p2rank_score DOUBLE, p2rank_probability DOUBLE, p2rank_match_status VARCHAR"
        ),
        [("Q9SA03", 1, 0.9, 0.8, 0.8, "MATCHED"), ("Q00002", 1, 0.85, 0.8, 0.8, "MATCHED")],
    )
    _write_parquet(
        ligand_root / "pocket_quality.parquet",
        (
            "accession VARCHAR, pocket_number INTEGER, mapping_fraction DOUBLE, "
            "conservative_fraction_plddt_ge_70 DOUBLE, mapped_mean_plddt DOUBLE"
        ),
        [("Q9SA03", 1, 1.0, 0.9, 90.0), ("Q00002", 1, 1.0, 0.85, 88.0)],
    )
    _write_parquet(
        ligand_root / "pocket_residue_mappings.parquet",
        (
            "accession VARCHAR, pocket_number INTEGER, mapping_status VARCHAR, "
            "model_label_seq_id INTEGER, model_residue_name VARCHAR, model_plddt DOUBLE"
        ),
        [
            ("Q9SA03", 1, "MAPPED", 2, "A", 90.0),
            ("Q9SA03", 1, "MAPPED", 3, "C", 90.0),
            ("Q00002", 1, "MAPPED", 2, "A", 88.0),
            ("Q00002", 1, "MAPPED", 3, "C", 88.0),
        ],
    )
    _write_parquet(
        ligand_root / "model_quality.parquet",
        "accession VARCHAR, mean_plddt DOUBLE",
        [("Q9SA03", 90.0), ("Q00002", 88.0)],
    )
    ligandability_manifest = build_ligandability_manifest(
        roots=[ligand_root.parents[1]],
        output_path=tmp_path / "ligandability_manifest.tsv",
    )

    working = base.run_root / "04_orthofinder" / "Results" / "WorkingDirectory"
    working.mkdir(parents=True)
    (working / "SequenceIDs.txt").write_text(
        "0_0: sp|Q9SA03|FB27_ARATH\n0_1: tr|Q00002|ENTRY_RICE\n",
        encoding="utf-8",
    )
    (working / "Species0.fa").write_text(
        ">0_0\nMACDEFGH\n>0_1\nMACDEFGH\n", encoding="utf-8"
    )

    target_species = ("Arabidopsis_thaliana", "Oryza_sativa")
    prioritisation = replace(
        base.analysis.prioritisation,
        target_species=target_species,
        mandatory_species=target_species,
        minimum_target_species_fraction=1.0,
        minimum_expression_species_fraction=1.0,
        minimum_domain_species_fraction=1.0,
        minimum_structural_species_fraction=1.0,
        structure_group_limit=1,
        final_candidate_limit=1,
    )
    domains = replace(
        base.analysis.domains,
        mode="downloaded_manifest",
        allow_network=False,
    )
    config = replace(
        base,
        mode="production",
        resources=replace(
            base.resources,
            inherited_sqlite=sqlite_path,
            expression_manifest=expression_manifest,
            ligandability_manifest=ligandability_manifest,
            domain_annotation_manifest=domain_manifest,
            e3_domain_catalogue=package_root / "data" / "e3_domain_catalogue.tsv",
        ),
        analysis=replace(
            base.analysis,
            domains=domains,
            prioritisation=prioritisation,
        ),
    )

    run_domain_stage(config=config, stage_root=config.run_root / "06_domains")
    run_expression_stage(config=config, stage_root=config.run_root / "07_expression")
    run_prestructure_stage(config=config, stage_root=config.run_root / "08_shortlist_gate")

    def copy_alignment(**kwargs: Any) -> None:
        """Use the identical fixture sequences as their own deterministic alignment."""
        shutil.copyfile(kwargs["input_fasta"], kwargs["output_fasta"])
        kwargs["log_path"].write_text("fixture alignment\n", encoding="utf-8")

    monkeypatch.setattr("e3workflow.ligandability._run_mafft", copy_alignment)
    run_ligandability_stage(
        config=config, stage_root=config.run_root / "09_ligandability"
    )
    structural_tables = (
        config.run_root
        / "09b_structural_alignment"
        / "structural_alignment"
        / "tables"
    )
    _write_parquet(
        structural_tables / "structural_alignments.parquet",
        "cluster_id VARCHAR, alignment_tool VARCHAR",
        [("cluster_1", "US-align"), ("cluster_1", "TM-align")],
    )
    _write_parquet(
        structural_tables / "pocket_comparisons.parquet",
        "cluster_id VARCHAR, alignment_tool VARCHAR",
        [("cluster_1", "US-align"), ("cluster_1", "TM-align")],
    )
    _write_parquet(
        structural_tables / "structural_alignment_summary.parquet",
        (
            "cluster_id VARCHAR, primary_group_type VARCHAR, primary_group_id VARCHAR, "
            "three_dimensional_pocket_score DOUBLE, "
            "alignment_status VARCHAR, mean_minimum_tm_score DOUBLE, "
            "mean_pocket_overlap_fraction DOUBLE, "
            "median_centroid_distance_angstrom DOUBLE"
        ),
        [
            (
                "cluster_1",
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0001",
                0.9,
                "CONSERVED_3D_POCKET_SUPPORTED",
                0.9,
                0.9,
                1.0,
            )
        ],
    )
    config = replace(
        config,
        stages=tuple(
            replace(
                stage,
                enabled=True,
                required=False,
                evidence_mode="generate",
            )
            if stage.name == "09b_structural_alignment"
            else stage
            for stage in config.stages
        ),
    )
    run_integrated_stage(
        config=config, stage_root=config.run_root / "10_integrated_resource"
    )
    run_app_ready_stage(config=config, stage_root=config.run_root / "11_app_ready")

    database = config.run_root / "10_integrated_resource/duckdb/e3_integrated_resource.duckdb"
    connection = duckdb.connect(str(database), read_only=True)
    try:
        result = connection.execute(
            "SELECT recommendation_status, grant_aligned_final_pass "
            "FROM final_candidate_prioritisation"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute("SHOW TABLES").fetchall()
        }
    finally:
        connection.close()
    assert result == ("PRIORITY_RECOMMENDATION", True)
    assert {
        "domain_summary",
        "candidate_expression_summary",
        "selected_pockets",
        "structural_alignment_summary",
    }.issubset(tables)
    assert (
        config.run_root
        / "10_integrated_resource/reports/final_computational_prioritisation.html"
    ).is_file()
    assert (config.run_root / "11_app_ready/app_release_manifest.json").is_file()
