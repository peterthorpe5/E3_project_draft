"""Shared method options and isolated LoL-align workflow preparation."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest
import yaml

from e3workflow.alignment_options import resolve_structural_methods, structural_method_arguments
from e3workflow.config import controlled_input_paths, load_config
from e3workflow.errors import ConfigurationError
from e3workflow.lolalign_config import METHODS, main, prepare_lolalign_config
from e3workflow.io_utils import read_tsv
import e3workflow.human_plant_extension as extension
from e3workflow.cli import main as workflow_main


@pytest.mark.parametrize("mode", tuple(METHODS))
def test_prepare_and_method_flags(*, synthetic_config: Path, mode: str) -> None:
    """Every method mode changes the run digest and preserves the original YAML."""
    source_bytes = synthetic_config.read_bytes()
    previous = load_config(path=synthetic_config)
    destination = synthetic_config.with_name(f"new_{mode}.yaml")
    result = prepare_lolalign_config(
        source_config=synthetic_config, output_config=destination,
        run_name=f"new_{mode}", mode=mode, foldseek_executable="/tools/foldseek",
    )
    prepared = load_config(path=result)
    settings = prepared.analysis.structural_alignment
    assert (settings.run_usalign, settings.run_tmalign, settings.run_lolalign) == METHODS[mode]
    assert prepared.digest != previous.digest
    assert prepared.run_root != previous.run_root
    assert controlled_input_paths(config=prepared) == controlled_input_paths(config=previous)
    assert synthetic_config.read_bytes() == source_bytes
    flags = structural_method_arguments(settings=settings)
    assert "--run-lolalign" in flags and "/tools/foldseek" in flags
    assert ("--skip-tmalign" in flags) == (mode != "alongside")
    assert ("--skip-usalign" in flags) == (mode == "lolalign-only")
    single_domain = replace(settings, lolalign_multidomain=False)
    assert "--lolalign-single-domain" in structural_method_arguments(settings=single_domain)


def test_default_methods_need_no_extra_flags(*, synthetic_config: Path) -> None:
    """Existing workflow configurations keep their existing US-align/TM-align command."""
    config = load_config(path=synthetic_config)
    assert structural_method_arguments(settings=config.analysis.structural_alignment) == ()


def test_config_rejects_disabled_methods_and_quoted_boolean(*, synthetic_config: Path) -> None:
    """Invalid aligner settings must fail before submitting cluster jobs."""
    raw = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    settings = raw.setdefault("analysis", {}).setdefault("structural_alignment", {})
    settings.update(run_usalign=False, run_tmalign=False, run_lolalign=False)
    synthetic_config.write_text(data=yaml.safe_dump(data=raw), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="At least one"):
        load_config(path=synthetic_config)
    settings["run_lolalign"] = "true"
    synthetic_config.write_text(data=yaml.safe_dump(data=raw), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="must be boolean"):
        load_config(path=synthetic_config)


def test_config_preparation_protects_paths_and_existing_files(*, synthetic_config: Path) -> None:
    """The preparation command cannot overwrite inputs or silently move relative references."""
    original = load_config(path=synthetic_config)
    destination = synthetic_config.with_name("new.yaml")
    for output, name, mode in (
        (synthetic_config, "new", "alongside"),
        (synthetic_config.parent / "other" / "new.yaml", "new", "alongside"),
        (destination, original.run_name, "alongside"),
        (destination, "../bad", "alongside"),
        (destination, "new", "invalid"),
    ):
        with pytest.raises(ValueError):
            prepare_lolalign_config(
                source_config=synthetic_config, output_config=output, run_name=name, mode=mode,
            )
    destination.write_text(data="existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        prepare_lolalign_config(
            source_config=synthetic_config, output_config=destination, run_name="new",
        )
    assert destination.read_text(encoding="utf-8") == "existing"


def test_preparation_cli_success_and_failure(*, synthetic_config: Path, capsys) -> None:
    """Named CLI options prepare a reviewable YAML and report errors cleanly."""
    output = synthetic_config.with_name("cli.yaml")
    argv = [
        "--source-config", str(synthetic_config), "--output-config", str(output),
        "--run-name", "new_cli", "--mode", "replace-tmalign",
    ]
    assert main(argv=argv) == 0
    assert str(output) in capsys.readouterr().out
    assert main(argv=argv) == 2


def test_preparation_group_limit(*, synthetic_config: Path) -> None:
    """The requested structural breadth remains explicit in the new run configuration."""
    output = synthetic_config.with_name("all_groups.yaml")
    prepare_lolalign_config(
        source_config=synthetic_config, output_config=output, run_name="all_groups",
        structure_group_limit=1972,
    )
    assert load_config(path=output).analysis.prioritisation.structure_group_limit == 1972
    with pytest.raises(ValueError, match="positive integer"):
        prepare_lolalign_config(
            source_config=synthetic_config, output_config=output, run_name="new",
            structure_group_limit=0,
        )
    settings = load_config(path=output).analysis.structural_alignment
    with pytest.raises(ConfigurationError, match="must be boolean"):
        replace(settings, run_lolalign="true")


def test_extension_method_overrides(*, synthetic_config: Path) -> None:
    """Override methods independently while preserving all parent scientific thresholds."""
    parent = load_config(path=synthetic_config).analysis.structural_alignment
    assert resolve_structural_methods(settings=parent, options=None) is parent
    changed = resolve_structural_methods(
        settings=parent,
        options='{"run_lolalign": true, "run_tmalign": false, '
        '"foldseek_executable": " /tools/fs "}',
    )
    assert changed.run_lolalign and not changed.run_tmalign
    assert changed.foldseek_executable == "/tools/fs"
    assert changed.minimum_global_tm_score == parent.minimum_global_tm_score
    assert not parent.run_lolalign
    for options in ("bad", "[]", '{"unknown": true}', '{"foldseek_executable": ""}'):
        with pytest.raises(ConfigurationError):
            resolve_structural_methods(settings=parent, options=options)


def test_human_extension_method_change_invalidates_only_its_task(
    *, synthetic_config: Path, tmp_path: Path, monkeypatch,
) -> None:
    """Pass extension options to the component and invalidate cached alignments on changes."""
    parent_bytes = synthetic_config.read_bytes()
    groups, ligandability = tmp_path / "groups.tsv", tmp_path / "ligandability.json"
    groups.write_text(data="group\nOG1\n", encoding="utf-8")
    ligandability.write_text(data="{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(extension, "_group_record", lambda **kwargs: {
        "primary_group_type": "orthogroup", "primary_group_id": "OG1",
    })
    keys = (
        "selected_pockets", "ranked_pockets", "pocket_residue_mappings",
        "pocket_sequence_coordinates", "ranked_pocket_sequence_coordinates",
        "asset_manifest", "reference_manifest",
    )
    monkeypatch.setattr(
        extension, "_prepare_human_plant_structural_inputs",
        lambda **kwargs: {key: groups for key in keys},
    )

    def component(*, argv, **kwargs):
        """Publish the minimal component authority consumed by the task wrapper."""
        calls.append(argv)
        output = Path(argv[argv.index("--output-dir") + 1]) / "provenance" / "run_manifest.json"
        output.parent.mkdir(parents=True)
        output.write_text(data='{"status": "complete"}', encoding="utf-8")

    monkeypatch.setattr(extension, "_run_component", component)
    arguments = {
        "parent_config_path": synthetic_config, "group_manifest": groups,
        "ligandability_manifest": ligandability, "output_root": tmp_path / "extension",
        "task_index": 0, "conda_environment": "structural",
    }
    options = {"run_lolalign": True, "foldseek_executable": "/tools/foldseek"}
    marker = extension.run_human_plant_structural_task(
        **arguments, structural_method_options=json.dumps(obj=options),
    )
    assert "--run-lolalign" in calls[0] and "/tools/foldseek" in calls[0]
    previous_digest = read_tsv(path=marker)[1][0]["configuration_digest"]
    extension.run_human_plant_structural_task(
        **arguments, structural_method_options=json.dumps(obj=options),
    )
    assert len(calls) == 1
    options["run_tmalign"] = False
    extension.run_human_plant_structural_task(
        **arguments, structural_method_options=json.dumps(obj=options),
    )
    assert len(calls) == 2 and "--skip-tmalign" in calls[1]
    assert read_tsv(path=marker)[1][0]["configuration_digest"] != previous_digest
    assert synthetic_config.read_bytes() == parent_bytes


def test_human_structural_cli_forwards_method_options(
    *, tmp_path: Path, monkeypatch, capsys,
) -> None:
    """The scheduler-facing CLI must preserve explicit extension method settings."""
    calls = []

    def worker(**kwargs):
        """Capture the task arguments supplied by the production CLI."""
        calls.append(kwargs)
        return tmp_path / "task_complete.tsv"

    monkeypatch.setattr("e3workflow.cli.run_human_plant_structural_task", worker)
    options = '{"run_lolalign": true, "run_tmalign": false}'
    assert workflow_main(argv=[
        "run-human-plant-structural-extension-task",
        "--parent-config", str(tmp_path / "parent.yaml"),
        "--group-manifest", str(tmp_path / "groups.tsv"),
        "--ligandability-manifest", str(tmp_path / "ligandability.json"),
        "--output-root", str(tmp_path / "extension"), "--task-index", "0",
        "--conda-environment", "structural", "--structural-method-options", options,
    ]) == 0
    assert calls[0]["structural_method_options"] == options
    assert json.loads(s=capsys.readouterr().out)["status"] == "complete"
