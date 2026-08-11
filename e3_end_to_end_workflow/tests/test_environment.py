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
    assert "packaging>=24,<27" in dependencies
    assert "psutil>=6,<8" in dependencies
    assert "snakemake>=9,<10" in dependencies
    assert "snakemake-executor-plugin-slurm>=2.7.1,<3" in dependencies
    assert "orthofinder=2.5.5" in dependencies
    assert "mafft>=7.5,<8" in dependencies


def test_profiles_drop_completed_job_metadata(package_root: Path) -> None:
    """Restart state must remain with manifests and tokens rather than stale rule metadata."""

    for profile_name in ("local", "slurm"):
        path = package_root / "profiles" / profile_name / "config.v8+.yaml"
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert profile["rerun-incomplete"] is True
        assert profile["drop-metadata"] is True

    slurm_profile = yaml.safe_load(
        (package_root / "profiles" / "slurm" / "config.v8+.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert slurm_profile["slurm-status-command"] == "squeue"
    assert slurm_profile["slurm-status-attempts"] == 5


def test_fresh_template_respects_dundee_walltime_limit(package_root: Path) -> None:
    """Every template stage must remain within the Dundee 72-hour maximum."""

    template = yaml.safe_load(
        (package_root / "config" / "production.cluster.template.yaml").read_text(
            encoding="utf-8"
        )
    )
    for stage_name, stage in template["stages"].items():
        assert stage["runtime_minutes"] <= 4320, stage_name


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

    for name in (
        "run_e3_end_to_end.sh",
        "submit_e3_end_to_end.sh",
        "submit_e3_controller_slurm.sh",
        "scripts/slurm_e3_controller_job.sh",
    ):
        shell = (package_root / name).read_text(encoding="utf-8")
        assert "python <<" not in shell
        assert "python - <<" not in shell
        assert "python -c" not in shell


def test_quality_gate_uses_an_isolated_synthetic_run(package_root: Path) -> None:
    """Repeated release tests must not reuse checksum tokens from an older configuration."""
    shell = (package_root / "run_tests.sh").read_text(encoding="utf-8")
    assert 'mktemp -d "${TMPDIR:-/tmp}/e3_workflow_tests.XXXXXX"' in shell
    assert 'SYNTHETIC_CONFIG="$(mktemp ' in shell
    assert '--config "${SYNTHETIC_CONFIG}"' in shell
    assert "test_runs/synthetic_e2e_v0_7_0" not in shell


def test_runner_rejects_stale_installed_version(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """The runner must stop before work when PATH exposes an older installation."""

    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    fake_workflow = binary_directory / "e3-workflow"
    fake_workflow.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${1-}" == "--version" ]]; then
    printf 'e3-workflow 0.7.6\\n'
    exit 0
fi
printf 'Unexpected invocation\\n' >&2
exit 99
""",
        encoding="utf-8",
    )
    fake_workflow.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{binary_directory}:{environment['PATH']}"
    result = subprocess.run(
        [str(package_root / "run_e3_end_to_end.sh"), "--check-install"],
        cwd=package_root,
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "source package is 0.15.0" in result.stderr
    assert "PATH resolves e3-workflow 0.7.6" in result.stderr
    assert str(fake_workflow) in result.stderr


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


def test_slurm_controller_launcher_contract(package_root: Path) -> None:
    """The batch controller must use Slurm, Conda, locks and durable metadata."""

    launcher = (package_root / "submit_e3_controller_slurm.sh").read_text(
        encoding="utf-8"
    )
    job = (package_root / "scripts" / "slurm_e3_controller_job.sh").read_text(
        encoding="utf-8"
    )
    assert "sbatch" in launcher
    assert "controller.slurm.tsv" in launcher
    assert "controller_submission.lock" in launcher
    assert "--controller-runtime" in launcher
    assert "--controller-qos" in launcher
    assert "--controller-memory-mb" in launcher
    assert "--status" in launcher
    assert "squeue" in launcher
    assert "sacct" in launcher
    assert "conda-executable" in launcher
    assert "flock --nonblock 9" in job
    assert "--allow-inside-slurm" in job
    assert "--profile" in job
    assert "slurm" in job


def test_slurm_controller_submission_and_duplicate_guard(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """A controller submission must record its job and reject an active duplicate."""

    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    run_root = tmp_path / "run"
    argument_record = tmp_path / "sbatch_arguments.bin"
    accounting_record = tmp_path / "sacct_invocations.txt"

    fake_workflow = binary_directory / "e3-workflow"
    fake_workflow.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
case "$1" in
    --version)
        printf 'e3-workflow 0.15.0\\n'
        ;;
    diagnose-install|diagnose-slurm-executor|validate)
        exit 0
        ;;
    run-root)
        printf '%s\\n' "${FAKE_RUN_ROOT}"
        ;;
    *)
        printf 'Unexpected e3-workflow command: %s\\n' "$1" >&2
        exit 2
        ;;
esac
""",
        encoding="utf-8",
    )
    fake_workflow.chmod(0o755)

    fake_conda = binary_directory / "conda"
    fake_conda.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
while (($#)); do
    case "$1" in
        run|--no-capture-output)
            shift
            ;;
        --name)
            shift 2
            ;;
        *)
            exec "$@"
            ;;
    esac
done
""",
        encoding="utf-8",
    )
    fake_conda.chmod(0o755)

    fake_sbatch = binary_directory / "sbatch"
    fake_sbatch.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${FAKE_SBATCH_MODE:-accepted}" == "rejected" ]]; then
    printf 'scheduler rejected submission\\n' >&2
    exit 42
fi
printf '%s\\0' "$@" >"${FAKE_SBATCH_ARGUMENT_RECORD}"
printf '98765;test-cluster\\n'
""",
        encoding="utf-8",
    )
    fake_sbatch.chmod(0o755)

    fake_squeue = binary_directory / "squeue"
    fake_squeue.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
