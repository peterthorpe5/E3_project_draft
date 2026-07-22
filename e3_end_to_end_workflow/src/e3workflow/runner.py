"""Atomic execution and publication of workflow stages."""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from e3workflow import __version__
from e3workflow.benchmarking import (
    ProcessTreeResourceMonitor,
    StageResourceUsage,
    write_stage_resource_outputs,
)
from e3workflow.config import STAGE_NAMES, WorkflowConfig, stage_dependencies, stage_purpose
from e3workflow.control import stage_token_path
from e3workflow.errors import StageError
from e3workflow.io_utils import (
    atomic_write_json,
    close_logger,
    configure_logging,
    inventory_files,
    read_json,
    sha256_file,
    utc_now,
    write_tsv,
)
from e3workflow.manifests import validate_proteomes, validate_seed_evidence, validate_shortlist


def format_command(command: tuple[str, ...], values: dict[str, str]) -> list[str]:
    """Substitute only documented placeholders in an argv sequence."""
    rendered = []
    for token in command:
        try:
            rendered.append(token.format_map(values))
        except KeyError as exc:
            raise StageError(f"Unknown command placeholder {exc.args[0]!r} in {token!r}") from exc
    return rendered


def _validate_upstream_manifest(path: Path, config: WorkflowConfig) -> list[dict[str, Any]]:
    """Validate one prerequisite manifest and return its lineage."""
    payload = read_json(path)
    if payload.get("configuration_digest") != config.digest:
        raise StageError(f"Upstream configuration digest differs: {path}")
    if payload.get("status") not in {"complete", "skipped_optional"}:
        raise StageError(f"Upstream stage is not complete: {path}")
    lineage = payload.get("lineage")
    if not isinstance(lineage, list):
        raise StageError(f"Upstream manifest has invalid lineage: {path}")
    outputs = payload.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise StageError(f"Upstream manifest has no output inventory: {path}")
    for record in outputs:
        if not isinstance(record, dict):
            raise StageError(f"Upstream manifest contains an invalid output record: {path}")
        relative = Path(str(record.get("path", "")))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise StageError(f"Upstream manifest contains an unsafe output path: {relative}")
        output = path.parent / relative
        if not output.is_file():
            raise StageError(f"Upstream output is missing: {output}")
        if output.stat().st_size != record.get("size_bytes"):
            raise StageError(f"Upstream output size changed: {output}")
        if sha256_file(output) != record.get("sha256"):
            raise StageError(f"Upstream output checksum changed: {output}")
    return list(lineage)


def validate_upstream(config: WorkflowConfig, stage_name: str) -> list[dict[str, Any]]:
    """Validate all scientific prerequisites and return de-duplicated lineage.

    Args:
        config: Validated workflow configuration.
        stage_name: Stable stage identifier.

    Returns:
        Ordered lineage records across every prerequisite branch.
    """
    merged: dict[str, dict[str, Any]] = {}
    for dependency in stage_dependencies(stage_name):
        path = config.run_root / dependency / "stage_manifest.json"
        for record in _validate_upstream_manifest(path, config):
            lineage_stage = str(record.get("stage", ""))
            if not lineage_stage:
                raise StageError(f"Upstream lineage record has no stage name: {path}")
            merged[lineage_stage] = record
    return [merged[name] for name in STAGE_NAMES if name in merged]


def validate_expected_outputs(stage_root: Path, outputs: tuple[str, ...]) -> None:
    """Require every declared stage output to exist and be non-empty."""
    missing = []
    for relative in outputs:
        path = stage_root / relative
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(relative)
    if missing:
        raise StageError(f"Missing or empty declared outputs: {', '.join(missing)}")


def _run_internal_inputs(config: WorkflowConfig, stage_root: Path) -> None:
    """Validate all controlled input manifests and publish a compact inventory."""
    proteomes = validate_proteomes(config.proteomes_manifest, verify_checksums=True)
    seeds = validate_seed_evidence(config.seeds_manifest)
    shortlist = validate_shortlist(config.shortlist_manifest)
    rows = [
        {"manifest": "proteomes", "path": config.proteomes_manifest, "row_count": len(proteomes)},
        {"manifest": "seeds", "path": config.seeds_manifest, "row_count": len(seeds)},
        {"manifest": "shortlist", "path": config.shortlist_manifest, "row_count": len(shortlist)},
    ]
    write_tsv(stage_root / "input_validation.tsv", rows, ("manifest", "path", "row_count"))


def _run_internal_shortlist(config: WorkflowConfig, stage_root: Path) -> None:
    """Publish only accessions explicitly approved at the human review gate."""
    rows = validate_shortlist(config.shortlist_manifest)
    approved = [row for row in rows if row["decision"].strip().lower() == "approve"]
    write_tsv(stage_root / "approved_accessions.tsv", approved, tuple(rows[0]))


