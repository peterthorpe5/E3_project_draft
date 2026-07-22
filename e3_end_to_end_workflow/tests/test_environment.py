"""Conda environment contract tests."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_environment_pins_workflow_and_orthology_engines(package_root: Path) -> None:
    """The package environment must provide reproducible workflow engines."""

    environment = yaml.safe_load((package_root / "environment.yml").read_text(encoding="utf-8"))
    assert environment["name"] == "e3_end_to_end_workflow"
    assert environment["channels"] == ["conda-forge", "bioconda", "nodefaults"]
    dependencies = environment["dependencies"]
    assert "duckdb>=1.4,<2" in dependencies
    assert "psutil>=6,<8" in dependencies
    assert "snakemake>=9,<10" in dependencies
    assert "snakemake-executor-plugin-slurm" in dependencies
    assert "orthofinder=2.5.5" in dependencies


def test_profiles_drop_completed_job_metadata(package_root: Path) -> None:
    """Restart state must remain with manifests and tokens rather than stale rule metadata."""

    for profile_name in ("local", "slurm"):
        path = package_root / "profiles" / profile_name / "config.v8+.yaml"
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert profile["rerun-incomplete"] is True
        assert profile["drop-metadata"] is True


def test_wrapper_safely_clears_completed_output_markers(package_root: Path) -> None:
    """A complete run must clear declared output markers after DAG success."""

    wrapper = (package_root / "run_e3_end_to_end.sh").read_text(encoding="utf-8")
    assert "--cleanup-metadata" in wrapper
    assert '[[ -z "${TARGET}" ]] || FULL_DAG_COMPLETION="false"' in wrapper
    assert '--nolock|--keep-going)' in wrapper
    assert "POSTPROCESSING_OUTPUTS" in wrapper
    assert "metadata was not present" in wrapper
    assert '"${RUN_ROOT}/${stage_name}/stage_manifest.json"' in wrapper
    assert '"${RUN_ROOT}/${stage_name}/report/stage_report.html"' in wrapper
