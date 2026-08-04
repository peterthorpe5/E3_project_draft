"""Tests for reusable orthology, expression, ranking and structure adapters."""

from __future__ import annotations

import json
import shutil
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
    _configure_expression_duckdb,
    _create_empty_expression_view,
    _expression_paths_for_species,
    find_one,
    find_orthology_table,
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
    orthology = config.run_root / "05_orthology" / "orthology" / "tables"
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
    component_stages = (
        "03_map_candidates",
        "05_publish_portable_outputs",
    )
    for component_stage in component_stages:
        duplicate_root = (
            config.run_root
            / "05_orthology"
            / "orthology"
            / "stages"
            / component_stage
            / "tables"
        )
        duplicate_root.mkdir(parents=True, exist_ok=True)
        for source in orthology.glob("*.parquet"):
            shutil.copyfile(source, duplicate_root / source.name)
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
        "expression_minimum DOUBLE, expression_lower_quartile DOUBLE, "
        "expression_median DOUBLE, expression_upper_quartile DOUBLE, "
        "expression_maximum DOUBLE, expression_value_statistic VARCHAR, "
        "expression_summary_type VARCHAR, expression_unit VARCHAR, source_file VARCHAR, "
        "source_file_sha256 VARCHAR"
    )

    def expression_row(
        *, accession: str, species: str, gene: str, context: str, value: float, unit: str
    ) -> tuple[Any, ...]:
        """Build one internally consistent Atlas five-number fixture row."""

        return (
            accession,
            species,
            gene,
            gene,
            context,
            value,
            value,
            value,
            value,
            value,
            value,
            "median",
            "atlas_five_number_summary",
            unit,
            "fixture",
            "a" * 64,
        )

    arabidopsis_dir = (
        expression_root
        / "atlas_expression_long"
        / "species_column=Arabidopsis_thaliana"
    )
    write_parquet(
        arabidopsis_dir / "tpms.parquet",
        expression_schema,
        [
            expression_row(
                accession="E-MTAB-1",
                species="Arabidopsis_thaliana",
                gene="AT1G31090",
                context="g1",
                value=0.4,
                unit="TPM",
            ),
            expression_row(
                accession="E-MTAB-1",
                species="Arabidopsis_thaliana",
                gene="AT1G31090",
                context="g2",
                value=0.5,
                unit="TPM",
            ),
        ],
    )
    write_parquet(
        arabidopsis_dir / "fpkms.parquet",
        expression_schema,
        [
            expression_row(
                accession="E-MTAB-1",
                species="Arabidopsis_thaliana",
                gene="AT1G31090",
                context=context,
                value=999.0,
                unit="FPKM",
            )
            for context in ("g1", "g2")
        ],
    )
    for accession, species, gene, context in (
        ("E-MTAB-2", "Oryza_sativa", "LOC_Os01g01010", "g1"),
        ("E-MTAB-3", "Zea_mays", "IRRELEVANT_GENE", "g1"),
    ):
        write_parquet(
            expression_root
            / "atlas_expression_long"
            / f"species_column={species}"
            / "part.parquet",
            expression_schema,
            [
                expression_row(
                    accession=accession,
                    species=species,
                    gene=gene,
                    context=context,
                    value=5.0,
                    unit="TPM",
                )
            ],
        )
    metadata_schema = (
        "experiment_accession VARCHAR, species_column VARCHAR, "
        "sample_or_condition VARCHAR, atlas_group_label VARCHAR, assay_ids VARCHAR, "
        "assay_count INTEGER, organism_part VARCHAR, developmental_stage VARCHAR, "
        "genotype VARCHAR, cultivar VARCHAR, treatment VARCHAR, condition VARCHAR, "
        "source_file VARCHAR, source_file_sha256 VARCHAR, configuration_file VARCHAR, "
        "configuration_file_sha256 VARCHAR, expression_file_sha256 VARCHAR"
    )
    for species, accession, groups in (
        (
            "Arabidopsis_thaliana",
            "E-MTAB-1",
            (("g1", "leaf"), ("g2", "root")),
        ),
        ("Oryza_sativa", "E-MTAB-2", (("g1", "root"),)),
    ):
        write_parquet(
            expression_root
            / "atlas_sample_metadata_wide"
            / f"species_column={species}"
            / "part.parquet",
            metadata_schema,
            [
                (
                    accession,
                    species,
                    group_id,
                    tissue,
                    f"{accession}_{group_id}_assay",
                    1,
                    tissue,
                    "adult",
                    "wild type",
                    "",
                    "control",
                    "treatment=control",
                    "metadata_fixture",
                    "b" * 64,
                    "configuration_fixture",
                    "c" * 64,
                    "a" * 64,
                )
                for group_id, tissue in groups
            ],
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
        analysis=replace(
            config.analysis,
            expression=replace(
                config.analysis.expression,
                minimum_expression_value=0.5,
                broad_positive_fraction=0.5,
            ),
            prioritisation=prioritisation,
        ),
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
    arabidopsis_summary = next(
        row for row in summaries if row["species_column"] == "Arabidopsis_thaliana"
    )
    assert arabidopsis_summary["selected_expression_units"] == "TPM"
    assert arabidopsis_summary["context_count"] == "2"
    assert arabidopsis_summary["positive_context_count"] == "1"
    assert arabidopsis_summary["positive_context_fraction"] == "0.5"
    _, contexts = read_tsv(
        stage_root / "tables" / "candidate_expression_context_summary.preview.tsv"
    )
    assert len(contexts) == 3
    assert {row["sample_or_condition"] for row in contexts} == {"g1", "g2"}
    assert {row["organism_part"] for row in contexts} == {"leaf", "root"}
    assert all(row["metadata_status"] == "MAPPED_WITH_TISSUE" for row in contexts)
    assert all(row["expression_unit"] == "TPM" for row in contexts)
    boundary = next(
        row
        for row in contexts
        if row["species_column"] == "Arabidopsis_thaliana"
        and row["sample_or_condition"] == "g2"
    )
    assert boundary["expression_value"] == "0.5"
    assert boundary["expression_positive"].lower() == "true"
    _, validation_rows = read_tsv(
        stage_root / "qc" / "expression_validation.tsv"
    )
    validation = validation_rows[0]
    assert validation["target_member_species_count"] == "2"
    assert validation["expression_manifest_file_count"] == "4"
    assert validation["expression_scanned_file_count"] == "3"
    assert validation["expression_skipped_file_count"] == "1"
    assert validation["expression_scanned_species_count"] == "2"
    assert validation["duckdb_memory_limit_mb"] == "6000"
    assert validation["selected_experiment_count"] == "2"
    assert validation["fpkm_fallback_experiment_count"] == "0"
    assert validation["sample_metadata_scanned_file_count"] == "2"
    assert validation["mapped_tissue_context_count"] == "3"
    assert validation["metadata_unmapped_context_count"] == "0"
    assert not (stage_root / "duckdb_spill").exists()


def test_expression_partition_selection_and_duckdb_limits(
    synthetic_config: Path, tmp_path: Path
) -> None:
    """Stage 07 prunes irrelevant species and reserves memory for process overhead."""
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    records = [
        {
            "resource_type": "atlas_expression_long",
            "species_column": "Species_a",
            "path": str(first),
        },
        {
            "resource_type": "atlas_expression_long",
            "species_column": "Species_b",
            "path": str(second),
        },
        {
            "resource_type": "atlas_sample_metadata_long",
            "species_column": "Species_a",
            "path": str(tmp_path / "metadata.parquet"),
        },
    ]
    assert _expression_paths_for_species(
        manifest_records=records,
        selected_species={"species_a", ""},
    ) == (first,)

    config = load_config(synthetic_config)
    stage_root = tmp_path / "stage"
    connection = duckdb.connect(":memory:")
    try:
        memory_limit_mb, spill_directory = _configure_expression_duckdb(
            connection=connection,
            config=config,
            stage_root=stage_root,
        )
        assert memory_limit_mb == 6000
        assert spill_directory.is_dir()
        assert connection.execute(
            "SELECT current_setting('threads')"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT current_setting('preserve_insertion_order')"
        ).fetchone()[0] is False
    finally:
        connection.close()


def test_empty_expression_view_preserves_the_atlas_contract() -> None:
    """A species without a resource partition must remain queryable as missing evidence."""
    connection = duckdb.connect(":memory:")
    try:
        _create_empty_expression_view(connection=connection)
        description = connection.execute("DESCRIBE atlas_expression").fetchall()
        assert [str(row[0]) for row in description] == [
            "experiment_accession",
            "species_column",
            "gene_id",
            "gene_name",
            "sample_or_condition",
            "expression_value",
            "expression_minimum",
            "expression_lower_quartile",
            "expression_median",
            "expression_upper_quartile",
            "expression_maximum",
            "expression_value_statistic",
            "expression_summary_type",
            "expression_unit",
            "source_file",
            "source_file_sha256",
        ]
        assert connection.execute(
            "SELECT count(*) FROM atlas_expression"
        ).fetchone()[0] == 0
    finally:
        connection.close()


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


def test_off_target_domain_rows_cannot_change_a_target_species_gate(
    synthetic_config: Path,
) -> None:
    """A supported non-target species must not rescue target-domain failure."""
    config = load_config(synthetic_config)
    prioritisation = replace(
        config.analysis.prioritisation,
        target_species=("Species_a", "Species_b"),
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
            "matched_seed_ids_calculated": "Q1",
            "matched_seed_id_count": 1,
            "reviewed_seed_count": 1,
            "ubiquitin_go_positive_seed_count": 1,
            "seed_with_exclusion_go_term_count": 0,
        },
        primary={
            "record_type": "HIERARCHICAL_ORTHOGROUP",
            "group_id": "N0.HOG0001",
            "alternative_group_count": 0,
        },
        full_species={"Species_a", "Species_b", "Off_target"},
        domain_rows=[
            {
                "species_column": "Species_a",
                "domain_support_status": "ANNOTATED_NO_CATALOGUED_E3_DOMAIN",
            },
            {
                "species_column": "Off_target",
                "domain_support_status": "SUPPORTED",
            },
        ],
        expression_rows=[
            {
                "species_column": species,
                "mapping_status": "MAPPED_UNIQUE",
                "evidence_status": "BROAD_EXPRESSION_SUPPORTED",
                "broad_expression_supported": True,
            }
            for species in ("Species_a", "Species_b")
        ],
        expression_available_species={"Species_a", "Species_b", "Off_target"},
    )

    assert record["domain_assessed_species_count"] == 1
    assert record["domain_supported_species_count"] == 0
    assert record["domain_species_fraction"] == 0.0
    assert record["domain_annotation_coverage_fraction"] == 0.5
    assert record["grant_aligned_criteria_status"] == "FAIL"
    assert (
        record["exclusion_reasons"]
        == "domain_species_fraction_below_threshold"
    )


