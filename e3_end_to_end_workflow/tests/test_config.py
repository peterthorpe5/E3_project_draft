"""Tests for workflow configuration validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from e3workflow.config import (
    STAGE_NAMES,
    controlled_input_paths,
    load_config,
    previous_stage,
    stage_ancestors,
    stage_dependencies,
    stage_interpretation,
    stage_purpose,
)
from e3workflow.errors import ConfigurationError


def test_load_valid_config_and_lookup(synthetic_config: Path) -> None:
    """Valid configuration resolves paths, stages and a stable digest."""

    config = load_config(synthetic_config)
    assert config.mode == "synthetic"
    assert config.stage("00_inputs").required
    assert config.stage("02_discovery").evidence_mode == "synthetic"
    assert config.benchmarking.sample_interval_seconds == 0.01
    assert config.benchmarking.collect_slurm_accounting is False
    assert config.reporting.preview_rows == 10
    assert config.reporting.max_table_columns == 12
    assert config.reporting.max_chart_items == 20
    assert config.run_root.name == "synthetic_e2e_v0_7_0"
    assert len(config.digest) == 64
    assert previous_stage("00_inputs") is None
    assert previous_stage("01_prepared_proteomes") == "00_inputs"
    assert stage_dependencies("04_orthofinder") == ("01_prepared_proteomes",)
    assert set(stage_dependencies("08_shortlist_gate")) == {
        "03_candidate_evidence",
        "05_orthology",
        "06_domains",
        "07_expression",
    }
    assert stage_dependencies("09b_structural_alignment") == ("09_ligandability",)
    assert stage_dependencies("09c_computational_chemistry") == ("09_ligandability",)
    assert "09b_structural_alignment" in stage_dependencies("10_integrated_resource")
    assert "09c_computational_chemistry" in stage_dependencies("10_integrated_resource")
    assert config.stage("09b_structural_alignment").enabled is False
    assert config.stage("09b_structural_alignment").required is False
    assert config.stage("09c_computational_chemistry").enabled is False
    assert config.stage("09c_computational_chemistry").required is False
    assert "04_orthofinder" in stage_ancestors("05_orthology")
    assert "02_discovery" in stage_ancestors("05_orthology")
    assert "reviewed reuse or a fresh isolated run" in stage_purpose("04_orthofinder")[0]
    assert "project-reviewed phylogeny was preferred" in stage_purpose("04_orthofinder")[1]
    assert "does not prove" in stage_interpretation("02_discovery")[1]
    with pytest.raises(ConfigurationError):
        config.stage("missing")
    with pytest.raises(ConfigurationError):
        previous_stage("missing")
    with pytest.raises(ConfigurationError):
        stage_dependencies("missing")
    with pytest.raises(ConfigurationError):
        stage_purpose("missing")
    with pytest.raises(ConfigurationError):
        stage_interpretation("missing")
    with pytest.raises(ConfigurationError):
        stage_ancestors("missing")


def test_five_proteome_orthofinder_configuration(package_root: Path) -> None:
    """The first real run enables only validated input preparation and OrthoFinder 2.5.5."""
    path = package_root / "config" / "five_proteome_orthofinder.cluster.yaml"
    config = load_config(path)
    enabled = [stage.name for stage in config.stages if stage.enabled]
    assert enabled == ["00_inputs", "01_prepared_proteomes", "04_orthofinder"]
    assert config.run_name == "five_proteome_orthofinder_v0_1_0_20260722"
    assert config.stage("01_prepared_proteomes").command == ()
    assert config.stage("04_orthofinder").command[0] == "orthofinder"
    assert config.stage("04_orthofinder").evidence_mode == "generate"
    assert config.stage("04_orthofinder").threads == 4
    assert config.stage("04_orthofinder").memory_mb == 64000
    assert config.stage("04_orthofinder").runtime_minutes == 1440
    assert [label for label, _ in controlled_input_paths(config)] == ["proteomes"]


def test_reuse_and_fresh_templates_expose_evidence_strategy(package_root: Path) -> None:
    """Current reuse and future scaled generation remain separate configuration modes."""
    reused = load_config(
        package_root / "config" / "grant_aligned_reuse.cluster.template.yaml"
    )
    fresh = load_config(package_root / "config" / "production.cluster.template.yaml")
    assert reused.stage("02_discovery").evidence_mode == "reuse"
    assert reused.stage("04_orthofinder").evidence_mode == "reuse"
    assert reused.stage("06_domains").evidence_mode == "download"
    assert fresh.stage("02_discovery").evidence_mode == "generate"
    assert fresh.stage("04_orthofinder").evidence_mode == "generate"
    assert fresh.stage("07_expression").evidence_mode == "generate"
    assert fresh.stage("09_ligandability").evidence_mode == "generate"
    assert reused.stage("09b_structural_alignment").evidence_mode == "disabled"
    assert fresh.stage("09b_structural_alignment").evidence_mode == "generate"
    assert fresh.stage("09b_structural_alignment").enabled is True
    assert reused.analysis.structural_alignment.usalign_executable == "USalign"
    assert reused.analysis.structural_alignment.tmalign_executable == "TMalign"
    assert reused.analysis.structural_alignment.use_for_prioritisation is False
    assert len(reused.analysis.prioritisation.target_species) == 12
    assert fresh.schema_version == 2
    assert fresh.tool("orthofinder").expected_version == "2.5.5"
    assert fresh.tool("orthofinder").parameter("search_threads") == 32
    assert (
        fresh.tool_command_values()["tool_orthofinder_analysis_threads"]
        == "32"
    )
    assert fresh.tool("structural_alignment").conda_environment == (
        "e3_structural_alignment"
    )
    with pytest.raises(ConfigurationError, match="Unknown tool"):
        fresh.tool("missing")
    with pytest.raises(ConfigurationError, match="Unknown parameter"):
        fresh.tool("orthofinder").parameter("missing")


def test_milestone_one_sensitivity_profile_is_explicit(package_root: Path) -> None:
    """The exploratory profile preserves strict evidence and expands review scope."""
    config = load_config(
        package_root
        / "config"
        / "grant_aligned_structural_sensitivity_top100_v0_11_0_20260729.cluster.yaml"
    )
    assert config.analysis.prioritisation.structure_group_limit == 100
    assert config.analysis.prioritisation.final_candidate_limit == 50
    assert config.analysis.structural_alignment.member_pocket_top_k == 5
    assert config.analysis.structural_alignment.require_for_final_recommendation
    assert not config.analysis.structural_alignment.use_for_prioritisation
    assert config.run_name.endswith("top100_v0_11_0_20260729")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(schema_version=3), "schema_version"),
        (lambda data: data.update(schema_version=True), "schema_version"),
        (lambda data: data["run"].update(mode="invalid"), "run.mode"),
        (lambda data: data["run"].update(name="../bad"), "run.name"),
        (lambda data: data["run"].update(project_root=""), "project_root"),
        (lambda data: data.update(stages={"unknown": {}}), "Unknown stage"),
        (lambda data: data.update(stages={"00_inputs": []}), "must be a YAML mapping"),
        (
            lambda data: data["stages"]["02_discovery"].update(enabled="yes"),
            "must be booleans",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(command="tool"),
            "list of non-empty strings",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(
                enabled=False, required=True
            ),
            "Required stage",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(
                expected_outputs=["../escape"]
            ),
            "Unsafe expected output",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(
                expected_outputs=["/absolute"]
            ),
            "Unsafe expected output",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(threads=0),
            "threads must be a positive integer",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(memory_mb=True),
            "memory_mb must be a positive integer",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(runtime_minutes="60"),
            "runtime_minutes must be a positive integer",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(
                evidence_mode="unsupported"
            ),
            "evidence_mode must be one of",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(
                evidence_mode="disabled"
            ),
            "Enabled stage cannot use disabled",
        ),
        (
            lambda data: data["stages"]["02_discovery"].update(
                enabled=False,
                required=False,
                evidence_mode="reuse",
            ),
            "Disabled stage must use disabled",
        ),
        (
            lambda data: data["benchmarking"].update(sample_interval_seconds=0),
            "sample_interval_seconds must be a positive number",
        ),
        (
            lambda data: data["benchmarking"].update(collect_slurm_accounting="yes"),
            "collect_slurm_accounting must be a boolean",
        ),
        (
            lambda data: data.update(benchmarking=[]),
            "benchmarking must be a YAML mapping",
        ),
        (
            lambda data: data["reporting"].update(preview_rows=0),
            "reporting.preview_rows must be a positive integer",
        ),
        (
            lambda data: data["reporting"].update(max_table_columns=True),
            "reporting.max_table_columns must be a positive integer",
        ),
        (
            lambda data: data.update(reporting=[]),
            "reporting must be a YAML mapping",
        ),
        (
            lambda data: data.setdefault("analysis", {})
            .setdefault("expression", {})
            .update(minimum_expression_value=float("inf")),
            "must be finite",
        ),
    ],
)
def test_invalid_configuration_branches(
    synthetic_config: Path, mutation: object, message: str
) -> None:
    """Malformed configuration is rejected with actionable context."""

    data = yaml.safe_load(synthetic_config.read_text())
    mutation(data)
    synthetic_config.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        load_config(synthetic_config)


def test_missing_and_non_mapping_config(tmp_path: Path) -> None:
    """Missing, invalid YAML and non-mapping roots fail closed."""

    with pytest.raises(ConfigurationError):
        load_config(tmp_path / "missing.yaml")
    for index, text in enumerate(("[", "[]")):
        path = tmp_path / f"bad{index}.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ConfigurationError):
            load_config(path)


@pytest.mark.parametrize(
    ("tools", "message"),
    [
        ([], "tools must be a YAML mapping"),
        ({"Bad-Name": {}}, "tools key must match"),
        ({"orthofinder": []}, "must be a YAML mapping"),
        ({"orthofinder": {"executable": ""}}, "executable"),
        (
            {"orthofinder": {"parameters": {"Bad-Name": 1}}},
            "parameters key must match",
        ),
        (
            {"orthofinder": {"parameters": {"threads": [1, 2]}}},
            "must be one non-empty string",
        ),
        (
            {"orthofinder": {"parameters": {"threshold": float("inf")}}},
            "must be finite",
        ),
        (
            {"orthofinder": {"parameters": {"label": "bad\tvalue"}}},
            "must not contain tabs",
        ),
        (
            {"orthofinder": {"unknown": "value"}},
            "Unknown settings",
        ),
    ],
)
def test_invalid_tool_configuration(
    synthetic_config: Path,
    tools: object,
    message: str,
) -> None:
    """Tool registry errors must fail before stage execution."""
    data = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    data["schema_version"] = 2
    data["tools"] = tools
    synthetic_config.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match=message):
        load_config(synthetic_config)


def test_path_base_preserves_relative_inputs_after_config_generation(
    synthetic_config: Path,
    tmp_path: Path,
) -> None:
    """A generated config can retain the base file's relative-path semantics."""
    original = load_config(synthetic_config)
    data = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    data["schema_version"] = 2
    data["path_base"] = str(synthetic_config.parent)
    generated = generated_dir / "run.yaml"
    generated.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    loaded = load_config(generated)
    assert loaded.proteomes_manifest == original.proteomes_manifest
    assert loaded.path_base == synthetic_config.parent.resolve()


