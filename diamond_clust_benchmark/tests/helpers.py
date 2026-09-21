"""Shared deterministic test builders."""

from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

import yaml

from diamond_clust_benchmark.runner import METRIC_FIELDS, StageMetrics

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PACKAGE_ROOT / "tests" / "fixtures"
FAKE_DIAMOND = FIXTURES / "fake_diamond.py"


def case_mapping(case_id: str = "baseline") -> dict[str, object]:
    """Build a valid direct-executable benchmark case mapping."""

    return {
        "case_id": case_id,
        "executable": str(FAKE_DIAMOND),
        "conda_environment": None,
        "expected_version": "2.2.3",
        "command": "deepclust",
        "identity_mode": "exact",
        "identity_percent": 50,
        "mutual_cover_percent": 50,
        "evalue": 0.1,
        "comp_based_stats": 0,
        "masking": "tantan",
        "cluster_steps": [],
        "no_reassign": False,
        "extra_args": [],
        "run_realign": True,
        "enabled": True,
    }


def write_config(
    directory: Path,
    cases: list[dict[str, object]] | None = None,
    repeats: int = 2,
    sentinels: bool = True,
) -> Path:
    """Write a valid isolated test configuration."""

    configured_cases = cases or [case_mapping()]
    payload = {
        "project": {"name": "test_benchmark"},
        "inputs": {
            "fasta": str(FIXTURES / "proteins.fasta"),
            "expected_sequences": 4,
            "expected_residues": 52,
            "sentinel_ids_tsv": (
                str(FIXTURES / "sentinels.tsv") if sentinels else None
            ),
        },
        "outputs": {
            "root": str(directory / "results"),
            "scratch_root": str(directory / "scratch"),
        },
        "resources": {
            "threads": 2,
            "diamond_memory_limit": "2G",
            "sampling_interval_seconds": 0.05,
        },
        "benchmark": {
            "repeats": repeats,
            "quality_repeat": 1,
            "baseline_case_id": configured_cases[0]["case_id"],
            "decision_stage": "pairwise_pipeline",
            "minimum_speedup_percent": 10,
            "minimum_pairwise_f1": 0.99,
            "minimum_sentinel_recall": 0.99,
            "bootstrap_iterations": 100,
            "cases": configured_cases,
        },
    }
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def metric(
    case_id: str,
    repeat: int,
    stage: str,
    wall_seconds: float,
) -> StageMetrics:
    """Build one successful resource observation."""

    return StageMetrics(
        case_id=case_id,
        repeat=repeat,
        stage=stage,
        wall_seconds=wall_seconds,
        user_cpu_seconds=wall_seconds,
        system_cpu_seconds=0.1,
        mean_cpu_equivalents=1.0,
        peak_rss_mib=12.0,
        read_bytes=10,
        write_bytes=20,
        maximum_processes=1,
        exit_code=0,
    )


def write_metrics(path: Path, records: Iterable[StageMetrics]) -> None:
    """Write package-compatible metrics for report tests."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            delimiter="\t",
            fieldnames=METRIC_FIELDS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(asdict(record) for record in records)
