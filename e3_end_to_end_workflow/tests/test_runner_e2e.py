"""Stage-runner unit checks and synthetic end-to-end execution."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from e3workflow.config import STAGE_NAMES, load_config
from e3workflow.control import initialise_stage_tokens
from e3workflow.errors import StageError
from e3workflow.io_utils import read_tsv
from e3workflow.runner import (
    _summarise_protein_fasta,
    execute_stage,
    format_command,
    materialise_orthology_component_outputs,
    run_internal_stage,
    validate_expected_outputs,
    validate_upstream,
)


def _write_partial_production_config(path: Path) -> None:
    """Convert a synthetic fixture into an OrthoFinder-branch production configuration."""
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["run"]["mode"] = "production"
    for stage_name, stage in raw["stages"].items():
        stage["enabled"] = stage_name in {"00_inputs", "01_prepared_proteomes", "04_orthofinder"}
        stage["required"] = stage["enabled"]
        stage.pop("command", None)
        if not stage["enabled"]:
            stage["expected_outputs"] = []
    raw["stages"]["01_prepared_proteomes"]["expected_outputs"] = ["prepared_proteomes.tsv"]
    raw["stages"]["04_orthofinder"].update(
        command=["orthofinder", "-f", "{run_root}/01_prepared_proteomes/proteomes"],
        expected_outputs=["Results/Log.txt"],
    )
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


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


def test_materialise_orthology_component_outputs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nested portable products satisfy the stable master-stage contract."""

    expected_outputs = (
        "orthology/tables/candidate_membership_mapping.parquet",
        "orthology/qc/validation_checks.tsv",
    )
    component_root = (
        tmp_path / "orthology" / "stages" / "05_publish_portable_outputs"
    )
    sources = {
        "tables/candidate_membership_mapping.parquet": b"parquet fixture",
        "qc/validation_checks.tsv": b"check_name\tstatus\nfixture\tPASS\n",
    }
    for relative_path, content in sources.items():
        source = component_root / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)

    logger = logging.getLogger("test.orthology_materialisation")
    with caplog.at_level(logging.INFO, logger=logger.name):
        materialise_orthology_component_outputs(
            stage_root=tmp_path,
            expected_outputs=expected_outputs,
            logger=logger,
        )

    validate_expected_outputs(tmp_path, expected_outputs)
    for expected_output in expected_outputs:
        destination = tmp_path / expected_output
        source = component_root / Path(expected_output).relative_to("orthology")
        assert destination.read_bytes() == source.read_bytes()
    assert "Materialised orthology component output" in caplog.text


def test_materialise_orthology_component_outputs_fails_closed(
    tmp_path: Path,
) -> None:
    """Missing component products and invalid master paths are never hidden."""

    logger = logging.getLogger("test.orthology_materialisation_failure")
    with pytest.raises(StageError, match="did not publish"):
        materialise_orthology_component_outputs(
            stage_root=tmp_path,
            expected_outputs=("orthology/tables/missing.parquet",),
            logger=logger,
        )
    with pytest.raises(StageError, match="below orthology"):
        materialise_orthology_component_outputs(
            stage_root=tmp_path,
            expected_outputs=("tables/unscoped.parquet",),
            logger=logger,
        )