def test_production_requires_external_commands(synthetic_config: Path) -> None:
    """Scientific production stages cannot silently use synthetic handlers."""

    data = yaml.safe_load(synthetic_config.read_text())
    data["run"]["mode"] = "production"
    synthetic_config.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=STAGE_NAMES[5]):
        load_config(synthetic_config)


def test_fresh_generation_requires_command(package_root: Path, tmp_path: Path) -> None:
    """A fresh scientific strategy cannot silently call a reuse implementation."""
    source = package_root / "config" / "production.cluster.template.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    data["stages"]["02_discovery"].pop("command")
    path = tmp_path / "fresh.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Fresh generation requires"):
        load_config(path)


def test_structural_prioritisation_requires_enabled_stage(
    synthetic_config: Path,
) -> None:
    """Three-dimensional evidence cannot affect ranking when its stage is disabled."""
    data = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    data.setdefault("analysis", {}).setdefault("structural_alignment", {})[
        "use_for_prioritisation"
    ] = True
    data["stages"]["09b_structural_alignment"].update(
        enabled=False,
        required=False,
        evidence_mode="disabled",
        expected_outputs=[],
    )
    synthetic_config.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="requires the 09b_structural_alignment"):
        load_config(synthetic_config)


def test_enabled_computational_chemistry_requires_component_config(
    synthetic_config: Path,
) -> None:
    """An enabled chemistry stage must never receive an empty config placeholder."""
    data = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    data["stages"]["09c_computational_chemistry"] = {
        "enabled": True,
        "required": False,
        "evidence_mode": "generate",
        "command": ["e3-chemistry", "run"],
        "expected_outputs": ["METHOD_STATUS.tsv"],
    }
    synthetic_config.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="component_config"):
        load_config(synthetic_config)


