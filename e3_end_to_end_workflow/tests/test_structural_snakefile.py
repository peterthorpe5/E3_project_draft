"""Snakemake DAG regression for the production structural-completion scatter."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from e3workflow.config import load_config
from e3workflow.control import initialise_stage_tokens


def test_structural_completion_snakefile_builds_full_scatter_dag(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """The production configuration must resolve all shard and aggregate rules."""
    snakemake = shutil.which("snakemake")
    if snakemake is None:
        pytest.skip("Snakemake is not installed")
    source = (
        package_root
        / "config"
        / "grant_aligned_structural_completion_top20_v0_10_0_20260728.cluster.yaml"
    )
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["run"].update(
        {
            "name": "structural_dag_fixture",
            "project_root": str(tmp_path),
            "output_root": str(tmp_path / "runs"),
            "parent_run_root": str(tmp_path / "parent"),
        }
    )
    controlled = tmp_path / "controlled_input"
    controlled.write_text("fixture\n", encoding="utf-8")
    for key in (
        "candidate_evidence",
        "candidate_evidence_manifest",
        "orthofinder_archive",
        "orthology_species_manifest",
        "inherited_sqlite",
        "expression_manifest",
        "e3_domain_catalogue",
    ):
        payload["inputs"][key] = str(controlled)
    component = tmp_path / "component.yaml"
    component.write_text("project:\n  name: fixture\n", encoding="utf-8")
    payload["analysis"]["ligandability"]["component_config"] = str(component)
    configuration = tmp_path / "structural.yaml"
    configuration.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    config = load_config(configuration)
    initialise_stage_tokens(config)
    environment = dict(os.environ)
    environment["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    result = subprocess.run(
        [
            snakemake,
            "--snakefile",
            str(package_root / "workflow" / "Snakefile"),
            "--configfile",
            str(configuration),
            "--cores",
            "8",
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
