"""Tests for reusable orthology, expression, ranking and structure adapters."""

from __future__ import annotations

import json
import sqlite3
import tarfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

import duckdb
import pytest

from e3workflow.config import load_config
from e3workflow.io_utils import read_tsv, sha256_file, write_tsv
from e3workflow.ligandability import (
    _load_sequences,
    build_selected_pockets,
    map_pocket_residues_to_fasta,
)
from e3workflow.prioritisation import score_candidate
from e3workflow.errors import StageError
from e3workflow.production import (
    find_one,
    iter_fasta,
    load_domain_catalogue,
    run_candidate_evidence_stage,
    run_expression_stage,
    run_reused_discovery_stage,
    run_reused_orthofinder_stage,
)
from e3workflow.resources import build_expression_manifest

MEMBERSHIP_SCHEMA = (
    "record_type VARCHAR, group_id VARCHAR, orthogroup_id VARCHAR, "
    "gene_tree_parent_clade VARCHAR, species VARCHAR, raw_identifier VARCHAR, "
    "parsed_accession VARCHAR, parsed_entry VARCHAR, review_status VARCHAR, "
    "identifier_format VARCHAR, mapping_status VARCHAR, mapping_reason VARCHAR, "
    "source_file VARCHAR, source_row INTEGER"
)