def _run_internal_app_ready(config: WorkflowConfig, stage_root: Path) -> None:
    """Write an application handoff that never overstates production readiness."""
    write_tsv(
        stage_root / "app_handoff.tsv",
        [
            {
                "run_name": config.run_name,
                "mode": config.mode,
                "production_eligible": str(config.mode == "production").lower(),
                "integrated_stage": config.run_root / "10_integrated_resource",
            }
        ],
        ("run_name", "mode", "production_eligible", "integrated_stage"),
    )


def run_internal_stage(config: WorkflowConfig, stage_name: str, stage_root: Path) -> None:
    """Run a safe built-in stage or a clearly labelled synthetic stage."""
    if stage_name == "00_inputs":
        _run_internal_inputs(config, stage_root)
    elif stage_name == "08_shortlist_gate":
        _run_internal_shortlist(config, stage_root)
    elif stage_name == "11_app_ready":
        _run_internal_app_ready(config, stage_root)
    elif config.mode == "synthetic":
        write_tsv(
            stage_root / "synthetic_stage.tsv",
            [{"stage": stage_name, "notice": "TEST DATA ONLY; NOT A SCIENTIFIC RESULT"}],
            ("stage", "notice"),
        )
    else:
        raise StageError(f"No internal production implementation exists for {stage_name}")


def run_external_command(
    argv: list[str],
    working_directory: Path,
    environment: dict[str, str],
    command_log: Path,
    logger: logging.Logger,
) -> int:
    """Run an external command while streaming output to file and console logs.

    Args:
        argv: Fully rendered command argument vector.
        working_directory: Existing command working directory.
        environment: Complete subprocess environment.
        command_log: Plain-text destination for unmodified tool output.
        logger: Configured stage logger.

    Returns:
        Process return code.
    """
    command_log.parent.mkdir(parents=True, exist_ok=True)
    with command_log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            argv,
            cwd=working_directory,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if process.stdout is None:
            raise StageError("External command did not provide a readable output stream")
        for line in process.stdout:
            handle.write(line)
            handle.flush()
            logger.info("tool | %s", line.rstrip("\n"))
        return process.wait()


