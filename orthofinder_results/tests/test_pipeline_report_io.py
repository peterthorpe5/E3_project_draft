"""Integration tests for portable resource and HTML publication."""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb
import pyarrow.parquet as pq
import pytest

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
from orthofinder_results.pipeline import inspect_results, run_pipeline
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
    assert manifest["counts"]["distance_pair_count"] == 3
    assert not any(path.name.startswith(".") for path in output.parent.iterdir())

    report = output / "report/orthofinder_results_summary.html"
    html = report.read_text(encoding="utf-8")
    assert "Interactive cluster view" in html
    assert "vis.Network" in html
    assert re.search(r'(?:src|href)=["\']https?://', html, re.IGNORECASE) is None
    assert "amino_acid_p_distance_pairwise_deletion" in html
    assert (output / "tables/hog_memberships.parquet").is_file()
    assert pq.read_table(output / "tables/group_statistics.parquet").num_rows > 0

    connection = duckdb.connect(str(output / "duckdb/orthofinder_results.duckdb"))
    try:
        assert connection.execute("SELECT count(*) FROM hog_memberships").fetchone()[0] == 6
        assert connection.execute("SELECT count(*) FROM tree_nodes").fetchone()[0] > 0
    finally:
        connection.close()
    checks = list(read_tsv(path=output / "qc/validation_checks.tsv"))
    assert checks and {row["status"] for row in checks} == {"PASS"}


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


def test_io_round_trip_and_path_policy(tmp_path: Path) -> None:
    """TSV, typed Parquet, DuckDB and checksum helpers preserve a small table."""

    tsv = tmp_path / "values.tsv"
    assert (
        write_tsv(path=tsv, fieldnames=("name", "count"), records=[{"name": "a", "count": 2}]) == 1
    )
    assert list(read_tsv(path=tsv))[0] == {"name": "a", "count": "2"}
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
            memberships=(),
            distances=(),
            distance_statistics=(),
            total_group_statistic_count=0,
            total_membership_count=0,
            max_network_groups=0,
            max_network_members=2,
            nearest_neighbours=1,
        )
