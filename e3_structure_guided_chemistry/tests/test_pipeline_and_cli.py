"""Pipeline, output-contract and command-line tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import write_config, write_tsv
import e3chemistry.pipeline as pipeline_module
from e3chemistry.cli import main
from e3chemistry.config import load_config
from e3chemistry.errors import InputValidationError
from e3chemistry.io_utils import read_records
from e3chemistry.pipeline import run_pipeline, select_chemistry_targets
from e3chemistry.structures import resolve_structure_assets


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
        candidate_manifest_path=scientific_inputs["candidate_manifest"],
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
    sensitivity = read_records(output / "tables/threshold_sensitivity.parquet")
    assert len(sensitivity) > 400
    assert (
        output / "tables/threshold_sensitivity_one_at_a_time.parquet"
    ).is_file()
    assert (output / "tables/integrated_candidate_evidence.parquet").is_file()
    assert sum(bool(row["is_configured_threshold_combination"]) for row in sensitivity) == 1
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
            candidate_manifest_path=scientific_inputs["candidate_manifest"],
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
        candidate_manifest_path=scientific_inputs["candidate_manifest"],
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


def test_low_confidence_pocket_is_not_chemistry_ready(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
) -> None:
    """The rank-nine pilot regression must fail the explicit pLDDT gate."""
    pockets = read_records(scientific_inputs["pockets"])
    pockets[0]["druggability_score"] = 0.997
    pockets[0]["conservative_fraction_plddt_ge_70"] = 0.10526315789473684
    altered_inputs = dict(scientific_inputs)
    altered_inputs["pockets"] = write_tsv(tmp_path / "low_confidence.tsv", pockets)

    _, output = _run(tmp_path=tmp_path, scientific_inputs=altered_inputs)

    summary = read_records(output / "tables/group_pharmacophore_summary.tsv")[0]
    assert summary["chemistry_handoff_status"] == "INSUFFICIENT_POCKET_CONFIDENCE"
    assert "INSUFFICIENT_POCKET_CONFIDENCE" in summary[
        "chemistry_handoff_failure_reasons"
    ]
    target = read_records(output / "tables/chemistry_target_manifest.tsv")[0]
    assert target["pocket_confidence_supported"] == "false"


def test_low_druggability_pocket_is_retained_but_not_handoff_ready(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
) -> None:
    """Biological support must remain visible when druggability fails."""
    pockets = read_records(scientific_inputs["pockets"])
    pockets[0]["druggability_score"] = 0.1
    altered_inputs = dict(scientific_inputs)
    altered_inputs["pockets"] = write_tsv(tmp_path / "low_drug.tsv", pockets)

    _, output = _run(tmp_path=tmp_path, scientific_inputs=altered_inputs)

    summary = read_records(output / "tables/group_pharmacophore_summary.tsv")[0]
    assert summary["biology_and_structure_supported"] == "true"
    assert summary["chemistry_handoff_status"] == (
        "INSUFFICIENT_REPRESENTATIVE_DRUGGABILITY"
    )
    assert summary["chemistry_review_tier"] == (
        "STRUCTURALLY_SUPPORTED_LOW_DRUGGABILITY"
    )


@pytest.mark.parametrize(
    ("source_state", "message"),
    [
        (
            {"available": False, "tracked_source_state": "UNAVAILABLE"},
            "provenance is unavailable",
        ),
        (
            {"available": True, "tracked_source_state": "DIRTY"},
            "package source is dirty",
        ),
    ],
)
def test_clean_source_requirement_fails_closed(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    source_state: dict[str, object],
    message: str,
) -> None:
    """A release config must reject unavailable or dirty tracked source."""
    monkeypatch.setattr(
        pipeline_module,
        "capture_source_provenance",
        lambda: source_state,
    )

    with pytest.raises(InputValidationError, match=message):
        run_pipeline(
            config_path=write_config(
                tmp_path / "strict.yaml", require_clean_tracked_source=True
            ),
            candidate_manifest_path=scientific_inputs["candidate_manifest"],
            group_ranking_path=scientific_inputs["ranking"],
            selected_pockets_path=scientific_inputs["pockets"],
            pocket_residue_mappings_path=scientific_inputs["mappings"],
            pocket_conservation_summary_path=scientific_inputs["conservation"],
            structure_asset_manifest_path=scientific_inputs["assets"],
            output_dir=tmp_path / "strict_output",
        )


def test_cli_prepares_expanded_candidate_manifest(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The named-argument CLI must prepare an auditable expanded panel."""
    output = tmp_path / "cli_panel"
    status = main(
        [
            "prepare-candidate-manifest",
            "--config",
            str(write_config(tmp_path / "prepare.yaml")),
            "--group-ranking",
            str(scientific_inputs["ranking"]),
            "--selected-pockets",
            str(scientific_inputs["pockets"]),
            "--pocket-residue-mappings",
            str(scientific_inputs["mappings"]),
            "--structure-asset-manifest",
            str(scientific_inputs["assets"]),
            "--output-dir",
            str(output),
            "--maximum-rank",
            "200",
            "--decision-basis",
            "EXPANDED_COMPUTATIONAL_SCREEN",
            "--decided-by",
            "Peter Thorpe",
            "--rationale",
            "Expanded test screen",
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["included_group_count"] == 1
    assert (output / "candidate_manifest.tsv").is_file()


def test_cli_runs_workflow_campaign_without_hand_written_manifest(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The end-to-end command must prepare and analyse the current full panel."""
    output = tmp_path / "workflow_campaign"
    status = main(
        [
            "run-workflow-campaign",
            "--config",
            str(write_config(tmp_path / "workflow_config.yaml")),
            "--group-ranking",
            str(scientific_inputs["ranking"]),
            "--selected-pockets",
            str(scientific_inputs["pockets"]),
            "--pocket-residue-mappings",
            str(scientific_inputs["mappings"]),
            "--pocket-conservation-summary",
            str(scientific_inputs["conservation"]),
            "--structure-asset-manifest",
            str(scientific_inputs["assets"]),
            "--output-dir",
            str(output),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "complete"
    assert payload["candidate_panel"]["included_group_count"] == 1
    assert (
        output / "provenance" / "candidate_panel" / "candidate_manifest.tsv"
    ).is_file()
    assert (output / "tables" / "integrated_candidate_evidence.parquet").is_file()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("missing_group", "absent from Stage 08"),
        ("identity", "identity conflicts"),
        ("missing_pocket", "absent from selected pockets"),
        ("missing_asset", "no validated structure"),
        ("checksum", "checksum conflicts"),
        ("missing_mapping", "no mapped pocket residues"),
        ("species", "species conflicts"),
        ("bad_rank", "must be an integer"),
        ("bad_score", "Expected a numeric value"),
        ("non_finite_score", "Expected a finite numeric value"),
    ],
)
def test_candidate_manifest_must_match_every_controlled_authority(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
    change: str,
    message: str,
) -> None:
    """No manifest identity may drift from Stage 08/09 evidence."""
    config = load_config(write_config(tmp_path / "config.yaml"))
    manifest = read_records(scientific_inputs["candidate_manifest"])
    ranking = read_records(scientific_inputs["ranking"])
    pockets = read_records(scientific_inputs["pockets"])
    mappings = read_records(scientific_inputs["mappings"])
    conservation = read_records(scientific_inputs["conservation"])
    assets = resolve_structure_assets(read_records(scientific_inputs["assets"]))
    if change == "missing_group":
        manifest[0]["evolutionary_group_key"] = "HIERARCHICAL_ORTHOGROUP:UNKNOWN"
    elif change == "identity":
        manifest[0]["evolutionary_group_rank"] = 2
    elif change == "missing_pocket":
        manifest[0]["pocket_number"] = 99
    elif change == "missing_asset":
        assets = {}
    elif change == "checksum":
        manifest[0]["structure_sha256"] = "0" * 64
    elif change == "missing_mapping":
        for row in mappings:
            row["mapping_status"] = "UNMAPPED"
    elif change == "species":
        manifest[0]["species_column"] = "Wrong_species"
    elif change == "bad_rank":
        ranking[0]["evolutionary_group_rank"] = "not-an-integer"
    elif change == "bad_score":
        pockets[0]["druggability_score"] = "bad"
    elif change == "non_finite_score":
        pockets[0]["druggability_score"] = "nan"

    with pytest.raises(InputValidationError, match=message):
        select_chemistry_targets(
            candidate_manifest=manifest,
            group_ranking=ranking,
            selected_pockets=pockets,
            conservation=conservation,
            assets=assets,
            mappings=mappings,
            config=config,
        )


def test_structure_resolution_failure_is_published_not_silenced(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late structure-resolution failure must produce an explicit empty result."""
    monkeypatch.setattr(
        pipeline_module,
        "load_pocket_residues",
        lambda **kwargs: (_ for _ in ()).throw(
            InputValidationError("controlled resolution failure")
        ),
    )

    result, output = _run(tmp_path=tmp_path, scientific_inputs=scientific_inputs)

    assert result["pharmacophore_feature_count"] == 0
    qc = read_records(output / "qc/computational_chemistry_validation.tsv")[0]
    assert qc["validation_status"] == "PASS_WITH_NO_RESOLVED_FEATURES"
    target = read_records(output / "tables/chemistry_target_manifest.tsv")[0]
    assert target["target_status"] == "STRUCTURE_RESIDUE_RESOLUTION_FAILED"


def test_output_file_and_missing_candidate_manifest_are_rejected(
    tmp_path: Path,
    scientific_inputs: dict[str, Path],
) -> None:
    """Output and input path failures must occur before scientific execution."""
    output_file = tmp_path / "output.txt"
    output_file.write_text("occupied\n", encoding="utf-8")
    common = {
        "config_path": write_config(tmp_path / "config.yaml"),
        "candidate_manifest_path": scientific_inputs["candidate_manifest"],
        "group_ranking_path": scientific_inputs["ranking"],
        "selected_pockets_path": scientific_inputs["pockets"],
        "pocket_residue_mappings_path": scientific_inputs["mappings"],
        "pocket_conservation_summary_path": scientific_inputs["conservation"],
        "structure_asset_manifest_path": scientific_inputs["assets"],
        "output_dir": output_file,
    }
    with pytest.raises(InputValidationError, match="Output directory is a file"):
        run_pipeline(**common)

    common["output_dir"] = tmp_path / "new_output"
    common["candidate_manifest_path"] = tmp_path / "missing.tsv"
    with pytest.raises(InputValidationError, match="candidate_manifest input"):
        run_pipeline(**common)
