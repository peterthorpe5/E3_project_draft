"""Integration tests for portable resource and HTML publication."""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import pytest

import orthofinder_results.pipeline as pipeline_module
from orthofinder_results.cli import main
from orthofinder_results.errors import InputValidationError, PublicationError
from orthofinder_results.io_utils import (
    create_duckdb,
    read_tsv,
    sha256_file,
    tsv_to_parquet,
    validate_persistent_path,
    write_tsv,
)
from orthofinder_results.pipeline import (
    _load_report_network_data,
    _table_path,
    _validate_published_copy,
    inspect_results,
    regenerate_report,
    run_pipeline,
)
from orthofinder_results.report import build_interactive_report
from orthofinder_results.trees import normalise_newick_tree, tree_id_from_path


def pipeline_arguments(results: Path, output: Path) -> dict[str, object]:
    """Return complete small-run pipeline arguments."""

    return {
        "results_dir": results,
        "output_dir": output,
        "run_id": "synthetic-run",
        "work_dir": output.parent / "work",
        "alignment_dir": None,
        "distance_source": "AUTO",
        "distance_group_type": "AUTO",
        "distance_hierarchy_node": "N0",
        "distance_max_groups": 0,
        "distance_max_members": 10,
        "parse_gene_trees": True,
        "report_max_statistic_rows": 100,
        "report_max_groups": 10,
        "report_max_members": 10,
        "report_nearest_neighbours": 2,
        "resume": False,
        "force": False,
        "verbose": False,
    }


@pytest.mark.parametrize("fixture_name", ["orthofinder2_results", "orthofinder3_results"])
def test_pipeline_publishes_queryable_offline_resource(
    fixture_name: str,
    request: pytest.FixtureRequest,
    persistent_test_root: Path,
) -> None:
    """Both version adapters produce equivalent portable analytical contracts."""

    results = request.getfixturevalue(fixture_name)
    output = persistent_test_root / f"published_{fixture_name}"
    manifest = run_pipeline(**pipeline_arguments(results, output))
    assert manifest["status"] == "complete"
    assert manifest["counts"]["hog_membership_count"] == 6
    expected_group_species_rows = 6 if fixture_name == "orthofinder2_results" else 4
    assert manifest["counts"]["group_species_statistic_count"] == (
        expected_group_species_rows
    )
    assert manifest["counts"]["distance_pair_count"] == 3
    assert not any(path.name.startswith(".") for path in output.parent.iterdir())

    report = output / "report/orthofinder_results_summary.html"
    html = report.read_text(encoding="utf-8")
    assert "Interactive cluster view" in html
    assert "Run-wide visual summary" in html
    assert "Cluster-size distribution" in html
    assert "Species-breadth distribution" in html
    assert "Copy-number complexity" in html
    assert "Authoritative group-by-species copy heatmap" in html
    assert "vis.Network" in html
    assert "function renderOverviewHistogram" in html
    assert "function renderDistanceHistogram" in html
    assert "function renderHistogram(" not in html
    assert '"distanceHistogram"' in html
    assert '"distanceValues"' not in html
    assert re.search(r'(?:src|href)=["\']https?://', html, re.IGNORECASE) is None
    assert "amino_acid_p_distance_pairwise_deletion" in html
    assert (output / "tables/hog_memberships.parquet").is_file()
    assert (output / "tables/hog_memberships.tsv.gz").is_file()
    assert not (output / "tables/hog_memberships.tsv").exists()
    assert pq.read_table(output / "tables/group_statistics.parquet").num_rows > 0

    connection = duckdb.connect(str(output / "duckdb/orthofinder_results.duckdb"))
    try:
        assert connection.execute("SELECT count(*) FROM hog_memberships").fetchone()[0] == 6
        assert connection.execute("SELECT count(*) FROM tree_nodes").fetchone()[0] > 0
        assert connection.execute(
            "SELECT count(*) FROM group_species_statistics"
        ).fetchone()[0] > 0
        assert connection.execute(
            "SELECT schema_version FROM resource_metadata"
        ).fetchone()[0] == 2
    finally:
        connection.close()
    checks = list(read_tsv(path=output / "qc/validation_checks.tsv"))
    assert checks and {row["status"] for row in checks} == {"PASS"}
    stages = list(read_tsv(path=output / "logs/stage_metrics.tsv"))
    assert stages and {row["status"] for row in stages} == {"PASS"}
    assert "offline_html_report" in {row["stage"] for row in stages}


