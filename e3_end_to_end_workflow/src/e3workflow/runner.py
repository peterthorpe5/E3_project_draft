"""Atomic execution and publication of workflow stages."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from e3workflow import __version__
from e3workflow.config import WorkflowConfig, previous_stage
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
from e3workflow.manifests import validate_accessions, validate_proteomes, validate_shortlist


def format_command(command: tuple[str, ...], values: dict[str, str]) -> list[str]:
    """Substitute only documented placeholders in an argv sequence."""

    rendered = []
    for token in command:
        try:
            rendered.append(token.format_map(values))
        except KeyError as exc:
            raise StageError(f"Unknown command placeholder {exc.args[0]!r} in {token!r}") from exc
    return rendered


def validate_upstream(config: WorkflowConfig, stage_name: str) -> list[dict[str, Any]]:
    """Validate the predecessor manifest and return its complete lineage."""

    predecessor = previous_stage(stage_name)
    if predecessor is None:
        return []
    path = config.run_root / predecessor / "stage_manifest.json"
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
    seeds = validate_accessions(config.seeds_manifest, {"evidence_type", "source"})
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
    lineage = validate_upstream(config, stage_name)
    run_root = config.run_root
    run_root.mkdir(parents=True, exist_ok=True)
    staging = run_root / ".staging" / f"{stage_name}.{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    logger = configure_logging(staging / "logs" / "stage.log", verbose)
    started = utc_now()
    status = "complete"
    try:
        logger.info("Starting stage %s in %s mode", stage_name, config.mode)
        if not stage.enabled:
            status = "skipped_optional"
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
            }
            argv = format_command(stage.command, values)
            logger.info("Command argv: %s", shlex.join(argv))
            environment = os.environ.copy()
            environment.update({f"E3_{key.upper()}": value for key, value in values.items()})
            with (staging / "logs" / "command.log").open("w", encoding="utf-8") as handle:
                completed = subprocess.run(
                    argv,
                    cwd=config.project_root,
                    env=environment,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    check=False,
                    text=True,
                )
            if completed.returncode:
                raise StageError(
                    f"Stage command returned {completed.returncode}; see logs/command.log"
                )
        else:
            run_internal_stage(config, stage_name, staging)
        if stage.enabled:
            validate_expected_outputs(staging, stage.expected_outputs)
        logger.info("Stage outputs validated; freezing log before checksum inventory.")
        close_logger(logger)
        outputs = inventory_files(staging, frozenset({"stage_manifest.json"}))
        summary = {
            "stage": stage_name,
            "status": status,
            "required": stage.required,
            "mode": config.mode,
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "configuration": str(config.source_path),
            "configuration_digest": config.digest,
            "package_version": __version__,
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
        close_logger(logger)
        failed = run_root / "failed" / staging.name
        failed.parent.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            shutil.move(str(staging), str(failed))
        raise
