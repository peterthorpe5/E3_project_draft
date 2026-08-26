"""Tests for the separate human-and-plant structural extension."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import duckdb
import pytest
import yaml

from e3workflow.config import load_config
from e3workflow.control import initialise_stage_tokens
from e3workflow.errors import StageError
from e3workflow.human_plant_extension import prepare_human_plant_extension
from e3workflow.io_utils import read_tsv
from e3workflow.tabular import quote_literal


def _write_parquet(
    *,
    path: Path,
    schema: str,
    rows: list[tuple[object, ...]],
) -> None:
    """Write one compact typed Parquet fixture through DuckDB."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"CREATE TABLE fixture ({schema})")
        placeholders = ", ".join("?" for _column in schema.split(","))
        connection.executemany(
            f"INSERT INTO fixture VALUES ({placeholders})",
            rows,
        )
        connection.execute(
            f"COPY fixture TO {quote_literal(path)} (FORMAT PARQUET)"
        )
    finally:
        connection.close()


def _prepare_parent_authorities(
    *,
    synthetic_config: Path,
    bad_checksum: bool = False,
) -> Path:
    """Create the minimum completed-run authorities consumed by preparation."""
    config = load_config(synthetic_config)
    run_root = config.run_root
    _write_parquet(
        path=(
            run_root
            / "08_shortlist_gate"
            / "tables"
            / "structural_analysis_accessions.parquet"
        ),
        schema=(
            "cluster_id VARCHAR, primary_group_type VARCHAR, "
            "primary_group_id VARCHAR"
        ),
        rows=[
            ("cluster_1", "HIERARCHICAL_ORTHOGROUP", "N0.HOG0001"),
            ("cluster_2", "HIERARCHICAL_ORTHOGROUP", "N0.HOG0002"),
        ],
    )
    sequence = "MPEPTIDE"
    digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
    if bad_checksum:
        digest = "0" * 64
    _write_parquet(
        path=(
            run_root
            / "05_orthology"
            / "orthology"
            / "tables"
            / "candidate_group_member_sequences.parquet"
        ),
        schema=(
            "cluster_id VARCHAR, record_type VARCHAR, group_id VARCHAR, "
            "species VARCHAR, parsed_accession VARCHAR, parsed_entry VARCHAR, "
            "raw_identifier VARCHAR, sequence_length BIGINT, "
            "sequence_sha256 VARCHAR, protein_sequence VARCHAR"
        ),
        rows=[
            (
                "cluster_1",
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0001",
                "Homo_sapiens",
                "HUMAN1",
                "HUMAN1_ENTRY",
                "sp|HUMAN1|HUMAN1_ENTRY",
                len(sequence),
                digest,
                sequence,
            ),
            (
                "cluster_1",
                "ORTHOGROUP",
                "N0.HOG0001",
                "Homo_sapiens",
                "WRONG_TYPE",
                "",
                "WRONG_TYPE",
                len(sequence),
                hashlib.sha256(sequence.encode("ascii")).hexdigest(),
                sequence,
            ),
        ],
    )
    _write_parquet(
        path=(
            run_root
            / "10_integrated_resource"
            / "final_results"
            / "top_computational_review_shortlist.parquet"
        ),
        schema=(
            "final_evolutionary_rank BIGINT, lead_cluster_id VARCHAR, "
            "primary_group_type VARCHAR, primary_group_id VARCHAR"
        ),
        rows=[
            (1, "cluster_1", "HIERARCHICAL_ORTHOGROUP", "N0.HOG0001"),
            (2, "cluster_2", "HIERARCHICAL_ORTHOGROUP", "N0.HOG0002"),
        ],
    )
    _write_parquet(
        path=(
            run_root
            / "09b_structural_alignment"
            / "structural_alignment"
            / "tables"
            / "structural_alignment_summary.parquet"
        ),
        schema=(
            "cluster_id VARCHAR, primary_group_type VARCHAR, "
            "primary_group_id VARCHAR, reference_accession VARCHAR"
        ),
        rows=[
            (
                "cluster_1",
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0001",
                "PLANT_REF",
            ),
            (
                "cluster_2",
                "HIERARCHICAL_ORTHOGROUP",
                "N0.HOG0002",
                "PLANT_REF_2",
            ),
        ],
    )
    return run_root


def test_prepare_selects_exact_human_hog_and_preserves_plant_reference(
    synthetic_config: Path,
    tmp_path: Path,
) -> None:
    """Preparation uses exact group type, validated sequence and plant reference."""
    _prepare_parent_authorities(synthetic_config=synthetic_config)
    output = tmp_path / "human_extension"
    payload = prepare_human_plant_extension(
        parent_config_path=synthetic_config,
        output_root=output,
        review_limit=2,
    )
    assert payload["human_accession_task_count"] == 1
    assert payload["qualifying_group_count"] == 1
    _fields, tasks = read_tsv(output / "manifests" / "human_accession_tasks.tsv")
    assert tasks[0]["accession"] == "HUMAN1"
    _fields, groups = read_tsv(output / "manifests" / "groups.tsv")
    assert groups[0]["primary_group_id"] == "N0.HOG0001"
    assert groups[0]["reference_accession"] == "PLANT_REF"


def test_prepare_rejects_sequence_checksum_mismatch(
    synthetic_config: Path,
    tmp_path: Path,
) -> None:
    """A corrupted human sequence authority cannot enter structural work."""
    _prepare_parent_authorities(
        synthetic_config=synthetic_config,
        bad_checksum=True,
    )
    with pytest.raises(StageError, match="checksum mismatch"):
        prepare_human_plant_extension(
            parent_config_path=synthetic_config,
            output_root=tmp_path / "human_extension",
            review_limit=2,
        )