def test_report_only_regeneration_preserves_completed_resource(
    orthofinder2_results: Path, persistent_test_root: Path
) -> None:
    """A compact standalone report can be rebuilt without changing its resource."""

    resource = persistent_test_root / "resource"
    run_pipeline(**pipeline_arguments(orthofinder2_results, resource))
    manifest = resource / "run_manifest.json"
    manifest_digest = sha256_file(path=manifest)
    standalone = persistent_test_root / "standalone.html"
    record = regenerate_report(
        resource_dir=resource,
        output_path=standalone,
        work_dir=persistent_test_root / "report_work",
        report_max_statistic_rows=2,
        report_max_groups=1,
        report_max_members=2,
        report_nearest_neighbours=1,
        force=False,
    )
    assert record["path"] == str(standalone.resolve())
    assert record["size_bytes"] == standalone.stat().st_size
    assert sha256_file(path=manifest) == manifest_digest
    html = standalone.read_text(encoding="utf-8")
    assert '"package_version":"0.1.3"' in html
    assert '"resource_package_version":"0.1.3"' in html
    with pytest.raises(PublicationError, match="already exists"):
        regenerate_report(
            resource_dir=resource,
            output_path=standalone,
            work_dir=None,
            report_max_statistic_rows=2,
            report_max_groups=1,
            report_max_members=2,
            report_nearest_neighbours=1,
            force=False,
        )
    replaced = regenerate_report(
        resource_dir=resource,
        output_path=standalone,
        work_dir=None,
        report_max_statistic_rows=2,
        report_max_groups=1,
        report_max_members=2,
        report_nearest_neighbours=1,
        force=True,
    )
    assert replaced["size_bytes"] == standalone.stat().st_size