case "${FAKE_SLURM_STATE:-inactive}" in
    active)
        printf 'RUNNING\\n'
        ;;
    failed_query)
        printf 'scheduler query unavailable\\n' >&2
        exit 1
        ;;
    stale_invalid_job)
        printf 'slurm_load_jobs error: Invalid job id specified\\n' >&2
        exit 1
        ;;
    hanging)
        trap '' TERM
        sleep 30
        ;;
    terminal)
        printf 'COMPLETED\\n'
        ;;
    unknown)
        printf 'FUTURE_UNKNOWN_STATE\\n'
        ;;
    inactive)
        ;;
    *)
        printf 'Unexpected fake scheduler state\\n' >&2
        exit 2
        ;;
esac
""",
        encoding="utf-8",
    )
    fake_squeue.chmod(0o755)

    fake_sacct = binary_directory / "sacct"
    fake_sacct.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
printf 'invoked\\n' >>"${FAKE_SACCT_INVOCATION_RECORD}"
case "${FAKE_SACCT_MODE:-completed}" in
    completed)
        printf 'COMPLETED|\\n'
        ;;
    failed)
        printf 'accounting database unavailable\\n' >&2
        exit 1
        ;;
    hanging)
        sleep 30
        ;;
    *)
        printf 'Unexpected fake accounting mode\\n' >&2
        exit 2
        ;;
esac
""",
        encoding="utf-8",
    )
    fake_sacct.chmod(0o755)

    fake_scontrol = binary_directory / "scontrol"
    fake_scontrol.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
case "${FAKE_SCONTROL_MODE:-available}" in
    available)
        printf 'MinJobAge = %s sec\\n' "${FAKE_MIN_JOB_AGE:-300}"
        ;;
    failed)
        printf 'scheduler configuration unavailable\\n' >&2
        exit 1
        ;;
    hanging)
        sleep 30
        ;;
    *)
        printf 'Unexpected fake scontrol mode\\n' >&2
        exit 2
        ;;
