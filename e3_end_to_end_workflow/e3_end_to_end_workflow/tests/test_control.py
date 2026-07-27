"""Tests for persistent restart tokens and stage target resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from e3workflow.config import STAGE_NAMES, load_config
from e3workflow.control import (
    initialise_stage_tokens,
    stage_manifest_target,
    stage_token_path,
)
from e3workflow.errors import WorkflowError


def test_initialise_reuse_and_force_stage_tokens(synthetic_config: Path) -> None:
    """Tokens are stable on resume and only selected stages are refreshed."""

    config = load_config(synthetic_config)
    first = initialise_stage_tokens(config)
    assert first["created"] == list(STAGE_NAMES)
    assert first["reused"] == []
    token = stage_token_path(config, "04_orthofinder")
    initial_text = token.read_text(encoding="utf-8")

    second = initialise_stage_tokens(config)
    assert second["reused"] == list(STAGE_NAMES)
    assert token.read_text(encoding="utf-8") == initial_text

    forced = initialise_stage_tokens(config, force_stages=["04_orthofinder"])
    assert forced["refreshed"] == ["04_orthofinder"]
    assert "action\tforced_rerun" in token.read_text(encoding="utf-8")
    assert stage_manifest_target(config, "04_orthofinder") == (
        config.run_root / "04_orthofinder" / "stage_manifest.json"
    )


def test_control_rejects_unknown_stages_and_changed_configuration(
    synthetic_config: Path,
) -> None:
    """Unknown stages and digest changes cannot silently reuse one run root."""

    config = load_config(synthetic_config)
    initialise_stage_tokens(config)
    with pytest.raises(WorkflowError, match="Unknown force stage"):
        initialise_stage_tokens(config, force_stages=["missing"])
    with pytest.raises(WorkflowError, match="Unknown stage"):
        stage_token_path(config, "missing")
    with pytest.raises(WorkflowError, match="Unknown stage"):
        stage_manifest_target(config, "missing")

    raw = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    raw["stages"]["02_discovery"]["threads"] = 2
    synthetic_config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    changed = load_config(synthetic_config)
    with pytest.raises(WorkflowError, match="different configuration digest"):
        initialise_stage_tokens(changed)
