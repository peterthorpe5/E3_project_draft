"""Tests for the separate human-and-plant structural extension."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable

import duckdb
import pytest
import yaml

import e3workflow.human_plant_extension as human_plant_extension
from e3workflow.config import load_config
from e3workflow.control import initialise_stage_tokens
from e3workflow.errors import StageError
from e3workflow.human_plant_extension import (
    _remove_empty_orchestrator_output_tree,
    build_human_plant_review,
    build_plant_baseline_review,
    prepare_human_plant_extension,
)
from e3workflow.io_utils import read_tsv
from e3workflow.tabular import quote_literal


def _write_parquet(
    *,
    path: Path,
    schema: str,
    rows: list[tuple[object, ...]],
) -> None:
    """Write one compact typed Parquet fixture through DuckDB.

    Args:
        path: Destination Parquet file.
        schema: DuckDB column definitions for the fixture table.
        rows: Typed rows to insert before publishing the table.
    """
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
    """Create the minimum completed-run authorities consumed by preparation.

    Args:
        synthetic_config: Workflow configuration supplied by the shared fixture.
        bad_checksum: Whether to corrupt the exact human sequence checksum.

    Returns:
        Root directory of the synthetic completed parent run.
    """
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
    """Verify exact group selection and preservation of the plant reference.

    Args:
        synthetic_config: Workflow configuration supplied by the shared fixture.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
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
    """Verify that a corrupted human sequence cannot enter structural work.

    Args:
        synthetic_config: Workflow configuration supplied by the shared fixture.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
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


def test_remove_empty_orchestrator_output_tree_removes_nested_placeholder(
    tmp_path: Path,
) -> None:
    """Verify that nested empty Snakemake output directories are removed.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    destination = tmp_path / "pocket_review"
    (destination / "provenance" / "nested").mkdir(parents=True)

    _remove_empty_orchestrator_output_tree(path=destination)

    assert not destination.exists()


def test_remove_empty_orchestrator_output_tree_preserves_nonempty_output(
    tmp_path: Path,
) -> None:
    """Verify that existing content remains protected for resume validation.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    destination = tmp_path / "pocket_review"
    marker = destination / "provenance" / "run_manifest.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"status": "partial"}\n', encoding="utf-8")

    _remove_empty_orchestrator_output_tree(path=destination)

    assert marker.read_text(encoding="utf-8") == '{"status": "partial"}\n'


def test_remove_empty_orchestrator_output_tree_rejects_symlink(
    tmp_path: Path,
) -> None:
    """Verify that a symlink is not treated as an empty placeholder.

    Args:
        tmp_path: Isolated temporary directory supplied by pytest.
    """
    target = tmp_path / "target"
    target.mkdir()
    destination = tmp_path / "pocket_review"
    destination.symlink_to(target, target_is_directory=True)

    with pytest.raises(StageError, match="output symlink"):
        _remove_empty_orchestrator_output_tree(path=destination)

    assert destination.is_symlink()
    assert target.is_dir()


@pytest.mark.parametrize(
    ("builder", "directory_name"),
    (
        (
            build_plant_baseline_review,
            "plant_pocket_review",
        ),
        (
            build_human_plant_review,
            "pocket_review",
        ),
    ),
)
def test_review_builders_remove_empty_snakemake_output_placeholder(
    *,
    builder: Callable[..., Path],
    directory_name: str,
    synthetic_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that both review builders remove Snakemake's empty hierarchy.

    Args:
        builder: Review builder under test.
        directory_name: Builder-specific portable-review directory name.
        synthetic_config: Workflow configuration supplied by the shared fixture.
        tmp_path: Isolated temporary directory supplied by pytest.
        monkeypatch: Pytest fixture used to replace the component runner.
    """
    output_root = tmp_path / "extension"
    output_directory = output_root / directory_name
    (output_directory / "provenance").mkdir(parents=True)
    manifest = output_directory / "provenance" / "run_manifest.json"

    def fake_run_component(
        *,
        argv: tuple[str, ...],
        log_path: Path,
        working_directory: Path,
    ) -> None:
        """Require placeholder removal before simulating component output.

        Args:
            argv: Component command-line arguments.
            log_path: Component log destination.
            working_directory: Component working directory.
        """
        assert not output_directory.exists()
        assert "e3-pocket-review" in argv
        assert log_path.parent == output_root / "logs"
        assert working_directory.is_absolute()
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"status": "complete"}\n', encoding="utf-8")

    monkeypatch.setattr(
        human_plant_extension,
        "_run_component",
        fake_run_component,
    )

    observed = builder(
        parent_config_path=synthetic_config,
        output_root=output_root,
        conda_environment="e3_structural_alignment",
        review_limit=2,
    )

    assert observed == manifest
    assert manifest.is_file()


def test_extension_snakefiles_support_standalone_and_full_run(
    package_root: Path,
) -> None:
    """Verify that one rule set powers standalone and full workflow runs.

    Args:
        package_root: Root directory of the workflow package under test.
    """
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
    """Verify executable launchers and separation from the reviewed parent.

    Args:
        package_root: Root directory of the workflow package under test.
    """
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
    assert "Controller partition (default: barton)." in submit_help.stdout
    assert "Child-job partition (default: barton)." in submit_help.stdout
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
    assert "structural_top200_v0_14_0_20260805.cluster.yaml" in configuration[
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
    """Verify that the attach-only entry point plans from a completed parent.

    Args:
        package_root: Root directory of the workflow package under test.
        synthetic_config: Workflow configuration supplied by the shared fixture.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
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
    """Verify that an enabled extension becomes a final workflow branch.

    Args:
        package_root: Root directory of the workflow package under test.
        synthetic_config: Workflow configuration supplied by the shared fixture.
        tmp_path: Isolated temporary directory supplied by pytest.
    """
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
