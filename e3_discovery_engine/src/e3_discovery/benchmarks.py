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


def _is_hidden_benchmark_artifact(path: Path, root: Path) -> bool:
    """Return whether a candidate benchmark path is a hidden artefact.

    macOS can create AppleDouble resource-fork sidecars named ``._*.tsv``
    when files are written to some external-drive filesystems. Those files
    are binary metadata rather than Snakemake benchmark tables. Hidden files
    and files below hidden directories are therefore excluded from benchmark
    discovery.

    Args:
        path: Candidate benchmark path.
        root: Benchmark directory used as the discovery root.

    Returns:
        ``True`` when any relative path component starts with a full stop;
        otherwise ``False``.
    """

    candidate = Path(path)
    benchmark_root = Path(root)
    try:
        relative = candidate.relative_to(benchmark_root)
    except ValueError:
        relative = candidate
    return any(part.startswith(".") for part in relative.parts)


def parse_snakemake_benchmark(path: Path) -> List[Dict[str, object]]:
    """Parse one Snakemake benchmark table into typed records.

    Numeric benchmark fields are converted to floats, missing numeric values
    are represented by ``None``, and every record is annotated with its source
    file, inferred rule name and one-based repeat index.

    Args:
        path: Path to a tab-separated Snakemake benchmark file.

    Returns:
        A list of dictionaries, one for each recorded benchmark repeat.

    Raises:
        FileNotFoundError: If ``path`` does not identify an existing file.
        DataValidationError: If the required ``s`` column is absent, a numeric
            value is invalid, or the file contains no benchmark rows.
    """

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Benchmark file does not exist: {source}")
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
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
                            record[key] = (
                                float(clean) if clean not in {"", "-"} else None
                            )
                        except ValueError as error:
                            raise DataValidationError(
                                f"Invalid benchmark number for {key}: {clean!r}"
                            ) from error
                    else:
                        record[key] = clean
                records.append(record)
    except UnicodeDecodeError as error:
        raise DataValidationError(
            "Benchmark file is not UTF-8 text and may be a binary "
            f"filesystem sidecar: {source}"
        ) from error
    if not records:
        raise DataValidationError(f"Benchmark file contains no runs: {source}")
    return records


def aggregate_benchmark_directory(
    benchmark_dir: Path,
    dataset_metadata: Mapping[str, object] | None = None,
) -> List[Dict[str, object]]:
    """Collect benchmark records from every TSV file below a directory.

    Files are visited recursively in deterministic path order. Optional
    dataset metadata is copied into every parsed record.

    Args:
        benchmark_dir: Root directory containing Snakemake benchmark TSV files.
        dataset_metadata: Optional metadata fields to add to every record.

    Returns:
        A flat list of typed benchmark-record dictionaries.

    Raises:
        FileNotFoundError: If ``benchmark_dir`` is not an existing directory.
        DataValidationError: If no TSV files are found or a benchmark file is
            malformed.
    """

    root = Path(benchmark_dir)
    LOGGER.info("Aggregating benchmark files below %s", root)
    if not root.is_dir():
        raise FileNotFoundError(f"Benchmark directory does not exist: {root}")
    records: List[Dict[str, object]] = []
    for path in sorted(root.rglob("*.tsv")):
        if _is_hidden_benchmark_artifact(path, root):
            LOGGER.info("Ignoring hidden benchmark artefact: %s", path)
            continue
        if not path.is_file():
            LOGGER.warning("Ignoring non-file benchmark candidate: %s", path)
            continue
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
    """Summarise repeated benchmark observations by workflow rule.

    Wall-clock time is summarised with the mean, minimum, maximum and
    population standard deviation. Peak resident-memory values are summarised
    when present.

    Args:
        records: Benchmark records containing at least ``rule_name`` and ``s``.

    Returns:
        One summary dictionary per rule, ordered by rule name.

    Raises:
        DataValidationError: If a record lacks ``rule_name`` or a rule has no
            usable wall-clock measurements.
    """

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
    """Calculate the population standard deviation of numeric values.

    Args:
        values: Non-empty sequence of floating-point observations.

    Returns:
        The population standard deviation using ``N`` as the denominator.

    Raises:
        ValueError: If ``values`` is empty.
    """
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
    """Write detailed and summarised benchmark outputs.

    Detailed records are written as TSV and Zstandard-compressed Parquet;
    summary records are written as TSV. File publication is atomic where
    supported by the package I/O helpers.

    Args:
        records: Detailed benchmark records to serialise.
        summary_records: Aggregated rule-level benchmark summaries.
        output_tsv: Destination for the detailed TSV table.
        output_parquet: Destination for the detailed Parquet table.
        summary_tsv: Destination for the summary TSV table.

    Returns:
        None.

    Raises:
        OSError: If an output cannot be created or replaced.
        ValueError: If records cannot be represented as one Arrow table.
    """

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
    """Plot mean wall-clock runtime by workflow rule.

    Rules are ordered from slowest to fastest and population standard
    deviations are shown as horizontal error bars. A 300-dpi PNG is always
    written and an optional vector PDF can also be produced.

    Args:
        summary_records: Rule summaries containing runtime means and standard
            deviations.
        output_png: Destination path for the PNG figure.
        output_pdf: Optional destination path for a PDF copy.

    Returns:
        None.

    Raises:
        ValueError: If ``summary_records`` is empty or lacks required values.
        OSError: If a requested output figure cannot be written.
    """

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
