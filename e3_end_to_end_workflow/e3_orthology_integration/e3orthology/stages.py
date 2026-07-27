"""Checksum-aware, restartable stage execution with atomic publication."""

from __future__ import annotations

import json
import logging
import os
import shutil
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from .errors import InputValidationError, StageStateError
from .io_utils import atomic_write_json, file_record, utc_now_iso

_LOGGER = logging.getLogger("e3orthology.stages")


StageExecutor = Callable[[Path], dict[str, Any]]
InputProvider = Callable[[], Sequence[Path]]


@dataclass(frozen=True)
class StageSpec:
    """Executable stage definition and its formal output contract."""

    name: str
    version: str
    expected_outputs: tuple[str, ...]
    input_provider: InputProvider
    executor: StageExecutor


@dataclass(frozen=True)
class StageReuseDecision:
    """Decision explaining whether one completed stage is reusable."""

    reusable: bool
    reason: str


def stage_directory(*, run_root: Path, stage_name: str) -> Path:
    """Return the formal directory for a named stage.

    Args:
        run_root: Run-specific output root.
        stage_name: Validated stage name.

    Returns:
        Formal stage directory.
    """

    return Path(run_root).expanduser().resolve() / "stages" / stage_name


def relative_file_record(*, root: Path, path: Path) -> dict[str, Any]:
    """Build a checksum record using a path relative to the stage root.

    Args:
        root: Stage root.
        path: File below the stage root.

    Returns:
        Relative path, size and SHA-256.

    Raises:
        InputValidationError: If ``path`` is not below ``root``.
    """

    stage_root = Path(root).expanduser().resolve()
    source = Path(path).expanduser().resolve()
    try:
        relative = source.relative_to(stage_root)
    except ValueError as error:
        raise InputValidationError(f"Stage output is outside its root: {source}") from error
    record = file_record(path=source)
    return {
        "relative_path": str(relative),
        "bytes": record["bytes"],
        "sha256": record["sha256"],
    }


def current_input_records(*, paths: Sequence[Path]) -> list[dict[str, Any]]:
    """Build sorted full-checksum records for formal stage inputs.

    Args:
        paths: Input paths.

    Returns:
        Records sorted by absolute path.
    """

    records = [file_record(path=path) for path in paths]
    return sorted(records, key=lambda record: str(record["path"]))


