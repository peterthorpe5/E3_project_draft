"""Persistent control records for safe Snakemake restarts and targeted reruns."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from e3workflow.config import STAGE_NAMES, WorkflowConfig
from e3workflow.errors import WorkflowError
from e3workflow.io_utils import atomic_write_text, utc_now


def stage_token_path(config: WorkflowConfig, stage_name: str) -> Path:
    """Return the persistent control-token path for a workflow stage.

    Args:
        config: Validated workflow configuration.
        stage_name: Stable stage identifier.

    Returns:
        Path used as a Snakemake input for the stage.

    Raises:
        WorkflowError: If the stage name is unknown.
    """
    if stage_name not in STAGE_NAMES:
        raise WorkflowError(f"Unknown stage: {stage_name}")
    return config.run_root / "workflow_control" / "stage_tokens" / f"{stage_name}.token"


def initialise_stage_tokens(
    config: WorkflowConfig,
    force_stages: Iterable[str] = (),
) -> dict[str, object]:
    """Initialise stable tokens and intentionally refresh selected stages.

    A stage token is an ordinary Snakemake input. Rewriting a selected token makes that stage
    out-of-date, after which normal DAG dependencies propagate the rerun downstream. Existing
    tokens must carry the current configuration digest, preventing accidental reuse of one run
    directory under a different configuration.

    Args:
        config: Validated workflow configuration.
        force_stages: Stages that should rerun intentionally.

    Returns:
        Summary containing created, reused and refreshed stage names.

    Raises:
        WorkflowError: If a stage is unknown or an existing token belongs to another configuration.
    """
    requested = tuple(force_stages)
    unknown = sorted(set(requested).difference(STAGE_NAMES))
    if unknown:
        raise WorkflowError(f"Unknown force stage: {', '.join(unknown)}")
    created: list[str] = []
    reused: list[str] = []
    refreshed: list[str] = []
    forced = set(requested)
    for stage_name in STAGE_NAMES:
        path = stage_token_path(config, stage_name)
        if path.exists():
            fields = dict(
                line.split("\t", maxsplit=1)
                for line in path.read_text(encoding="utf-8").splitlines()
                if "\t" in line
            )
            if fields.get("configuration_digest") != config.digest:
                raise WorkflowError(
                    "Existing workflow control token has a different configuration digest: "
                    f"{path}. Use a new run name for a changed configuration."
                )
            if stage_name not in forced:
                reused.append(stage_name)
                continue
        action = "forced_rerun" if path.exists() else "initialised"
        text = (
            f"stage\t{stage_name}\n"
            f"configuration_digest\t{config.digest}\n"
            f"action\t{action}\n"
            f"updated_at_utc\t{utc_now()}\n"
        )
        atomic_write_text(path, text)
        (refreshed if action == "forced_rerun" else created).append(stage_name)
    return {
        "run_root": str(config.run_root),
        "created": created,
        "reused": reused,
        "refreshed": refreshed,
    }


def stage_manifest_target(config: WorkflowConfig, stage_name: str) -> Path:
    """Return the formal manifest target for one stage.

    Args:
        config: Validated workflow configuration.
        stage_name: Stable stage identifier.

    Returns:
        Snakemake target path.
    """
    if stage_name not in STAGE_NAMES:
        raise WorkflowError(f"Unknown stage: {stage_name}")
    return config.run_root / stage_name / "stage_manifest.json"
