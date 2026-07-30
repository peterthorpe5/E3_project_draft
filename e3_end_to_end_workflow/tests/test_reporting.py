"""Unit and end-to-end checks for portable HTML reporting."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest
import yaml

from e3workflow import reporting, runner
from e3workflow.benchmarking import aggregate_run_benchmarks
from e3workflow.config import STAGE_NAMES, load_config
from e3workflow.control import initialise_stage_tokens
from e3workflow.errors import WorkflowError
from e3workflow.io_utils import write_tsv
from e3workflow.reporting import (
    RUN_REPORT_FILENAME,
    _authoritative_evolutionary_group_counts,
    _bar_chart,
    _controlled_input_role,
    _input_records,
    _integer,
    _line_chart,
    _number,
    _result_html,
    _timeseries_points,
    generate_run_report,
    record_workflow_invocation,
    summarise_output,
)
from e3workflow.runner import execute_stage


def _write_evolutionary_group_ranking(
    *,
    path: Path,
    rows: tuple[tuple[object, object], ...],
    key_type: str = "VARCHAR",
    flag_type: str = "BOOLEAN",
) -> None:
    """Write a minimal Stage 08 evolutionary-group authority for report tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            "CREATE TABLE evolutionary_groups ("
            f"evolutionary_group_key {key_type}, "
            f"lead_grant_aligned_stringent_pass {flag_type}"
            ")"
        )
        if rows:
            connection.executemany(
                "INSERT INTO evolutionary_groups VALUES (?, ?)",
                rows,
            )
        connection.execute(
            "COPY evolutionary_groups TO ? (FORMAT PARQUET)",
            [str(path)],
        )


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("candidate_evidence", "candidate evidence Parquet"),
        ("candidate_evidence_manifest", "candidate evidence provenance manifest"),
        ("orthology_species_manifest", "orthology species manifest"),
        ("inherited_sqlite", "inherited E3 SQLite database"),
        ("orthofinder_archive", "reviewed OrthoFinder result archive"),
        ("e3_domain_catalogue", "E3 domain catalogue"),
        ("domain_annotation_manifest", "domain annotation manifest"),
        ("expression_manifest", "Expression Atlas resource manifest"),
        ("ligandability_manifest", "ligandability resource manifest"),
        ("future_evidence_authority", "controlled input: future evidence authority"),
        ("", "controlled input: unlabelled resource"),
    ],
)
def test_controlled_input_roles_are_complete_and_forward_compatible(
    label: str, expected: str
) -> None:
    """Production and future controlled inputs receive non-failing report labels."""
    assert _controlled_input_role(label) == expected