def evaluate_stage_reuse(
    *,
    run_root: Path,
    spec: StageSpec,
    config_digest: str,
    package_version: str,
) -> StageReuseDecision:
    """Validate a completed stage against inputs, configuration and outputs.

    Args:
        run_root: Run-specific output root.
        spec: Stage contract.
        config_digest: Digest of the effective configuration and runtime paths.
        package_version: Current package version.

    Returns:
        Reuse decision with a machine-readable reason.
    """

    final_directory = stage_directory(run_root=run_root, stage_name=spec.name)
    manifest_path = final_directory / "stage_manifest.json"
    if not final_directory.is_dir():
        return StageReuseDecision(False, "stage_directory_missing")
    if not manifest_path.is_file():
        return StageReuseDecision(False, "stage_manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return StageReuseDecision(False, "stage_manifest_invalid_json")
    if manifest.get("status") != "SUCCESS":
        return StageReuseDecision(False, "stage_status_not_success")
    if manifest.get("stage_version") != spec.version:
        return StageReuseDecision(False, "stage_version_changed")
    if manifest.get("package_version") != package_version:
        return StageReuseDecision(False, "package_version_changed")
    if manifest.get("config_digest") != config_digest:
        return StageReuseDecision(False, "configuration_changed")
    try:
        observed_inputs = current_input_records(paths=spec.input_provider())
    except InputValidationError:
        return StageReuseDecision(False, "stage_input_missing_or_invalid")
    if manifest.get("inputs") != observed_inputs:
        return StageReuseDecision(False, "stage_inputs_changed")
    output_records = manifest.get("outputs")
    if not isinstance(output_records, list):
        return StageReuseDecision(False, "output_manifest_missing")
    expected = set(spec.expected_outputs)
    recorded = {record.get("relative_path") for record in output_records}
    if expected - recorded:
        return StageReuseDecision(False, "expected_output_not_recorded")
    for record in output_records:
        relative_path = record.get("relative_path")
        if not isinstance(relative_path, str):
            return StageReuseDecision(False, "invalid_output_record")
        output_path = final_directory / relative_path
        try:
            observed = relative_file_record(root=final_directory, path=output_path)
        except InputValidationError:
            return StageReuseDecision(False, "recorded_output_missing_or_invalid")
        if observed != record:
            return StageReuseDecision(False, "recorded_output_checksum_changed")
    return StageReuseDecision(True, "validated_success")


def invalidate_downstream(
    *,
    run_root: Path,
    ordered_specs: Sequence[StageSpec],
    changed_stage_index: int,
) -> list[str]:
    """Move downstream stages into a recoverable invalidated location.

    Args:
        run_root: Run-specific output root.
        ordered_specs: Complete ordered stage plan.
        changed_stage_index: Index of the stage being rerun.

    Returns:
        Names of downstream stage directories moved aside.
    """

    root = Path(run_root).expanduser().resolve()
    timestamp = utc_now_iso().replace(":", "").replace("+", "_")
    invalidated: list[str] = []
    for spec in ordered_specs[changed_stage_index + 1:]:
        directory = stage_directory(run_root=root, stage_name=spec.name)
        if not directory.exists():
            continue
        destination = root / "invalidated" / timestamp / spec.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(directory), str(destination))
        _LOGGER.warning("Invalidated downstream stage %s to %s", spec.name, destination)
        invalidated.append(spec.name)
    return invalidated


def execute_stage(
    *,
    run_root: Path,
    spec: StageSpec,
    config_digest: str,
    package_version: str,
) -> dict[str, Any]:
    """Execute one stage in temporary storage and publish it atomically.

    Args:
        run_root: Run-specific output root.
        spec: Stage definition.
        config_digest: Effective configuration digest.
        package_version: Current package version.

    Returns:
        Completed success manifest.

    Raises:
        StageStateError: If publication cannot proceed safely.
        Exception: Re-raises executor or validation failures after recording them.
    """

    root = Path(run_root).expanduser().resolve()
    inputs = current_input_records(paths=spec.input_provider())
    staging = root / ".staging" / f"{spec.name}.{os.getpid()}.{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    manifest_path = staging / "stage_manifest.json"
    started_at = utc_now_iso()
    _LOGGER.info("Starting stage %s in %s", spec.name, staging)
    running_manifest = {
        "stage_name": spec.name,
        "stage_version": spec.version,
        "package_version": package_version,
        "status": "RUNNING",
        "started_at": started_at,
        "finished_at": None,
        "config_digest": config_digest,
        "inputs": inputs,
        "outputs": [],
        "metrics": {},
        "error": None,
    }
    atomic_write_json(path=manifest_path, value=running_manifest)
    try:
        metrics = spec.executor(staging)
        missing = [
            relative for relative in spec.expected_outputs if not (staging / relative).is_file()
        ]
        if missing:
            raise StageStateError(
                f"Stage {spec.name} did not create expected outputs: {'; '.join(missing)}"
            )
        output_paths = [staging / relative for relative in spec.expected_outputs]
        success_manifest = {
            **running_manifest,
            "status": "SUCCESS",
            "finished_at": utc_now_iso(),
            "metrics": metrics,
            "outputs": [relative_file_record(root=staging, path=path) for path in output_paths],
        }
        atomic_write_json(path=manifest_path, value=success_manifest)
        final_directory = stage_directory(run_root=root, stage_name=spec.name)
        if final_directory.exists():
            timestamp = utc_now_iso().replace(":", "").replace("+", "_")
            superseded = root / "superseded" / timestamp / spec.name
            superseded.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(final_directory), str(superseded))
        final_directory.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final_directory)
        _LOGGER.info("Completed stage %s at %s", spec.name, final_directory)
        return success_manifest
    except BaseException as error:
        failed_manifest = {
            **running_manifest,
            "status": "FAILED",
            "finished_at": utc_now_iso(),
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        }
        atomic_write_json(path=manifest_path, value=failed_manifest)
        failed_destination = root / "failed" / f"{spec.name}.{os.getpid()}.{uuid.uuid4().hex}"
        failed_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(failed_destination))
        _LOGGER.exception(
            "Stage %s failed; diagnostics retained at %s",
            spec.name,
            failed_destination,
        )
        raise


