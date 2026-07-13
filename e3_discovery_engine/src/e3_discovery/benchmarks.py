"""Benchmark aggregation and publication-ready summary figures."""

from __future__ import annotations

import csv
import logging
import math
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

import matplotlib.pyplot as plt
import pyarrow as pa
import pyarrow.parquet as pq

from e3_discovery.exceptions import DataValidationError
from e3_discovery.io_utils import atomic_binary_path, write_tsv

LOGGER = logging.getLogger(__name__)


def parse_snakemake_benchmark(path: Path) -> List[Dict[str, object]]:
    """Parse one Snakemake benchmark TSV and annotate its source file."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Benchmark file does not exist: {source}")
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or "s" not in reader.fieldnames:
            raise DataValidationError(
                f"Benchmark file lacks required 's' column: {source}"
            )
        records = []
        for repeat_index, row in enumerate(reader, start=1):
            record: Dict[str, object] = {
                "benchmark_file": str(source.resolve()),
                "rule_name": source.stem,
                "repeat_index": repeat_index,
            }
            for key, value in row.items():
                clean = str(value or "").strip()
                if key in {
                    "s",
                    "max_rss",
                    "max_vms",
                    "max_uss",
                    "max_pss",
                    "io_in",
                    "io_out",
                    "mean_load",
                    "cpu_time",
                }:
                    try:
                        record[key] = float(clean) if clean not in {"", "-"} else None
                    except ValueError as error:
                        raise DataValidationError(
                            f"Invalid benchmark number for {key}: {clean!r}"
                        ) from error
                else:
                    record[key] = clean
            records.append(record)
    if not records:
        raise DataValidationError(f"Benchmark file contains no runs: {source}")
    return records


def aggregate_benchmark_directory(
    benchmark_dir: Path,
    dataset_metadata: Mapping[str, object] | None = None,
) -> List[Dict[str, object]]:
    """Aggregate all benchmark TSV files below a directory."""

    root = Path(benchmark_dir)
    LOGGER.info("Aggregating benchmark files below %s", root)
    if not root.is_dir():
        raise FileNotFoundError(f"Benchmark directory does not exist: {root}")
    records: List[Dict[str, object]] = []
    for path in sorted(root.rglob("*.tsv")):
        for record in parse_snakemake_benchmark(path):
            if dataset_metadata:
                record.update(dataset_metadata)
            records.append(record)
    if not records:
        raise DataValidationError(f"No benchmark TSV files found below: {root}")
    LOGGER.info("Aggregated %d benchmark records", len(records))
    return records


def summarise_benchmarks(
    records: Iterable[Mapping[str, object]],
) -> List[Dict[str, object]]:
    """Summarise repeated benchmark measurements by rule name."""

    groups: Dict[str, List[Mapping[str, object]]] = {}
    for record in records:
        rule = str(record.get("rule_name", "")).strip()
        if not rule:
            raise DataValidationError("Benchmark record lacks rule_name")
        groups.setdefault(rule, []).append(record)

    summaries: List[Dict[str, object]] = []
    for rule, items in sorted(groups.items()):
        seconds = [float(item["s"]) for item in items if item.get("s") is not None]
        if not seconds:
            raise DataValidationError(f"No wall-clock times for benchmark rule {rule}")
        memory = [
            float(item["max_rss"])
            for item in items
            if item.get("max_rss") is not None
        ]
        summaries.append(
            {
                "rule_name": rule,
                "repeat_count": len(seconds),
                "mean_seconds": sum(seconds) / len(seconds),
                "minimum_seconds": min(seconds),
                "maximum_seconds": max(seconds),
                "standard_deviation_seconds": _population_sd(seconds),
                "mean_max_rss_mb": sum(memory) / len(memory) if memory else None,
                "maximum_max_rss_mb": max(memory) if memory else None,
            }
        )
    return summaries


def _population_sd(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("At least one value is required")
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def write_benchmark_outputs(
    records: Sequence[Mapping[str, object]],
    summary_records: Sequence[Mapping[str, object]],
    output_tsv: Path,
    output_parquet: Path,
    summary_tsv: Path,
) -> None:
    """Write detailed and summary benchmark tables."""

    write_tsv(records, output_tsv)
    write_tsv(summary_records, summary_tsv)
    with atomic_binary_path(output_parquet) as temporary:
        table = pa.Table.from_pylist([dict(record) for record in records])
        pq.write_table(table, temporary, compression="zstd")


def plot_runtime_by_rule(
    summary_records: Sequence[Mapping[str, object]],
    output_png: Path,
    output_pdf: Path | None = None,
) -> None:
    """Plot mean rule runtime with standard-deviation error bars."""

    if not summary_records:
        raise ValueError("summary_records cannot be empty")
    ordered = sorted(
        summary_records,
        key=lambda row: float(row["mean_seconds"]),
        reverse=True,
    )
    labels = [str(row["rule_name"]) for row in ordered]
    means = [float(row["mean_seconds"]) for row in ordered]
    errors = [float(row["standard_deviation_seconds"]) for row in ordered]

    figure, axis = plt.subplots(figsize=(10, max(4, 0.45 * len(labels))))
    positions = list(range(len(labels)))
    axis.barh(positions, means, xerr=errors)
    axis.set_yticks(positions, labels=labels)
    axis.invert_yaxis()
    axis.set_xlabel("Wall-clock time (seconds)")
    axis.set_title("E3 discovery workflow runtime by rule")
    figure.tight_layout()
    Path(output_png).parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_png, dpi=300, bbox_inches="tight")
    if output_pdf is not None:
        Path(output_pdf).parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_pdf, bbox_inches="tight")
    plt.close(figure)