def test_input_records_accept_complete_production_resources(
    synthetic_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage-00 reporting inventories every reuse input without a label lookup failure."""
    config = load_config(path=synthetic_config)
    labels = (
        "candidate_evidence",
        "candidate_evidence_manifest",
        "orthology_species_manifest",
        "inherited_sqlite",
        "orthofinder_archive",
        "e3_domain_catalogue",
        "domain_annotation_manifest",
        "expression_manifest",
        "ligandability_manifest",
        "future_evidence_authority",
    )
    controlled_inputs = []
    for label in labels:
        path = tmp_path / f"{label}.input"
        path.write_text(f"{label}\n", encoding="utf-8")
        controlled_inputs.append((label, path))
    monkeypatch.setattr(
        reporting,
        "controlled_input_paths",
        lambda _config: tuple(controlled_inputs),
    )

    records = _input_records(config, "00_inputs")
    roles = [str(record[0]) for record in records]

    assert len(records) == len(controlled_inputs) + 1
    assert roles[0] == "workflow configuration"
    assert "candidate evidence Parquet" in roles
    assert "reviewed OrthoFinder result archive" in roles
    assert "controlled input: future evidence authority" in roles


def test_production_stage_zero_publishes_complete_resource_report(
    synthetic_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complete production reuse inventory survives stage execution and HTML publication."""
    config = replace(load_config(path=synthetic_config), mode="production")
    labels = (
        "candidate_evidence",
        "candidate_evidence_manifest",
        "orthology_species_manifest",
        "inherited_sqlite",
        "orthofinder_archive",
        "e3_domain_catalogue",
        "expression_manifest",
        "ligandability_manifest",
    )
    controlled_inputs = []
    for label in labels:
        path = tmp_path / f"{label}.input"
        path.write_text(f"{label}\n", encoding="utf-8")
        controlled_inputs.append((label, path))
    controlled_input_result = tuple(controlled_inputs)
    monkeypatch.setattr(
        reporting,
        "controlled_input_paths",
        lambda _config: controlled_input_result,
    )
    monkeypatch.setattr(
        runner,
        "controlled_input_paths",
        lambda _config: controlled_input_result,
    )
    monkeypatch.setattr(runner, "read_resource_manifest", lambda **_kwargs: ({},))
    initialise_stage_tokens(config=config)

    manifest_path = execute_stage(config=config, stage_name="00_inputs")
    report_path = config.run_root / "00_inputs" / "report" / "stage_report.html"
    report = report_path.read_text(encoding="utf-8")

    assert manifest_path.is_file()
    assert "candidate evidence Parquet" in report
    assert "reviewed OrthoFinder result archive" in report
    assert "Expression Atlas resource manifest" in report
    assert "ligandability resource manifest" in report


def test_streaming_output_summaries_are_bounded(tmp_path: Path) -> None:
    """TSV, FASTA, JSON and binary outputs receive conservative summaries."""
    write_tsv(
        path=tmp_path / "table.tsv.gz",
        rows=({"accession": "A&1", "score": index} for index in range(5)),
        columns=("accession", "score"),
    )
    (tmp_path / "sequences.faa").write_text(
        ">protein_one description\nMAAA\n>protein_two\nMKKKKK\n",
        encoding="utf-8",
    )
    (tmp_path / "summary.json").write_text(
        json.dumps({"status": "complete", "count": 5, "nested": {"ignored": True}}),
        encoding="utf-8",
    )
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(query="CREATE TABLE results AS SELECT 1 AS identifier, 2.5 AS score")
        connection.execute(
            query="COPY results TO ? (FORMAT PARQUET)",
            parameters=[str(tmp_path / "result.parquet")],
        )
    with duckdb.connect(database=str(tmp_path / "results.duckdb")) as connection:
        connection.execute(query="CREATE TABLE candidates AS SELECT 1 AS identifier")
        connection.execute(query="CREATE VIEW candidate_view AS SELECT * FROM candidates")
    with sqlite3.connect(database=tmp_path / "results.sqlite") as connection:
        connection.execute("CREATE TABLE evidence (identifier TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('Q9SA03')")

    table = summarise_output(
        stage_root=tmp_path,
        relative_path="table.tsv.gz",
        preview_rows=2,
        max_columns=1,
    )
    fasta = summarise_output(
        stage_root=tmp_path,
        relative_path="sequences.faa",
        preview_rows=2,
        max_columns=2,
    )
    json_summary = summarise_output(
        stage_root=tmp_path,
        relative_path="summary.json",
        preview_rows=2,
        max_columns=2,
    )
    parquet = summarise_output(
        stage_root=tmp_path,
        relative_path="result.parquet",
        preview_rows=2,
        max_columns=2,
    )
    duckdb_summary = summarise_output(
        stage_root=tmp_path,
        relative_path="results.duckdb",
        preview_rows=5,
        max_columns=2,
    )
    sqlite_summary = summarise_output(
        stage_root=tmp_path,
        relative_path="results.sqlite",
        preview_rows=5,
        max_columns=2,
    )

    assert table["row_count"] == 5
    assert table["column_count"] == 2
    assert table["columns"] == ["accession"]
    assert len(table["preview"]) == 2
    assert fasta["sequence_count"] == 2
    assert fasta["total_residues"] == 10
    assert fasta["identifiers"] == ["protein_one", "protein_two"]
    assert json_summary["scalar_values"]["status"] == "complete"
    assert parquet["kind"] == "Parquet table"
    assert parquet["row_count"] == 1
    assert parquet["column_count"] == 2
    assert duckdb_summary["row_count"] == 2
    assert any(row["relation"] == "candidates" for row in duckdb_summary["preview"])
    assert sqlite_summary["row_count"] == 1
    assert sqlite_summary["preview"][0]["row_count"] == "1"


def test_defensive_summary_and_graphic_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed and uncommon outputs remain reportable without invented results."""
    (tmp_path / "malformed.tsv").write_text("a\tb\n1\n", encoding="utf-8")
    (tmp_path / "empty.tsv").write_text("", encoding="utf-8")
    (tmp_path / "empty.faa").write_text("sequence-without-header\n", encoding="utf-8")
    (tmp_path / "list.json").write_text("[1, 2]", encoding="utf-8")
    (tmp_path / "scalar.json").write_text("true", encoding="utf-8")
    (tmp_path / "invalid.json").write_text("{", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("\nfirst <line>\nsecond\n", encoding="utf-8")
    (tmp_path / "result.sqlite").write_bytes(b"SQLite format")
    (tmp_path / "unknown.bin").write_bytes(b"binary")

    malformed = summarise_output(
        stage_root=tmp_path,
        relative_path="malformed.tsv",
        preview_rows=2,
        max_columns=2,
    )
    empty_table = summarise_output(
        stage_root=tmp_path,
        relative_path="empty.tsv",
        preview_rows=2,
        max_columns=2,
    )
    empty_fasta = summarise_output(
        stage_root=tmp_path,
        relative_path="empty.faa",
        preview_rows=2,
        max_columns=2,
    )
    list_json = summarise_output(
        stage_root=tmp_path,
        relative_path="list.json",
        preview_rows=2,
        max_columns=2,
    )
    scalar_json = summarise_output(
        stage_root=tmp_path,
        relative_path="scalar.json",
        preview_rows=2,
        max_columns=2,
    )
    invalid_json = summarise_output(
        stage_root=tmp_path,
        relative_path="invalid.json",
        preview_rows=2,
        max_columns=2,
    )
    text = summarise_output(
        stage_root=tmp_path,
        relative_path="notes.txt",
        preview_rows=1,
        max_columns=2,
    )
    database = summarise_output(
        stage_root=tmp_path,
        relative_path="result.sqlite",
        preview_rows=1,
        max_columns=2,
    )
    unknown = summarise_output(
        stage_root=tmp_path,
        relative_path="unknown.bin",
        preview_rows=1,
        max_columns=2,
    )

    assert "did not match" in malformed["warning"]
    assert "could not be previewed" in empty_table["summary"]
    assert "No FASTA headers" in empty_fasta["warning"]
    assert "2 top-level items" in list_json["summary"]
    assert "bool" in scalar_json["summary"]
    assert "could not be inspected" in invalid_json["summary"]
    assert text["text_preview"] == ["first <line>"]
    assert database["kind"] == "database"
    assert unknown["kind"] == "file"

    monkeypatch.setattr(reporting, "MAX_JSON_INSPECTION_BYTES", 1)
    large_json = summarise_output(
        stage_root=tmp_path,
        relative_path="list.json",
        preview_rows=1,
        max_columns=1,
    )
    assert "safe report-inspection limit" in large_json["summary"]
    assert _number("bad", default=3.0) == 3.0
    assert _number(float("inf"), default=4.0) == 4.0
    assert _integer(None, default=5) == 5
    assert "No values" in _bar_chart(title="empty", items=(), unit="s", maximum_items=2)
    assert "Too few samples" in _line_chart(title="empty", points=(), y_unit="MiB")
    assert _timeseries_points(tmp_path / "missing.tsv.gz", sample_count=0) == {
        "cpu": [],
        "rss": [],
    }
    rendered = _result_html(
        {
            "path": "unsafe<&.tsv",
            "kind": "TSV table",
            "summary": "summary",
            "size_bytes": 10,
            "sha256": "abc",
            "columns": ["a"],
            "preview": [{"a": "<&"}],
            "columns_truncated": True,
            "identifiers": ["seq<1"],
            "text_preview": ["line<1"],
            "warning": "warning<1",
        },
        "../",
    )
    assert "unsafe&lt;&amp;.tsv" in rendered
    assert "Additional columns" in rendered
    assert "warning&lt;1" in rendered


def test_stage_report_is_manifest_bound_and_escaped(synthetic_config: Path) -> None:
    """A successful stage publishes verbose HTML as a checksummed output."""
    config = load_config(path=synthetic_config)
    initialise_stage_tokens(config=config)
    manifest_path = execute_stage(config=config, stage_name="00_inputs")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    report_path = config.run_root / "00_inputs" / "report" / "stage_report.html"
    report = report_path.read_text(encoding="utf-8")

    assert report_path.is_file()
    assert any(item["path"] == "report/stage_report.html" for item in payload["outputs"])
    assert payload["validation"]["declared_outputs_validated"] is True
    assert payload["execution"]["implementation"] == "internal"
    assert payload["result_summaries"][0]["row_count"] == 3
    assert "Scientific summary" in report
    assert "Inputs and provenance" in report
    assert "Computation and command" in report
    assert "Resource use" in report
    assert "SYNTHETIC TEST RUN" in report
    assert "stage_manifest.json" not in {
        item["path"] for item in payload["outputs"]
    }


def test_complete_report_contains_all_stages_and_commands(synthetic_config: Path) -> None:
    """The final report joins all validated stage, benchmark and command evidence."""
    config = load_config(path=synthetic_config)
    initialise_stage_tokens(config=config)
    record = record_workflow_invocation(
        config=config,
        argv=("snakemake", "--cores", "4", "target with spaces"),
        working_directory=config.project_root,
    )
    assert record["status"] == "recorded"
    for stage_name in STAGE_NAMES:
        execute_stage(config=config, stage_name=stage_name)
    aggregate_run_benchmarks(
        config=config,
        output_dir=config.run_root / "benchmark_summary",
    )
    result = generate_run_report(config=config, output_dir=config.run_root / "reports")
    report_path = Path(result["html_report"])
    report = report_path.read_text(encoding="utf-8")

    assert report_path.name == RUN_REPORT_FILENAME
    assert result["stage_count"] == len(STAGE_NAMES)
    assert result["skipped_stage_count"] == 1
    assert result["application_release_eligible"] is False
    assert all(f'id="{stage_name}"' in report for stage_name in STAGE_NAMES)
    assert "target with spaces" in report
    assert "Stage wall time" in report
    assert "Scientific interpretation policy" in report
    assert "Cluster membership is similarity evidence" in report
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["configuration_digest"] == config.digest
    assert manifest["outputs"][0]["path"] == RUN_REPORT_FILENAME

    second = generate_run_report(config=config, output_dir=config.run_root / "reports")
    assert Path(second["html_report"]).is_file()
    assert any((config.run_root / "superseded").glob("reports.*"))


@pytest.mark.parametrize(
    ("flag_type", "rows", "expected"),
    [
        (
            "BOOLEAN",
            (("HOG:1", True), ("HOG:2", False), ("HOG:3", True)),
            (3, 2),
        ),
        (
            "VARCHAR",
            (("HOG:1", "true"), ("HOG:2", "false"), ("HOG:3", "TRUE")),
            (3, 2),
        ),
    ],
)
def test_authoritative_evolutionary_group_counts_use_group_schema(
    synthetic_config: Path,
    flag_type: str,
    rows: tuple[tuple[object, object], ...],
    expected: tuple[int, int],
) -> None:
    """The report counts native or textual lead-group pass flags."""
    config = replace(load_config(path=synthetic_config), mode="production")
    ranking = (
        config.run_root
        / "08_shortlist_gate"
        / "tables"
        / "evolutionary_candidate_group_ranking.parquet"
    )
    _write_evolutionary_group_ranking(
        path=ranking,
        rows=rows,
        flag_type=flag_type,
    )

    assert _authoritative_evolutionary_group_counts(config) == expected


def test_authoritative_evolutionary_group_counts_match_completed_run_shape(
    synthetic_config: Path,
) -> None:
    """The completed-run dimensions yield 1,972 groups and 38 stringent passes."""
    config = replace(load_config(path=synthetic_config), mode="production")
    ranking = (
        config.run_root
        / "08_shortlist_gate"
        / "tables"
        / "evolutionary_candidate_group_ranking.parquet"
    )
    rows = tuple(
        (f"ORTHOFINDER_HIERARCHICAL_GROUP:HOG{index:07d}", index <= 38)
        for index in range(1, 1_973)
    )
    _write_evolutionary_group_ranking(path=ranking, rows=rows)

    assert _authoritative_evolutionary_group_counts(config) == (1_972, 38)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ((), "ranking is empty"),
        ((("HOG:1", "not-a-boolean"),), "invalid stringent-pass"),
        ((("", "true"),), "empty group key"),
        ((("HOG:1", "true"), ("HOG:1", "false")), "not one row per group"),
    ],
)
def test_authoritative_evolutionary_group_counts_reject_invalid_authority(
    synthetic_config: Path,
    rows: tuple[tuple[object, object], ...],
    message: str,
) -> None:
    """Empty, ambiguous or duplicate Stage 08 authorities fail closed."""
    config = replace(load_config(path=synthetic_config), mode="production")
    ranking = (
        config.run_root
        / "08_shortlist_gate"
        / "tables"
        / "evolutionary_candidate_group_ranking.parquet"
    )
    _write_evolutionary_group_ranking(
        path=ranking,
        rows=rows,
        flag_type="VARCHAR",
    )

    with pytest.raises(WorkflowError, match=message):
        _authoritative_evolutionary_group_counts(config)


def test_authoritative_evolutionary_group_counts_require_lead_flag(
    synthetic_config: Path,
) -> None:
    """A cluster-level flag cannot silently replace the lead-group flag."""
    config = replace(load_config(path=synthetic_config), mode="production")
    ranking = (
        config.run_root
        / "08_shortlist_gate"
        / "tables"
        / "evolutionary_candidate_group_ranking.parquet"
    )
    ranking.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            "CREATE TABLE evolutionary_groups AS "
            "SELECT 'HOG:1' AS evolutionary_group_key, "
            "TRUE AS grant_aligned_stringent_pass"
        )
        connection.execute(
            "COPY evolutionary_groups TO ? (FORMAT PARQUET)",
            [str(ranking)],
        )

    with pytest.raises(WorkflowError, match="lead_grant_aligned_stringent_pass"):
        _authoritative_evolutionary_group_counts(config)


def test_complete_report_labels_bounded_runs(synthetic_config: Path) -> None:
    """A completed configuration with skipped stages is not called application-release ready."""
    raw = yaml.safe_load(synthetic_config.read_text(encoding="utf-8"))
    raw["run"]["name"] = "synthetic_bounded_report"
    raw["stages"]["02_discovery"].update(
        enabled=False,
        required=False,
        expected_outputs=[],
    )
    synthetic_config.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    config = load_config(path=synthetic_config)
    initialise_stage_tokens(config=config)
    for stage_name in STAGE_NAMES:
        execute_stage(config=config, stage_name=stage_name)
    aggregate_run_benchmarks(
        config=config,
        output_dir=config.run_root / "benchmark_summary",
    )
    result = generate_run_report(config=config, output_dir=config.run_root / "reports")
    report = Path(result["html_report"]).read_text(encoding="utf-8")
    assert result["skipped_stage_count"] == 2
    assert result["application_release_eligible"] is False
    assert "complete configured run" in report
    assert (
        "2 optional stages were explicitly skipped: 02_discovery, "
        "09b_structural_alignment"
    ) in report


def test_report_rejects_incomplete_or_mismatched_evidence(synthetic_config: Path) -> None:
    """Final reporting fails closed when stage or benchmark provenance differs."""
    config = load_config(path=synthetic_config)
    initialise_stage_tokens(config=config)
    for stage_name in STAGE_NAMES:
        execute_stage(config=config, stage_name=stage_name)
    aggregate_run_benchmarks(
        config=config,
        output_dir=config.run_root / "benchmark_summary",
    )
    path = config.run_root / "05_orthology" / "stage_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["configuration_digest"] = "different"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkflowError, match="digest differs"):
        generate_run_report(config=config, output_dir=config.run_root / "reports")


def test_report_rejects_benchmark_mismatch_and_retains_failed_build(
    synthetic_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Benchmark mismatches and report-write failures fail closed with diagnostics."""
    config = load_config(path=synthetic_config)
    initialise_stage_tokens(config=config)
    for stage_name in STAGE_NAMES:
        execute_stage(config=config, stage_name=stage_name)
    aggregate_run_benchmarks(
        config=config,
        output_dir=config.run_root / "benchmark_summary",
    )
    benchmark_path = config.run_root / "benchmark_summary" / "benchmark_manifest.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    original_digest = benchmark["configuration_digest"]
    benchmark["configuration_digest"] = "wrong"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
    with pytest.raises(WorkflowError, match="Benchmark and workflow"):
        generate_run_report(config=config, output_dir=config.run_root / "reports")
    benchmark["configuration_digest"] = original_digest
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")

    def fail_write(path: Path, text: str) -> None:
        """Raise a deterministic output failure after report staging begins."""
        raise OSError(f"cannot write {path}: {len(text)}")

    monkeypatch.setattr(reporting, "atomic_write_text", fail_write)
    with pytest.raises(OSError, match="cannot write"):
        generate_run_report(config=config, output_dir=config.run_root / "reports")
    assert any((config.run_root / "failed").glob("reports.*"))


def test_invalid_invocation_history_is_rejected(synthetic_config: Path) -> None:
    """Invocation provenance requires a non-empty argv and valid prior history."""
    config = load_config(path=synthetic_config)
    with pytest.raises(WorkflowError, match="argument vector"):
        record_workflow_invocation(config=config, argv=())
    path = config.run_root / "workflow_logs" / "workflow_invocations.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"invocations": {}}', encoding="utf-8")
    with pytest.raises(WorkflowError, match="Invalid workflow invocation"):
        record_workflow_invocation(config=config, argv=("snakemake",))