def execute_stage(config: WorkflowConfig, stage_name: str, verbose: bool = False) -> Path:
    """Execute one stage in a temporary directory and atomically publish it.

    Args:
        config: Validated workflow configuration.
        stage_name: Stable stage identifier.
        verbose: Emit DEBUG messages to the console as well as the log.

    Returns:
        Formal stage-manifest path.
    """
    stage = config.stage(stage_name)
    run_root = config.run_root
    run_root.mkdir(parents=True, exist_ok=True)
    staging = run_root / ".staging" / f"{stage_name}.{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    logger = configure_logging(staging / "logs" / "stage.log", verbose)
    started = utc_now()
    started_monotonic = time.monotonic()
    status = "complete"
    stage_return_code = 0
    resource_usage: StageResourceUsage | None = None
    monitor_stopped = False
    monitor = ProcessTreeResourceMonitor(
        stage_name=stage_name,
        requested_threads=stage.threads,
        requested_memory_mb=stage.memory_mb,
        requested_runtime_minutes=stage.runtime_minutes,
        sample_interval_seconds=config.benchmarking.sample_interval_seconds,
    )
    try:
        monitor.start()
        lineage = validate_upstream(config=config, stage_name=stage_name)
        control_token = stage_token_path(config, stage_name)
        if not control_token.is_file():
            raise StageError(
                f"Workflow control token is missing: {control_token}. Run the shell wrapper."
            )
        purpose, rationale = stage_purpose(stage_name)
        dependencies = stage_dependencies(stage_name)
        logger.info("Stage: %s", stage_name)
        logger.info("What this stage does: %s", purpose)
        logger.info("Why this stage is required: %s", rationale)
        logger.info("Run mode: %s", config.mode)
        logger.info("Prerequisite stages: %s", ", ".join(dependencies) or "controlled inputs")
        logger.info("Temporary stage directory: %s", staging)
        logger.info(
            "Requested resources: threads=%d, memory_mb=%d, runtime_minutes=%d",
            stage.threads,
            stage.memory_mb,
            stage.runtime_minutes,
        )
        logger.info(
            "Expected outputs: %s",
            ", ".join(stage.expected_outputs) or "explicit skipped-stage record",
        )
        logger.info(
            "Benchmarking: process-tree CPU, memory, I/O, processes and threads every %.3f s; "
            "the run summary also records broader runner timing and optional Slurm accounting.",
            config.benchmarking.sample_interval_seconds,
        )
        if not stage.enabled:
            status = "skipped_optional"
            logger.info("Stage is disabled and optional; publishing an explicit skipped record.")
            write_tsv(
                staging / "SKIPPED.tsv",
                [{"stage": stage_name, "reason": "disabled in configuration"}],
                ("stage", "reason"),
            )
        elif stage.command:
            values = {
                "project_root": str(config.project_root),
                "run_root": str(run_root),
                "stage_dir": str(staging),
                "proteomes_manifest": str(config.proteomes_manifest),
                "seeds_manifest": str(config.seeds_manifest),
                "shortlist_manifest": str(config.shortlist_manifest),
                "threads": str(stage.threads),
            }
            argv = format_command(stage.command, values)
            logger.info("Command argv: %s", shlex.join(argv))
            environment = os.environ.copy()
            environment.update({f"E3_{key.upper()}": value for key, value in values.items()})
            return_code = run_external_command(
                argv=argv,
                working_directory=config.project_root,
                environment=environment,
                command_log=staging / "logs" / "command.log",
                logger=logger,
            )
            if return_code:
                stage_return_code = return_code
                raise StageError(
                    f"Stage command returned {return_code}; see logs/command.log"
                )
        else:
            logger.info("Using the package's validated internal implementation for this stage.")
            run_internal_stage(config, stage_name, staging)
        if stage.enabled:
            validate_expected_outputs(staging, stage.expected_outputs)
        logger.info("Validated %d declared outputs.", len(stage.expected_outputs))
        resource_usage, resource_samples = monitor.stop(
            return_code=stage_return_code,
            status=status,
        )
        monitor_stopped = True
        write_stage_resource_outputs(
            stage_root=staging,
            usage=resource_usage,
            samples=resource_samples,
        )
        logger.info(
            "Measured resources: wall=%.3f s, cpu=%.3f s, mean_cpu_cores=%.3f, "
            "peak_rss=%.3f MiB, read=%.3f MiB, write=%.3f MiB.",
            resource_usage.wall_seconds,
            resource_usage.total_cpu_seconds,
            resource_usage.mean_cpu_cores,
            resource_usage.peak_rss_mb,
            resource_usage.read_bytes / (1024.0**2),
            resource_usage.write_bytes / (1024.0**2),
        )
        logger.info("Freezing the stage log before calculating the checksum inventory.")
        close_logger(logger)
        outputs = inventory_files(staging, frozenset({"stage_manifest.json"}))
        runner_wall_seconds = max(0.0, time.monotonic() - started_monotonic)
        summary = {
            "stage": stage_name,
            "status": status,
            "required": stage.required,
            "mode": config.mode,
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "runner_wall_seconds": runner_wall_seconds,
            "configuration": str(config.source_path),
            "configuration_digest": config.digest,
            "package_version": __version__,
            "purpose": purpose,
            "rationale": rationale,
            "dependencies": list(dependencies),
            "control_token": {
                "path": str(control_token),
                "sha256": sha256_file(control_token),
            },
            "resources": {
                "threads": stage.threads,
                "memory_mb": stage.memory_mb,
                "runtime_minutes": stage.runtime_minutes,
            },
            "benchmark": resource_usage.as_record(),
            "outputs": outputs,
        }
        summary["lineage"] = lineage + [
            {key: summary[key] for key in ("stage", "status", "required", "mode")}
        ]
        atomic_write_json(staging / "stage_manifest.json", summary)
        formal = run_root / stage_name
        if formal.exists():
            superseded = run_root / "superseded" / f"{stage_name}.{uuid.uuid4().hex}"
            superseded.parent.mkdir(parents=True, exist_ok=True)
            os.replace(formal, superseded)
        os.replace(staging, formal)
        return formal / "stage_manifest.json"
    except BaseException:
        if not monitor_stopped:
            try:
                resource_usage, resource_samples = monitor.stop(
                    return_code=stage_return_code or 1,
                    status="failed",
                )
                write_stage_resource_outputs(
                    stage_root=staging,
                    usage=resource_usage,
                    samples=resource_samples,
                )
                logger.error(
                    "Failed-stage resources retained: wall=%.3f s, cpu=%.3f s, "
                    "peak_rss=%.3f MiB.",
                    resource_usage.wall_seconds,
                    resource_usage.total_cpu_seconds,
                    resource_usage.peak_rss_mb,
                )
            except BaseException:
                logger.exception("Could not finalise failed-stage resource measurements.")
        close_logger(logger)
        failed = run_root / "failed" / staging.name
        failed.parent.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            shutil.move(str(staging), str(failed))
        raise
