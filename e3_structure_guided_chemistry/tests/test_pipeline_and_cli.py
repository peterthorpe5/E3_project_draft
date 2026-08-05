"""Pipeline, output-contract and command-line tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import write_config
from e3chemistry.cli import main
from e3chemistry.errors import InputValidationError
from e3chemistry.pipeline import run_pipeline


def _run(
    *,
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
    mode: str = "prepare_only",
) -> tuple[dict[str, object], Path]:
    """Run one complete fixture workflow."""
    config = write_config(
        tmp_path / f"{mode}.yaml",
        mode=mode,
        fragment_library=(
            scientific_inputs["fragments"]
            if mode == "open_fragment_screen"
            else None
        ),
    )
    output = tmp_path / f"output_{mode}"
    result = run_pipeline(
        config_path=config,
        group_ranking_path=scientific_inputs["ranking"],
        selected_pockets_path=scientific_inputs["pockets"],
        pocket_residue_mappings_path=scientific_inputs["mappings"],
        pocket_conservation_summary_path=scientific_inputs["conservation"],
        structure_asset_manifest_path=scientific_inputs["assets"],
        output_dir=output,
    )
    return result, output


def test_prepare_only_pipeline_contract(
    tmp_path: Path, scientific_inputs: dict[str, Path]
) -> None:
    """Structure preparation must publish complete empty fragment authorities."""
    result, output = _run(
        tmp_path=tmp_path,
        scientific_inputs=scientific_inputs,
    )

    assert result["status"] == "complete"
    manifest = json.loads(
        (output / "provenance/run_manifest.json").read_text(encoding="utf-8")
    )
    assert not any(row["path"].startswith("logs/") for row in manifest["outputs"])
    assert int(result["pharmacophore_feature_count"]) >= 2
    assert (output / "tables/group_pharmacophore_summary.parquet").is_file()
    assert (output / "tables/fragment_pharmacophore_ranking.parquet").is_file()
    assert (output / "reports/structure_guided_chemistry_summary.html").is_file()
    method_status = (output / "METHOD_STATUS.tsv").read_text(encoding="utf-8")
    assert "FMOPhore\tfalse\tNOT_RUN" in method_status
    assert "FrAncestor\tfalse\tNOT_RUN" in method_status
    assert "AlphaFold3\tfalse\tNOT_RUN" in method_status
    component_licences = (output / "COMPONENT_LICENCES.tsv").read_text(
        encoding="utf-8"
    )
    assert "DuckDB\tMIT\ttrue\tfalse" in component_licences
    assert "Gemmi\tMPL-2.0\ttrue\tfalse" in component_licences
    milestone_coverage = (output / "MILESTONE_COVERAGE.tsv").read_text(
        encoding="utf-8"
    )
    assert "structure_prediction_refinement\tEXISTING_STRUCTURES_CONSUMED" in (
        milestone_coverage
    )
    assert "fragment_prioritisation\tPREPARED_NOT_SCREENED" in milestone_coverage


def test_open_fragment_pipeline_and_manifest(
    tmp_path: Path, scientific_inputs: dict[str, Path]
) -> None:
    """The RDKit route must rank open fragments and record input checksums."""
    result, output = _run(
        tmp_path=tmp_path,
        scientific_inputs=scientific_inputs,
        mode="open_fragment_screen",
    )

    assert int(result["fragment_ranking_count"]) == 2
    manifest = json.loads(
        (output / "provenance/run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["licence_policy"]["allow_restricted_licence_tools"] is False
    assert manifest["inputs"]["fragment_library"]["sha256"]
    assert manifest["counts"]["restricted_licence_tools_used"] is False
    milestone_coverage = (output / "MILESTONE_COVERAGE.tsv").read_text(
        encoding="utf-8"
    )
    assert "fragment_prioritisation\tEXECUTED_OPEN_ALTERNATIVE" in (
        milestone_coverage
    )


def test_non_empty_output_is_rejected(
    tmp_path: Path, scientific_inputs: dict[str, Path]
) -> None:
    """Standalone runs must not silently mix with an earlier result."""
    output = tmp_path / "occupied"
    output.mkdir()
    (output / "existing.txt").write_text("occupied", encoding="utf-8")

    with pytest.raises(InputValidationError, match="not empty"):
        run_pipeline(
            config_path=write_config(tmp_path / "config.yaml"),
            group_ranking_path=scientific_inputs["ranking"],
            selected_pockets_path=scientific_inputs["pockets"],
            pocket_residue_mappings_path=scientific_inputs["mappings"],
            pocket_conservation_summary_path=scientific_inputs["conservation"],
            structure_asset_manifest_path=scientific_inputs["assets"],
            output_dir=output,
        )


def test_runner_log_directory_is_allowed(
    tmp_path: Path, scientific_inputs: dict[str, Path]
) -> None:
    """The workflow runner may create its command log before package startup."""
    output = tmp_path / "runner_staging"
    (output / "logs").mkdir(parents=True)
    (output / "logs" / "command.log").write_text("started\n", encoding="utf-8")

    result = run_pipeline(
        config_path=write_config(tmp_path / "config.yaml"),
        group_ranking_path=scientific_inputs["ranking"],
        selected_pockets_path=scientific_inputs["pockets"],
        pocket_residue_mappings_path=scientific_inputs["mappings"],
        pocket_conservation_summary_path=scientific_inputs["conservation"],
        structure_asset_manifest_path=scientific_inputs["assets"],
        output_dir=output,
    )

    assert result["status"] == "complete"
    manifest = json.loads(
        (output / "provenance/run_manifest.json").read_text(encoding="utf-8")
    )
    assert not any(row["path"].startswith("logs/") for row in manifest["outputs"])


def test_cli_validation_and_controlled_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI must emit JSON for valid YAML and status 2 for missing YAML."""
    config = write_config(tmp_path / "config.yaml")

    assert main(["validate-config", "--config", str(config)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "valid"
    assert payload["restricted_licence_tools_allowed"] is False
    assert main(["validate-config", "--config", str(tmp_path / "missing.yaml")]) == 2
