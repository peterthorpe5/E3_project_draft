"""Defensive branch tests for malformed inputs and controlled recovery."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pytest
from conftest import make_results
from test_pipeline_report_io import pipeline_arguments

from orthofinder_results.cli import main
from orthofinder_results.distances import (
    _quantile,
    calculate_alignment_distances,
    calculate_patristic_distances,
    deterministic_member_sample,
    read_fasta,
    summarise_distances,
)
from orthofinder_results.errors import (
    DistanceCalculationError,
    InputValidationError,
    PublicationError,
)
from orthofinder_results.io_utils import (
    _arrow_type,
    atomic_write_json,
    create_duckdb,
    file_record,
    open_text,
    read_tsv,
    sha256_file,
    tsv_to_parquet,
    write_tsv,
)
from orthofinder_results.layout import (
    _hog_sort_key,
    _major_version,
    detect_version,
    discover_layout,
)
from orthofinder_results.parsers import iter_memberships, iter_sequence_ids, read_species_ids
from orthofinder_results.pipeline import (
    _group_id_from_alignment,
    _HashRowSampler,
    _inventory_digest,
    _load_report_group_species_data,
    _load_report_group_statistics,
    _qc,
    _qc_rows,
    _resolve_alignment_dir,
    _resolve_distance_source,
    _resolve_pipeline_alignment_dir,
    _stratified_quotas,
    _table_path,
    _validate_controls,
    run_pipeline,
)
from orthofinder_results.report import build_interactive_report
from orthofinder_results.trees import normalise_newick_tree, tree_id_from_path


def test_distance_input_failures_are_diagnostic(tmp_path: Path) -> None:
    """Distance readers reject missing, empty and incomplete biological inputs."""

    with pytest.raises(InputValidationError, match="Missing or empty FASTA"):
        read_fasta(path=tmp_path / "missing.fa")
    empty = tmp_path / "empty.fa"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Missing or empty FASTA"):
        read_fasta(path=empty)
    malformed = tmp_path / "malformed.fa"
    malformed.write_text("\n>\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Empty FASTA identifier"):
        read_fasta(path=malformed)
    incomplete = tmp_path / "incomplete.fa"
    incomplete.write_text(">a\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="no complete sequences"):
        read_fasta(path=incomplete)
    with pytest.raises(ValueError, match="at least two"):
        calculate_alignment_distances(
            sequences={"a": "AA", "b": "AA"},
            run_id="r",
            group_type="HOG",
            hierarchy_node="N0",
            group_id="g",
            max_members=1,
        )
    with pytest.raises(DistanceCalculationError, match="fewer than two"):
        calculate_alignment_distances(
            sequences={"a": "AA"},
            run_id="r",
            group_type="HOG",
            hierarchy_node="N0",
            group_id="g",
            max_members=2,
        )


def test_tree_distance_failures_are_diagnostic(tmp_path: Path) -> None:
    """Patristic calculations reject absent, malformed and ambiguous leaves."""

    common = {
        "run_id": "r",
        "group_type": "HOG",
        "hierarchy_node": "N0",
        "group_id": "g",
        "max_members": 10,
    }
    with pytest.raises(DistanceCalculationError, match="Missing or empty tree"):
        calculate_patristic_distances(tree_path=tmp_path / "missing", **common)
    malformed = tmp_path / "malformed.tree"
    malformed.write_text("not(newick\n", encoding="utf-8")
    with pytest.raises(DistanceCalculationError, match="Could not parse tree"):
        calculate_patristic_distances(tree_path=malformed, **common)
    unnamed = tmp_path / "unnamed.tree"
    unnamed.write_text("(:0.1,b:0.2);\n", encoding="utf-8")
    with pytest.raises(DistanceCalculationError, match="unnamed leaf"):
        calculate_patristic_distances(tree_path=unnamed, **common)
    duplicate = tmp_path / "duplicate.tree"
    duplicate.write_text("(a:0.1,a:0.2);\n", encoding="utf-8")
    with pytest.raises(DistanceCalculationError, match="duplicate leaf"):
        calculate_patristic_distances(tree_path=duplicate, **common)
    singleton = tmp_path / "singleton.tree"
    singleton.write_text("a:0.1;\n", encoding="utf-8")
    with pytest.raises(DistanceCalculationError, match="fewer than two"):
        calculate_patristic_distances(tree_path=singleton, **common)


def test_sampling_summary_and_quantile_edge_cases() -> None:
    """Empty identifiers, distributions and invalid quantiles remain explicit."""

    with pytest.raises(ValueError, match="empty values"):
        deterministic_member_sample(member_ids=("a", ""), run_id="r", group_id="g", max_members=2)
    summary = summarise_distances(
        rows=(),
        run_id="r",
        group_type="HOG",
        hierarchy_node="N0",
        group_id="g",
        method="none",
        status="EXACT",
        total_member_count=0,
        sampled_member_count=0,
    )
    assert summary["distance_pair_count"] == 0
    assert summary["mean_distance"] == 0.0
    with pytest.raises(ValueError, match="must not be empty"):
        _quantile(values=(), probability=0.5)
    with pytest.raises(ValueError, match="between zero and one"):
        _quantile(values=(1.0,), probability=2.0)
    assert _quantile(values=(1.0,), probability=0.5) == 1.0


def test_identifier_parser_failure_branches(tmp_path: Path) -> None:
    """Every empty, duplicate and malformed identifier/table case is checked."""

    species = tmp_path / "SpeciesIDs.txt"
    species.write_text("\n0: a.fa\n0: b.fa\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Duplicate species index"):
        read_species_ids(path=species, run_id="r")
    species.write_text("\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="no species"):
        read_species_ids(path=species, run_id="r")
    sequence = tmp_path / "SequenceIDs.txt"
    sequence.write_text("\nbroken\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Malformed SequenceIDs"):
        list(iter_sequence_ids(path=sequence, run_id="r", species_by_index={"0": "a.fa"}))
    group = tmp_path / "group.tsv"
    group.write_text("Orthogroup\tSpecies\nOG1\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="fields; expected"):
        list(iter_memberships(path=group, run_id="r", group_type="LEGACY_ORTHOGROUP"))
    group.write_text("Orthogroup\tSpecies\n\tp1\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Empty group identifier"):
        list(iter_memberships(path=group, run_id="r", group_type="LEGACY_ORTHOGROUP"))
    group.write_text("Orthogroup\nOG1\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="no species columns"):
        list(iter_memberships(path=group, run_id="r", group_type="LEGACY_ORTHOGROUP"))
    group.write_text("Orthogroup\t \nOG1\tp1\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="empty species heading"):
        list(iter_memberships(path=group, run_id="r", group_type="LEGACY_ORTHOGROUP"))


def test_io_failure_branches_and_scalar_types(tmp_path: Path) -> None:
    """I/O helpers validate schemas, paths, blocks and SQL relation sources."""

    missing = tmp_path / "missing"
    with pytest.raises(InputValidationError, match="Cannot checksum"):
        sha256_file(path=missing)
    with pytest.raises(InputValidationError, match="Cannot inventory"):
        file_record(path=missing)
    with pytest.raises(ValueError, match="At least one TSV field"):
        write_tsv(path=tmp_path / "none.tsv", fieldnames=(), records=())
    with pytest.raises(InputValidationError, match="does not exist"):
        list(read_tsv(path=missing))
    no_header = tmp_path / "no_header.tsv"
    no_header.write_text("", encoding="utf-8")
    with pytest.raises(InputValidationError, match="no header"):
        list(read_tsv(path=no_header))
    with pytest.raises(ValueError, match="positive"):
        tsv_to_parquet(tsv_path=no_header, parquet_path=tmp_path / "x.parquet", block_size=0)
    with pytest.raises(PublicationError, match="no header"):
        tsv_to_parquet(tsv_path=no_header, parquet_path=tmp_path / "x.parquet")
    empty_heading = tmp_path / "empty_heading.tsv"
    empty_heading.write_text("name\t\nvalue\tx\n", encoding="utf-8")
    with pytest.raises(PublicationError, match="empty column heading"):
        tsv_to_parquet(tsv_path=empty_heading, parquet_path=tmp_path / "empty.parquet")
    duplicate_heading = tmp_path / "duplicate_heading.tsv"
    duplicate_heading.write_text("name\tname\na\tb\n", encoding="utf-8")
    with pytest.raises(PublicationError, match="duplicate column headings"):
        tsv_to_parquet(tsv_path=duplicate_heading, parquet_path=tmp_path / "duplicate.parquet")
    table = tmp_path / "values.tsv"
    write_tsv(
        path=table,
        fieldnames=("name", "active", "note"),
        records=({"name": "a", "active": True, "note": None},),
    )
    assert list(read_tsv(path=table))[0]["active"] == "true"
    with pytest.raises(PublicationError, match="absent TSV columns"):
        tsv_to_parquet(
            tsv_path=table,
            parquet_path=tmp_path / "unknown.parquet",
            column_types={"missing": "int64"},
        )
    with pytest.raises(ValueError, match="Unsupported Arrow"):
        _arrow_type(type_name="decimal", pa_module=pa)
    with pytest.raises(PublicationError, match="Missing Parquet source"):
        create_duckdb(
            database_path=tmp_path / "missing.duckdb",
            parquet_tables={"valid_name": missing},
        )


def test_layout_optional_and_version_branches(tmp_path: Path) -> None:
    """Layout discovery handles legacy-only, empty and long log variants."""

    legacy = tmp_path / "legacy"
    (legacy / "Orthogroups").mkdir(parents=True)
    (legacy / "Log.txt").write_text("Version = 2.5.5\n", encoding="utf-8")
    (legacy / "Orthogroups/Orthogroups.tsv").write_text(
        "Orthogroup\tA\nOG1\tp1\n", encoding="utf-8"
    )
    layout = discover_layout(results_dir=legacy)
    assert layout.primary_group_authority == "LEGACY_ORTHOGROUP"
    assert layout.species_ids_path is None
    empty = tmp_path / "empty_results"
    empty.mkdir()
    (empty / "Log.txt").write_text("Version: 2.5.5\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="No HOG tables"):
        discover_layout(results_dir=empty)
    long_log = tmp_path / "long.log"
    long_log.write_text("x\n" * 501 + "Version: 2.5.5\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Could not detect"):
        detect_version(log_path=long_log)
    with pytest.raises(InputValidationError, match="Invalid OrthoFinder version"):
        _major_version(version="bad")
    assert _hog_sort_key(Path("other.tsv"))[0] == 2**31


def test_tree_normalisation_failure_branches(tmp_path: Path) -> None:
    """Tree readers reject missing, malformed and empty derived identifiers."""

    with pytest.raises(InputValidationError, match="Missing or empty Newick"):
        normalise_newick_tree(
            path=tmp_path / "missing",
            run_id="r",
            tree_type="GENE_TREE",
            tree_id="g",
        )
    malformed = tmp_path / "bad.tree"
    malformed.write_text("not(newick\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Could not parse Newick"):
        normalise_newick_tree(path=malformed, run_id="r", tree_type="GENE_TREE", tree_id="g")
    with pytest.raises(InputValidationError, match="derive a tree identifier"):
        tree_id_from_path(path=Path(".txt"), tree_type="GENE_TREE")


def test_pipeline_without_optional_identifiers_alignments_or_gene_expansion(
    tmp_path: Path, persistent_test_root: Path
) -> None:
    """A portable result subset remains useful when optional files are absent."""

    results = make_results(tmp_path, include_alignments=False)
    (results / "WorkingDirectory/SpeciesIDs.txt").unlink()
    (results / "WorkingDirectory/SequenceIDs.txt").unlink()
    (results / "Resolved_Gene_Trees/OG0000001_tree.txt").write_text(
        "((Species_A_protA:0.1,Species_A_protA2:0.2):0.1,"
        "Species_B_protB:0.3)N0:0.0;\n",
        encoding="utf-8",
    )
    output = persistent_test_root / "minimal"
    arguments = pipeline_arguments(results, output)
    manifest = run_pipeline(**{**arguments, "parse_gene_trees": False})
    assert manifest["counts"]["sequence_count"] == 0
    assert manifest["counts"]["distance_pair_count"] == 3
    assert manifest["counts"]["tree_node_count"] == 3
    summaries = list(read_tsv(path=output / "tables/distance_statistics.tsv.gz"))
    assert summaries[0]["distance_method"] == "patristic_branch_length"
    assert summaries[0]["computation_status"] == "EXACT"
    assert summaries[0]["member_identifier_resolution"] == (
        "SPECIES_PREFIXED_MEMBER_ID"
    )
    assert list(read_tsv(path=output / "tables/species.tsv.gz"))[0]["source_file"] == (
        "derived_from_group_table_headings"
    )


@pytest.mark.parametrize("keep_failed_work", [False, True])
def test_pipeline_failed_staging_cleanup_is_configurable(
    tmp_path: Path,
    persistent_test_root: Path,
    keep_failed_work: bool,
) -> None:
    """Failures clean partial data by default with an explicit diagnostic opt-in."""

    results = make_results(tmp_path)
    alignment = results / "MultipleSequenceAlignments/N0.HOG0000001.fa"
    alignment.write_text(">only\nAAAA\n", encoding="utf-8")
    output = persistent_test_root / "failed"
    with pytest.raises(DistanceCalculationError, match="fewer than two"):
        run_pipeline(
            **{
                **pipeline_arguments(results, output),
                "keep_failed_work": keep_failed_work,
            }
        )
    failed = list((persistent_test_root / "work").glob("failed.failed.*"))
    assert len(failed) == int(keep_failed_work)
    if keep_failed_work:
        assert (failed[0] / "logs/run.log").is_file()
    assert not list((persistent_test_root / "work").glob("failed.staging.*"))


def test_pipeline_control_and_alignment_validation(tmp_path: Path) -> None:
    """Named controls and optional alignment paths are validated independently."""

    defaults = {
        "run_id": "valid",
        "distance_source": "AUTO",
        "distance_group_type": "AUTO",
        "distance_max_groups": 0,
        "distance_max_members": 2,
        "report_max_statistic_rows": 100,
        "report_max_groups": 1,
        "report_max_members": 2,
        "report_nearest_neighbours": 1,
        "resume": False,
        "force": False,
    }
    invalid = (
        ({"run_id": " bad"}, "run_id"),
        ({"distance_source": "BAD"}, "Unsupported distance_source"),
        ({"distance_group_type": "BAD"}, "Unsupported"),
        ({"distance_max_groups": -1}, "must not be negative"),
        ({"report_max_statistic_rows": 0}, "browser safety"),
        ({"report_max_statistic_rows": 50001}, "browser safety"),
        ({"report_max_groups": 0}, "must be positive"),
        ({"distance_max_members": 1}, "at least two"),
        ({"resume": True, "force": True}, "mutually exclusive"),
    )
    for changes, message in invalid:
        with pytest.raises(InputValidationError, match=message):
            _validate_controls(**{**defaults, **changes})
    assert _resolve_alignment_dir(requested=None, discovered=None) is None
    assert (
        _resolve_pipeline_alignment_dir(
            requested=None, discovered=None, distance_source="RESOLVED_GENE_TREE"
        )
        is None
    )
    with pytest.raises(InputValidationError, match="does not exist"):
        _resolve_alignment_dir(requested=tmp_path / "missing", discovered=None)
    empty = tmp_path / "alignments"
    empty.mkdir()
    with pytest.raises(InputValidationError, match="contains no recognised"):
        _resolve_alignment_dir(requested=empty, discovered=None)
    with pytest.raises(InputValidationError, match="derive group identifier"):
        _group_id_from_alignment(path=Path("."))
    with pytest.raises(InputValidationError, match="requires a recognised alignment"):
        _resolve_distance_source(
            requested="ALIGNED_SEQUENCE",
            alignment_dir=None,
            resolved_tree_dir=None,
        )
    with pytest.raises(InputValidationError, match="requires resolved gene-tree"):
        _resolve_distance_source(
            requested="RESOLVED_GENE_TREE",
            alignment_dir=None,
            resolved_tree_dir=None,
        )
    assert (
        _resolve_distance_source(requested="AUTO", alignment_dir=None, resolved_tree_dir=None)
        == "NONE"
    )


def test_pipeline_helpers_cover_sampling_digest_qc_and_bounds(tmp_path: Path) -> None:
    """Small internal helpers remain deterministic and independently testable."""

    sampler = _HashRowSampler(maximum=1, salt="s")
    sampler.add(row={"member_id": "a"})
    sampler.add(row={"member_id": "a"})
    sampler.add(row={"member_id": "b"})
    assert len(sampler.rows()) == 1
    first = _inventory_digest(records=[{"role": "x", "path": "a", "sha256": "1"}])
    second = _inventory_digest(records=[{"sha256": "1", "path": "a", "role": "x"}])
    assert first == second
    assert _qc("x", False, 0, 1, "details")["status"] == "FAIL"

    statistics = tmp_path / "statistics.tsv"
    write_tsv(
        path=statistics,
        fieldnames=("group_id",),
        records=({"group_id": "g1"}, {"group_id": "g2"}),
    )
    assert len(_load_report_group_statistics(path=statistics, maximum=1)) == 1
    stratified = tmp_path / "stratified.tsv"
    write_tsv(
        path=stratified,
        fieldnames=("group_type", "hierarchy_node", "group_id"),
        records=(
            {"group_type": "LEGACY_ORTHOGROUP", "hierarchy_node": "", "group_id": "og1"},
            {"group_type": "LEGACY_ORTHOGROUP", "hierarchy_node": "", "group_id": "og2"},
            {"group_type": "HOG", "hierarchy_node": "N0", "group_id": "hog1"},
            {"group_type": "HOG", "hierarchy_node": "N0", "group_id": "hog2"},
        ),
    )
    stratified_rows = _load_report_group_statistics(path=stratified, maximum=2)
    assert {
        (row["group_type"], row["hierarchy_node"]) for row in stratified_rows
    } == {("LEGACY_ORTHOGROUP", ""), ("HOG", "N0")}
    proportional = _stratified_quotas(counts={"legacy": 10, "n0": 20}, maximum=10)
    assert sum(proportional.values()) == 10
    assert proportional["n0"] > proportional["legacy"] > 0
    truncated = _stratified_quotas(counts={"a": 1, "b": 3, "c": 2}, maximum=2)
    assert truncated == {"a": 0, "b": 1, "c": 1}
    assert _load_report_group_species_data(tables_dir=tmp_path, memberships=()) == []
    with pytest.raises(ValueError, match="Unsafe analytical relation"):
        _table_path(tables_dir=tmp_path, relation="bad-name")
    with pytest.raises(ValueError, match="mode must"):
        open_text(path=tmp_path / "unused.tsv", mode="x")
    with pytest.raises(PublicationError, match="does not exist"):
        tsv_to_parquet(
            tsv_path=tmp_path / "missing.tsv.gz",
            parquet_path=tmp_path / "missing.parquet",
        )


def test_qc_failure_states_and_report_limit_errors(
    orthofinder2_results: Path, tmp_path: Path
) -> None:
    """QC and report controls expose failed capabilities and unsafe limits."""

    layout = discover_layout(results_dir=orthofinder2_results)
    checks = _qc_rows(
        layout=layout,
        membership_counts={"x": 0},
        group_count=0,
        species_count=0,
        sequence_count=0,
        tree_inventory_count=0,
        tree_node_count=0,
        distance_count=0,
        offline_report=False,
    )
    assert "FAIL" in {row["status"] for row in checks}
    common = {
        "output_path": tmp_path / "report.html",
        "run_metadata": {},
        "group_statistics": (),
        "network_group_statistics": (),
        "memberships": (),
        "group_species_statistics": (),
        "distances": (),
        "distance_statistics": (),
        "total_group_statistic_count": 0,
        "total_membership_count": 0,
        "max_network_groups": 1,
        "max_network_members": 2,
        "nearest_neighbours": 1,
    }
    with pytest.raises(ValueError, match="at least two"):
        build_interactive_report(**{**common, "max_network_members": 1})
    with pytest.raises(ValueError, match="positive"):
        build_interactive_report(**{**common, "nearest_neighbours": 0})


def test_cli_complete_run_errors_and_action_conflicts(
    orthofinder2_results: Path, persistent_test_root: Path
) -> None:
    """CLI run, package-error return and action-conflict branches are covered."""

    output = persistent_test_root / "cli_run"
    assert (
        main(
            [
                "--action",
                "run",
                "--results-dir",
                str(orthofinder2_results),
                "--output-dir",
                str(output),
                "--run-id",
                "cli-run",
                "--work-dir",
                str(persistent_test_root / "cli_work"),
                "--distance-max-groups",
                "1",
            ]
        )
        == 0
    )
    standalone = persistent_test_root / "cli_report.html"
    assert (
        main(
            [
                "--action",
                "report",
                "--resource-dir",
                str(output),
                "--report-output",
                str(standalone),
                "--report-max-statistic-rows",
                "2",
                "--report-max-groups",
                "1",
                "--report-max-members",
                "2",
            ]
        )
        == 0
    )
    assert standalone.is_file()
    assert standalone.with_suffix(".log").is_file()
    assert (
        main(
            [
                "--action",
                "inspect",
                "--results-dir",
                str(persistent_test_root / "missing"),
                "--inspection-output",
                str(persistent_test_root / "bad.json"),
            ]
        )
        == 2
    )
    conflicts = (
        ["--action", "inspect", "--results-dir", str(orthofinder2_results)],
        [
            "--action",
            "inspect",
            "--inspection-output",
            str(persistent_test_root / "missing_results.json"),
        ],
        [
            "--action",
            "inspect",
            "--results-dir",
            str(orthofinder2_results),
            "--inspection-output",
            str(persistent_test_root / "i.json"),
            "--output-dir",
            str(output),
        ],
        [
            "--action",
            "run",
            "--results-dir",
            str(orthofinder2_results),
            "--output-dir",
            str(output),
            "--run-id",
            "x",
            "--inspection-output",
            str(persistent_test_root / "i.json"),
        ],
        [
            "--action",
            "run",
            "--results-dir",
            str(orthofinder2_results),
            "--output-dir",
            str(persistent_test_root / "run_conflict"),
            "--run-id",
            "x",
            "--resource-dir",
            str(output),
        ],
        ["--action", "report", "--resource-dir", str(output)],
        [
            "--action",
            "report",
            "--resource-dir",
            str(output),
            "--report-output",
            str(persistent_test_root / "conflict.html"),
            "--results-dir",
            str(orthofinder2_results),
        ],
        [
            "--action",
            "report",
            "--resource-dir",
            str(output),
            "--report-output",
            str(persistent_test_root / "safe.html"),
            "--log-output",
            str(output / "report.log"),
        ],
    )
    for arguments in conflicts:
        with pytest.raises(SystemExit):
            main(arguments)


def test_atomic_json_and_existing_database_replacement(tmp_path: Path) -> None:
    """Atomic JSON and database replacement paths produce complete outputs."""

    record = tmp_path / "record.json"
    atomic_write_json(path=record, record={"b": 2, "a": 1})
    assert json.loads(record.read_text(encoding="utf-8")) == {"a": 1, "b": 2}
    tsv = tmp_path / "table.tsv"
    write_tsv(path=tsv, fieldnames=("value",), records=({"value": 1},))
    parquet = tmp_path / "table.parquet"
    tsv_to_parquet(tsv_path=tsv, parquet_path=parquet, column_types={"value": "int64"})
    database = tmp_path / "database.duckdb"
    create_duckdb(database_path=database, parquet_tables={"table_values": parquet})
    create_duckdb(database_path=database, parquet_tables={"table_values": parquet})
    assert database.is_file()