def test_extension_snakefiles_support_standalone_and_full_run(
    package_root: Path,
) -> None:
    """One shared rule set powers both attach-only and start-to-finish runs."""
    main = (package_root / "workflow" / "Snakefile").read_text(encoding="utf-8")
    standalone = (
        package_root / "workflow" / "HumanPlantExtension.smk"
    ).read_text(encoding="utf-8")
    rules = (
        package_root / "workflow" / "human_plant_extension_rules.smk"
    ).read_text(encoding="utf-8")
    assert 'include: "human_plant_extension_rules.smk"' in main
    assert 'include: "human_plant_extension_rules.smk"' in standalone
    assert "checkpoint prepare_human_plant_extension" in rules
    assert "rule run_human_ligandability_extension_task" in rules
    assert "rule run_human_plant_structural_extension_task" in rules
    assert "rule build_plant_baseline_review" in rules
    assert "rule build_human_plant_review" in rules
    assert "HUMAN_PLANT_PLANT_REVIEW_MANIFEST" in main
    assert "python -" not in rules


def test_extension_launchers_and_reviewed_cluster_configuration(
    package_root: Path,
) -> None:
    """Public launchers are executable and the reviewed parent stays separate."""
    runner = package_root / "run_human_plant_structural_extension.sh"
    submitter = package_root / "submit_human_plant_extension_slurm.sh"
    controller = (
        package_root
        / "scripts"
        / "slurm_human_plant_extension_controller.sh"
    )
    for script in (runner, submitter, controller):
        assert os.access(script, os.X_OK)
        syntax = subprocess.run(
            ["bash", "-n", str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert syntax.returncode == 0, syntax.stderr
    help_result = subprocess.run(
        [str(runner), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0
    assert "Existing plant outputs are never modified" in " ".join(
        help_result.stdout.split()
    )
    submit_help = subprocess.run(
        [str(submitter), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert submit_help.returncode == 0
    assert "continues after logout" in submit_help.stdout
    submit_source = submitter.read_text(encoding="utf-8")
    assert "another controller submission is in progress" in submit_source
    assert "controller job %s is still active" in submit_source

    configuration = yaml.safe_load(
        (
            package_root
            / "config"
            / "grant_human_plant_structural_top200_v0_16_0_20260826.cluster.yaml"
        ).read_text(encoding="utf-8")
    )["human_plant_extension"]
    assert configuration["enabled"] is True
    assert configuration["review_limit"] == 200
    assert "all1972_v0_15_0_20260811.yaml" in configuration[
        "parent_workflow_config"
    ]
    assert "v0_16_0_20260826" in configuration["output_root"]
    assert configuration["output_root"] not in configuration[
        "parent_workflow_config"
    ]


def test_standalone_extension_snakefile_builds_checkpoint_dag(
    package_root: Path,
    synthetic_config: Path,
    tmp_path: Path,
) -> None:
    """The attach-only entry point parses and plans from a completed parent."""
    snakemake = shutil.which("snakemake")
    if snakemake is None:
        pytest.skip("Snakemake is not installed")
    parent = load_config(synthetic_config)
    parent_complete = parent.run_root / "11_app_ready" / "stage_manifest.json"
    parent_complete.parent.mkdir(parents=True, exist_ok=True)
    parent_complete.write_text('{"status": "complete"}\n', encoding="utf-8")
    component = tmp_path / "ligandability.yaml"
    component.write_text("input:\n  accession_column: accession\n", encoding="utf-8")
    extension = tmp_path / "extension.yaml"
    extension.write_text(
        yaml.safe_dump(
            {
                "human_plant_extension": {
                    "enabled": True,
                    "parent_workflow_config": str(synthetic_config),
                    "output_root": str(tmp_path / "extension_output"),
                    "ligandability_component_config": str(component),
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    result = subprocess.run(
        [
            snakemake,
            "--snakefile",
            str(package_root / "workflow" / "HumanPlantExtension.smk"),
            "--configfile",
            str(extension),
            "--cores",
            "2",
            "--dry-run",
            "--nolock",
            "--quiet",
            "rules",
        ],
        cwd=package_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_main_snakefile_includes_extension_in_full_dag(
    package_root: Path,
    synthetic_config: Path,
    tmp_path: Path,
) -> None:
    """An enabled extension becomes a true final branch of the main workflow."""
    snakemake = shutil.which("snakemake")
    if snakemake is None:
        pytest.skip("Snakemake is not installed")
    raw = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    component = tmp_path / "ligandability.yaml"
    component.write_text("input:\n  accession_column: accession\n", encoding="utf-8")
    output = tmp_path / "full_dag_human_extension"
    raw["human_plant_extension"] = {
        "enabled": True,
        "output_root": str(output),
        "ligandability_component_config": str(component),
    }
    configuration = synthetic_config.parent / "full_with_human.yaml"
    configuration.write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )
    initialise_stage_tokens(load_config(configuration))
    target = output / "pocket_review" / "provenance" / "run_manifest.json"
    environment = dict(os.environ)
    environment["XDG_CACHE_HOME"] = str(tmp_path / "main_cache")
    result = subprocess.run(
        [
            snakemake,
            "--snakefile",
            str(package_root / "workflow" / "Snakefile"),
            "--configfile",
            str(configuration),
            "--cores",
            "2",
            "--dry-run",
            "--nolock",
            str(target),
        ],
        cwd=package_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