def test_enabled_computational_chemistry_registers_controlled_config(
    synthetic_config: Path,
    tmp_path: Path,
) -> None:
    """The reviewed component YAML must enter the checksum-controlled inputs."""
    component_config = tmp_path / "chemistry.yaml"
    component_config.write_text("schema_version: 2\n", encoding="utf-8")
    candidate_manifest = tmp_path / "candidate_manifest.tsv"
    candidate_manifest.write_text("panel_order\n1\n", encoding="utf-8")
    data = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    data.setdefault("analysis", {})["computational_chemistry"] = {
        "component_config": str(component_config),
        "candidate_manifest": str(candidate_manifest),
        "conda_environment": "e3_structure_guided_chemistry",
    }
    data["stages"]["09c_computational_chemistry"] = {
        "enabled": True,
        "required": False,
        "evidence_mode": "generate",
        "command": ["e3-chemistry", "run"],
        "expected_outputs": ["METHOD_STATUS.tsv"],
    }
    synthetic_config.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )

    config = load_config(synthetic_config)
    controlled = dict(controlled_input_paths(config))

    assert controlled["computational_chemistry_component_config"] == (
        component_config.resolve()
    )
    assert controlled["computational_chemistry_candidate_manifest"] == (
        candidate_manifest.resolve()
    )


def test_enabled_computational_chemistry_requires_candidate_manifest(
    synthetic_config: Path,
    tmp_path: Path,
) -> None:
    """Enabled v0.2.0 chemistry must not restore automatic rank selection."""
    component_config = tmp_path / "chemistry.yaml"
    component_config.write_text("schema_version: 2\n", encoding="utf-8")
    data = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    data.setdefault("analysis", {})["computational_chemistry"] = {
        "component_config": str(component_config),
        "conda_environment": "e3_structure_guided_chemistry",
    }
    data["stages"]["09c_computational_chemistry"] = {
        "enabled": True,
        "required": False,
        "evidence_mode": "generate",
        "command": ["e3-chemistry", "run"],
        "expected_outputs": ["METHOD_STATUS.tsv"],
    }
    synthetic_config.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="candidate_manifest"):
        load_config(synthetic_config)