def test_report_only_rejects_incomplete_or_mutating_inputs(
    persistent_test_root: Path,
) -> None:
    """Report-only validation protects the source resource and diagnoses damage."""

    controls = {
        "output_path": persistent_test_root / "outside.html",
        "work_dir": None,
        "report_max_statistic_rows": 2,
        "report_max_groups": 1,
        "report_max_members": 2,
        "report_nearest_neighbours": 1,
        "force": False,
    }
    missing = persistent_test_root / "missing"
    with pytest.raises(InputValidationError, match="does not exist"):
        regenerate_report(resource_dir=missing, **controls)

    resource = persistent_test_root / "resource_validation"
    resource.mkdir()
    with pytest.raises(InputValidationError, match="lacks run_manifest"):
        regenerate_report(resource_dir=resource, **controls)
    with pytest.raises(InputValidationError, match="outside the immutable"):
        regenerate_report(
            resource_dir=resource,
            **{**controls, "output_path": resource / "report.html"},
        )
    with pytest.raises(InputValidationError, match="work directory"):
        regenerate_report(
            resource_dir=resource,
            **{**controls, "work_dir": resource / "work"},
        )

    manifest = resource / "run_manifest.json"
    manifest.write_text("{\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="unreadable"):
        regenerate_report(resource_dir=resource, **controls)
    manifest.write_text(json.dumps({"status": "running"}), encoding="utf-8")
    with pytest.raises(PublicationError, match="complete resource"):
        regenerate_report(resource_dir=resource, **controls)
    manifest.write_text(json.dumps({"status": "complete"}), encoding="utf-8")
    with pytest.raises(InputValidationError, match="required compressed TSV"):
        regenerate_report(resource_dir=resource, **controls)


def test_network_report_members_follow_distance_sample(tmp_path: Path) -> None:
    """Distance-backed networks retain sampled endpoints, not unrelated members."""

    tables = tmp_path / "tables"
    tables.mkdir()
    key_fields = {
        "run_id": "run",
        "group_type": "HOG",
        "hierarchy_node": "N0",
        "group_id": "N0.HOG1",
    }
    write_tsv(
        path=_table_path(tables_dir=tables, relation="group_statistics"),
        fieldnames=("run_id", "group_type", "hierarchy_node", "group_id", "member_count"),
        records=({**key_fields, "member_count": 4},),
    )
    membership_fields = (
        "run_id",
        "group_type",
        "hierarchy_node",
        "group_id",
        "member_id",
        "species_label",
    )
    write_tsv(
        path=_table_path(tables_dir=tables, relation="hog_memberships"),
        fieldnames=membership_fields,
        records=(
            {**key_fields, "member_id": member, "species_label": f"species_{member}"}
            for member in ("unrelated_a", "distance_a", "unrelated_b", "distance_b")
        ),
    )
    write_tsv(
        path=_table_path(tables_dir=tables, relation="legacy_orthogroup_memberships"),
        fieldnames=membership_fields,
        records=(),
    )
    write_tsv(
        path=_table_path(tables_dir=tables, relation="pairwise_distances"),
        fieldnames=(
            "run_id",
            "group_type",
            "hierarchy_node",
            "group_id",
            "member_a",
            "member_b",
            "distance",
        ),
        records=(
            {
                **key_fields,
                "member_a": "distance_a",
                "member_b": "distance_b",
                "distance": 0.25,
            },
        ),
    )
    statistics, memberships, distances = _load_report_network_data(
        tables_dir=tables,
        group_statistics_path=_table_path(tables_dir=tables, relation="group_statistics"),
        distance_summaries=({**key_fields, "distance_pair_count": 1},),
        maximum_groups=1,
        maximum_members=2,
    )
    assert len(statistics) == 1 and len(distances) == 1
    assert {row["member_id"] for row in memberships} == {"distance_a", "distance_b"}


def test_resume_and_recoverable_force_behaviour(
    orthofinder2_results: Path, persistent_test_root: Path
) -> None:
    """Resume requires exact identity and force preserves the old output."""

    output = persistent_test_root / "published"
    arguments = pipeline_arguments(orthofinder2_results, output)
    first = run_pipeline(**arguments)
    resumed = run_pipeline(**{**arguments, "resume": True})
    assert resumed["input_digest"] == first["input_digest"]
    with pytest.raises(PublicationError, match="already exists"):
        run_pipeline(**arguments)
    replacement = run_pipeline(**{**arguments, "force": True})
    assert replacement["status"] == "complete"
    assert list(persistent_test_root.glob("published.superseded.*"))


def test_cross_filesystem_publication_is_verified_before_atomic_rename(
    orthofinder2_results: Path,
    persistent_test_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Node-local staging is copied, checksum-verified and then published."""

    output = persistent_test_root / "published_from_scratch"
    arguments = pipeline_arguments(orthofinder2_results, output)
    monkeypatch.setattr(pipeline_module, "_same_filesystem", lambda **_: False)
    manifest = run_pipeline(**arguments)
    assert manifest["publication"]["method"] == "VERIFIED_COPY_THEN_ATOMIC_RENAME"
    assert manifest["publication"]["copy_verified"] is True
    assert output.is_dir()
    assert not list((persistent_test_root / "work").glob("*.staging.*"))
    assert not list(persistent_test_root.glob(".*.incoming.*"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_manifest", "missing run_manifest"),
        ("manifest_mismatch", "checksum does not match"),
        ("unreadable_manifest", "unreadable"),
        ("incomplete_manifest", "not marked complete"),
        ("unsafe_path", "Unsafe output path"),
        ("missing_file", "missing manifested file"),
        ("wrong_size", "size differs"),
        ("wrong_checksum", "checksum differs"),
        ("unexpected_file", "file set differs"),
    ],
)
def test_cross_filesystem_copy_validation_rejects_corruption(
    tmp_path: Path, mutation: str, message: str
) -> None:
    """Every corruption class blocks publication of an incoming copy."""

    source = tmp_path / mutation / "source"
    destination = tmp_path / mutation / "destination"
    for root in (source, destination):
        (root / "tables").mkdir(parents=True)
        (root / "tables/value.tsv").write_text("x\n", encoding="utf-8")
    record = {
        "path": "tables/value.tsv",
        "size_bytes": 2,
        "sha256": sha256_file(path=source / "tables/value.tsv"),
    }
    manifest: dict[str, object] = {"status": "complete", "outputs": [record]}

    if mutation == "unreadable_manifest":
        manifest_text = "{\n"
    else:
        if mutation == "incomplete_manifest":
            manifest["status"] = "running"
        elif mutation == "unsafe_path":
            record["path"] = "../outside.tsv"
        elif mutation == "wrong_size":
            record["size_bytes"] = 99
        elif mutation == "wrong_checksum":
            record["sha256"] = "0" * 64
        manifest_text = json.dumps(manifest, sort_keys=True)
    for root in (source, destination):
        (root / "run_manifest.json").write_text(manifest_text, encoding="utf-8")

    if mutation == "missing_manifest":
        (destination / "run_manifest.json").unlink()
    elif mutation == "manifest_mismatch":
        with (destination / "run_manifest.json").open(mode="a", encoding="utf-8") as handle:
            handle.write("\n")
    elif mutation == "missing_file":
        (destination / "tables/value.tsv").unlink()
    elif mutation == "unexpected_file":
        (destination / "tables/unexpected.tsv").write_text("x\n", encoding="utf-8")

    with pytest.raises(PublicationError, match=message):
        _validate_published_copy(source=source, destination=destination)


def test_cli_inspection_and_run_validation(orthofinder3_results: Path, tmp_path: Path) -> None:
    """Named CLI actions publish files and reject missing action-specific arguments."""

    inspection = tmp_path / "inspection.json"
    assert (
        main(
            [
                "--action",
                "inspect",
                "--results-dir",
                str(orthofinder3_results),
                "--inspection-output",
                str(inspection),
            ]
        )
        == 0
    )
    assert json.loads(inspection.read_text(encoding="utf-8"))["adapter_name"] == "orthofinder_3"
    assert inspect_results(results_dir=orthofinder3_results)["primary_group_authority"] == "HOG"
    with pytest.raises(SystemExit):
        main(["--action", "run", "--results-dir", str(orthofinder3_results)])


@pytest.mark.parametrize("suffix", [".tsv", ".tsv.gz"])
def test_io_round_trip_and_path_policy(tmp_path: Path, suffix: str) -> None:
    """Plain/compressed TSV, Parquet, DuckDB and checksums preserve a table."""

    tsv = tmp_path / f"values{suffix}"
    assert (
        write_tsv(path=tsv, fieldnames=("name", "count"), records=[{"name": "a", "count": 2}]) == 1
    )
    assert list(read_tsv(path=tsv))[0] == {"name": "a", "count": "2"}
    if suffix == ".tsv.gz":
        assert tsv.read_bytes()[:2] == b"\x1f\x8b"
    assert len(sha256_file(path=tsv)) == 64
    parquet = tmp_path / "values.parquet"
    assert tsv_to_parquet(tsv_path=tsv, parquet_path=parquet, column_types={"count": "int64"}) == 1
    database = tmp_path / "values.duckdb"
    create_duckdb(database_path=database, parquet_tables={"values": parquet})
    connection = duckdb.connect(str(database))
    try:
        assert connection.execute("SELECT sum(count) FROM values").fetchone()[0] == 2
    finally:
        connection.close()
    with pytest.raises(InputValidationError, match="temporary"):
        validate_persistent_path(path=Path("/tmp/run"), role="output")
    with pytest.raises(ValueError, match="positive"):
        sha256_file(path=tsv, block_size=0)


def test_empty_tsv_and_invalid_duckdb_relation(tmp_path: Path) -> None:
    """Empty authorities retain schemas and unsafe SQL relation names fail."""

    tsv = tmp_path / "empty.tsv"
    write_tsv(path=tsv, fieldnames=("name", "count"), records=())
    parquet = tmp_path / "empty.parquet"
    assert tsv_to_parquet(tsv_path=tsv, parquet_path=parquet, column_types={"count": "int64"}) == 0
    assert pq.read_table(parquet).num_rows == 0
    with pytest.raises(PublicationError, match="Unsafe"):
        create_duckdb(database_path=tmp_path / "bad.duckdb", parquet_tables={"bad-name": parquet})


@pytest.mark.parametrize("suffix", [".tsv", ".tsv.gz"])
def test_tsv_to_parquet_keeps_late_text_after_empty_inference_blocks(
    tmp_path: Path, suffix: str
) -> None:
    """A text value after many blanks cannot be inferred as Arrow null."""

    tsv = tmp_path / f"late_hierarchy{suffix}"
    records = [
        {
            "run_id": "run",
            "group_type": "LEGACY_ORTHOGROUP",
            "hierarchy_node": "",
            "member_count": 1,
        }
        for _ in range(100)
    ]
    records.append(
        {
            "run_id": "run",
            "group_type": "HOG",
            "hierarchy_node": "N0",
            "member_count": 2,
        }
    )
    write_tsv(
        path=tsv,
        fieldnames=("run_id", "group_type", "hierarchy_node", "member_count"),
        records=records,
    )
    parquet = tmp_path / "late_hierarchy.parquet"
    assert (
        tsv_to_parquet(
            tsv_path=tsv,
            parquet_path=parquet,
            column_types={"member_count": "int64"},
            block_size=256,
        )
        == 101
    )
    table = pq.read_table(parquet)
    assert str(table.schema.field("hierarchy_node").type) == "string"
    assert table.column("hierarchy_node").to_pylist()[-1] == "N0"
    assert table.column("hierarchy_node").to_pylist()[0] == ""


def test_tree_normalisation_and_identifier_rules(tmp_path: Path) -> None:
    """Newick trees become queryable nodes and edges with stable identifiers."""

    tree = tmp_path / "OG0001_tree.txt"
    tree.write_text("(a:0.1,b:0.2)N0:0.0;\n", encoding="utf-8")
    assert tree_id_from_path(path=tree, tree_type="GENE_TREE") == "OG0001"
    assert tree_id_from_path(path=tree, tree_type="SPECIES_TREE") == "SPECIES_TREE"
    nodes, edges = normalise_newick_tree(
        path=tree, run_id="r", tree_type="GENE_TREE", tree_id="OG0001"
    )
    assert len(nodes) == 3 and len(edges) == 2
    assert sum(bool(row["is_leaf"]) for row in nodes) == 2
    with pytest.raises(ValueError, match="Unsupported"):
        tree_id_from_path(path=tree, tree_type="BAD")


def test_report_bounds_and_script_escape(tmp_path: Path) -> None:
    """The report enforces safe bounds and neutralises script terminators."""

    output = tmp_path / "report.html"
    metadata = {
        "run_id": "run-</script>",
        "orthofinder_version": "3.1.0",
        "adapter_name": "orthofinder_3",
        "primary_group_authority": "HOG",
    }
    with pytest.raises(ValueError, match="positive"):
        build_interactive_report(
            output_path=output,
            run_metadata=metadata,
            group_statistics=(),
            network_group_statistics=(),
            memberships=(),
            group_species_statistics=(),
            distances=(),
            distance_statistics=(),
            total_group_statistic_count=0,
            total_membership_count=0,
            max_network_groups=0,
            max_network_members=2,
            nearest_neighbours=1,
        )
