"""Stage-runner unit checks and synthetic end-to-end execution."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from e3workflow.config import STAGE_NAMES, load_config
from e3workflow.control import initialise_stage_tokens
from e3workflow.errors import StageError
from e3workflow.io_utils import read_tsv
from e3workflow.runner import (
    execute_stage,
    format_command,
    run_internal_stage,
    validate_expected_outputs,
    validate_upstream,
)


def test_format_command_and_expected_outputs(tmp_path: Path) -> None:
    """Argv placeholders and non-empty output contracts are strict."""

    assert format_command(("tool", "{value}"), {"value": "a b"}) == ["tool", "a b"]
    with pytest.raises(StageError, match="placeholder"):
        format_command(("{missing}",), {})
    output = tmp_path / "output.txt"
    output.write_text("ok", encoding="utf-8")
    validate_expected_outputs(tmp_path, ("output.txt",))
    with pytest.raises(StageError, match="Missing"):
        validate_expected_outputs(tmp_path, ("missing",))


def test_stage_requires_wrapper_control_token(synthetic_config: Path) -> None:
    """Direct stage execution fails clearly when wrapper control was not initialised."""

    with pytest.raises(StageError, match="control token is missing"):
        execute_stage(load_config(synthetic_config), "00_inputs")


def test_synthetic_end_to_end_and_lineage(synthetic_config: Path) -> None:
    """All stages publish atomically and carry complete ordered lineage."""

    config = load_config(synthetic_config)
    initialise_stage_tokens(config)
    assert validate_upstream(config, "00_inputs") == []
    for stage in STAGE_NAMES:
        manifest_path = execute_stage(config, stage)
        assert manifest_path.is_file()
    payload = json.loads(manifest_path.read_text())
    assert payload["status"] == "complete"
    assert payload["runner_wall_seconds"] > 0.0
    assert payload["benchmark"]["peak_rss_mb"] > 0
    assert (
        config.run_root / STAGE_NAMES[-1] / "benchmark" / "stage_resource_timeseries.tsv.gz"
    ).is_file()
    assert [row["stage"] for row in payload["lineage"]] == list(STAGE_NAMES)
    assert payload["mode"] == "synthetic"
    handoff = read_tsv(config.run_root / "11_app_ready" / "app_handoff.tsv")[1]
    assert handoff[0]["production_eligible"] == "false"
    execute_stage(config, STAGE_NAMES[-1])
    assert any((config.run_root / "superseded").iterdir())


def test_internal_unknown_and_bad_upstream(synthetic_config: Path, tmp_path: Path) -> None:
    """Unknown production internals and tampered lineage fail closed."""

    config = load_config(synthetic_config)
    initialise_stage_tokens(config)
    run_internal_stage(config, "02_discovery", tmp_path / "synthetic")
    execute_stage(config, "00_inputs")
    upstream = config.run_root / "00_inputs" / "stage_manifest.json"
    payload = json.loads(upstream.read_text())
    payload["configuration_digest"] = "wrong"
    upstream.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(StageError, match="digest"):
        validate_upstream(config, "01_prepared_proteomes")
    production = replace(config, mode="production")
    with pytest.raises(StageError, match="No internal production"):
        run_internal_stage(production, "02_discovery", tmp_path / "production")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update(status="failed"), "not complete"),
        (lambda payload: payload.update(lineage={}), "invalid lineage"),
        (lambda payload: payload.update(outputs=[]), "no output inventory"),
        (lambda payload: payload.update(outputs=["bad"]), "invalid output record"),
        (
            lambda payload: payload["outputs"][0].update(path="../escape"),
            "unsafe output path",
        ),
        (
            lambda payload: payload["outputs"][0].update(path="missing.tsv"),
            "output is missing",
        ),
        (
            lambda payload: payload["outputs"][0].update(size_bytes=-1),
            "output size changed",
        ),
        (
            lambda payload: payload["outputs"][0].update(sha256="0" * 64),
            "checksum changed",
        ),
    ],
)
def test_upstream_manifest_tampering(
    synthetic_config: Path, mutation: object, message: str
) -> None:
    """Every upstream status, path, size and checksum is revalidated."""

    config = load_config(synthetic_config)
    initialise_stage_tokens(config)
    manifest = execute_stage(config, "00_inputs")
    original = manifest.read_text(encoding="utf-8")
    payload = json.loads(original)
    mutation(payload)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(StageError, match=message):
        validate_upstream(config, "01_prepared_proteomes")


def test_disabled_optional_stage(synthetic_config: Path) -> None:
    """An optional disabled stage is explicit and remains in lineage."""

    import yaml

    raw = yaml.safe_load(synthetic_config.read_text())
    raw["stages"]["01_prepared_proteomes"].update(
        enabled=False, required=False, expected_outputs=[]
    )
    synthetic_config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_config(synthetic_config)
    initialise_stage_tokens(config)
    execute_stage(config, "00_inputs")
    manifest = execute_stage(config, "01_prepared_proteomes")
    assert json.loads(manifest.read_text())["status"] == "skipped_optional"


def test_external_command_success_and_failure(synthetic_config: Path) -> None:
    """External argv commands must succeed and meet their output contract."""

    import sys
    import yaml

    raw = yaml.safe_load(synthetic_config.read_text())
    raw["stages"]["01_prepared_proteomes"].update(
        command=[
            sys.executable,
            "-c",
            "from pathlib import Path; Path(r'{stage_dir}/done.txt').write_text('ok')",
        ],
        expected_outputs=["done.txt"],
    )
    synthetic_config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_config(synthetic_config)
    initialise_stage_tokens(config)
    execute_stage(config, "00_inputs")
    assert execute_stage(config, "01_prepared_proteomes").is_file()

    raw["run"]["name"] = "failure"
    raw["stages"]["01_prepared_proteomes"].update(
        command=[sys.executable, "-c", "raise SystemExit(7)"], expected_outputs=[]
    )
    synthetic_config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_config(synthetic_config)
    initialise_stage_tokens(config)
    execute_stage(config, "00_inputs")
    with pytest.raises(StageError, match="returned 7"):
        execute_stage(config, "01_prepared_proteomes")
    failed_directories = list((config.run_root / "failed").iterdir())
    assert failed_directories
    failed_usage = failed_directories[0] / "benchmark" / "stage_resource_usage.tsv"
    assert failed_usage.is_file()
    assert read_tsv(failed_usage)[1][0]["return_code"] == "7"