esac
""",
        encoding="utf-8",
    )
    fake_scontrol.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{binary_directory}:{environment['PATH']}"
    environment["FAKE_RUN_ROOT"] = str(run_root)
    environment["FAKE_SBATCH_ARGUMENT_RECORD"] = str(argument_record)
    environment["FAKE_SACCT_INVOCATION_RECORD"] = str(accounting_record)
    environment.pop("SLURM_JOB_ID", None)

    launcher = package_root / "submit_e3_controller_slurm.sh"
    configuration = package_root / "config" / "synthetic.yaml"
    launcher_text = launcher.read_text(encoding="utf-8")
    assert launcher_text.count("timeout --signal=KILL") == 3
    assert "--kill-after" not in launcher_text
    unsafe_environment = environment.copy()
    unsafe_environment["FAKE_MIN_JOB_AGE"] = "60"
    unsafe = subprocess.run(
        [str(launcher), "--config", str(configuration)],
        cwd=package_root,
        check=False,
        env=unsafe_environment,
        capture_output=True,
        text=True,
    )
    assert unsafe.returncode == 2
    assert "requires at least 120 seconds" in unsafe.stderr
    assert "stopped unexpectedly" not in unsafe.stderr

    result = subprocess.run(
        [
            str(launcher),
            "--config",
            str(configuration),
            "--account",
            "science_account",
            "--partition",
            "science_partition",
            "--controller-memory-mb",
            "6000",
            "--controller-runtime",
            "2-00:00:00",
            "--controller-qos",
            "4week",
            "--max-jobs",
            "7",
            "--resume",
        ],
        cwd=package_root,
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert "Controller job: 98765" in result.stdout
    arguments = argument_record.read_bytes().decode("utf-8").rstrip("\0").split("\0")
    assert "--account" in arguments
    assert arguments[arguments.index("--account") + 1] == "science_account"
    assert "--partition" in arguments
    assert arguments[arguments.index("--partition") + 1] == "science_partition"
    assert "--mem" in arguments
    assert arguments[arguments.index("--mem") + 1] == "6000M"
    assert "--time" in arguments
    assert arguments[arguments.index("--time") + 1] == "2-00:00:00"
    assert "--qos" in arguments
    assert arguments[arguments.index("--qos") + 1] == "4week"
    assert "--source-root" in arguments
    assert arguments[arguments.index("--source-root") + 1] == str(package_root)
    assert "--max-jobs" in arguments
    assert arguments[arguments.index("--max-jobs") + 1] == "7"
    assert "--resume" in arguments

    metadata = run_root / "workflow_control" / "controller.slurm.tsv"
    rows = metadata.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("job_id\tsubmitted_at_utc")
    assert rows[1].startswith("98765\t")
    assert rows[0].endswith("controller_qos")
    assert rows[1].endswith("4week")

    unavailable_accounting_environment = environment.copy()
    unavailable_accounting_environment["FAKE_SACCT_MODE"] = "failed"
    stale_metadata_resume = subprocess.run(
        [
            str(launcher),
            "--config",
            str(configuration),
            "--resume",
        ],
        cwd=package_root,
        check=False,
        env=unavailable_accounting_environment,
        capture_output=True,
        text=True,
    )
    assert stale_metadata_resume.returncode == 0, stale_metadata_resume.stderr
    assert "Controller job: 98765" in stale_metadata_resume.stdout
    assert "safe resume is permitted" in stale_metadata_resume.stdout
    assert not accounting_record.exists()

    stale_job_environment = environment.copy()
    stale_job_environment["FAKE_SLURM_STATE"] = "stale_invalid_job"
    stale_job_resume = subprocess.run(
        [str(launcher), "--config", str(configuration), "--resume"],
        cwd=package_root,
        check=False,
        env=stale_job_environment,
        capture_output=True,
        text=True,
    )
    assert stale_job_resume.returncode == 0, stale_job_resume.stderr
    assert "safe resume is permitted" in stale_job_resume.stdout
    assert "squeue could not determine" not in stale_job_resume.stderr
    assert "Controller job: 98765" in stale_job_resume.stdout
    assert not accounting_record.exists()

    duplicate_environment = environment.copy()
    duplicate_environment["FAKE_SLURM_STATE"] = "active"
    duplicate = subprocess.run(
        [str(launcher), "--config", str(configuration)],
        cwd=package_root,
        check=False,
        env=duplicate_environment,
        capture_output=True,
        text=True,
    )
    assert duplicate.returncode == 3
    assert "already active" in duplicate.stderr
    assert "Status source: squeue" in duplicate.stderr
    assert not accounting_record.exists()

    failed_squeue_environment = environment.copy()
    failed_squeue_environment["FAKE_SLURM_STATE"] = "failed_query"
    failed_squeue = subprocess.run(
        [str(launcher), "--config", str(configuration), "--resume"],
        cwd=package_root,
        check=False,
        env=failed_squeue_environment,
        capture_output=True,
        text=True,
    )
    assert failed_squeue.returncode == 3
    assert "squeue could not determine" in failed_squeue.stderr
    assert "refusing to submit" in failed_squeue.stderr
    assert not accounting_record.exists()

    hanging_squeue_environment = environment.copy()
    hanging_squeue_environment["FAKE_SLURM_STATE"] = "hanging"
    hanging_squeue = subprocess.run(
        [
            str(launcher),
            "--config",
            str(configuration),
            "--resume",
            "--scheduler-query-timeout-seconds",
            "1",
        ],
        cwd=package_root,
        check=False,
        env=hanging_squeue_environment,
        capture_output=True,
        text=True,
    )
    assert hanging_squeue.returncode == 3
    assert "squeue could not determine" in hanging_squeue.stderr
    assert "refusing to submit" in hanging_squeue.stderr
    assert "stopped unexpectedly" not in hanging_squeue.stderr

    terminal_squeue_environment = environment.copy()
    terminal_squeue_environment["FAKE_SLURM_STATE"] = "terminal"
    terminal_state_resume = subprocess.run(
        [str(launcher), "--config", str(configuration), "--resume"],
        cwd=package_root,
        check=False,
        env=terminal_squeue_environment,
        capture_output=True,
        text=True,
    )
    assert terminal_state_resume.returncode == 0, terminal_state_resume.stderr
    assert "safe resume is permitted" in terminal_state_resume.stdout
    assert not accounting_record.exists()

    unknown_squeue_environment = environment.copy()
    unknown_squeue_environment["FAKE_SLURM_STATE"] = "unknown"
    unknown_state = subprocess.run(
        [str(launcher), "--config", str(configuration), "--resume"],
        cwd=package_root,
        check=False,
        env=unknown_squeue_environment,
        capture_output=True,
        text=True,
    )
    assert unknown_state.returncode == 3
    assert "unrecognised controller state" in unknown_state.stderr
    assert not accounting_record.exists()

    status_unavailable = subprocess.run(
        [
            str(launcher),
            "--config",
            str(configuration),
            "--status",
            "--scheduler-query-timeout-seconds",
            "1",
        ],
        cwd=package_root,
        check=True,
        env=unavailable_accounting_environment,
        capture_output=True,
        text=True,
    )
    assert "Controller: NOT_IN_QUEUE" in status_unavailable.stdout
    assert "Status source: squeue" in status_unavailable.stdout
    assert "Accounting: UNAVAILABLE_OR_NO_RECORD" in status_unavailable.stdout
    assert accounting_record.read_text(encoding="utf-8").splitlines() == ["invoked"]

    hanging_accounting_environment = environment.copy()
    hanging_accounting_environment["FAKE_SACCT_MODE"] = "hanging"
    status_timeout = subprocess.run(
        [
            str(launcher),
            "--config",
            str(configuration),
            "--status",
            "--scheduler-query-timeout-seconds",
            "1",
        ],
        cwd=package_root,
        check=True,
        env=hanging_accounting_environment,
        capture_output=True,
        text=True,
    )
    assert "Controller: NOT_IN_QUEUE" in status_timeout.stdout
    assert "Accounting: UNAVAILABLE_OR_NO_RECORD" in status_timeout.stdout

    hanging_scontrol_environment = environment.copy()
    hanging_scontrol_environment["FAKE_SCONTROL_MODE"] = "hanging"
    scontrol_timeout = subprocess.run(
        [
            str(launcher),
            "--config",
            str(configuration),
            "--resume",
            "--scheduler-query-timeout-seconds",
            "1",
        ],
        cwd=package_root,
        check=False,
        env=hanging_scontrol_environment,
        capture_output=True,
        text=True,
    )
    assert scontrol_timeout.returncode == 0, scontrol_timeout.stderr
    assert "scontrol could not verify MinJobAge within 1 seconds" in (
        scontrol_timeout.stderr
    )
    assert "Controller job: 98765" in scontrol_timeout.stdout
    assert "stopped unexpectedly" not in scontrol_timeout.stderr

    failed_scontrol_environment = environment.copy()
    failed_scontrol_environment["FAKE_SCONTROL_MODE"] = "failed"
    failed_scontrol = subprocess.run(
        [str(launcher), "--config", str(configuration), "--resume"],
        cwd=package_root,
        check=False,
        env=failed_scontrol_environment,
        capture_output=True,
        text=True,
    )
    assert failed_scontrol.returncode == 0, failed_scontrol.stderr
    assert "scontrol could not verify MinJobAge" in failed_scontrol.stderr
    assert "Controller job: 98765" in failed_scontrol.stdout
    assert "stopped unexpectedly" not in failed_scontrol.stderr

    rejected_submission_environment = environment.copy()
    rejected_submission_environment["FAKE_SBATCH_MODE"] = "rejected"
    rejected_submission = subprocess.run(
        [str(launcher), "--config", str(configuration), "--resume"],
        cwd=package_root,
        check=False,
        env=rejected_submission_environment,
        capture_output=True,
        text=True,
    )
    assert rejected_submission.returncode == 42
    assert "scheduler rejected submission" in rejected_submission.stderr
    assert "sbatch rejected" in rejected_submission.stderr
    assert "stopped unexpectedly" not in rejected_submission.stderr

    metadata.write_text(
        "job_id\tsubmitted_at_utc\trun_name\tconfiguration\n",
        encoding="utf-8",
    )
    malformed_metadata = subprocess.run(
        [str(launcher), "--config", str(configuration), "--resume"],
        cwd=package_root,
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert malformed_metadata.returncode == 2
    assert "does not contain a valid Slurm job ID" in malformed_metadata.stderr


def test_slurm_spool_copy_uses_explicit_source_root(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """A Slurm-copied job body must run the real source-tree workflow runner."""

    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    fake_source_root = tmp_path / "workflow-source"
    fake_source_root.mkdir()
    run_root = tmp_path / "run"
    runner_argument_record = tmp_path / "runner_arguments.bin"

    fake_workflow = binary_directory / "e3-workflow"
    fake_workflow.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
case "$1" in
    --version)
        printf 'e3-workflow 0.15.0\\n'
        ;;
    diagnose-install|validate)
        exit 0
        ;;
    run-root)
        printf '%s\\n' "${FAKE_RUN_ROOT}"
        ;;
    *)
        printf 'Unexpected e3-workflow command: %s\\n' "$1" >&2
        exit 2
        ;;
esac
""",
        encoding="utf-8",
    )
    fake_workflow.chmod(0o755)

    fake_conda = binary_directory / "conda"
    fake_conda.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