def test_external_orthology_command_materialises_master_contract(
    synthetic_config: Path,
    tmp_path: Path,
) -> None:
    """A successful nested component publication completes outer stage 05."""

    import sys
    import yaml

    fake_component = tmp_path / "fake_orthology_component.py"
    fake_component.write_text(
        "\n".join(
            (
                "from pathlib import Path",
                "import sys",
                "root = (Path(sys.argv[1]) / 'orthology' / 'stages' / "
                "'05_publish_portable_outputs')",
                "outputs = {",
                "    'tables/candidate_membership_mapping.parquet': b'parquet fixture',",
                "    'qc/validation_checks.tsv': b'check_name\\tstatus\\nfixture\\tPASS\\n',",
                "}",
                "for relative_path, content in outputs.items():",
                "    destination = root / relative_path",
                "    destination.parent.mkdir(parents=True, exist_ok=True)",
                "    destination.write_bytes(content)",
                "",
            )
        ),
        encoding="utf-8",
    )
    raw = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    raw["schema_version"] = 2
    raw["tools"] = {
        "fake_orthology": {
            "executable": sys.executable,
            "expected_version": "test",
            "parameters": {"component_script": str(fake_component)},
        }
    }
    expected_outputs = [
        "orthology/tables/candidate_membership_mapping.parquet",
        "orthology/qc/validation_checks.tsv",
    ]
    raw["stages"]["05_orthology"].update(
        command=[
            "{tool_fake_orthology_executable}",
            "{tool_fake_orthology_component_script}",
            "{stage_dir}",
        ],
        expected_outputs=expected_outputs,
    )
    synthetic_config.write_text(
        yaml.safe_dump(raw, sort_keys=False),
        encoding="utf-8",
    )

    config = load_config(synthetic_config)
    initialise_stage_tokens(config)
    for stage_name in STAGE_NAMES[:5]:
        execute_stage(config, stage_name)
    manifest = execute_stage(config, "05_orthology")

    assert manifest.is_file()
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "complete"
    validate_expected_outputs(manifest.parent, tuple(expected_outputs))


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
    assert (config.run_root / STAGE_NAMES[-1] / "report" / "stage_report.html").is_file()
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
        run_internal_stage(production, "05_orthology", tmp_path / "production")


def test_production_prepares_checksum_bound_proteomes(synthetic_config: Path) -> None:
    """The native production adapter validates and copies every selected protein FASTA."""
    _write_partial_production_config(synthetic_config)
    config = load_config(synthetic_config)
    initialise_stage_tokens(config)
    execute_stage(config, "00_inputs")
    manifest = execute_stage(config, "01_prepared_proteomes")
    prepared_root = manifest.parent
    fields, rows = read_tsv(prepared_root / "prepared_proteomes.tsv")
    assert "prepared_fasta_sha256" in fields
    assert [row["species_id"] for row in rows] == [
        "arabidopsis_thaliana",
        "homo_sapiens",
    ]
    assert all(int(row["sequence_count"]) > 0 for row in rows)
    assert all(int(row["residue_count"]) > 0 for row in rows)
    for row in rows:
        prepared = prepared_root / row["prepared_fasta_relative_path"]
        assert prepared.is_file()
        assert row["prepared_fasta_sha256"] == row["source_fasta_sha256"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "no records"),
        ("MPEPTIDE\n", "precede the first header"),
        (">x\nM\n>x\nM\n", "Duplicate FASTA identifier"),
        (">x\n>y\nM\n", "has no residues"),
        (">x\n", "has no residues"),
    ],
)
def test_protein_fasta_preparation_rejects_malformed_records(
    tmp_path: Path, content: str, message: str
) -> None:
    """Malformed or ambiguous protein FASTA records fail before OrthoFinder execution."""
    fasta = tmp_path / "bad.fasta"
    fasta.write_text(content, encoding="utf-8")
    with pytest.raises(StageError, match=message):
        _summarise_protein_fasta(fasta)


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
    """A disabled stage reports its skip record, not inactive scientific outputs."""

    import yaml

    raw = yaml.safe_load(synthetic_config.read_text())
    raw["stages"]["01_prepared_proteomes"].update(
        enabled=False,
        required=False,
        expected_outputs=["inactive/tables/prepared_proteomes.parquet"],
    )
    synthetic_config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_config(synthetic_config)
    initialise_stage_tokens(config)
    execute_stage(config, "00_inputs")
    manifest = execute_stage(config, "01_prepared_proteomes")
    payload = json.loads(manifest.read_text())
    assert payload["status"] == "skipped_optional"
    assert payload["validation"] == {
        "configured_output_count": 1,
        "declared_output_count": 0,
        "declared_outputs_validated": False,
        "skipped_record_validated": True,
        "upstream_manifests_validated": 1,
    }
    assert [item["path"] for item in payload["result_summaries"]] == ["SKIPPED.tsv"]
    assert payload["result_summaries"][0]["row_count"] == 1
    assert not (manifest.parent / "inactive").exists()
    assert (manifest.parent / "report" / "stage_report.html").is_file()


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
