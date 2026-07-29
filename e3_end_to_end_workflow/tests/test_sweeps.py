"""Tests for parameter-sweep generation and comparison."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from e3workflow.config import load_config
from e3workflow.errors import ConfigurationError
from e3workflow.io_utils import write_tsv
from e3workflow.sweeps import compare_sweep, load_sweep_spec, prepare_sweep

FINAL_COLUMNS = (
    "final_rank",
    "recommendation_status",
    "cluster_id",
    "candidate_accessions",
    "final_score",
    "grant_aligned_prestructure_pass",
    "grant_aligned_final_pass",
    "profile_name",
)


def _base_config(
    *,
    package_root: Path,
    tmp_path: Path,
) -> Path:
    """Create an isolated sweepable base configuration."""
    source = package_root / "config" / "synthetic.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    data["schema_version"] = 2
    data["path_base"] = str(source.parent)
    data["run"]["name"] = "sweep_base"
    data["run"]["output_root"] = str(tmp_path / "runs")
    data["analysis"] = {
        "expression": {
            "minimum_expression_value": 0.0,
            "broad_positive_fraction": 0.5,
        },
        "ligandability": {
            "minimum_druggability_score": 0.5,
        },
    }
    path = tmp_path / "base.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _sweep_config(
    *,
    base_config: Path,
    tmp_path: Path,
    maximum_runs: int = 10,
) -> Path:
    """Create a small two-threshold Cartesian sweep."""
    data = {
        "schema_version": 1,
        "name": "threshold_test",
        "base_config": str(base_config),
        "strategy": "cartesian",
        "include_baseline": True,
        "maximum_runs": maximum_runs,
        "parameters": [
            {
                "path": "analysis.expression.broad_positive_fraction",
                "values": [0.4, 0.6],
            },
            {
                "path": "analysis.ligandability.minimum_druggability_score",
                "values": [0.3, 0.7],
            },
        ],
    }
    path = tmp_path / "sweep.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _read_tsv(path: Path) -> list[dict[str, str]]:
    """Read one test TSV."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def test_prepare_cartesian_sweep_generates_valid_immutable_configs(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """The generator publishes a baseline plus every requested combination."""
    base = _base_config(package_root=package_root, tmp_path=tmp_path)
    sweep = _sweep_config(base_config=base, tmp_path=tmp_path)
    output = tmp_path / "generated"
    result = prepare_sweep(sweep_config=sweep, output_dir=output)
    assert result["run_count"] == 5
    rows = _read_tsv(output / "sweep_runs.tsv")
    assert len(rows) == 5
    assert rows[0]["baseline"] == "true"
    assert len({row["run_name"] for row in rows}) == 5
    for row in rows:
        generated = load_config(Path(row["config_path"]))
        assert generated.schema_version == 2
        assert generated.run_root == Path(row["run_root"])
        assert generated.path_base == base.parent
    with pytest.raises(ConfigurationError, match="already exists"):
        prepare_sweep(sweep_config=sweep, output_dir=output)
    replaced = prepare_sweep(sweep_config=sweep, output_dir=output, force=True)
    assert replaced["run_count"] == 5


def test_one_at_a_time_and_maximum_run_guard(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """One-at-a-time expansion and the hard run-count limit are deterministic."""
    base = _base_config(package_root=package_root, tmp_path=tmp_path)
    sweep = _sweep_config(base_config=base, tmp_path=tmp_path, maximum_runs=4)
    data = yaml.safe_load(sweep.read_text(encoding="utf-8"))
    with pytest.raises(ConfigurationError, match="exceeding maximum_runs"):
        prepare_sweep(sweep_config=sweep, output_dir=tmp_path / "too_many")
    data["strategy"] = "one_at_a_time"
    data["maximum_runs"] = 5
    sweep.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    result = prepare_sweep(sweep_config=sweep, output_dir=tmp_path / "one")
    assert result["run_count"] == 5


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(schema_version=2), "schema_version"),
        (lambda data: data.update(name="bad name"), "name must contain"),
        (lambda data: data.update(strategy="random"), "strategy"),
        (lambda data: data.update(include_baseline="yes"), "include_baseline"),
        (lambda data: data.update(maximum_runs=0), "positive integer"),
        (
            lambda data: data["parameters"][0].update(path="inputs.expression_manifest"),
            "must begin with",
        ),
        (
            lambda data: data["parameters"][0].update(path="analysis.Bad-Key"),
            "unsafe path segment",
        ),
        (
            lambda data: data["parameters"][0].update(values=[]),
            "non-empty YAML list",
        ),
        (
            lambda data: data["parameters"][0].update(values=[0.4, 0.4]),
            "Duplicate values",
        ),
        (
            lambda data: data["parameters"][0].update(values=[float("inf")]),
            "must be finite",
        ),
        (
            lambda data: data["parameters"][0].update(values=["bad\tvalue"]),
            "must not contain tabs",
        ),
        (
            lambda data: data["parameters"].append(data["parameters"][0].copy()),
            "Duplicate sweep parameter path",
        ),
        (lambda data: data.update(unknown=True), "Unknown sweep settings"),
    ],
)
def test_invalid_sweep_specifications_fail_closed(
    package_root: Path,
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    """Malformed or unsafe sweep settings are rejected."""
    base = _base_config(package_root=package_root, tmp_path=tmp_path)
    sweep = _sweep_config(base_config=base, tmp_path=tmp_path)
    data = yaml.safe_load(sweep.read_text(encoding="utf-8"))
    mutation(data)
    sweep.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        load_sweep_spec(sweep)


def test_sweep_loader_rejects_missing_malformed_and_out_of_bounds_specs(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Sweep loading must reject unreadable YAML and unsafe run or value bounds."""
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_sweep_spec(path=missing)

    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("[", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Could not read sweep configuration"):
        load_sweep_spec(path=malformed)

    base = _base_config(package_root=package_root, tmp_path=tmp_path)
    sweep = _sweep_config(base_config=base, tmp_path=tmp_path)
    data = yaml.safe_load(sweep.read_text(encoding="utf-8"))

    data["maximum_runs"] = 501
    sweep.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="cannot exceed 500"):
        load_sweep_spec(path=sweep)

    data["maximum_runs"] = 10
    data["parameters"] = "not-a-list"
    sweep.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="non-empty YAML list"):
        load_sweep_spec(path=sweep)

    data["parameters"] = [
        {
            "path": "analysis.expression.broad_positive_fraction",
            "values": [""],
        }
    ]
    sweep.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="non-empty string"):
        load_sweep_spec(path=sweep)


