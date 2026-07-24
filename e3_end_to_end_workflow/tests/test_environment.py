"""Conda environment contract tests."""

from __future__ import annotations

import os
import subprocess
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


def test_bounded_slurm_target_precedes_variadic_resources(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """A bounded target must not be consumed as a default-resource expression."""

    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    run_root = tmp_path / "run"
    argument_record = tmp_path / "snakemake_arguments.bin"

    fake_workflow = binary_directory / "e3-workflow"
    fake_workflow.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
command_name="$1"
shift
case "${command_name}" in
    validate|control|record-invocation)
        exit 0
        ;;
    plan)
        printf 'Synthetic plan\\n'
        ;;
    stage-target)
        stage_name=""
        while (($#)); do
            if [[ "$1" == "--stage" ]]; then
                stage_name="$2"
                break
            fi
            shift
        done
        printf '%s/%s/stage_manifest.json\\n' "${FAKE_RUN_ROOT}" "${stage_name}"
        ;;
    *)
        printf 'Unexpected fake e3-workflow command: %s\\n' "${command_name}" >&2
        exit 2
        ;;
esac
""",
        encoding="utf-8",
    )
    fake_workflow.chmod(0o755)

    fake_snakemake = binary_directory / "snakemake"
    fake_snakemake.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\\0' "$@" >"${FAKE_SNAKEMAKE_ARGUMENT_RECORD}"
""",
        encoding="utf-8",
    )
    fake_snakemake.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{binary_directory}:{environment['PATH']}"
    environment["FAKE_RUN_ROOT"] = str(run_root)
    environment["FAKE_SNAKEMAKE_ARGUMENT_RECORD"] = str(argument_record)
    environment.pop("SLURM_JOB_ID", None)

    subprocess.run(
        [
            str(package_root / "run_e3_end_to_end.sh"),
            "--config",
            str(package_root / "config" / "synthetic.yaml"),
            "--profile",
            "slurm",
            "--stop-after",
            "05_orthology",
        ],
        cwd=package_root,
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    arguments = argument_record.read_bytes().decode("utf-8").rstrip("\0").split("\0")
    target = str(run_root / "05_orthology" / "stage_manifest.json")
    resource_index = arguments.index("--default-resources")
    assert arguments.index(target) < resource_index
    assert arguments[resource_index + 1:resource_index + 5] == [
        "slurm_account=barton",
        "slurm_partition=general",
        "mem_mb=8000",
        "runtime=60",
    ]