def test_no_expression_records_are_unavailable_not_measured_zero(
    synthetic_config: Path,
) -> None:
    """A mapped gene with no Atlas rows must not enter the negative denominator."""
    config = load_config(synthetic_config)
    prioritisation = replace(
        config.analysis.prioritisation,
        target_species=("Species_a", "Species_b"),
        mandatory_species=("Species_a",),
        minimum_target_species_fraction=1.0,
        minimum_domain_species_fraction=1.0,
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
            "matched_seed_ids_calculated": "Q1",
            "matched_seed_id_count": 1,
            "reviewed_seed_count": 1,
            "ubiquitin_go_positive_seed_count": 1,
            "seed_with_exclusion_go_term_count": 0,
        },
        primary={
            "record_type": "HIERARCHICAL_ORTHOGROUP",
            "group_id": "N0.HOG0001",
            "alternative_group_count": 0,
        },
        full_species={"Species_a", "Species_b"},
        domain_rows=[
            {
                "species_column": species,
                "domain_support_status": "SUPPORTED",
            }
            for species in ("Species_a", "Species_b")
        ],
        expression_rows=[
            {
                "species_column": "Species_a",
                "mapping_status": "MAPPED_UNIQUE",
                "evidence_status": "BROAD_EXPRESSION_SUPPORTED",
                "broad_expression_supported": True,
            },
            {
                "species_column": "Species_b",
                "mapping_status": "MAPPED_UNIQUE",
                "evidence_status": "NO_EXPRESSION_RECORDS",
                "broad_expression_supported": None,
            },
        ],
        expression_available_species={"Species_a", "Species_b"},
    )
    assert record["expression_assessed_species_count"] == 1
    assert record["expression_supported_species_count"] == 1
    assert record["expression_species_fraction"] == 1.0
    assert record["expression_unavailable_species"] == "Species_b"
    assert "expression_evidence_unavailable_for_species=Species_b" in record[
        "missing_evidence"
    ]


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
        {
            "accession": "Q9SA03",
            "pocket_number": 3,
            "mapping_status": "MAPPED",
            "model_label_chain": "A",
            "model_label_seq_id": "",
            "model_auth_chain": "A",
            "model_auth_seq_id": "4",
            "model_insertion_code": "",
            "model_residue_name": "ALA",
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
    assert rows[2]["fasta_position"] is None
    assert rows[2]["sequence_coordinate_status"] == "LABEL_SEQUENCE_ID_UNAVAILABLE"


def test_repeated_accession_pocket_maps_to_each_group_context() -> None:
    """One physical pocket can support several retained evolutionary-group contexts."""
    selected = [
        {
            "cluster_id": cluster_id,
            "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
            "primary_group_id": group_id,
            "candidate_accession": "A0A8I6YKD5",
            "species_column": "Species_a",
            "pocket_number": 5,
        }
        for cluster_id, group_id in (
            ("cluster_1", "N0.HOG0001"),
            ("cluster_2", "N0.HOG0002"),
        )
    ]
    mappings = [
        {
            "accession": "A0A8I6YKD5",
            "pocket_number": 5,
            "mapping_status": "MAPPED",
            "model_label_chain": "A",
            "model_label_seq_id": "2",
            "model_auth_chain": "A",
            "model_auth_seq_id": "2",
            "model_insertion_code": "",
            "model_residue_name": "SER",
        }
    ]

    rows = map_pocket_residues_to_fasta(
        selected_records=selected,
        mapping_records=mappings,
        sequences={"A0A8I6YKD5": "MSA"},
    )

    assert len(rows) == 2
    assert {
        (row["cluster_id"], row["primary_group_id"]) for row in rows
    } == {
        ("cluster_1", "N0.HOG0001"),
        ("cluster_2", "N0.HOG0002"),
    }
    assert all(row["sequence_coordinate_status"] == "MAPPED_EXACT" for row in rows)


def test_duplicate_selected_group_context_is_rejected() -> None:
    """An exact duplicate context remains an error rather than being silently discarded."""
    selected = {
        "cluster_id": "cluster_1",
        "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
        "primary_group_id": "N0.HOG0001",
        "candidate_accession": "A0A8I6YKD5",
        "species_column": "Species_a",
        "pocket_number": 5,
    }

    with pytest.raises(StageError, match="Duplicate selected pocket group context"):
        map_pocket_residues_to_fasta(
            selected_records=[selected, dict(selected)],
            mapping_records=[],
            sequences={"A0A8I6YKD5": "MSA"},
        )


def test_repeated_shard_evidence_uses_unique_top_k_pockets(
    synthetic_config: Path,
    tmp_path: Path,
) -> None:
    """Repeated identical shards cannot consume several ranks for one physical pocket."""
    config = load_config(synthetic_config)
    structural = tmp_path / "structural_repeated.parquet"
    joined = tmp_path / "joined_repeated.parquet"
    quality = tmp_path / "quality_repeated.parquet"
    output = tmp_path / "ranked_unique.parquet"
    write_parquet(
        structural,
        (
            "cluster_id VARCHAR, primary_group_type VARCHAR, primary_group_id VARCHAR, "
            "candidate_accession VARCHAR, species_column VARCHAR"
        ),
        [
            (
                "cluster_1",
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0001",
                "A0A8I6YKD5",
                "Species_a",
            ),
            (
                "cluster_2",
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0002",
                "A0A8I6YKD5",
                "Species_a",
            ),
        ],
    )
    joined_rows = [
        ("resource_a", "A0A8I6YKD5", 5, 0.9, 0.8, 0.8, "MATCHED"),
        ("resource_b", "A0A8I6YKD5", 5, 0.9, 0.8, 0.8, "MATCHED"),
        ("resource_a", "A0A8I6YKD5", 8, 0.7, 0.6, 0.6, "MATCHED"),
        ("resource_b", "A0A8I6YKD5", 8, 0.7, 0.6, 0.6, "MATCHED"),
    ]
    write_parquet(
        joined,
        (
            "source_resource_id VARCHAR, accession VARCHAR, pocket_number INTEGER, "
            "druggability_score DOUBLE, p2rank_score DOUBLE, p2rank_probability DOUBLE, "
            "p2rank_match_status VARCHAR"
        ),
        joined_rows,
    )
    quality_rows = [
        ("resource_a", "A0A8I6YKD5", 5, 1.0, 0.9, 90.0),
        ("resource_b", "A0A8I6YKD5", 5, 1.0, 0.9, 90.0),
        ("resource_a", "A0A8I6YKD5", 8, 1.0, 0.8, 85.0),
        ("resource_b", "A0A8I6YKD5", 8, 1.0, 0.8, 85.0),
    ]
    write_parquet(
        quality,
        (
            "source_resource_id VARCHAR, accession VARCHAR, pocket_number INTEGER, "
            "mapping_fraction DOUBLE, conservative_fraction_plddt_ge_70 DOUBLE, "
            "mapped_mean_plddt DOUBLE"
        ),
        quality_rows,
    )

    build_selected_pockets(
        config=config,
        structural_accessions=structural,
        joined_pockets=joined,
        pocket_quality=quality,
        output_path=output,
        maximum_rank=2,
    )

    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            f"SELECT cluster_id, pocket_number, selection_rank "
            f"FROM read_parquet('{output}') "
            "ORDER BY cluster_id, selection_rank"
        ).fetchall()
    finally:
        connection.close()
    assert rows == [
        ("cluster_1", 5, 1),
        ("cluster_1", 8, 2),
        ("cluster_2", 5, 1),
        ("cluster_2", 8, 2),
    ]