def test_absent_parameter_path_is_rejected(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """A typo cannot silently add a new configuration key."""
    base = _base_config(package_root=package_root, tmp_path=tmp_path)
    sweep = _sweep_config(base_config=base, tmp_path=tmp_path)
    data = yaml.safe_load(sweep.read_text(encoding="utf-8"))
    data["parameters"][0]["path"] = "analysis.expression.not_a_real_threshold"
    sweep.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="absent from the base"):
        prepare_sweep(sweep_config=sweep, output_dir=tmp_path / "generated")


def test_compare_sweep_publishes_tsv_sensitivity_tables(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Completed final rankings are combined without a Parquet-only dependency."""
    base = _base_config(package_root=package_root, tmp_path=tmp_path)
    sweep = _sweep_config(base_config=base, tmp_path=tmp_path)
    generated = tmp_path / "generated"
    prepare_sweep(sweep_config=sweep, output_dir=generated)
    manifest_rows = _read_tsv(generated / "sweep_runs.tsv")
    for index, row in enumerate(manifest_rows):
        final_table = (
            Path(row["run_root"])
            / "10_integrated_resource"
            / "tables"
            / "final_candidate_prioritisation.tsv"
        )
        write_tsv(
            final_table,
            [
                {
                    "final_rank": 1 if index % 2 == 0 else 2,
                    "recommendation_status": (
                        "PRIORITY_RECOMMENDATION"
                        if index % 2 == 0
                        else "FURTHER_EVIDENCE_OR_REVIEW_REQUIRED"
                    ),
                    "cluster_id": "cluster_1",
                    "candidate_accessions": "Q9SA03",
                    "final_score": 0.8 - index * 0.05,
                    "grant_aligned_prestructure_pass": "true",
                    "grant_aligned_final_pass": str(index % 2 == 0).lower(),
                    "profile_name": "test_profile",
                }
            ],
            FINAL_COLUMNS,
        )
    output = tmp_path / "comparison"
    result = compare_sweep(
        manifest=generated / "sweep_runs.tsv",
        output_dir=output,
    )
    assert result["status"] == "complete"
    assert result["completed_run_count"] == 5
    summary = _read_tsv(output / "sweep_candidate_summary.tsv")
    assert summary[0]["cluster_id"] == "cluster_1"
    assert summary[0]["runs_present"] == "5"
    assert summary[0]["priority_recommendation_runs"] == "3"
    assert (output / "sweep_candidate_sensitivity.tsv").is_file()
    assert (output / "sweep_run_status.tsv").is_file()


def test_compare_sweep_requires_complete_runs_unless_explicitly_allowed(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Missing final tables are reported but do not masquerade as completed runs."""
    base = _base_config(package_root=package_root, tmp_path=tmp_path)
    sweep = _sweep_config(base_config=base, tmp_path=tmp_path)
    generated = tmp_path / "generated"
    prepare_sweep(sweep_config=sweep, output_dir=generated)
    manifest = generated / "sweep_runs.tsv"
    with pytest.raises(ConfigurationError, match="incomplete"):
        compare_sweep(manifest=manifest, output_dir=tmp_path / "strict")
    result = compare_sweep(
        manifest=manifest,
        output_dir=tmp_path / "partial",
        allow_incomplete=True,
    )
    assert result["status"] == "partial"
    assert result["completed_run_count"] == 0
