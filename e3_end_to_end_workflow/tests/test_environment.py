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
    assert "mafft>=7.5,<8" in dependencies


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
    assert "for cleanup_attempt in 1 2 3" in wrapper
    assert "filesystem-latency retry" in wrapper
    assert '"${RUN_ROOT}/${stage_name}/stage_manifest.json"' in wrapper
    assert '"${RUN_ROOT}/${stage_name}/report/stage_report.html"' in wrapper


def test_main_shell_entrypoints_contain_no_embedded_python(package_root: Path) -> None:
    """User-facing shells must delegate Python work to installed, tested commands."""

    for name in ("run_e3_end_to_end.sh", "submit_e3_end_to_end.sh"):
        shell = (package_root / name).read_text(encoding="utf-8")
        assert "python <<" not in shell
        assert "python - <<" not in shell
        assert "python -c" not in shell


def test_detached_launcher_contract(package_root: Path) -> None:
    """The cluster launcher must detach, lock, log and guard nested execution."""

    launcher = (package_root / "submit_e3_end_to_end.sh").read_text(encoding="utf-8")
    assert "nohup setsid flock" in launcher
    assert "controller.lock" in launcher
    assert "controller.pid.tsv" in launcher
    assert "submission_${TIMESTAMP}.log" in launcher
    assert "--status" in launcher
    assert "--foreground" in launcher
    assert "SLURM_JOB_ID" in launcher
    assert "RUNNER_ARGS+=(--profile slurm)" in launcher