def write_parquet(path: Path, schema: str, rows: Sequence[Sequence[Any]]) -> None:
    """Write a small typed Parquet fixture through DuckDB."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"CREATE TABLE fixture ({schema})")
        if rows:
            placeholders = ", ".join("?" for _ in rows[0])
            connection.executemany(f"INSERT INTO fixture VALUES ({placeholders})", rows)
        escaped = str(path).replace("'", "''")
        connection.execute(f"COPY fixture TO '{escaped}' (FORMAT PARQUET)")
    finally:
        connection.close()


def membership_row(
    record_type: str,
    group_id: str,
    species: str,
    raw_identifier: str,
    accession: str,
    entry: str,
) -> tuple[Any, ...]:
    """Return one complete orthology membership fixture row."""
    return (
        record_type,
        group_id,
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


def test_expression_maps_full_selected_group_members(
    synthetic_config: Path, tmp_path: Path
) -> None:
    """Expression is assessed across selected group members, not only original seed accessions."""
    config = load_config(synthetic_config)
    orthology = config.run_root / "05_orthology" / "tables"
    write_parquet(
        orthology / "candidate_membership_mapping.parquet",
        (
            "cluster_id VARCHAR, candidate_accession VARCHAR, record_type VARCHAR, "
            "group_id VARCHAR, species VARCHAR, mapping_status VARCHAR, ambiguity_status VARCHAR"
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
            )
        ],
    )
    write_parquet(
        orthology / "orthogroup_membership.parquet",
        MEMBERSHIP_SCHEMA,
        [],
    )
    write_parquet(
        orthology / "hierarchical_membership.parquet",
        MEMBERSHIP_SCHEMA,
        [
            membership_row(
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0001",
                "Arabidopsis_thaliana",
                "AT1G31090",
                "Q9SA03",
                "FB27_ARATH",
            ),
            membership_row(
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0001",
                "Oryza_sativa",
                "LOC_Os01g01010",
                "Q00002",
                "ENTRY_RICE",
            ),
        ],
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
    expression_root = tmp_path / "parquet"
    expression_schema = (
        "experiment_accession VARCHAR, species_column VARCHAR, gene_id VARCHAR, "
        "gene_name VARCHAR, sample_or_condition VARCHAR, expression_value DOUBLE, "
        "expression_unit VARCHAR, source_file VARCHAR"
    )
    for species, gene in (
        ("Arabidopsis_thaliana", "AT1G31090"),
        ("Oryza_sativa", "LOC_Os01g01010"),
    ):
        write_parquet(
            expression_root
            / "atlas_expression_long"
            / f"species_column={species}"
            / "part.parquet",
            expression_schema,
            [("E-MTAB-1", species, gene, gene, "leaf", 5.0, "TPM", "fixture")],
        )
    manifest = build_expression_manifest(
        expression_root=expression_root,
        output_path=tmp_path / "expression_manifest.tsv",
    )
    prioritisation = replace(
        config.analysis.prioritisation,
        target_species=("Arabidopsis_thaliana", "Oryza_sativa"),
        mandatory_species=("Oryza_sativa",),
    )
    configured = replace(
        config,
        resources=replace(
            config.resources,
            expression_manifest=manifest,
            inherited_sqlite=sqlite_path,
        ),
        analysis=replace(config.analysis, prioritisation=prioritisation),
    )
    stage_root = tmp_path / "expression_stage"
    run_expression_stage(config=configured, stage_root=stage_root)
    _, summaries = read_tsv(stage_root / "tables" / "candidate_expression_summary.tsv")
    assert {row["species_column"] for row in summaries} == {
        "Arabidopsis_thaliana",
        "Oryza_sativa",
    }
    assert all(row["mapping_status"] == "MAPPED_UNIQUE" for row in summaries)
    assert all(
        row["broad_expression_supported"].lower() == "true" for row in summaries
    )


def test_missing_domain_annotation_is_not_a_biological_negative(
    synthetic_config: Path,
) -> None:
    """Unavailable domain species reduce completeness but do not enter the negative denominator."""
    config = load_config(synthetic_config)
    prioritisation = replace(
        config.analysis.prioritisation,
        target_species=("Species_a", "Species_b", "Species_c"),
        mandatory_species=("Species_a",),
        minimum_target_species_fraction=1.0,
        minimum_domain_species_fraction=0.5,
        minimum_expression_species_fraction=1.0,
    )
    configured = replace(
        config,
        analysis=replace(config.analysis, prioritisation=prioritisation),
    )
    record = score_candidate(
        config=configured,
        candidate={
            "cluster_id": "cluster_1",
            "matched_seed_ids_calculated": "Q1;Q2",
            "matched_seed_id_count": 2,
            "reviewed_seed_count": 2,
            "ubiquitin_go_positive_seed_count": 2,
            "seed_with_exclusion_go_term_count": 0,
        },
        primary={
            "record_type": "HIERARCHICAL_ORTHOGROUP",
            "group_id": "N0.HOG0001",
            "alternative_group_count": 0,
        },
        full_species={"Species_a", "Species_b", "Species_c"},
        domain_rows=[
            {
                "species_column": "Species_a",
                "domain_support_status": "SUPPORTED",
            },
            {
                "species_column": "Species_b",
                "domain_support_status": "ANNOTATED_NO_CATALOGUED_E3_DOMAIN",
            },
            {
                "species_column": "Species_c",
                "domain_support_status": "ANNOTATION_UNAVAILABLE",
            },
        ],
        expression_rows=[
            {
                "species_column": species,
                "mapping_status": "MAPPED_UNIQUE",
                "broad_expression_supported": True,
            }
            for species in ("Species_a", "Species_b")
        ],
        expression_available_species={"Species_a", "Species_b"},
    )
    assert record["domain_supported_species_count"] == 1
    assert record["domain_assessed_species_count"] == 2
    assert record["domain_unavailable_species_count"] == 1
    assert record["domain_species_fraction"] == 0.5
    assert record["grant_aligned_criteria_status"] == "PASS_WITH_MISSING_EVIDENCE"
    assert record["grant_aligned_stringent_pass"] is True
    assert "domain_annotation_unavailable_for_species=Species_c" in record["missing_evidence"]


def test_reused_orthofinder_sequences_and_best_pocket_selection(
    synthetic_config: Path, tmp_path: Path
) -> None:
    """Reused Results_Feb26 working sequences feed the standard pocket selector."""
    config = load_config(synthetic_config)
    working = config.run_root / "04_orthofinder" / "Results" / "WorkingDirectory"
    working.mkdir(parents=True)
    (working / "SequenceIDs.txt").write_text(
        "0_0: sp|Q9SA03|FB27_ARATH\n0_1: tr|Q00002|ENTRY_RICE\n",
        encoding="utf-8",
    )
    (working / "Species0.fa").write_text(
        ">0_0\nMABCDE\n>0_1\nMFGHIJ\n", encoding="utf-8"
    )
    assert _load_sequences(config, {"Q9SA03", "Q00002"}) == {
        "Q9SA03": "MABCDE",
        "Q00002": "MFGHIJ",
    }
    structural = tmp_path / "structural.parquet"
    joined = tmp_path / "joined.parquet"
    quality = tmp_path / "quality.parquet"
    write_parquet(
        structural,
        (
            "cluster_id VARCHAR, primary_group_type VARCHAR, primary_group_id VARCHAR, "
            "candidate_accession VARCHAR, species_column VARCHAR"
        ),
        [("cluster_1", "HIERARCHICAL_ORTHOGROUP", "H1", "Q9SA03", "Species_a")],
    )
    write_parquet(
        joined,
        (
            "source_resource_id VARCHAR, accession VARCHAR, pocket_number INTEGER, "
            "druggability_score DOUBLE, p2rank_score DOUBLE, p2rank_probability DOUBLE, "
            "p2rank_match_status VARCHAR"
        ),
        [
            ("resource", "Q9SA03", 1, 0.4, 0.2, 0.2, "UNMATCHED"),
            ("resource", "Q9SA03", 2, 0.8, 0.9, 0.9, "MATCHED"),
        ],
    )
    write_parquet(
        quality,
        (
            "accession VARCHAR, pocket_number INTEGER, mapping_fraction DOUBLE, "
            "conservative_fraction_plddt_ge_70 DOUBLE, mapped_mean_plddt DOUBLE"
        ),
        [("Q9SA03", 1, 1.0, 0.9, 85.0), ("Q9SA03", 2, 1.0, 0.9, 90.0)],
    )
    output = tmp_path / "selected.parquet"
    build_selected_pockets(
        config=config,
        structural_accessions=structural,
        joined_pockets=joined,
        pocket_quality=quality,
        output_path=output,
    )
    assert duckdb.connect(":memory:").execute(
        f"SELECT pocket_number FROM read_parquet('{output}')"
    ).fetchone()[0] == 2


def test_pocket_residues_map_to_exact_fasta_coordinates() -> None:
    """Model label numbering becomes FASTA coordinates only after residue validation."""
    selected = [
        {
            "cluster_id": "cluster_1",
            "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
            "primary_group_id": "N0.HOG0001",
            "candidate_accession": "Q9SA03",
            "species_column": "Arabidopsis_thaliana",
            "pocket_number": 3,
        }
    ]
    mappings = [
        {
            "accession": "Q9SA03",
            "pocket_number": 3,
            "mapping_status": "MAPPED",
            "model_label_chain": "A",
            "model_label_seq_id": "2",
            "model_auth_chain": "A",
            "model_auth_seq_id": "2",
            "model_insertion_code": "",
            "model_residue_name": "SER",
        },
        {
            "accession": "Q9SA03",
            "pocket_number": 3,
            "mapping_status": "MAPPED",
            "model_label_chain": "A",
            "model_label_seq_id": "3",
            "model_auth_chain": "A",
            "model_auth_seq_id": "3",
            "model_insertion_code": "",
            "model_residue_name": "GLY",
        },
    ]
    rows = map_pocket_residues_to_fasta(
        selected_records=selected,
        mapping_records=mappings,
        sequences={"Q9SA03": "MSA"},
    )
    assert rows[0]["fasta_position"] == 2
    assert rows[0]["fasta_residue"] == "S"
    assert rows[0]["sequence_coordinate_status"] == "MAPPED_EXACT"
    assert rows[1]["sequence_coordinate_status"] == "RESIDUE_IDENTITY_MISMATCH"


def test_reused_orthofinder_archive_is_validated_and_published(
    synthetic_config: Path, tmp_path: Path
) -> None:
    """A reviewed OrthoFinder archive is safely extracted into the standard stage contract."""
    source = tmp_path / "archive_source" / "Results_Feb26"
    required = (
        "WorkingDirectory/SpeciesIDs.txt",
        "WorkingDirectory/SequenceIDs.txt",
        "Orthogroups/Orthogroups.tsv",
        "Phylogenetic_Hierarchical_Orthogroups/N0.tsv",
        "Species_Tree/SpeciesTree_rooted_node_labels.txt",
    )
    for relative in required:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture for {relative}\n", encoding="utf-8")
    archive = tmp_path / "Results_Feb26.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname="Results_Feb26")
    config = load_config(synthetic_config)
    configured = replace(
        config,
        mode="production",
        resources=replace(config.resources, orthofinder_archive=archive),
    )
    inputs = configured.run_root / "00_inputs"
    write_tsv(
        inputs / "input_validation.tsv",
        [
            {
                "manifest": "orthofinder_archive",
                "path": archive,
                "row_count": "",
                "size_bytes": archive.stat().st_size,
                "sha256": sha256_file(archive),
            }
        ],
        ("manifest", "path", "row_count", "size_bytes", "sha256"),
    )
    stage_root = tmp_path / "stage04"
    run_reused_orthofinder_stage(config=configured, stage_root=stage_root)
    assert (stage_root / "Results" / required[0]).is_file()
    _, authority = read_tsv(stage_root / "orthofinder_authority.tsv")
    assert authority[0]["orthofinder_version"] == "2.5.5"


def test_reused_discovery_and_candidate_authorities(
    synthetic_config: Path, tmp_path: Path
) -> None:
    """Completed Discovery evidence is checksummed, validated and republished unchanged."""
    candidate = tmp_path / "candidate.parquet"
    write_parquet(
        candidate,
        (
            "representative_id VARCHAR, matched_seed_ids_calculated VARCHAR, "
            "matched_seed_id_count INTEGER, reviewed_seed_count INTEGER, "
            "ubiquitin_go_positive_seed_count INTEGER, "
            "seed_with_exclusion_go_term_count INTEGER, strict_member_count INTEGER, "
            "strict_named_species_count INTEGER"
        ),
        [("cluster_1", "Q9SA03", 1, 1, 1, 0, 5, 2)],
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"package_version": "0.4.0"}), encoding="utf-8")
    base = load_config(synthetic_config)
    config = replace(
        base,
        mode="production",
        resources=replace(
            base.resources,
            candidate_evidence=candidate,
            candidate_evidence_manifest=manifest,
        ),
    )
    discovery = tmp_path / "discovery"
    candidate_stage = tmp_path / "candidate_stage"
    run_reused_discovery_stage(config=config, stage_root=discovery)
    run_candidate_evidence_stage(config=config, stage_root=candidate_stage)
    assert (discovery / "discovery_authority.tsv").is_file()
    published = (
        candidate_stage
        / "candidate_evidence"
        / "e3_cluster_candidate_evidence.parquet"
    )
    assert sha256_file(published) == sha256_file(candidate)
    with pytest.raises(StageError, match="missing columns"):
        bad = tmp_path / "bad.parquet"
        write_parquet(bad, "representative_id VARCHAR", [("cluster",)])
        run_candidate_evidence_stage(
            config=replace(
                config,
                resources=replace(config.resources, candidate_evidence=bad),
            ),
            stage_root=tmp_path / "bad_stage",
        )


def test_fasta_catalogue_and_recursive_lookup_errors(tmp_path: Path) -> None:
    """Small production readers reject malformed or ambiguous authorities."""
    fasta = tmp_path / "bad.fasta"
    fasta.write_text("MPEPTIDE\n", encoding="utf-8")
    with pytest.raises(StageError, match="precede"):
        list(iter_fasta(fasta))
    with pytest.raises(StageError, match="observed 0"):
        find_one(root=tmp_path, name="missing.tsv")
    first = tmp_path / "a" / "same.tsv"
    second = tmp_path / "b" / "same.tsv"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("x\n", encoding="utf-8")
    second.write_text("x\n", encoding="utf-8")
    with pytest.raises(StageError, match="observed 2"):
        find_one(root=tmp_path, name="same.tsv")
    catalogue = tmp_path / "catalogue.tsv"
    write_tsv(catalogue, [{"pfam_accession": "PF1"}], ("pfam_accession",))
    with pytest.raises(StageError, match="missing columns"):
        load_domain_catalogue(catalogue)


def test_orthofinder_archive_rejects_unsafe_member(
    synthetic_config: Path, tmp_path: Path
) -> None:
    """Archive reuse rejects path traversal before extracting any scientific result."""
    payload = tmp_path / "payload.txt"
    payload.write_text("unsafe\n", encoding="utf-8")
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(payload, arcname="../escape.txt")
    base = load_config(synthetic_config)
    config = replace(
        base,
        mode="production",
        resources=replace(base.resources, orthofinder_archive=archive),
    )
    with pytest.raises(StageError, match="Unsafe path"):
        run_reused_orthofinder_stage(config=config, stage_root=tmp_path / "stage")