while (($#)); do
    case "$1" in
        run|--no-capture-output)
            shift
            ;;
        --name)
            shift 2
            ;;
        *)
            exec "$@"
            ;;
    esac
done
""",
        encoding="utf-8",
    )
    fake_conda.chmod(0o755)

    fake_runner = fake_source_root / "run_e3_end_to_end.sh"
    fake_runner.write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\\0' "$@" >"${FAKE_RUNNER_ARGUMENT_RECORD}"
""",
        encoding="utf-8",
    )
    fake_runner.chmod(0o755)

    spool_directory = tmp_path / "var" / "spool" / "slurmd"
    spool_directory.mkdir(parents=True)
    spooled_job = spool_directory / "slurm_script"
    spooled_job.write_bytes(
        (package_root / "scripts" / "slurm_e3_controller_job.sh").read_bytes()
    )
    spooled_job.chmod(0o755)
    configuration = tmp_path / "configuration.yaml"
    configuration.write_text("schema_version: 2\n", encoding="utf-8")

    environment = os.environ.copy()
    environment["PATH"] = f"{binary_directory}:{environment['PATH']}"
    environment["FAKE_RUN_ROOT"] = str(run_root)
    environment["FAKE_RUNNER_ARGUMENT_RECORD"] = str(runner_argument_record)
    environment["SLURM_JOB_ID"] = "62079"

    result = subprocess.run(
        [
            str(spooled_job),
            "--source-root",
            str(fake_source_root),
            "--config",
            str(configuration),
            "--conda-executable",
            str(fake_conda),
            "--conda-environment",
            "e3_end_to_end_workflow",
            "--",
            "--resume",
        ],
        cwd=spool_directory,
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "/var/spool/slurmd/run_e3_end_to_end.sh" not in result.stderr
    runner_arguments = (
        runner_argument_record.read_bytes().decode("utf-8").rstrip("\0").split("\0")
    )
    assert runner_arguments == [
        "--config",
        str(configuration),
        "--profile",
        "slurm",
        "--allow-inside-slurm",
        "--resume",
    ]


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
    --version)
        printf 'e3-workflow 0.15.0\\n'
        ;;
    diagnose-install|validate|control|record-invocation)
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
