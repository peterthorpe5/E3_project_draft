"""Offline integration of exact human models, pocket aggregation and method-tagged results."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

import e3workflow.human_plant_extension as extension
from e3workflow.config import load_config
from e3workflow.distributed import STRUCTURAL_DATASETS
from e3workflow.errors import StageError
from e3workflow.io_utils import read_tsv, sha256_file
from e3workflow.ligandability import (
    _copy_strict_selected_pockets,
    build_selected_pockets,
    map_pocket_residues_to_fasta,
)
from e3workflow.tabular import write_records

SEQUENCE = "MPEPTIDE"
RESIDUES = ("MET", "PRO", "GLU", "PRO", "THR", "ILE", "ASP", "GLU")
GROUP = {
    "cluster_id": "cluster_1", "primary_group_type": "HIERARCHICAL_ORTHOGROUP",
    "primary_group_id": "N0.HOG0001",
}


def _publish(*, path: Path, records: list[dict]) -> Path:
    """Write small typed fixture records through the production TSV/Parquet writer."""
    write_records(
        tsv_path=path.with_suffix(".tsv"), parquet_path=path,
        fieldnames=tuple(records[0]), records=records,
    )
    return path


def _ligandability_fixture(*, root: Path, accession: str, offset: float) -> dict[str, Path]:
    """Publish a coherent local-model and pocket component contract without external prediction."""
    model = root / "models" / f"{accession}.pdb"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(
        data="".join(
            f"ATOM  {index:5d}  CA  {residue} A{index:4d}    "
            f"{offset + index * 3.8:8.3f}{float(index % 2):8.3f}{0.0:8.3f}"
            "  1.00 90.00           C\n"
            for index, residue in enumerate(RESIDUES, start=1)
        ) + "END\n", encoding="utf-8",
    )
    mappings = [
        {
            "accession": accession, "pocket_number": 1, "mapping_status": "MAPPED",
            "model_label_chain": "A", "model_label_seq_id": index,
            "model_auth_chain": "A", "model_auth_seq_id": index,
            "model_insertion_code": "", "model_residue_name": residue, "model_plddt": 90.0,
        }
        for index, residue in enumerate(RESIDUES, start=1)
    ]
    datasets = {
        "model_quality": [{"accession": accession, "mean_plddt": 90.0}],
        "alphafold_metadata": [{
            "accession": accession, "selection_rule": "input_record",
            "selection_policy": "explicit_input_record",
        }],
        "accession_status": [{"accession": accession, "status": "SUCCESS"}],
        "joined_pockets": [{
            "accession": accession, "pocket_number": 1, "druggability_score": 0.9,
            "p2rank_score": 5.0, "p2rank_probability": 0.99, "p2rank_match_status": "MATCHED",
        }],
        "pocket_quality": [{
            "accession": accession, "pocket_number": 1, "mapping_fraction": 1.0,
            "conservative_fraction_plddt_ge_70": 1.0, "mapped_mean_plddt": 90.0,
        }],
        "pocket_residue_mappings": mappings,
        "asset_manifest": [{
            "accession": accession, "path": str(model), "sha256": sha256_file(model),
            "bytes": model.stat().st_size, "action": "copied", "url": "",
        }],
    }
    paths = {
        name: _publish(path=root / "tables" / "parquet" / f"{name}.parquet", records=rows)
        for name, rows in datasets.items()
    }
    manifest = root / "provenance" / "run_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(data='{"status": "complete"}', encoding="utf-8")
    return paths


def test_human_plant_component_contract(
    *, synthetic_config: Path, tmp_path: Path, monkeypatch,
) -> None:
    """Preserve exact sequences, references, model bytes and LoL scores through aggregation."""
    mafft = tmp_path / "mafft"
    mafft.write_text(data='#!/usr/bin/env bash\nset -euo pipefail\ncat -- "${@: -1}"\n',
                     encoding="utf-8")
    mafft.chmod(mode=0o755)
    raw = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    raw.setdefault("analysis", {}).setdefault("ligandability", {})["mafft_executable"] = str(mafft)
    synthetic_config.write_text(data=yaml.safe_dump(data=raw), encoding="utf-8")
    config = load_config(path=synthetic_config)
    parent_bytes = synthetic_config.read_bytes()
    parent = config.run_root
    _publish(path=parent / "08_shortlist_gate/tables/structural_analysis_accessions.parquet",
             records=[GROUP])
    _publish(path=parent / "10_integrated_resource/final_results/"
             "top_computational_review_shortlist.parquet",
             records=[{"final_evolutionary_rank": 1, "lead_cluster_id": "cluster_1", **GROUP}])
    _publish(path=parent / "09b_structural_alignment/structural_alignment/tables/"
             "structural_alignment_summary.parquet",
             records=[{**GROUP, "reference_accession": "PLANT_REF"}])
    sequence_rows = [
        {
            "cluster_id": "cluster_1", "record_type": GROUP["primary_group_type"],
            "group_id": GROUP["primary_group_id"], "species": species,
            "parsed_accession": accession, "parsed_entry": accession,
            "raw_identifier": accession, "sequence_length": len(SEQUENCE),
            "sequence_sha256": hashlib.sha256(string=SEQUENCE.encode()).hexdigest(),
            "protein_sequence": SEQUENCE,
        }
        for accession, species in (("HUMAN1", "Homo_sapiens"), ("PLANT_REF", "Species_a"))
    ]
    _publish(path=parent / "05_orthology/orthology/tables/candidate_group_member_sequences.parquet",
             records=sequence_rows)
    plant_component = _ligandability_fixture(
        root=tmp_path / "plant_component", accession="PLANT_REF", offset=0.0,
    )
    plant_tables = parent / "09_ligandability" / "tables"
    requested = _publish(path=plant_tables / "structural_analysis_accessions.parquet", records=[{
        **GROUP, "candidate_accession": "PLANT_REF", "species_column": "Species_a",
    }])
    ranked = plant_tables / "ranked_member_pockets.parquet"
    build_selected_pockets(
        config=config, structural_accessions=requested,
        joined_pockets=plant_component["joined_pockets"],
        pocket_quality=plant_component["pocket_quality"], output_path=ranked, maximum_rank=1,
    )
    selected = plant_tables / "selected_pockets.parquet"
    _copy_strict_selected_pockets(ranked_path=ranked, output_path=selected)
    selected_rows = extension._table_records(path=selected)
    mapping_rows = extension._table_records(path=plant_component["pocket_residue_mappings"])
    coordinates = map_pocket_residues_to_fasta(
        selected_records=selected_rows, mapping_records=mapping_rows,
        sequences={"PLANT_REF": SEQUENCE},
    )
    for name in ("pocket_sequence_coordinates", "ranked_pocket_sequence_coordinates"):
        _publish(path=plant_tables / f"{name}.parquet", records=coordinates)
    for name in ("asset_manifest", "pocket_residue_mappings"):
        shutil.copyfile(src=plant_component[name], dst=plant_tables / f"reused_{name}.parquet")

    output = tmp_path / "extension"
    extension.prepare_human_plant_extension(
        parent_config_path=synthetic_config, output_root=output, review_limit=1,
    )
    manifests = output / "manifests"
    aggregate_arguments = {
        "parent_config_path": synthetic_config,
        "task_manifest": manifests / "human_accession_tasks.tsv",
        "group_member_manifest": manifests / "human_group_members.parquet",
        "group_manifest": manifests / "groups.tsv", "output_root": output,
    }
    with pytest.raises(StageError, match="incomplete"):
        extension.aggregate_human_ligandability(**aggregate_arguments)

    calls = []

    def component(*, argv, **kwargs):
        """Simulate external executables while keeping their published file contracts real."""
        calls.append(argv)
        root = Path(argv[argv.index("--output-dir") + 1])
        if "e3-ligandability" in argv:
            tasks = read_tsv(path=Path(argv[argv.index("--input") + 1]))[1]
            assert tasks[0]["accession"] == "HUMAN1"
            _ligandability_fixture(root=root, accession="HUMAN1", offset=10.0)
            return
        assert "--run-lolalign" in argv
        references = read_tsv(path=Path(argv[argv.index("--reference-manifest") + 1]))[1]
        assert references[0]["reference_accession"] == "PLANT_REF"
        methods = ["US-align", "TM-align", "LoL-align"]
        for dataset in STRUCTURAL_DATASETS:
            records = [{**GROUP, "reference_accession": "PLANT_REF"}]
            if dataset == "structural_alignments":
                records = [
                    {
                        **records[0], "mobile_accession": "HUMAN1", "alignment_tool": method,
                        "lol_normalised_score": 0.88 if method == "LoL-align" else None,
                        "lol_homology_probability": 0.99 if method == "LoL-align" else None,
                    }
                    for method in methods
                ]
            _publish(path=root / "tables" / f"{dataset}.parquet", records=records)
        viewer = root / "interactive" / "structural_alignment_browser.html"
        viewer.parent.mkdir(parents=True)
        viewer.write_text(data="<html><body>Method comparison</body></html>", encoding="utf-8")
        provenance = root / "provenance" / "run_manifest.json"
        provenance.parent.mkdir(parents=True)
        provenance.write_text(data='{"status": "complete"}', encoding="utf-8")

    monkeypatch.setattr(extension, "_run_component", component)
    component_config = tmp_path / "component.yaml"
    component_config.write_text(data="project:\n  name: fixture\n", encoding="utf-8")
    task_arguments = {
        "parent_config_path": synthetic_config,
        "task_manifest": manifests / "human_accession_tasks.tsv", "output_root": output,
        "task_index": 0, "component_config": component_config, "conda_environment": "fixture",
    }
    extension.run_human_ligandability_task(**task_arguments)
    extension.run_human_ligandability_task(**task_arguments)
    assert len(calls) == 1
    component_config.write_text(data="project:\n  name: updated_fixture\n", encoding="utf-8")
    extension.run_human_ligandability_task(**task_arguments)
    assert len(calls) == 2
    monkeypatch.setattr(extension, "_run_component", lambda **kwargs: None)
    with pytest.raises(StageError, match="no run manifest"):
        extension.run_human_ligandability_task(
            **{**task_arguments, "output_root": tmp_path / "failed_component"},
        )
    monkeypatch.setattr(extension, "_run_component", component)
    sequence_loader = extension._load_sequences
    monkeypatch.setattr(extension, "_load_sequences", lambda **kwargs: {"PLANT_REF": SEQUENCE})
    with pytest.raises(StageError, match="lacks exact sequence"):
        extension.aggregate_human_ligandability(**aggregate_arguments)
    monkeypatch.setattr(extension, "_load_sequences", sequence_loader)
    aggregate = extension.aggregate_human_ligandability(**aggregate_arguments)
    assert json.loads(aggregate.read_text(encoding="utf-8"))["combined_selected_pocket_count"] == 2
    combined_tables = output / "ligandability/combined/tables"
    models = extension._table_records(path=combined_tables / "asset_manifest.parquet")
    assert {row["accession"] for row in models} == {"HUMAN1", "PLANT_REF"}
    assert all(sha256_file(Path(row["path"])) == row["sha256"] for row in models)
    group = read_tsv(path=manifests / "groups.tsv")[1][0]
    with pytest.raises(StageError, match="Preserved plant reference"):
        extension._prepare_human_plant_structural_inputs(
            combined_root=output / "ligandability/combined",
            group={**group, "reference_accession": "UNAVAILABLE"},
            destination=tmp_path / "unavailable_reference",
        )
    with pytest.raises(StageError, match="incomplete"):
        extension.aggregate_human_plant_structural(
            group_manifest=manifests / "groups.tsv", output_root=output,
        )
    extension.run_human_plant_structural_task(
        parent_config_path=synthetic_config, group_manifest=manifests / "groups.tsv",
        ligandability_manifest=aggregate, output_root=output, task_index=0,
        conda_environment="fixture", structural_method_options='{"run_lolalign": true}',
    )
    structural = extension.aggregate_human_plant_structural(
        group_manifest=manifests / "groups.tsv", output_root=output,
    )
    assert json.loads(structural.read_text(encoding="utf-8"))["plant_references_preserved"]
    aligned = extension._table_records(
        path=output / "structural_alignment/tables/structural_alignments.parquet",
    )
    assert next(row for row in aligned if row["alignment_tool"] == "LoL-align")[
        "lol_normalised_score"
    ] == 0.88
    assert (output / "structural_alignment/interactive/structural_alignment_browser.html").is_file()
    assert synthetic_config.read_bytes() == parent_bytes
    _publish(
        path=output / "work_cache/human_plant_structural/task_0000/component_output/tables/"
        "structural_alignment_summary.parquet",
        records=[{**GROUP, "reference_accession": "HUMAN1"}],
    )
    with pytest.raises(StageError, match="Plant reference changed"):
        extension.aggregate_human_plant_structural(
            group_manifest=manifests / "groups.tsv", output_root=output,
        )
