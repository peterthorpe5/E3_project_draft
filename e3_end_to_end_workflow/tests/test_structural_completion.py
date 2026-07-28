"""Regression tests for the distributed structural-completion release."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from e3workflow.config import ConfigurationError, WorkflowConfig, load_config
from e3workflow.distributed import (
    TASK_MARKER_FIELDS,
    _archive_partial,
    _copy_parquet_union,
    _publish_rebased_asset_manifest,
    _read_marker,
    _relative_component_asset_path,
    _run_component,
    _validate_reusable_marker,
    _validate_structural_summary_evidence,
    aggregate_ligandability_shards,
    aggregate_structural_alignment_shards,
    ligandability_task_count,
    run_ligandability_shard,
    run_structural_alignment_shard,
    structural_alignment_task_count,
)
from e3workflow.errors import StageError
from e3workflow.io_utils import read_tsv, sha256_file
from e3workflow.parent_reuse import import_parent_stage
from e3workflow.parent_reuse import (
    _link_or_copy,
    _output_inventory,
    _read_manifest,
    _validate_parent_file,
)
from e3workflow.resources import LIGANDABILITY_DATASETS
from e3workflow.tabular import quote_literal


def _write_parquet(path: Path, schema: str, rows: list[tuple[Any, ...]]) -> None:
    """Write one small typed Parquet fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(f"CREATE TABLE fixture ({schema})")
        if rows:
            placeholders = ", ".join("?" for _ in rows[0])
            connection.executemany(
                f"INSERT INTO fixture VALUES ({placeholders})",
                rows,
            )
        connection.execute(
            f"COPY fixture TO {quote_literal(path)} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()


@pytest.fixture
def structural_config(tmp_path: Path, package_root: Path) -> WorkflowConfig:
    """Return a small structural-completion configuration under a temporary root."""
    source = (
        package_root
        / "config"
        / "grant_aligned_structural_completion_top20_v0_10_0_20260728.cluster.yaml"
    )
    base = load_config(source)
    component = tmp_path / "component.yaml"
    component.write_text("project:\n  name: fixture\n", encoding="utf-8")
    prioritisation = replace(
        base.analysis.prioritisation,
        target_species=("Species_a", "Species_b"),
        mandatory_species=("Species_a",),
        structure_group_limit=2,
        final_candidate_limit=2,
    )
    ligandability = replace(
        base.analysis.ligandability,
        component_config=component,
    )
    return replace(
        base,
        project_root=tmp_path,
        output_root=tmp_path / "runs",
        run_name="structural_fixture",
        parent_run_root=tmp_path / "parent",
        analysis=replace(
            base.analysis,
            ligandability=ligandability,
            prioritisation=prioritisation,
        ),
        digest="fixture-configuration-digest",
    )


def test_structural_completion_configuration_contract(package_root: Path) -> None:
    """The release configuration must retain the agreed decision and scatter limits."""
    config = load_config(
        package_root
        / "config"
        / "grant_aligned_structural_completion_top20_v0_10_0_20260728.cluster.yaml"
    )
    assert config.analysis.prioritisation.structure_group_limit == 50
    assert config.analysis.prioritisation.final_candidate_limit == 20
    assert config.analysis.ligandability.shard_threads == 4
    assert config.analysis.structural_alignment.shard_threads == 4
    assert not config.analysis.structural_alignment.use_for_prioritisation
    assert config.analysis.structural_alignment.require_for_final_recommendation
    assert config.stage("09_ligandability").evidence_mode == "generate"
    assert config.stage("09b_structural_alignment").evidence_mode == "generate"
    assert ligandability_task_count(config) == 600
    assert structural_alignment_task_count(config) == 50


def test_parent_reuse_validates_checksum_and_publishes_provenance(
    structural_config: WorkflowConfig,
) -> None:
    """Parent imports must checksum every declared output before publication."""
    parent_stage = structural_config.parent_run_root / "02_discovery"
    parent_stage.mkdir(parents=True)
    authority = parent_stage / "discovery_authority.tsv"
    authority.write_text("authority\tvalue\nsource\tparent\n", encoding="utf-8")
    (parent_stage / "stage_manifest.json").write_text(
        json.dumps(
            {
                "stage": "02_discovery",
                "status": "complete",
                "configuration_digest": "parent-digest",
                "outputs": [
                    {
                        "path": "discovery_authority.tsv",
                        "size_bytes": authority.stat().st_size,
                        "sha256": sha256_file(authority),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    destination = structural_config.run_root / "02_discovery"
    import_parent_stage(
        config=structural_config,
        stage_name="02_discovery",
        stage_root=destination,
    )
    assert (destination / "discovery_authority.tsv").read_bytes() == authority.read_bytes()
    fields, records = read_tsv(destination / "provenance" / "parent_stage_import.tsv")
    assert "publication_action" in fields
    assert records[0]["parent_configuration_digest"] == "parent-digest"
    authority.write_text("authority\tvalue\nsource\tchanged\n", encoding="utf-8")
    with pytest.raises(StageError, match="size changed|checksum changed"):
        import_parent_stage(
            config=structural_config,
            stage_name="02_discovery",
            stage_root=structural_config.run_root / "bad_import",
        )


def test_parent_reuse_rejects_malformed_or_changed_authorities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every malformed parent-manifest and output branch must fail closed."""
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(StageError, match="Could not read"):
        _read_manifest(invalid)
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(StageError, match="not a JSON object"):
        _read_manifest(invalid)
    with pytest.raises(StageError, match="lacks an output inventory"):
        _output_inventory({})
    with pytest.raises(StageError, match="non-mapping"):
        _output_inventory({"outputs": ["bad"]})
    with pytest.raises(StageError, match="empty or duplicate"):
        _output_inventory({"outputs": [{"path": ""}]})
    with pytest.raises(StageError, match="empty or duplicate"):
        _output_inventory(
            {"outputs": [{"path": "same"}, {"path": "same"}]}
        )

    source = tmp_path / "authority.tsv"
    source.write_text("a\tb\n", encoding="utf-8")
    with pytest.raises(StageError, match="does not inventory"):
        _validate_parent_file(
            source=source,
            relative_path="authority.tsv",
            inventory={},
        )
    with pytest.raises(StageError, match="is missing"):
        _validate_parent_file(
            source=tmp_path / "missing.tsv",
            relative_path="authority.tsv",
            inventory={"authority.tsv": {"size_bytes": 1, "sha256": "x"}},
        )
    with pytest.raises(StageError, match="invalid size"):
        _validate_parent_file(
            source=source,
            relative_path="authority.tsv",
            inventory={
                "authority.tsv": {
                    "size_bytes": "bad",
                    "sha256": sha256_file(source),
                }
            },
        )
    with pytest.raises(StageError, match="size changed"):
        _validate_parent_file(
            source=source,
            relative_path="authority.tsv",
            inventory={"authority.tsv": {"size_bytes": 999, "sha256": "x"}},
        )
    with pytest.raises(StageError, match="checksum changed"):
        _validate_parent_file(
            source=source,
            relative_path="authority.tsv",
            inventory={
                "authority.tsv": {
                    "size_bytes": source.stat().st_size,
                    "sha256": "x",
                }
            },
        )
    destination = tmp_path / "copy" / "authority.tsv"

    def fail_link(*_args: Any) -> None:
        """Simulate a cross-filesystem hard-link failure."""
        raise OSError

    monkeypatch.setattr("e3workflow.parent_reuse.os.link", fail_link)
    assert _link_or_copy(source, destination) == "copied"
    assert destination.read_bytes() == source.read_bytes()


def test_structural_configuration_validation_branches(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """New structural and parent-reuse configuration errors remain explicit."""
    source = (
        package_root
        / "config"
        / "grant_aligned_structural_completion_top20_v0_10_0_20260728.cluster.yaml"
    )
    base = yaml.safe_load(source.read_text(encoding="utf-8"))

    def rejected(
        mutator: Any,
        message: str,
    ) -> None:
        payload = json.loads(json.dumps(base))
        mutator(payload)
        path = tmp_path / f"invalid_{len(list(tmp_path.glob('invalid_*')))}.yaml"
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        with pytest.raises(ConfigurationError, match=message):
            load_config(path)

    rejected(
        lambda payload: payload["analysis"]["ligandability"].update(
            {"mode": "invented"}
        ),
        "mode must be",
    )
    rejected(
        lambda payload: payload["analysis"]["structural_alignment"].update(
            {"use_for_prioritisation": "yes"}
        ),
        "use_for_prioritisation must be",
    )
    rejected(
        lambda payload: payload["analysis"]["structural_alignment"].update(
            {"require_for_final_recommendation": "yes"}
        ),
        "require_for_final_recommendation",
    )
    rejected(
        lambda payload: payload["run"].pop("parent_run_root"),
        "parent_run_root is required",
    )
    rejected(
        lambda payload: payload["stages"]["09_ligandability"].update(
            {"evidence_mode": "parent_reuse"}
        ),
        "supported only through 08",
    )

    def disable_alignment(payload: dict[str, Any]) -> None:
        payload["stages"]["09b_structural_alignment"].update(
            {
                "enabled": False,
                "required": False,
                "evidence_mode": "disabled",
            }
        )

    rejected(
        disable_alignment,
        "require_for_final_recommendation requires",
    )


def test_distributed_marker_and_union_defensive_contracts(
    structural_config: WorkflowConfig,
    tmp_path: Path,
) -> None:
    """Shard resume markers and Parquet aggregation must reject unsafe state."""
    malformed_root = tmp_path / "malformed"
    malformed_root.mkdir()
    (malformed_root / "task_complete.tsv").write_text(
        "wrong\nvalue\n",
        encoding="utf-8",
    )
    with pytest.raises(StageError, match="Malformed"):
        _read_marker(malformed_root)
    complete_root = tmp_path / "complete"
    complete_root.mkdir()
    (complete_root / "task_complete.tsv").write_text(
        "\t".join(TASK_MARKER_FIELDS)
        + "\nligandability\t0\tCOMPLETE\twrong-digest\tQ1\t"
        + str(complete_root / "component_output")
        + "\tnow\n",
        encoding="utf-8",
    )
    with pytest.raises(StageError, match="does not match"):
        _validate_reusable_marker(
            root=complete_root,
            config=structural_config,
            task_kind="ligandability",
            task_index=0,
            entity_id="Q1",
        )
    fields = (complete_root / "task_complete.tsv").read_text(encoding="utf-8")
    (complete_root / "task_complete.tsv").write_text(
        fields.replace("wrong-digest", structural_config.digest),
        encoding="utf-8",
    )
    with pytest.raises(StageError, match="lacks its run manifest"):
        _validate_reusable_marker(
            root=complete_root,
            config=structural_config,
            task_kind="ligandability",
            task_index=0,
            entity_id="Q1",
        )
    partial = tmp_path / "work" / "task_0000"
    partial.mkdir(parents=True)
    _archive_partial(partial)
    assert not partial.exists()
    assert list((partial.parent / "failed").iterdir())
    with pytest.raises(StageError, match="No Parquet shards"):
        _copy_parquet_union(
            sources=[],
            destination=tmp_path / "empty.parquet",
        )


def test_rebased_asset_manifest_rejects_invalid_publication_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stable asset publication must reject malformed paths, metadata and files."""
    for path, message in (
        ("/tmp/no-component-directory/model.cif", "exactly one"),
        ("/tmp/component_output", "unsafe suffix"),
    ):
        with pytest.raises(StageError, match=message):
            _relative_component_asset_path(recorded_path=path)
    with pytest.raises(StageError, match="no asset records"):
        _publish_rebased_asset_manifest(
            roots=[],
            destination=tmp_path / "empty" / "asset_manifest.parquet",
        )

    task_root = tmp_path / "task_0000"
    source = (
        task_root
        / "component_output"
        / "tables"
        / "parquet"
        / "asset_manifest.parquet"
    )
    source.parent.mkdir(parents=True)
    source.write_text("fixture", encoding="utf-8")
    marker = task_root / "task_complete.tsv"
    marker.write_text(
        "\t".join(TASK_MARKER_FIELDS)
        + "\nligandability\t0\tCOMPLETE\tdigest\tQ1\t"
        + str(task_root / "component_output")
        + "\tnow\n",
        encoding="utf-8",
    )
    model = task_root / "component_output" / "models" / "Q1.cif"
    model.parent.mkdir(parents=True)
    model.write_text("data_model\n", encoding="utf-8")
    base_row = {
        "accession": "Q1",
        "action": "downloaded",
        "bytes": model.stat().st_size,
        "path": "/old/.task_0000.running.uuid/component_output/models/Q1.cif",
        "sha256": sha256_file(model),
        "url": "https://example.invalid/Q1.cif",
    }
    cases = (
        ({**base_row, "accession": "Q2"}, "does not match"),
        ({**base_row, "path": base_row["path"].replace("Q1.cif", "missing.cif")}, "missing"),
        ({**base_row, "bytes": "invalid"}, "invalid byte count"),
        ({**base_row, "bytes": model.stat().st_size + 1}, "size changed"),
        ({**base_row, "sha256": "0" * 64}, "checksum changed"),
    )
    for index, (row, message) in enumerate(cases):
        monkeypatch.setattr(
            "e3workflow.distributed._table_records",
            lambda _path, selected=row: [selected],
        )
        with pytest.raises(StageError, match=message):
            _publish_rebased_asset_manifest(
                roots=[task_root],
                destination=tmp_path / f"case_{index}" / "asset_manifest.parquet",
            )
    monkeypatch.setattr(
        "e3workflow.distributed._table_records",
        lambda _path: [base_row, dict(base_row)],
    )
    with pytest.raises(StageError, match="Duplicate"):
        _publish_rebased_asset_manifest(
            roots=[task_root],
            destination=tmp_path / "duplicate" / "asset_manifest.parquet",
        )


def _fake_ligandability_component(*, argv: tuple[str, ...], **_kwargs: Any) -> None:
    """Publish the minimum complete ligandability component contract."""
    output = Path(argv[argv.index("--output-dir") + 1])
    accession = Path(argv[argv.index("--input") + 1]).read_text(
        encoding="utf-8"
    ).splitlines()[1].split("\t")[0]
    parquet_root = output / "tables" / "parquet"
    for dataset in LIGANDABILITY_DATASETS:
        if dataset == "accession_status":
            _write_parquet(
                parquet_root / f"{dataset}.parquet",
                "accession VARCHAR, status VARCHAR, stage VARCHAR, message VARCHAR",
                [(accession, "SUCCESS", "complete", "")],
            )
        elif dataset == "asset_manifest":
            model = output / "models" / accession / f"{accession}.cif"
            model.parent.mkdir(parents=True)
            model.write_text("data_fixture\n", encoding="utf-8")
            _write_parquet(
                parquet_root / f"{dataset}.parquet",
                (
                    "accession VARCHAR, action VARCHAR, bytes BIGINT, path VARCHAR, "
                    "sha256 VARCHAR, url VARCHAR"
                ),
                [
                    (
                        accession,
                        "downloaded",
                        model.stat().st_size,
                        str(model),
                        sha256_file(model),
                        f"https://example.invalid/{accession}.cif",
                    )
                ],
            )
        else:
            _write_parquet(
                parquet_root / f"{dataset}.parquet",
                "accession VARCHAR, fixture_value DOUBLE",
                [(accession, 1.0)],
            )
    provenance = output / "provenance"
    provenance.mkdir(parents=True)
    (provenance / "run_manifest.json").write_text(
        json.dumps({"status": "complete", "accession": accession}),
        encoding="utf-8",
    )


def test_ligandability_scatter_resume_and_aggregation(
    structural_config: WorkflowConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accession shards must resume independently and aggregate all typed tables."""
    table = (
        structural_config.run_root
        / "08_shortlist_gate"
        / "tables"
        / "ligandability_accessions.tsv"
    )
    table.parent.mkdir(parents=True)
    table.write_text(
        "accession\tevolutionary_group_rank\tevolutionary_group_key\tcluster_id\t"
        "primary_group_type\tprimary_group_id\tspecies_column\tsequence_length\n"
        "Q00001\t1\tORTHOGROUP:OG1\tcluster_1\tORTHOGROUP\tOG1\tSpecies_a\t400\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "e3workflow.distributed._run_component",
        _fake_ligandability_component,
    )
    assert run_ligandability_shard(
        config=structural_config,
        task_index=0,
    )["status"] == "complete"
    assert run_ligandability_shard(
        config=structural_config,
        task_index=0,
    )["status"] == "reused"
    for index in range(1, ligandability_task_count(structural_config)):
        assert run_ligandability_shard(
            config=structural_config,
            task_index=index,
        )["status"] == "skipped_unused_slot"
    with pytest.raises(StageError, match="outside the configured range"):
        run_ligandability_shard(config=structural_config, task_index=4)
    stage_root = structural_config.run_root / "09_ligandability"
    manifest = aggregate_ligandability_shards(
        config=structural_config,
        stage_root=stage_root,
    )
    assert manifest.is_file()
    fields, records = read_tsv(
        stage_root
        / "generated_ligandability"
        / "qc"
        / "distributed_ligandability_summary.tsv"
    )
    assert "successful_accession_count" in fields
    assert records[0]["successful_accession_count"] == "1"
    assert records[0]["maximum_concurrent_jobs"] == "100"
    asset_path = (
        stage_root
        / "generated_ligandability"
        / "tables"
        / "parquet"
        / "asset_manifest.parquet"
    )
    connection = duckdb.connect(":memory:")
    try:
        published_path = Path(
            connection.execute(
                f"SELECT path FROM read_parquet({quote_literal(asset_path)})"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    assert ".running." not in str(published_path)
    assert "/task_0000/component_output/" in str(published_path)
    assert published_path.is_file()
    assert published_path.read_text(encoding="utf-8") == "data_fixture\n"


def _fake_structural_component(*, argv: tuple[str, ...], **_kwargs: Any) -> None:
    """Publish the minimum complete structural-alignment component contract."""
    output = Path(argv[argv.index("--output-dir") + 1])
    tables = output / "tables"
    for dataset in (
        "structural_alignments",
        "pocket_comparisons",
        "pocket_residue_matches",
    ):
        _write_parquet(
            tables / f"{dataset}.parquet",
            "cluster_id VARCHAR, primary_group_id VARCHAR, alignment_tool VARCHAR",
            [("cluster_1", "OG1", "US-align")],
        )
    _write_parquet(
        tables / "structural_alignment_summary.parquet",
        (
            "cluster_id VARCHAR, primary_group_id VARCHAR, "
            "reference_accession VARCHAR, aligned_species_count INTEGER, "
            "selected_accession_count INTEGER, model_available_accession_count INTEGER, "
            "group_support_fraction DOUBLE, mean_minimum_tm_score DOUBLE, "
            "mean_pocket_overlap_fraction DOUBLE, alignment_status VARCHAR"
        ),
        [("cluster_1", "OG1", "Q00001", 2, 2, 2, 1.0, 0.9, 0.8, "PASS")],
    )
    interactive = output / "interactive"
    (interactive / "assets").mkdir(parents=True)
    (interactive / "assets" / "pair.json").write_text("{}", encoding="utf-8")
    (interactive / "structural_alignment_browser.html").write_text(
        '<a href="assets/pair.json">pair</a>',
        encoding="utf-8",
    )
    provenance = output / "provenance"
    provenance.mkdir(parents=True)
    (provenance / "run_manifest.json").write_text(
        json.dumps({"status": "complete"}),
        encoding="utf-8",
    )


def test_structural_scatter_and_aggregate_preserve_browser_assets(
    structural_config: WorkflowConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group shards must aggregate tables and retain complete offline browsers."""
    tables = structural_config.run_root / "09_ligandability" / "tables"
    _write_parquet(
        tables / "selected_pockets.parquet",
        (
            "cluster_id VARCHAR, primary_group_type VARCHAR, primary_group_id VARCHAR, "
            "candidate_accession VARCHAR"
        ),
        [
            ("cluster_1", "ORTHOGROUP", "OG1", "Q00001"),
            ("cluster_1", "ORTHOGROUP", "OG1", "Q00002"),
        ],
    )
    _write_parquet(
        tables / "reused_pocket_residue_mappings.parquet",
        "accession VARCHAR, mapping_status VARCHAR",
        [("Q00001", "MAPPED"), ("Q00002", "MAPPED")],
    )
    _write_parquet(
        tables / "pocket_sequence_coordinates.parquet",
        "candidate_accession VARCHAR, fasta_position INTEGER",
        [("Q00001", 10), ("Q00002", 10)],
    )
    _write_parquet(
        tables / "reused_asset_manifest.parquet",
        "accession VARCHAR, path VARCHAR",
        [("Q00001", "/model/1.cif"), ("Q00002", "/model/2.cif")],
    )
    monkeypatch.setattr(
        "e3workflow.distributed._run_component",
        _fake_structural_component,
    )
    assert run_structural_alignment_shard(
        config=structural_config,
        task_index=0,
    )["status"] == "complete"
    assert run_structural_alignment_shard(
        config=structural_config,
        task_index=0,
    )["status"] == "reused"
    assert run_structural_alignment_shard(
        config=structural_config,
        task_index=1,
    )["status"] == "skipped_unused_slot"
    with pytest.raises(StageError, match="outside the configured range"):
        run_structural_alignment_shard(config=structural_config, task_index=2)
    stage_root = structural_config.run_root / "09b_structural_alignment"
    aggregate_structural_alignment_shards(
        config=structural_config,
        stage_root=stage_root,
    )
    output = stage_root / "structural_alignment"
    assert (output / "tables" / "structural_alignment_summary.parquet").is_file()
    assert (
        output
        / "interactive"
        / "groups"
        / "ORTHOGROUP__OG1"
        / "assets"
        / "pair.json"
    ).is_file()
    assert "ORTHOGROUP:OG1" in (
        output / "interactive" / "structural_alignment_browser.html"
    ).read_text(encoding="utf-8")


def test_structural_validation_rejects_zero_resolved_models() -> None:
    """Completed task markers cannot conceal a zero-model Stage 09b result."""
    with pytest.raises(StageError, match="resolved zero structural models"):
        _validate_structural_summary_evidence(
            summaries=[
                {
                    "selected_accession_count": 12,
                    "model_available_accession_count": 0,
                }
            ]
        )
    with pytest.raises(StageError, match="no evolutionary group"):
        _validate_structural_summary_evidence(
            summaries=[
                {
                    "selected_accession_count": 2,
                    "model_available_accession_count": 1,
                }
            ]
        )
    assert _validate_structural_summary_evidence(
        summaries=[
            {
                "selected_accession_count": 2,
                "model_available_accession_count": 2,
            }
        ]
    )["resolved_comparable_group_count"] == 1


def test_component_runner_reports_process_failures(tmp_path: Path) -> None:
    """The shard command wrapper must retain logs and report launch/exit failures."""
    log = tmp_path / "success.log"
    _run_component(
        argv=(sys.executable, "-c", "print('ok')"),
        log_path=log,
        working_directory=tmp_path,
    )
    assert "ok" in log.read_text(encoding="utf-8")
    with pytest.raises(StageError, match="returned 3"):
        _run_component(
            argv=(sys.executable, "-c", "raise SystemExit(3)"),
            log_path=tmp_path / "failure.log",
            working_directory=tmp_path,
        )
    with pytest.raises(StageError, match="Could not start"):
        _run_component(
            argv=(str(tmp_path / "missing-executable"),),
            log_path=tmp_path / "missing.log",
            working_directory=tmp_path,
        )
