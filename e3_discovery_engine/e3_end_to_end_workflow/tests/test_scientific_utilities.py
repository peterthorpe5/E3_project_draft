"""Focused validation branches for reusable scientific-resource helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import duckdb
import pytest

from e3workflow.config import load_config
from e3workflow.errors import ManifestError, StageError
from e3workflow.io_utils import sha256_file, write_tsv
from e3workflow.ligandability import (
    _alignment_position_map,
    _chemical_conservation,
    _column_expression,
    _connected_components,
    _load_sequences,
    _manifest_union_query,
    _pairwise_overlaps,
    _read_query,
    _run_mafft,
    _structural_status,
    measure_pocket_conservation,
    quote_identifier_safe,
    re_safe_filename,
    region_overlap,
)
from e3workflow.resources import (
    RESOURCE_COLUMNS,
    build_domain_cache_manifest,
    build_expression_manifest,
    build_ligandability_manifest,
    paths_for_dataset,
    read_resource_manifest,
    resource_record,
)
from e3workflow.tabular import (
    copy_query_to_parquet,
    parquet_columns,
    parquet_row_count,
    quote_identifier,
    quote_literal,
    write_records,
)


def test_resource_builders_reject_missing_or_incomplete_roots(tmp_path: Path) -> None:
    """Reusable resources must exist and satisfy their dataset-level contracts."""
    with pytest.raises(ManifestError, match="missing or empty"):
        resource_record(
            resource_id="x",
            resource_type="x",
            species_column="",
            dataset="x",
            path=tmp_path / "missing",
        )
    with pytest.raises(ManifestError, match="does not exist"):
        build_expression_manifest(
            expression_root=tmp_path / "missing",
            output_path=tmp_path / "expression.tsv",
        )
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ManifestError, match="No Expression"):
        build_expression_manifest(
            expression_root=empty,
            output_path=tmp_path / "expression.tsv",
        )
    with pytest.raises(ManifestError, match="At least one"):
        build_ligandability_manifest(roots=[], output_path=tmp_path / "ligand.tsv")
    with pytest.raises(ManifestError, match="does not exist"):
        build_ligandability_manifest(
            roots=[tmp_path / "missing"], output_path=tmp_path / "ligand.tsv"
        )
    with pytest.raises(ManifestError, match="lack required"):
        build_ligandability_manifest(
            roots=[empty], output_path=tmp_path / "ligand.tsv"
        )
    with pytest.raises(ManifestError, match="does not exist"):
        build_domain_cache_manifest(
            cache_root=tmp_path / "missing", output_path=tmp_path / "domain.tsv"
        )
    bad_cache = tmp_path / "bad_cache"
    bad_cache.mkdir()
    (bad_cache / "bad.json").write_text("[", encoding="utf-8")
    with pytest.raises(ManifestError, match="Unreadable"):
        build_domain_cache_manifest(
            cache_root=bad_cache, output_path=tmp_path / "domain.tsv"
        )


def test_resource_manifest_validation_states(tmp_path: Path) -> None:
    """Manifest schema, resource type, checksums and inclusion are validated independently."""
    resource = tmp_path / "resource.bin"
    resource.write_bytes(b"resource")
    base = {
        "resource_id": "r1",
        "resource_type": "type_a",
        "species_column": "Species_a",
        "dataset": "data",
        "path": str(resource),
        "sha256": sha256_file(resource),
        "include": "true",
    }
    manifest = tmp_path / "manifest.tsv"
    write_tsv(manifest, [base], RESOURCE_COLUMNS)
    records = read_resource_manifest(
        path=manifest, allowed_resource_types={"type_a"}, verify_checksums=True
    )
    assert paths_for_dataset(records, "data") == [resource]
    with pytest.raises(ManifestError, match="Unsupported"):
        read_resource_manifest(path=manifest, allowed_resource_types={"other"})
    wrong = dict(base, sha256="0" * 64)
    write_tsv(manifest, [wrong], RESOURCE_COLUMNS)
    with pytest.raises(ManifestError, match="mismatch"):
        read_resource_manifest(path=manifest)
    excluded = dict(base, include="false")
    write_tsv(manifest, [excluded], RESOURCE_COLUMNS)
    with pytest.raises(ManifestError, match="selects no"):
        read_resource_manifest(path=manifest)
    manifest.write_text("wrong\theader\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="columns"):
        read_resource_manifest(path=manifest)


def test_tabular_helpers_cover_empty_and_error_contracts(tmp_path: Path) -> None:
    """SQL quoting and atomic Parquet publication fail closed."""
    assert quote_identifier("valid_name") == '"valid_name"'
    assert quote_literal("a'b") == "'a''b'"
    for invalid in ("", "1bad", "bad-name"):
        with pytest.raises(StageError, match="Unsafe SQL identifier"):
            quote_identifier(invalid)
    empty_tsv = tmp_path / "empty.tsv"
    empty_parquet = tmp_path / "empty.parquet"
    assert (
        write_records(
            tsv_path=empty_tsv,
            parquet_path=empty_parquet,
            fieldnames=("name", "count"),
            records=[],
            column_types={"count": "INTEGER"},
        )
        == 0
    )
    assert parquet_columns(empty_parquet) == ("name", "count")
    assert parquet_row_count(empty_parquet) == 0
    with pytest.raises(StageError, match="does not exist"):
        parquet_columns(tmp_path / "missing.parquet")
    bad = tmp_path / "bad.parquet"
    bad.write_text("not parquet", encoding="utf-8")
    with pytest.raises(StageError, match="Could not count"):
        parquet_row_count(bad)
    connection = duckdb.connect(":memory:")
    try:
        with pytest.raises(StageError, match="Could not publish query"):
            copy_query_to_parquet(
                connection=connection,
                query="SELECT * FROM absent_table",
                path=tmp_path / "bad_query.parquet",
            )
    finally:
        connection.close()


def test_ligandability_helpers_and_missing_structure_state(
    synthetic_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pocket helper calculations and explicit missing states are deterministic."""
    assert "COALESCE" in _column_expression(
        {"a", "b"}, ("a", "b"), "NULL", table_alias="x"
    )
    assert _column_expression(set(), ("a",), "NULL", table_alias="x") == "NULL"
    assert quote_identifier_safe('a"b') == '"a""b"'
    with pytest.raises(StageError, match="contains no absent"):
        _manifest_union_query([], "absent")
    query = _manifest_union_query(
        [{"dataset": "d", "resource_id": "r", "path": "/tmp/x.parquet"}],
        "d",
    )
    assert "source_resource_id" in query
    assert _alignment_position_map("A-C.D") == {1: 1, 2: 3, 3: 5}
    assert region_overlap(set(), {1}) == 0.0
    assert region_overlap({1, 2}, {2, 3}) == 0.5
    regions = {"a": {1, 2}, "b": {2, 3}, "c": {9}}
    components = _connected_components(regions=regions, minimum_overlap=0.5)
    assert {frozenset(value) for value in components} == {
        frozenset({"a", "b"}),
        frozenset({"c"}),
    }
    assert _pairwise_overlaps({"a", "b"}, regions) == [0.5]
    chemical = _chemical_conservation(
        component={"a", "b"},
        aligned={"a": "AC", "b": "AV"},
        regions={"a": {1, 2}, "b": {1, 2}},
    )
    assert chemical == 0.75
    assert re_safe_filename("a/b c") == "a_b_c"
    assert re_safe_filename("/" * 3) == "___"
    requested = [
        {
            "cluster_id": "c",
            "primary_group_id": "g",
            "candidate_accession": "Q1",
            "species_column": "Species_a",
        }
    ]
    assert _structural_status(requested=requested, selected=[])[0]["status"] == (
        "MISSING_REUSED_PREDICTION"
    )

    config = load_config(synthetic_config)
    selected = [
        {
            **requested[0],
            "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
            "pocket_number": 1,
            "druggability_score": 0.8,
            "conservative_fraction_plddt_ge_70": 0.9,
            "passes_druggability_threshold": True,
            "passes_mapping_threshold": True,
            "predictor_agreement": True,
        }
    ]
    summaries, members = measure_pocket_conservation(
        config=config,
        selected_records=selected,
        mapping_records=[
            {
                "accession": "Q1",
                "pocket_number": 1,
                "mapping_status": "MAPPED",
                "model_label_seq_id": 2,
            }
        ],
        sequences={"Q1": "MACD"},
        stage_root=tmp_path / "stage",
    )
    assert summaries[0]["conservation_status"] == "INSUFFICIENT_STRUCTURES"
    assert members == []

    input_fasta = tmp_path / "input.fasta"
    input_fasta.write_text(">Q1\nMACD\n", encoding="utf-8")

    def successful_run(**kwargs: Any) -> subprocess.CompletedProcess[str]:
        kwargs["stdout"].write(">Q1\nMACD\n")
        return subprocess.CompletedProcess(kwargs["args"], 0)

    monkeypatch.setattr("e3workflow.ligandability.subprocess.run", successful_run)
    output_fasta = tmp_path / "aligned.fasta"
    _run_mafft(
        executable="mafft",
        input_fasta=input_fasta,
        output_fasta=output_fasta,
        log_path=tmp_path / "mafft.log",
        threads=2,
    )
    assert output_fasta.is_file()

    def failed_run(**kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(kwargs["args"], 1)

    monkeypatch.setattr("e3workflow.ligandability.subprocess.run", failed_run)
    with pytest.raises(StageError, match="MAFFT returned"):
        _run_mafft(
            executable="mafft",
            input_fasta=input_fasta,
            output_fasta=tmp_path / "failed.fasta",
            log_path=tmp_path / "failed.log",
            threads=1,
        )


def test_prepared_sequence_loading_and_bad_parquet(
    synthetic_config: Path, tmp_path: Path
) -> None:
    """Fresh prepared proteomes are preferred and malformed Parquet is labelled."""
    config = load_config(synthetic_config)
    prepared = config.run_root / "01_prepared_proteomes"
    fasta = prepared / "proteomes" / "species.fasta"
    fasta.parent.mkdir(parents=True)
    fasta.write_text(">sp|Q9SA03|FB27_ARATH\nMACD\n", encoding="utf-8")
    write_tsv(
        prepared / "prepared_proteomes.tsv",
        [
            {
                "species_id": "Species_a",
                "prepared_fasta_relative_path": "proteomes/species.fasta",
            }
        ],
        ("species_id", "prepared_fasta_relative_path"),
    )
    assert _load_sequences(config, {"Q9SA03"}) == {"Q9SA03": "MACD"}
    bad = tmp_path / "bad.parquet"
    bad.write_text("bad", encoding="utf-8")
    with pytest.raises(StageError, match="Could not read Parquet"):
        _read_query(bad)