def run_stage_plan(
    *,
    run_root: Path,
    ordered_specs: Sequence[StageSpec],
    config_digest: str,
    package_version: str,
    resume: bool,
    start_at: str | None,
    stop_after: str | None,
    force_stages: set[str],
    dry_run: bool,
) -> list[dict[str, str]]:
    """Run or plan ordered stages with dependency-aware reuse.

    Args:
        run_root: Run-specific output root.
        ordered_specs: Complete ordered stage definitions.
        config_digest: Effective configuration digest.
        package_version: Current package version.
        resume: Permit validated stages to be skipped.
        start_at: Optional first stage.
        stop_after: Optional final stage.
        force_stages: Stages that must rerun.
        dry_run: Report decisions without writing outputs.

    Returns:
        Ordered stage decision records.

    Raises:
        StageStateError: If controls or existing state are unsafe.
    """

    if not ordered_specs:
        raise StageStateError("Stage plan must not be empty.")
    names = [spec.name for spec in ordered_specs]
    if len(names) != len(set(names)):
        raise StageStateError("Stage names must be unique.")
    unknown_force = sorted(force_stages - set(names))
    if unknown_force:
        raise StageStateError("Unknown force stages: " + ", ".join(unknown_force))
    if start_at is not None and start_at not in names:
        raise StageStateError(f"Unknown start stage: {start_at}")
    if stop_after is not None and stop_after not in names:
        raise StageStateError(f"Unknown stop stage: {stop_after}")
    start_index = 0 if start_at is None else names.index(start_at)
    stop_index = len(names) - 1 if stop_after is None else names.index(stop_after)
    if start_index > stop_index:
        raise StageStateError("start_at occurs after stop_after.")
    decisions: list[dict[str, str]] = []
    for index in range(start_index):
        decision = evaluate_stage_reuse(
            run_root=run_root,
            spec=ordered_specs[index],
            config_digest=config_digest,
            package_version=package_version,
        )
        if not decision.reusable:
            raise StageStateError(
                f"Upstream stage {names[index]} is not reusable: {decision.reason}"
            )
        decisions.append(
            {"stage": names[index], "decision": "UPSTREAM_VALIDATED", "reason": decision.reason}
        )
    upstream_changed = False
    for index in range(start_index, stop_index + 1):
        spec = ordered_specs[index]
        reuse = evaluate_stage_reuse(
            run_root=run_root,
            spec=spec,
            config_digest=config_digest,
            package_version=package_version,
        )
        forced = spec.name in force_stages
        should_run = forced or upstream_changed or not reuse.reusable
        if reuse.reusable and not resume and not forced and not upstream_changed:
            raise StageStateError(
                f"Stage {spec.name} already completed successfully. Use --resume or --force-stage."
            )
        if should_run:
            reason = (
                "forced" if forced else "upstream_changed" if upstream_changed else reuse.reason
            )
            decisions.append({"stage": spec.name, "decision": "RUN", "reason": reason})
            if not dry_run:
                invalidate_downstream(
                    run_root=run_root,
                    ordered_specs=ordered_specs,
                    changed_stage_index=index,
                )
                execute_stage(
                    run_root=run_root,
                    spec=spec,
                    config_digest=config_digest,
                    package_version=package_version,
                )
            upstream_changed = True
        else:
            decisions.append(
                {"stage": spec.name, "decision": "SKIPPED_VALIDATED", "reason": reuse.reason}
            )
    return decisions