def test_conflicting_repeated_shard_evidence_is_rejected(
    synthetic_config: Path,
    tmp_path: Path,
) -> None:
    """Conflicting accession/pocket results stop aggregation for scientific review."""
    config = load_config(synthetic_config)
    structural = tmp_path / "structural_conflict.parquet"
    joined = tmp_path / "joined_conflict.parquet"
    quality = tmp_path / "quality_conflict.parquet"
    write_parquet(
        structural,
        (
            "cluster_id VARCHAR, primary_group_type VARCHAR, primary_group_id VARCHAR, "
            "candidate_accession VARCHAR, species_column VARCHAR"
        ),
        [
            (
                "cluster_1",
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0001",
                "A0A8I6YKD5",
                "Species_a",
            )
        ],
    )
    write_parquet(
        joined,
        (
            "source_resource_id VARCHAR, accession VARCHAR, pocket_number INTEGER, "
            "druggability_score DOUBLE, p2rank_score DOUBLE, p2rank_probability DOUBLE, "
            "p2rank_match_status VARCHAR"
        ),
        [
            ("resource_a", "A0A8I6YKD5", 5, 0.9, 0.8, 0.8, "MATCHED"),
            ("resource_b", "A0A8I6YKD5", 5, 0.4, 0.8, 0.8, "MATCHED"),
        ],
    )
    write_parquet(
        quality,
        (
            "accession VARCHAR, pocket_number INTEGER, mapping_fraction DOUBLE, "
            "conservative_fraction_plddt_ge_70 DOUBLE, mapped_mean_plddt DOUBLE"
        ),
        [("A0A8I6YKD5", 5, 1.0, 0.9, 90.0)],
    )

    with pytest.raises(
        StageError,
        match="Conflicting duplicate joined-pocket evidence for A0A8I6YKD5/5",
    ):
        build_selected_pockets(
            config=config,
            structural_accessions=structural,
            joined_pockets=joined,
            pocket_quality=quality,
            output_path=tmp_path / "must_not_exist.parquet",
        )

    write_parquet(
        joined,
        (
            "source_resource_id VARCHAR, accession VARCHAR, pocket_number INTEGER, "
            "druggability_score DOUBLE, p2rank_score DOUBLE, p2rank_probability DOUBLE, "
            "p2rank_match_status VARCHAR"
        ),
        [
            ("resource_a", "A0A8I6YKD5", 5, 0.9, 0.8, 0.8, "MATCHED"),
            ("resource_b", "A0A8I6YKD5", 5, 0.9, 0.8, 0.8, "MATCHED"),
        ],
    )
    write_parquet(
        quality,
        (
            "source_resource_id VARCHAR, accession VARCHAR, pocket_number INTEGER, "
            "mapping_fraction DOUBLE, conservative_fraction_plddt_ge_70 DOUBLE, "
            "mapped_mean_plddt DOUBLE"
        ),
        [
            ("resource_a", "A0A8I6YKD5", 5, 1.0, 0.9, 90.0),
            ("resource_b", "A0A8I6YKD5", 5, 0.4, 0.9, 90.0),
        ],
    )
    with pytest.raises(
        StageError,
        match="Conflicting duplicate pocket-quality evidence for A0A8I6YKD5/5",
    ):
        build_selected_pockets(
            config=config,
            structural_accessions=structural,
            joined_pockets=joined,
            pocket_quality=quality,
            output_path=tmp_path / "quality_conflict_must_not_exist.parquet",
        )

    write_parquet(
        quality,
        (
            "accession VARCHAR, pocket_number INTEGER, mapping_fraction DOUBLE, "
            "conservative_fraction_plddt_ge_70 DOUBLE, mapped_mean_plddt DOUBLE"
        ),
        [("A0A8I6YKD5", None, 1.0, 0.9, 90.0)],
    )
    with pytest.raises(StageError, match="non-integer pocket numbers"):
        build_selected_pockets(
            config=config,
            structural_accessions=structural,
            joined_pockets=joined,
            pocket_quality=quality,
            output_path=tmp_path / "malformed_must_not_exist.parquet",
        )


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


def test_orthology_lookup_ignores_component_stage_copies(tmp_path: Path) -> None:
    """Only a public stage-05 contract file is a downstream orthology authority."""
    name = "candidate_membership_mapping.parquet"
    public = tmp_path / "orthology" / "tables" / name
    public.parent.mkdir(parents=True)
    public.write_bytes(b"public authority")
    for component_stage in ("03_map_candidates", "05_publish_portable_outputs"):
        internal = (
            tmp_path
            / "orthology"
            / "stages"
            / component_stage
            / "tables"
            / name
        )
        internal.parent.mkdir(parents=True)
        internal.write_bytes(b"component provenance")

    assert find_orthology_table(root=tmp_path, name=name) == public

    direct_public = tmp_path / "tables" / name
    direct_public.parent.mkdir(parents=True)
    direct_public.write_bytes(b"second public authority")
    with pytest.raises(StageError, match="observed 2"):
        find_orthology_table(root=tmp_path, name=name)


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
