#!/usr/bin/env python3
"""Compare every retained DIAMOND clustering result with every other result.

The script is intentionally runnable without installing the surrounding
package.  Small inputs are analysed with the Python standard library.  Large
inputs use DuckDB with a bounded thread count, an explicit memory limit and
filesystem spill space.

All scientific outputs are tab-separated.  Figures are written as PNG and PDF
files by default.  Agreement metrics describe similarity between clustering
results; they do not establish which result is biologically correct.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import logging
import math
import os
import re
import shutil
import socket
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence
from typing import Set, Tuple

LOGGER = logging.getLogger("diamond_all_against_all")
SCRIPT_VERSION = "0.2.0"
MEMBERSHIP_HEADERS = {
    ("centroid", "member"),
    ("representative", "member"),
    ("cluster", "member"),
}
SIZE_BINS = (
    ("singleton", 1, 1),
    ("2-5", 2, 5),
    ("6-20", 6, 20),
    ("21-100", 21, 100),
    ("101-1000", 101, 1000),
    (">1000", 1001, None),
)
PAIR_FIELDS = (
    "method_a",
    "method_b",
    "repeat_a",
    "repeat_b",
    "member_count",
    "cluster_count_a",
    "cluster_count_b",
    "same_cluster_pairs_a",
    "same_cluster_pairs_b",
    "shared_same_cluster_pairs",
    "pair_recall_a_in_b",
    "pair_recall_b_in_a",
    "pairwise_f1",
    "pairwise_jaccard",
    "adjusted_rand_index",
    "normalised_mutual_information",
    "variation_of_information",
    "normalised_variation_of_information",
    "exact_match_cluster_count",
    "exact_match_member_count",
    "exact_match_member_fraction",
    "split_cluster_count_a_to_b",
    "split_cluster_fraction_a_to_b",
    "members_in_split_clusters_a_to_b",
    "member_fraction_in_split_clusters_a_to_b",
    "split_cluster_count_b_to_a",
    "split_cluster_fraction_b_to_a",
    "members_in_split_clusters_b_to_a",
    "member_fraction_in_split_clusters_b_to_a",
    "best_match_jaccard_mean_a_to_b",
    "best_match_jaccard_median_a_to_b",
    "best_match_jaccard_weighted_mean_a_to_b",
    "best_match_jaccard_mean_b_to_a",
    "best_match_jaccard_median_b_to_a",
    "best_match_jaccard_weighted_mean_b_to_a",
)
SENTINEL_FIELDS = (
    "method_a",
    "method_b",
    "repeat_a",
    "repeat_b",
    "sentinel_count",
    "matched_sentinel_count",
    "neighbour_count_a",
    "neighbour_count_b",
    "shared_neighbour_count",
    "neighbour_recall_a_in_b",
    "neighbour_recall_b_in_a",
    "neighbour_jaccard",
    "per_sentinel_jaccard_mean",
    "per_sentinel_jaccard_median",
    "per_sentinel_jaccard_minimum",
)


class AnalysisError(RuntimeError):
    """Raised when inputs or analysis state violate the workflow contract."""


@dataclass(frozen=True)
class MembershipInput:
    """Describe one retained cluster-membership table.

    Attributes:
        method_id: Stable benchmark case identifier.
        display_name: Short plot label.
        repeat: Benchmark repeat number.
        path: Absolute membership-table path.
        manifest_path: Optional case-manifest path.
        sha256: Optional checksum recovered from the case manifest.
    """

    method_id: str
    display_name: str
    repeat: int
    path: Path
    manifest_path: Optional[Path] = None
    sha256: Optional[str] = None

    def signature(self) -> Dict[str, Any]:
        """Return stable metadata used to validate cached comparisons."""

        stat = self.path.stat()
        return {
            "method_id": self.method_id,
            "repeat": self.repeat,
            "path": str(self.path),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": self.sha256 or "",
        }


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse the named command-line interface.

    Args:
        argv: Optional argument sequence for testing.

    Returns:
        Parsed command-line namespace.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Calculate all-against-all similarity, split/merge and E3 "
            "sentinel metrics for retained DIAMOND membership tables."
        )
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--sentinel-ids-tsv", type=Path)
    parser.add_argument("--quality-repeat", type=int)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--memory-limit", default="200GB")
    parser.add_argument("--temporary-directory", default="auto")
    parser.add_argument(
        "--small-file-limit-bytes",
        type=int,
        default=64 * 1024 * 1024,
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=("png", "pdf"),
        default=("png", "pdf"),
    )
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser.parse_args(argv)


def configure_logging(level: str, log_path: Optional[Path] = None) -> None:
    """Configure console logging and an optional persistent log file.

    Args:
        level: Standard logging level name.
        log_path: Optional file receiving the same messages as stderr.
    """

    handlers: List[logging.Handler] = [logging.StreamHandler()]
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


def _require_positive(value: int, label: str) -> None:
    """Raise a clear error when an integer option is not positive."""

    if value < 1:
        raise AnalysisError(f"{label} must be a positive integer")


def validate_memory_limit(value: str) -> str:
    """Validate and normalise a DuckDB memory-limit string.

    Args:
        value: Value such as ``200GB`` or ``1.5TB``.

    Returns:
        Upper-case, whitespace-free memory limit.

    Raises:
        AnalysisError: If the value is not an explicit storage quantity.
    """

    normalised = value.strip().upper().replace(" ", "")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:KB|MB|GB|TB)", normalised):
        raise AnalysisError(
            "--memory-limit must include KB, MB, GB or TB, for example 200GB"
        )
    return normalised


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML mapping with a clear dependency and schema error.

    Args:
        path: YAML configuration path.

    Returns:
        Top-level configuration mapping.
    """

    source = path.expanduser().resolve()
    if not source.is_file():
        raise AnalysisError(f"Configuration does not exist: {source}")
    try:
        import yaml
    except ImportError as error:
        raise AnalysisError("PyYAML is required to read --config") from error
    with source.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise AnalysisError("Configuration must contain a top-level mapping")
    return payload


def _resolve_config_path(value: Any, config_path: Path) -> Optional[Path]:
    """Resolve an optional configuration path relative to its YAML file."""

    if value in (None, ""):
        return None
    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    return candidate.resolve()


def display_name(case: Mapping[str, Any]) -> str:
    """Create a compact, deterministic label from a benchmark case.

    Args:
        case: Case mapping from the benchmark configuration.

    Returns:
        Human-readable method label suitable for figure axes.
    """

    version = str(case.get("expected_version", "unknown"))
    command_value = str(case.get("command", "cluster")).lower()
    command = {
        "deepclust": "DeepClust",
        "linclust": "LinClust",
    }.get(command_value, command_value)
    identity = str(case.get("identity_mode", "unknown"))
    label = f"{version} {command} {identity}"
    steps = case.get("cluster_steps") or []
    if steps:
        label += " fast-final"
    return label


def _manifest_checksum(manifest_path: Path) -> Optional[str]:
    """Recover the retained membership checksum from a case manifest."""

    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Could not read case manifest: %s", manifest_path)
        return None
    summary = payload.get("membership_summary", {})
    value = summary.get("membership_sha256")
    if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return value.lower()
    return None


def discover_memberships(
    config: Mapping[str, Any],
    config_path: Path,
    run_root: Path,
    quality_repeat_override: Optional[int] = None,
) -> Tuple[List[MembershipInput], List[MembershipInput], Optional[Path]]:
    """Discover quality-repeat and any additional retained memberships.

    Args:
        config: Parsed benchmark configuration.
        config_path: Resolved configuration path.
        run_root: Existing benchmark result root.
        quality_repeat_override: Optional repeat selected on the command line.

    Returns:
        Quality inputs, every retained input and configured sentinel path.

    Raises:
        AnalysisError: If configuration cases or required memberships are
            absent.
    """

    benchmark = config.get("benchmark")
    if not isinstance(benchmark, dict):
        raise AnalysisError("Configuration is missing benchmark mapping")
    cases = benchmark.get("cases")
    if not isinstance(cases, list) or len(cases) < 2:
        raise AnalysisError("At least two benchmark cases are required")
    quality_repeat = quality_repeat_override or int(
        benchmark.get("quality_repeat", 1)
    )
    _require_positive(quality_repeat, "quality repeat")
    all_inputs: List[MembershipInput] = []
    quality_inputs: List[MembershipInput] = []
    seen_ids: Set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or not case.get("case_id"):
            raise AnalysisError("Every benchmark case requires case_id")
        case_id = str(case["case_id"])
        if case_id in seen_ids:
            raise AnalysisError(f"Duplicate benchmark case_id: {case_id}")
        seen_ids.add(case_id)
        case_root = run_root / "cases" / case_id
        retained_for_case: List[MembershipInput] = []
        if case_root.is_dir():
            for repeat_root in sorted(case_root.glob("repeat_*")):
                match = re.fullmatch(r"repeat_([0-9]+)", repeat_root.name)
                if not match:
                    continue
                repeat = int(match.group(1))
                candidates = [
                    repeat_root / "clusters.tsv",
                    repeat_root / "clusters.tsv.gz",
                ]
                membership = next((item for item in candidates if item.is_file()), None)
                if membership is None:
                    continue
                manifest = repeat_root / "case_manifest.json"
                retained_for_case.append(
                    MembershipInput(
                        method_id=case_id,
                        display_name=display_name(case),
                        repeat=repeat,
                        path=membership.resolve(),
                        manifest_path=manifest if manifest.is_file() else None,
                        sha256=_manifest_checksum(manifest),
                    )
                )
        quality_matches = [
            item for item in retained_for_case if item.repeat == quality_repeat
        ]
        if len(quality_matches) != 1:
            expected = case_root / f"repeat_{quality_repeat}" / "clusters.tsv"
            raise AnalysisError(
                f"Expected one quality membership for {case_id}: {expected}"
            )
        quality_inputs.append(quality_matches[0])
        all_inputs.extend(retained_for_case)
    inputs = config.get("inputs", {})
    sentinel = None
    if isinstance(inputs, dict):
        sentinel = _resolve_config_path(inputs.get("sentinel_ids_tsv"), config_path)
    return quality_inputs, all_inputs, sentinel


def _open_text(path: Path):
    """Open a plain or gzip-compressed membership table as text."""

    if path.suffix.lower() == ".gz":
        import gzip

        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def membership_header(path: Path) -> Tuple[str, str]:
    """Read and validate a two-column membership-table header."""

    if not path.is_file():
        raise AnalysisError(f"Membership table does not exist: {path}")
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            header = tuple(next(reader))
        except StopIteration as error:
            raise AnalysisError(f"Membership table is empty: {path}") from error
    if header not in MEMBERSHIP_HEADERS:
        raise AnalysisError(f"Unrecognised membership header in {path}: {header}")
    return header


def load_mapping(path: Path) -> Dict[str, str]:
    """Load and validate a small membership table into memory.

    Args:
        path: Membership table accepted by :func:`membership_header`.

    Returns:
        Mapping from member identifier to cluster identifier.
    """

    expected = membership_header(path)
    mapping: Dict[str, str] = {}
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter="\t")
        if tuple(next(reader)) != expected:
            raise AnalysisError(f"Membership header changed while reading: {path}")
        for line_number, row in enumerate(reader, start=2):
            if len(row) != 2 or not row[0] or not row[1]:
                raise AnalysisError(f"Invalid membership row at {path}:{line_number}")
            if row[1] in mapping:
                raise AnalysisError(f"Duplicate member in {path}: {row[1]}")
            mapping[row[1]] = row[0]
    if not mapping:
        raise AnalysisError(f"Membership table has no data rows: {path}")
    return mapping


def read_sentinels(path: Optional[Path]) -> Set[str]:
    """Read a headered sentinel TSV containing ``sequence_id``."""

    if path is None:
        return set()
    source = path.expanduser().resolve()
    if not source.is_file():
        raise AnalysisError(f"Sentinel TSV does not exist: {source}")
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not reader.fieldnames or "sequence_id" not in reader.fieldnames:
            raise AnalysisError("Sentinel TSV must contain a sequence_id column")
        values = {str(row.get("sequence_id", "")).strip() for row in reader}
    values.discard("")
    if not values:
        raise AnalysisError("Sentinel TSV contains no sequence identifiers")
    return values


def combination_two(value: int) -> int:
    """Return the number of unordered pairs among ``value`` items."""

    return value * (value - 1) // 2


def percentile(values: Sequence[float], probability: float) -> float:
    """Calculate a linearly interpolated percentile without NumPy."""

    if not values:
        raise AnalysisError("Cannot calculate a percentile of no values")
    if probability < 0.0 or probability > 1.0:
        raise AnalysisError("Percentile probability must be between zero and one")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def cluster_summary_from_counts(
    membership: MembershipInput,
    counts: Mapping[str, int],
) -> Dict[str, Any]:
    """Create structural cluster-size metrics from cluster counts."""

    sizes = list(counts.values())
    member_count = sum(sizes)
    cluster_count = len(sizes)
    singleton_count = sum(value == 1 for value in sizes)
    return {
        "method_id": membership.method_id,
        "display_name": membership.display_name,
        "repeat": membership.repeat,
        "membership_path": str(membership.path),
        "membership_sha256": membership.sha256 or "",
        "member_count": member_count,
        "cluster_count": cluster_count,
        "singleton_cluster_count": singleton_count,
        "singleton_cluster_fraction": singleton_count / cluster_count,
        "mean_cluster_size": member_count / cluster_count,
        "median_cluster_size": percentile(sizes, 0.5),
        "cluster_size_p25": percentile(sizes, 0.25),
        "cluster_size_p75": percentile(sizes, 0.75),
        "cluster_size_p90": percentile(sizes, 0.90),
        "cluster_size_p95": percentile(sizes, 0.95),
        "cluster_size_p99": percentile(sizes, 0.99),
        "largest_cluster_size": max(sizes),
    }


def _entropy(counts: Iterable[int], total: int) -> float:
    """Calculate natural-log entropy from positive category counts."""

    return -sum(
        (value / total) * math.log(value / total)
        for value in counts
        if value > 0
    )


def _size_bin(size: int) -> str:
    """Return the declared cluster-size stratum for ``size``."""

    for label, minimum, maximum in SIZE_BINS:
        if size >= minimum and (maximum is None or size <= maximum):
            return label
    raise AnalysisError(f"Could not assign size bin for cluster size {size}")


def _best_match_rows(
    source_id: str,
    target_id: str,
    source_counts: Mapping[str, int],
    target_counts: Mapping[str, int],
    contingency: Mapping[Tuple[str, str], int],
    reverse: bool = False,
) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
    """Calculate best-overlap Jaccard statistics in one direction."""

    best: Dict[str, float] = {cluster: 0.0 for cluster in source_counts}
    overlaps: Counter[str] = Counter()
    for (cluster_a, cluster_b), intersection in contingency.items():
        source = cluster_b if reverse else cluster_a
        target = cluster_a if reverse else cluster_b
        source_n = source_counts[source]
        target_n = target_counts[target]
        union = source_n + target_n - intersection
        score = intersection / union if union else 1.0
        best[source] = max(best[source], score)
        overlaps[source] += 1
    values = list(best.values())
    total_members = sum(source_counts.values())
    summary = {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "weighted_mean": sum(
            best[cluster] * size for cluster, size in source_counts.items()
        )
        / total_members,
        "split_count": sum(value > 1 for value in overlaps.values()),
        "split_fraction": sum(value > 1 for value in overlaps.values())
        / len(source_counts),
        "split_members": sum(
            source_counts[cluster]
            for cluster, value in overlaps.items()
            if value > 1
        ),
    }
    strata: Dict[str, List[Tuple[float, int]]] = defaultdict(list)
    for cluster, score in best.items():
        size = source_counts[cluster]
        strata[_size_bin(size)].append((score, size))
    rows: List[Dict[str, Any]] = []
    for label, _minimum, _maximum in SIZE_BINS:
        entries = strata.get(label, [])
        if not entries:
            continue
        scores = [entry[0] for entry in entries]
        members = sum(entry[1] for entry in entries)
        rows.append(
            {
                "source_method": source_id,
                "target_method": target_id,
                "source_size_bin": label,
                "source_cluster_count": len(entries),
                "source_member_count": members,
                "best_match_jaccard_mean": statistics.fmean(scores),
                "best_match_jaccard_median": statistics.median(scores),
                "best_match_jaccard_weighted_mean": sum(
                    score * size for score, size in entries
                )
                / members,
            }
        )
    return summary, rows


def _sentinel_metrics_small(
    method_a: MembershipInput,
    method_b: MembershipInput,
    mapping_a: Mapping[str, str],
    mapping_b: Mapping[str, str],
    counts_a: Mapping[str, int],
    counts_b: Mapping[str, int],
    contingency: Mapping[Tuple[str, str], int],
    sentinels: Set[str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Calculate aggregate and per-sentinel neighbourhood agreement."""

    if not sentinels:
        return {}, []
    matched = sorted(sentinels.intersection(mapping_a).intersection(mapping_b))
    if not matched:
        raise AnalysisError("No sentinel identifier matched both memberships")
    clusters_a = {mapping_a[value] for value in matched}
    clusters_b = {mapping_b[value] for value in matched}
    neighbours_a = {
        member for member, cluster in mapping_a.items() if cluster in clusters_a
    }
    neighbours_b = {
        member for member, cluster in mapping_b.items() if cluster in clusters_b
    }
    shared = len(neighbours_a.intersection(neighbours_b))
    union = len(neighbours_a.union(neighbours_b))
    detail: List[Dict[str, Any]] = []
    per_scores: List[float] = []
    for sentinel in matched:
        cluster_a = mapping_a[sentinel]
        cluster_b = mapping_b[sentinel]
        intersection = contingency[(cluster_a, cluster_b)]
        size_a = counts_a[cluster_a]
        size_b = counts_b[cluster_b]
        sentinel_union = size_a + size_b - intersection
        score = intersection / sentinel_union if sentinel_union else 1.0
        per_scores.append(score)
        detail.append(
            {
                "method_a": method_a.method_id,
                "method_b": method_b.method_id,
                "repeat_a": method_a.repeat,
                "repeat_b": method_b.repeat,
                "sequence_id": sentinel,
                "cluster_a": cluster_a,
                "cluster_b": cluster_b,
                "neighbour_count_a": size_a,
                "neighbour_count_b": size_b,
                "shared_neighbour_count": intersection,
                "neighbour_jaccard": score,
            }
        )
    aggregate = {
        "method_a": method_a.method_id,
        "method_b": method_b.method_id,
        "repeat_a": method_a.repeat,
        "repeat_b": method_b.repeat,
        "sentinel_count": len(sentinels),
        "matched_sentinel_count": len(matched),
        "neighbour_count_a": len(neighbours_a),
        "neighbour_count_b": len(neighbours_b),
        "shared_neighbour_count": shared,
        "neighbour_recall_a_in_b": shared / len(neighbours_a),
        "neighbour_recall_b_in_a": shared / len(neighbours_b),
        "neighbour_jaccard": shared / union if union else 1.0,
        "per_sentinel_jaccard_mean": statistics.fmean(per_scores),
        "per_sentinel_jaccard_median": statistics.median(per_scores),
        "per_sentinel_jaccard_minimum": min(per_scores),
    }
    return aggregate, detail


def compare_mappings(
    method_a: MembershipInput,
    method_b: MembershipInput,
    mapping_a: Mapping[str, str],
    mapping_b: Mapping[str, str],
    sentinels: Set[str],
) -> Dict[str, Any]:
    """Calculate all metrics for two small in-memory memberships."""

    members_a = set(mapping_a)
    members_b = set(mapping_b)
    if members_a != members_b:
        raise AnalysisError(
            "Membership identifier sets differ: "
            f"missing={len(members_a - members_b)}, "
            f"extra={len(members_b - members_a)}"
        )
    member_count = len(mapping_a)
    counts_a = Counter(mapping_a.values())
    counts_b = Counter(mapping_b.values())
    contingency = Counter(
        (mapping_a[member], mapping_b[member]) for member in mapping_a
    )
    pairs_a = sum(combination_two(value) for value in counts_a.values())
    pairs_b = sum(combination_two(value) for value in counts_b.values())
    shared_pairs = sum(
        combination_two(value) for value in contingency.values()
    )
    recall_a = shared_pairs / pairs_a if pairs_a else 1.0
    recall_b = shared_pairs / pairs_b if pairs_b else 1.0
    pair_f1 = (
        2.0 * recall_a * recall_b / (recall_a + recall_b)
        if recall_a + recall_b
        else 0.0
    )
    pair_union = pairs_a + pairs_b - shared_pairs
    pair_jaccard = shared_pairs / pair_union if pair_union else 1.0
    all_pairs = combination_two(member_count)
    expected = pairs_a * pairs_b / all_pairs if all_pairs else 0.0
    maximum = 0.5 * (pairs_a + pairs_b)
    adjusted_rand = (
        (shared_pairs - expected) / (maximum - expected)
        if maximum != expected
        else 1.0
    )
    entropy_a = _entropy(counts_a.values(), member_count)
    entropy_b = _entropy(counts_b.values(), member_count)
    mutual_information = sum(
        (value / member_count)
        * math.log(
            value
            * member_count
            / (counts_a[cluster_a] * counts_b[cluster_b])
        )
        for (cluster_a, cluster_b), value in contingency.items()
    )
    variation = entropy_a + entropy_b - 2.0 * mutual_information
    variation = max(0.0, variation)
    normalised_variation = (
        variation / math.log(member_count) if member_count > 1 else 0.0
    )
    normalised_variation = min(1.0, max(0.0, normalised_variation))
    normalised_mutual = (
        2.0 * mutual_information / (entropy_a + entropy_b)
        if entropy_a + entropy_b
        else 1.0
    )
    normalised_mutual = min(1.0, max(0.0, normalised_mutual))
    best_a, strata_a = _best_match_rows(
        method_a.method_id,
        method_b.method_id,
        counts_a,
        counts_b,
        contingency,
    )
    best_b, strata_b = _best_match_rows(
        method_b.method_id,
        method_a.method_id,
        counts_b,
        counts_a,
        contingency,
        reverse=True,
    )
    exact_cells = [
        (cluster_a, cluster_b, value)
        for (cluster_a, cluster_b), value in contingency.items()
        if value == counts_a[cluster_a] == counts_b[cluster_b]
    ]
    exact_members = sum(value for _a, _b, value in exact_cells)
    pair_metrics = {
        "method_a": method_a.method_id,
        "method_b": method_b.method_id,
        "repeat_a": method_a.repeat,
        "repeat_b": method_b.repeat,
        "member_count": member_count,
        "cluster_count_a": len(counts_a),
        "cluster_count_b": len(counts_b),
        "same_cluster_pairs_a": pairs_a,
        "same_cluster_pairs_b": pairs_b,
        "shared_same_cluster_pairs": shared_pairs,
        "pair_recall_a_in_b": recall_a,
        "pair_recall_b_in_a": recall_b,
        "pairwise_f1": pair_f1,
        "pairwise_jaccard": pair_jaccard,
        "adjusted_rand_index": adjusted_rand,
        "normalised_mutual_information": normalised_mutual,
        "variation_of_information": variation,
        "normalised_variation_of_information": normalised_variation,
        "exact_match_cluster_count": len(exact_cells),
        "exact_match_member_count": exact_members,
        "exact_match_member_fraction": exact_members / member_count,
        "split_cluster_count_a_to_b": best_a["split_count"],
        "split_cluster_fraction_a_to_b": best_a["split_fraction"],
        "members_in_split_clusters_a_to_b": best_a["split_members"],
        "member_fraction_in_split_clusters_a_to_b": (
            best_a["split_members"] / member_count
        ),
        "split_cluster_count_b_to_a": best_b["split_count"],
        "split_cluster_fraction_b_to_a": best_b["split_fraction"],
        "members_in_split_clusters_b_to_a": best_b["split_members"],
        "member_fraction_in_split_clusters_b_to_a": (
            best_b["split_members"] / member_count
        ),
        "best_match_jaccard_mean_a_to_b": best_a["mean"],
        "best_match_jaccard_median_a_to_b": best_a["median"],
        "best_match_jaccard_weighted_mean_a_to_b": best_a["weighted_mean"],
        "best_match_jaccard_mean_b_to_a": best_b["mean"],
        "best_match_jaccard_median_b_to_a": best_b["median"],
        "best_match_jaccard_weighted_mean_b_to_a": best_b["weighted_mean"],
    }
    sentinel_metrics, sentinel_detail = _sentinel_metrics_small(
        method_a,
        method_b,
        mapping_a,
        mapping_b,
        counts_a,
        counts_b,
        contingency,
        sentinels,
    )
    for row in strata_a + strata_b:
        row["repeat_source"] = (
            method_a.repeat
            if row["source_method"] == method_a.method_id
            else method_b.repeat
        )
        row["repeat_target"] = (
            method_b.repeat
            if row["target_method"] == method_b.method_id
            else method_a.repeat
        )
    return {
        "pair_metrics": pair_metrics,
        "sentinel_metrics": sentinel_metrics,
        "sentinel_detail": sentinel_detail,
        "size_stratified": strata_a + strata_b,
    }


def _sql_path(path: Path) -> str:
    """Escape an absolute filesystem path for a DuckDB SQL literal."""

    return str(path.expanduser().resolve()).replace("'", "''")


def _sql_text(value: str) -> str:
    """Escape a short string for a DuckDB SQL literal."""

    return value.replace("'", "''")


def duckdb_view_sql(path: Path, view_name: str) -> str:
    """Build a normalised DuckDB view for a membership table."""

    representative, member = membership_header(path)
    return f"""
        CREATE VIEW {view_name} AS
        SELECT
            \"{representative}\" AS centroid,
            \"{member}\" AS member
        FROM read_csv(
            '{_sql_path(path)}', delim='\\t', header=true, all_varchar=true
        )
    """


@contextmanager
def duckdb_connection(
    working_directory: Path,
    threads: int,
    memory_limit: str,
) -> Iterator[Any]:
    """Yield an isolated DuckDB connection with bounded resources."""

    try:
        import duckdb
    except ImportError as error:
        raise AnalysisError(
            "DuckDB is required for large memberships; activate e3_discovery"
        ) from error
    working_directory.mkdir(parents=True, exist_ok=True)
    database = working_directory / "comparison.duckdb"
    spill = working_directory / "spill"
    spill.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database))
    try:
        connection.execute(f"SET threads = {threads}")
        connection.execute("SET preserve_insertion_order = false")
        connection.execute(
            f"SET memory_limit = '{_sql_text(memory_limit)}'"
        )
        connection.execute(
            f"SET temp_directory = '{_sql_path(spill)}'"
        )
        yield connection
    finally:
        connection.close()


def _duckdb_method_summary(
    membership: MembershipInput,
    working_directory: Path,
    threads: int,
    memory_limit: str,
) -> Dict[str, Any]:
    """Summarise one large membership table with DuckDB."""

    with duckdb_connection(working_directory, threads, memory_limit) as connection:
        connection.execute(duckdb_view_sql(membership.path, "membership"))
        audit = connection.execute(
            """
            SELECT count(*)::BIGINT, count(DISTINCT member)::BIGINT
            FROM membership
            """
        ).fetchone()
        if audit[0] == 0:
            raise AnalysisError(f"Membership has no data rows: {membership.path}")
        if audit[0] != audit[1]:
            raise AnalysisError(
                f"Membership contains duplicate members: {membership.path}"
            )
        row = connection.execute(
            """
            WITH sizes AS (
                SELECT centroid, count(*)::BIGINT AS n
                FROM membership
                GROUP BY centroid
            )
            SELECT
                sum(n)::BIGINT,
                count(*)::BIGINT,
                count(*) FILTER (WHERE n = 1)::BIGINT,
                avg(n)::DOUBLE,
                quantile_cont(n, 0.50)::DOUBLE,
                quantile_cont(n, 0.25)::DOUBLE,
                quantile_cont(n, 0.75)::DOUBLE,
                quantile_cont(n, 0.90)::DOUBLE,
                quantile_cont(n, 0.95)::DOUBLE,
                quantile_cont(n, 0.99)::DOUBLE,
                max(n)::BIGINT
            FROM sizes
            """
        ).fetchone()
    members, clusters, singletons, mean, median, p25, p75, p90, p95, p99, largest = row
    return {
        "method_id": membership.method_id,
        "display_name": membership.display_name,
        "repeat": membership.repeat,
        "membership_path": str(membership.path),
        "membership_sha256": membership.sha256 or "",
        "member_count": members,
        "cluster_count": clusters,
        "singleton_cluster_count": singletons,
        "singleton_cluster_fraction": singletons / clusters,
        "mean_cluster_size": mean,
        "median_cluster_size": median,
        "cluster_size_p25": p25,
        "cluster_size_p75": p75,
        "cluster_size_p90": p90,
        "cluster_size_p95": p95,
        "cluster_size_p99": p99,
        "largest_cluster_size": largest,
    }


def summarise_membership(
    membership: MembershipInput,
    working_directory: Path,
    threads: int,
    memory_limit: str,
    small_file_limit_bytes: int,
) -> Dict[str, Any]:
    """Summarise a membership using Python or bounded-memory DuckDB."""

    if membership.path.stat().st_size <= small_file_limit_bytes:
        mapping = load_mapping(membership.path)
        return cluster_summary_from_counts(
            membership,
            Counter(mapping.values()),
        )
    if working_directory.exists():
        shutil.rmtree(working_directory)
    working_directory.mkdir(parents=True)
    try:
        return _duckdb_method_summary(
            membership,
            working_directory,
            threads,
            memory_limit,
        )
    finally:
        shutil.rmtree(working_directory, ignore_errors=True)


def _duckdb_pair_metrics(
    connection: Any,
    method_a: MembershipInput,
    method_b: MembershipInput,
) -> Dict[str, Any]:
    """Calculate global partition metrics from materialised contingencies."""

    row = connection.execute(
        """
        WITH totals AS (
            SELECT sum(n)::DOUBLE AS total FROM a_counts
        ),
        base AS (
            SELECT
                (SELECT total FROM totals) AS member_count,
                (SELECT count(*) FROM a_counts) AS clusters_a,
                (SELECT count(*) FROM b_counts) AS clusters_b,
                (SELECT coalesce(sum(n * (n - 1) / 2), 0)
                 FROM a_counts) AS pairs_a,
                (SELECT coalesce(sum(n * (n - 1) / 2), 0)
                 FROM b_counts) AS pairs_b,
                (SELECT coalesce(sum(n * (n - 1) / 2), 0)
                 FROM cells) AS shared_pairs,
                (SELECT -sum((n / (SELECT total FROM totals)) *
                             ln(n / (SELECT total FROM totals)))
                 FROM a_counts) AS entropy_a,
                (SELECT -sum((n / (SELECT total FROM totals)) *
                             ln(n / (SELECT total FROM totals)))
                 FROM b_counts) AS entropy_b,
                (
                    SELECT sum(
                        (c.n / (SELECT total FROM totals)) *
                        ln(c.n * (SELECT total FROM totals) / (a.n * b.n))
                    )
                    FROM cells c
                    JOIN a_counts a USING (a_cluster)
                    JOIN b_counts b USING (b_cluster)
                ) AS mutual_information
        )
        SELECT * FROM base
        """
    ).fetchone()
    (
        member_count_raw,
        clusters_a,
        clusters_b,
        pairs_a_raw,
        pairs_b_raw,
        shared_pairs_raw,
        entropy_a,
        entropy_b,
        mutual_information,
    ) = row
    member_count = int(member_count_raw)
    pairs_a = int(pairs_a_raw)
    pairs_b = int(pairs_b_raw)
    shared_pairs = int(shared_pairs_raw)
    recall_a = shared_pairs / pairs_a if pairs_a else 1.0
    recall_b = shared_pairs / pairs_b if pairs_b else 1.0
    pair_f1 = (
        2.0 * recall_a * recall_b / (recall_a + recall_b)
        if recall_a + recall_b
        else 0.0
    )
    pair_union = pairs_a + pairs_b - shared_pairs
    all_pairs = combination_two(member_count)
    expected = pairs_a * pairs_b / all_pairs if all_pairs else 0.0
    maximum = 0.5 * (pairs_a + pairs_b)
    adjusted_rand = (
        (shared_pairs - expected) / (maximum - expected)
        if maximum != expected
        else 1.0
    )
    variation = max(
        0.0,
        float(entropy_a + entropy_b - 2.0 * mutual_information),
    )
    normalised_variation = (
        variation / math.log(member_count) if member_count > 1 else 0.0
    )
    normalised_variation = min(1.0, max(0.0, normalised_variation))
    normalised_mutual = (
        2.0 * mutual_information / (entropy_a + entropy_b)
        if entropy_a + entropy_b
        else 1.0
    )
    normalised_mutual = min(1.0, max(0.0, normalised_mutual))
    exact_clusters, exact_members = connection.execute(
        """
        SELECT count(*)::BIGINT, coalesce(sum(c.n), 0)::BIGINT
        FROM cells c
        JOIN a_counts a USING (a_cluster)
        JOIN b_counts b USING (b_cluster)
        WHERE c.n = a.n AND c.n = b.n
        """
    ).fetchone()
    directional = {}
    for source in ("a", "b"):
        target = "b" if source == "a" else "a"
        source_cluster = f"{source}_cluster"
        target_cluster = f"{target}_cluster"
        connection.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE {source}_best AS
            SELECT
                c.{source_cluster} AS source_cluster,
                s.n AS source_n,
                count(*)::BIGINT AS overlap_count,
                max(c.n::DOUBLE / (s.n + t.n - c.n)) AS best_jaccard
            FROM cells c
            JOIN {source}_counts s
              ON c.{source_cluster} = s.{source_cluster}
            JOIN {target}_counts t
              ON c.{target_cluster} = t.{target_cluster}
            GROUP BY c.{source_cluster}, s.n
            """
        )
        directional[source] = connection.execute(
            f"""
            SELECT
                avg(best_jaccard)::DOUBLE,
                median(best_jaccard)::DOUBLE,
                sum(best_jaccard * source_n) /
                    sum(source_n)::DOUBLE,
                count(*) FILTER (WHERE overlap_count > 1)::BIGINT,
                count(*) FILTER (WHERE overlap_count > 1) /
                    count(*)::DOUBLE,
                coalesce(sum(source_n) FILTER
                    (WHERE overlap_count > 1), 0)::BIGINT
            FROM {source}_best
            """
        ).fetchone()
    a_best = directional["a"]
    b_best = directional["b"]
    return {
        "method_a": method_a.method_id,
        "method_b": method_b.method_id,
        "repeat_a": method_a.repeat,
        "repeat_b": method_b.repeat,
        "member_count": member_count,
        "cluster_count_a": clusters_a,
        "cluster_count_b": clusters_b,
        "same_cluster_pairs_a": pairs_a,
        "same_cluster_pairs_b": pairs_b,
        "shared_same_cluster_pairs": shared_pairs,
        "pair_recall_a_in_b": recall_a,
        "pair_recall_b_in_a": recall_b,
        "pairwise_f1": pair_f1,
        "pairwise_jaccard": shared_pairs / pair_union if pair_union else 1.0,
        "adjusted_rand_index": adjusted_rand,
        "normalised_mutual_information": normalised_mutual,
        "variation_of_information": variation,
        "normalised_variation_of_information": normalised_variation,
        "exact_match_cluster_count": exact_clusters,
        "exact_match_member_count": exact_members,
        "exact_match_member_fraction": exact_members / member_count,
        "split_cluster_count_a_to_b": a_best[3],
        "split_cluster_fraction_a_to_b": a_best[4],
        "members_in_split_clusters_a_to_b": a_best[5],
        "member_fraction_in_split_clusters_a_to_b": a_best[5] / member_count,
        "split_cluster_count_b_to_a": b_best[3],
        "split_cluster_fraction_b_to_a": b_best[4],
        "members_in_split_clusters_b_to_a": b_best[5],
        "member_fraction_in_split_clusters_b_to_a": b_best[5] / member_count,
        "best_match_jaccard_mean_a_to_b": a_best[0],
        "best_match_jaccard_median_a_to_b": a_best[1],
        "best_match_jaccard_weighted_mean_a_to_b": a_best[2],
        "best_match_jaccard_mean_b_to_a": b_best[0],
        "best_match_jaccard_median_b_to_a": b_best[1],
        "best_match_jaccard_weighted_mean_b_to_a": b_best[2],
    }


def _duckdb_size_stratified(
    connection: Any,
    method_a: MembershipInput,
    method_b: MembershipInput,
) -> List[Dict[str, Any]]:
    """Return directional best-match metrics stratified by source size."""

    rows: List[Dict[str, Any]] = []
    for source, source_method, target_method in (
        ("a", method_a, method_b),
        ("b", method_b, method_a),
    ):
        result = connection.execute(
            f"""
            SELECT
                CASE
                    WHEN source_n = 1 THEN 'singleton'
                    WHEN source_n <= 5 THEN '2-5'
                    WHEN source_n <= 20 THEN '6-20'
                    WHEN source_n <= 100 THEN '21-100'
                    WHEN source_n <= 1000 THEN '101-1000'
                    ELSE '>1000'
                END AS size_bin,
                count(*)::BIGINT,
                sum(source_n)::BIGINT,
                avg(best_jaccard)::DOUBLE,
                median(best_jaccard)::DOUBLE,
                sum(best_jaccard * source_n) / sum(source_n)::DOUBLE
            FROM {source}_best
            GROUP BY size_bin
            """
        ).fetchall()
        order = {label: index for index, (label, _low, _high) in enumerate(SIZE_BINS)}
        for row in sorted(result, key=lambda item: order[item[0]]):
            rows.append(
                {
                    "source_method": source_method.method_id,
                    "target_method": target_method.method_id,
                    "repeat_source": source_method.repeat,
                    "repeat_target": target_method.repeat,
                    "source_size_bin": row[0],
                    "source_cluster_count": row[1],
                    "source_member_count": row[2],
                    "best_match_jaccard_mean": row[3],
                    "best_match_jaccard_median": row[4],
                    "best_match_jaccard_weighted_mean": row[5],
                }
            )
    return rows


def _duckdb_sentinel_metrics(
    connection: Any,
    method_a: MembershipInput,
    method_b: MembershipInput,
    sentinels: Set[str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Calculate aggregate and per-sentinel metrics from contingency tables."""

    if not sentinels:
        return {}, []
    connection.execute(
        "CREATE TEMP TABLE sentinels(sequence_id VARCHAR PRIMARY KEY)"
    )
    connection.executemany(
        "INSERT INTO sentinels VALUES (?)",
        [(value,) for value in sorted(sentinels)],
    )
    connection.execute(
        """
        CREATE TEMP TABLE matched_sentinels AS
        SELECT
            s.sequence_id,
            a.centroid AS a_cluster,
            b.centroid AS b_cluster
        FROM sentinels s
        JOIN membership_a a ON a.member = s.sequence_id
        JOIN membership_b b ON b.member = s.sequence_id
        """
    )
    matched = connection.execute(
        "SELECT count(*)::BIGINT FROM matched_sentinels"
    ).fetchone()[0]
    if matched == 0:
        raise AnalysisError("No sentinel identifier matched both memberships")
    detail_rows = connection.execute(
        """
        SELECT
            m.sequence_id,
            m.a_cluster,
            m.b_cluster,
            a.n AS size_a,
            b.n AS size_b,
            c.n AS shared,
            c.n::DOUBLE / (a.n + b.n - c.n) AS jaccard
        FROM matched_sentinels m
        JOIN a_counts a USING (a_cluster)
        JOIN b_counts b USING (b_cluster)
        JOIN cells c USING (a_cluster, b_cluster)
        ORDER BY m.sequence_id
        """
    ).fetchall()
    detail = [
        {
            "method_a": method_a.method_id,
            "method_b": method_b.method_id,
            "repeat_a": method_a.repeat,
            "repeat_b": method_b.repeat,
            "sequence_id": row[0],
            "cluster_a": row[1],
            "cluster_b": row[2],
            "neighbour_count_a": row[3],
            "neighbour_count_b": row[4],
            "shared_neighbour_count": row[5],
            "neighbour_jaccard": row[6],
        }
        for row in detail_rows
    ]
    aggregate_row = connection.execute(
        """
        WITH sentinel_a AS (
            SELECT DISTINCT a_cluster FROM matched_sentinels
        ),
        sentinel_b AS (
            SELECT DISTINCT b_cluster FROM matched_sentinels
        ),
        totals AS (
            SELECT
                (SELECT sum(a.n) FROM a_counts a
                 SEMI JOIN sentinel_a s USING (a_cluster)) AS n_a,
                (SELECT sum(b.n) FROM b_counts b
                 SEMI JOIN sentinel_b s USING (b_cluster)) AS n_b,
                (SELECT sum(c.n) FROM cells c
                 SEMI JOIN sentinel_a sa USING (a_cluster)
                 SEMI JOIN sentinel_b sb USING (b_cluster)) AS shared
        )
        SELECT n_a::BIGINT, n_b::BIGINT, shared::BIGINT FROM totals
        """
    ).fetchone()
    n_a, n_b, shared = aggregate_row
    union = n_a + n_b - shared
    scores = [float(row[6]) for row in detail_rows]
    aggregate = {
        "method_a": method_a.method_id,
        "method_b": method_b.method_id,
        "repeat_a": method_a.repeat,
        "repeat_b": method_b.repeat,
        "sentinel_count": len(sentinels),
        "matched_sentinel_count": matched,
        "neighbour_count_a": n_a,
        "neighbour_count_b": n_b,
        "shared_neighbour_count": shared,
        "neighbour_recall_a_in_b": shared / n_a if n_a else 1.0,
        "neighbour_recall_b_in_a": shared / n_b if n_b else 1.0,
        "neighbour_jaccard": shared / union if union else 1.0,
        "per_sentinel_jaccard_mean": statistics.fmean(scores),
        "per_sentinel_jaccard_median": statistics.median(scores),
        "per_sentinel_jaccard_minimum": min(scores),
    }
    return aggregate, detail


def compare_large_memberships(
    method_a: MembershipInput,
    method_b: MembershipInput,
    sentinels: Set[str],
    working_directory: Path,
    threads: int,
    memory_limit: str,
) -> Dict[str, Any]:
    """Compare two large membership tables with staged DuckDB queries."""

    with duckdb_connection(working_directory, threads, memory_limit) as connection:
        connection.execute(duckdb_view_sql(method_a.path, "membership_a"))
        connection.execute(duckdb_view_sql(method_b.path, "membership_b"))
        audit = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM membership_a),
                (SELECT count(DISTINCT member) FROM membership_a),
                (SELECT count(*) FROM membership_b),
                (SELECT count(DISTINCT member) FROM membership_b),
                (SELECT count(*) FROM membership_a a
                 ANTI JOIN membership_b b USING (member)),
                (SELECT count(*) FROM membership_b b
                 ANTI JOIN membership_a a USING (member))
            """
        ).fetchone()
        if audit[0] != audit[1] or audit[2] != audit[3]:
            raise AnalysisError("A membership table contains duplicate members")
        if audit[4] or audit[5] or audit[0] != audit[2]:
            raise AnalysisError(
                "Membership identifier sets differ: "
                f"missing={audit[4]}, extra={audit[5]}"
            )
        connection.execute(
            """
            CREATE TEMP TABLE a_counts AS
            SELECT centroid AS a_cluster, count(*)::BIGINT AS n
            FROM membership_a GROUP BY centroid
            """
        )
        connection.execute(
            """
            CREATE TEMP TABLE b_counts AS
            SELECT centroid AS b_cluster, count(*)::BIGINT AS n
            FROM membership_b GROUP BY centroid
            """
        )
        connection.execute(
            """
            CREATE TEMP TABLE cells AS
            SELECT
                a.centroid AS a_cluster,
                b.centroid AS b_cluster,
                count(*)::BIGINT AS n
            FROM membership_a a
            JOIN membership_b b USING (member)
            GROUP BY a.centroid, b.centroid
            """
        )
        pair_metrics = _duckdb_pair_metrics(connection, method_a, method_b)
        strata = _duckdb_size_stratified(connection, method_a, method_b)
        sentinel_metrics, sentinel_detail = _duckdb_sentinel_metrics(
            connection,
            method_a,
            method_b,
            sentinels,
        )
    return {
        "pair_metrics": pair_metrics,
        "sentinel_metrics": sentinel_metrics,
        "sentinel_detail": sentinel_detail,
        "size_stratified": strata,
    }


def compare_memberships(
    method_a: MembershipInput,
    method_b: MembershipInput,
    sentinels: Set[str],
    working_directory: Path,
    threads: int,
    memory_limit: str,
    small_file_limit_bytes: int,
) -> Dict[str, Any]:
    """Compare memberships with a small-data or large-data implementation."""

    combined_size = method_a.path.stat().st_size + method_b.path.stat().st_size
    if combined_size <= small_file_limit_bytes:
        return compare_mappings(
            method_a,
            method_b,
            load_mapping(method_a.path),
            load_mapping(method_b.path),
            sentinels,
        )
    return compare_large_memberships(
        method_a,
        method_b,
        sentinels,
        working_directory,
        threads,
        memory_limit,
    )


def _normalise_value(value: Any) -> Any:
    """Convert non-finite and implementation-specific numbers safely."""

    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AnalysisError("A calculated metric is not finite")
        if abs(value) < 1e-15:
            return 0.0
        return value
    return value


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically after validating numeric values."""

    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = json.loads(
        json.dumps(payload, default=str, allow_nan=False)
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(cleaned, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_checkpoint(
    path: Path,
    method_a: MembershipInput,
    method_b: MembershipInput,
    sentinels: Set[str],
) -> Optional[Dict[str, Any]]:
    """Load a pair checkpoint only when both input signatures match."""

    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Ignoring unreadable checkpoint: %s", path)
        return None
    expected = {
        "method_a": method_a.signature(),
        "method_b": method_b.signature(),
        "sentinel_set_sha256": sentinel_set_sha256(sentinels),
        "script_version": SCRIPT_VERSION,
    }
    if payload.get("input_signature") != expected:
        LOGGER.warning("Ignoring stale checkpoint: %s", path)
        return None
    result = payload.get("result")
    return result if isinstance(result, dict) else None


def checkpoint_name(method_a: MembershipInput, method_b: MembershipInput) -> str:
    """Create a safe, deterministic checkpoint filename."""

    raw = (
        f"{method_a.method_id}__r{method_a.repeat}__vs__"
        f"{method_b.method_id}__r{method_b.repeat}"
    )
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)
    return f"{safe}.json"


def sentinel_set_sha256(sentinels: Set[str]) -> str:
    """Hash the sorted sentinel set for checkpoint validation."""

    digest = hashlib.sha256()
    for value in sorted(sentinels):
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def run_comparison_with_checkpoint(
    method_a: MembershipInput,
    method_b: MembershipInput,
    sentinels: Set[str],
    output_directory: Path,
    temporary_root: Path,
    threads: int,
    memory_limit: str,
    small_file_limit_bytes: int,
    resume: bool,
) -> Dict[str, Any]:
    """Run or resume one pair comparison and persist its result."""

    checkpoint = output_directory / "checkpoints" / checkpoint_name(
        method_a,
        method_b,
    )
    if resume:
        cached = load_checkpoint(checkpoint, method_a, method_b, sentinels)
        if cached is not None:
            LOGGER.info(
                "Reusing comparison checkpoint: %s versus %s",
                method_a.method_id,
                method_b.method_id,
            )
            return cached
    pair_key = checkpoint.stem
    pair_work = temporary_root / pair_key
    if pair_work.exists():
        shutil.rmtree(pair_work)
    pair_work.mkdir(parents=True)
    LOGGER.info(
        "Comparing %s repeat %d versus %s repeat %d",
        method_a.method_id,
        method_a.repeat,
        method_b.method_id,
        method_b.repeat,
    )
    started = time.monotonic()
    try:
        result = compare_memberships(
            method_a,
            method_b,
            sentinels,
            pair_work,
            threads,
            memory_limit,
            small_file_limit_bytes,
        )
    finally:
        shutil.rmtree(pair_work, ignore_errors=True)
    result["elapsed_seconds"] = time.monotonic() - started
    atomic_json(
        checkpoint,
        {
            "input_signature": {
                "method_a": method_a.signature(),
                "method_b": method_b.signature(),
                "sentinel_set_sha256": sentinel_set_sha256(sentinels),
                "script_version": SCRIPT_VERSION,
            },
            "result": result,
        },
    )
    return result


def _format_tsv_value(value: Any) -> str:
    """Format a value deterministically for a TSV cell."""

    value = _normalise_value(value)
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.12g}"
    return str(value)


def write_tsv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
) -> None:
    """Write a headered UTF-8 TSV atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            delimiter="\t",
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {field: _format_tsv_value(row.get(field, "")) for field in fields}
            )
    os.replace(temporary, path)


def _matrix(
    method_ids: Sequence[str],
    pair_rows: Sequence[Mapping[str, Any]],
    field: str,
    diagonal: float,
) -> List[List[float]]:
    """Create a symmetric matrix from unordered pair rows."""

    index = {method_id: position for position, method_id in enumerate(method_ids)}
    matrix = [
        [float("nan") for _column in method_ids]
        for _row in method_ids
    ]
    for position in range(len(method_ids)):
        matrix[position][position] = diagonal
    for row in pair_rows:
        if field not in row or row[field] in (None, ""):
            continue
        a = index[str(row["method_a"])]
        b = index[str(row["method_b"])]
        matrix[a][b] = float(row[field])
        matrix[b][a] = float(row[field])
    return matrix


def _directional_matrix(
    method_ids: Sequence[str],
    pair_rows: Sequence[Mapping[str, Any]],
    field_a_to_b: str,
    field_b_to_a: str,
) -> List[List[float]]:
    """Create a directional method-by-method matrix."""

    index = {method_id: position for position, method_id in enumerate(method_ids)}
    matrix = [[0.0 for _column in method_ids] for _row in method_ids]
    for row in pair_rows:
        a = index[str(row["method_a"])]
        b = index[str(row["method_b"])]
        matrix[a][b] = float(row[field_a_to_b])
        matrix[b][a] = float(row[field_b_to_a])
    return matrix


def _plot_dependencies() -> Tuple[Any, Any]:
    """Import plotting dependencies after selecting a non-interactive backend."""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as error:
        raise AnalysisError(
            "matplotlib and numpy are required to create figures"
        ) from error
    return plt, np


def validate_runtime_dependencies(require_duckdb: bool) -> Dict[str, str]:
    """Import every runtime dependency before starting costly comparisons.

    Args:
        require_duckdb: Whether membership sizes require the DuckDB path.

    Returns:
        Dependency version mapping for provenance.
    """

    plt, np = _plot_dependencies()
    try:
        import matplotlib
        import scipy
    except ImportError as error:
        raise AnalysisError(
            "matplotlib, numpy and scipy are required for this analysis"
        ) from error
    versions = {
        "python": sys.version.split()[0],
        "matplotlib": str(matplotlib.__version__),
        "numpy": str(np.__version__),
        "scipy": str(scipy.__version__),
    }
    plt.close("all")
    if require_duckdb:
        try:
            import duckdb
        except ImportError as error:
            raise AnalysisError(
                "DuckDB is required for the production memberships; "
                "activate e3_discovery"
            ) from error
        versions["duckdb"] = str(duckdb.__version__)
    return versions


def save_figure(
    figure: Any,
    stem: Path,
    formats: Sequence[str],
    dpi: int,
) -> None:
    """Save one figure in every requested format."""

    stem.parent.mkdir(parents=True, exist_ok=True)
    for output_format in formats:
        figure.savefig(
            stem.with_suffix(f".{output_format}"),
            dpi=dpi if output_format == "png" else None,
            bbox_inches="tight",
            facecolor="white",
        )


def plot_heatmap(
    matrix: Sequence[Sequence[float]],
    labels: Sequence[str],
    title: str,
    colour_label: str,
    stem: Path,
    formats: Sequence[str],
    dpi: int,
    minimum: float,
    maximum: float,
    higher_is_better: bool = True,
) -> None:
    """Plot an annotated method-similarity heatmap."""

    plt, np = _plot_dependencies()
    data = np.asarray(matrix, dtype=float)
    size = max(7.5, 1.15 * len(labels) + 2.5)
    figure, axis = plt.subplots(figsize=(size, size - 0.5))
    cmap = "viridis" if higher_is_better else "viridis_r"
    image = axis.imshow(data, cmap=cmap, vmin=minimum, vmax=maximum)
    axis.set_xticks(range(len(labels)), labels=labels, rotation=42, ha="right")
    axis.set_yticks(range(len(labels)), labels=labels)
    axis.set_title(title, loc="left", fontweight="bold")
    for row in range(data.shape[0]):
        for column in range(data.shape[1]):
            value = data[row, column]
            if math.isfinite(float(value)):
                span = maximum - minimum
                scaled = (float(value) - minimum) / span if span else 0.5
                colour = "white" if 0.25 < scaled < 0.75 else "black"
                axis.text(
                    column,
                    row,
                    f"{value:.3f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color=colour,
                )
    colourbar = figure.colorbar(image, ax=axis, shrink=0.82)
    colourbar.set_label(colour_label)
    figure.subplots_adjust(left=0.30, bottom=0.25, right=0.88, top=0.90)
    figure.text(
        0.5,
        0.01,
        "Agreement measures similarity, not biological correctness.",
        ha="center",
        fontsize=8,
        color="#444444",
    )
    save_figure(figure, stem, formats, dpi)
    plt.close(figure)


def plot_dendrogram(
    distance_matrix: Sequence[Sequence[float]],
    labels: Sequence[str],
    stem: Path,
    formats: Sequence[str],
    dpi: int,
) -> None:
    """Plot a method dendrogram from normalised variation of information."""

    if len(labels) < 2:
        return
    plt, np = _plot_dependencies()
    try:
        from scipy.cluster.hierarchy import dendrogram, linkage
        from scipy.spatial.distance import squareform
    except ImportError as error:
        raise AnalysisError("scipy is required for the dendrogram") from error
    distances = np.asarray(distance_matrix, dtype=float)
    distances = np.clip((distances + distances.T) / 2.0, 0.0, None)
    np.fill_diagonal(distances, 0.0)
    condensed = squareform(distances, checks=True)
    hierarchy = linkage(condensed, method="average")
    figure, axis = plt.subplots(figsize=(10, max(5.5, len(labels) * 0.75)))
    dendrogram(hierarchy, labels=list(labels), orientation="right", ax=axis)
    axis.set_xlabel("Normalised variation of information")
    axis.set_title(
        "Clustering-result similarity landscape",
        loc="left",
        fontweight="bold",
    )
    axis.grid(axis="x", alpha=0.25)
    figure.text(
        0.01,
        0.01,
        "Shorter branches indicate more similar partitions; they do not "
        "identify a biologically superior method.",
        fontsize=8,
        color="#444444",
    )
    save_figure(figure, stem, formats, dpi)
    plt.close(figure)


def plot_cluster_profiles(
    summaries: Sequence[Mapping[str, Any]],
    labels_by_id: Mapping[str, str],
    stem: Path,
    formats: Sequence[str],
    dpi: int,
) -> None:
    """Plot four complementary cluster-size summaries."""

    plt, np = _plot_dependencies()
    labels = [labels_by_id[str(row["method_id"])] for row in summaries]
    positions = np.arange(len(labels))
    figure, axes = plt.subplots(2, 2, figsize=(13, 9))
    panels = (
        ("cluster_count", "Number of clusters", False),
        ("singleton_cluster_fraction", "Singleton-cluster fraction", False),
        ("median_cluster_size", "Median cluster size", False),
        ("largest_cluster_size", "Largest cluster size", True),
    )
    for axis, (field, title, log_scale) in zip(axes.flat, panels):
        values = [float(row[field]) for row in summaries]
        axis.barh(positions, values, color="#2B6F9C")
        axis.set_yticks(positions, labels=labels)
        axis.invert_yaxis()
        axis.set_title(title, loc="left", fontweight="bold")
        axis.grid(axis="x", alpha=0.2)
        positive = [value for value in values if value > 0]
        if (
            log_scale
            and positive
            and max(positive) / min(positive) >= 100.0
        ):
            axis.set_xscale("log")
    figure.suptitle("Cluster-number and cluster-size profiles", fontweight="bold")
    figure.tight_layout()
    save_figure(figure, stem, formats, dpi)
    plt.close(figure)


def plot_split_merge(
    cluster_fraction: Sequence[Sequence[float]],
    member_fraction: Sequence[Sequence[float]],
    labels: Sequence[str],
    stem: Path,
    formats: Sequence[str],
    dpi: int,
) -> None:
    """Plot directional fragmentation by clusters and affected members."""

    plt, np = _plot_dependencies()
    arrays = [np.asarray(cluster_fraction), np.asarray(member_fraction)]
    figure, axes = plt.subplots(1, 2, figsize=(16, 7.5), constrained_layout=True)
    titles = (
        "Fraction of source clusters split across target clusters",
        "Fraction of source members in split clusters",
    )
    for axis, data, title in zip(axes, arrays, titles):
        image = axis.imshow(data, cmap="magma", vmin=0.0, vmax=1.0)
        axis.set_xticks(range(len(labels)), labels=labels, rotation=42, ha="right")
        axis.set_yticks(range(len(labels)), labels=labels)
        axis.set_xlabel("Target clustering")
        axis.set_ylabel("Source clustering")
        axis.set_title(title, loc="left", fontweight="bold")
        for row in range(data.shape[0]):
            for column in range(data.shape[1]):
                axis.text(
                    column,
                    row,
                    f"{data[row, column]:.2f}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="white" if data[row, column] > 0.42 else "black",
                )
        figure.colorbar(image, ax=axis, shrink=0.75)
    figure.suptitle(
        "Directional split and merge structure",
        fontsize=14,
        fontweight="bold",
    )
    save_figure(figure, stem, formats, dpi)
    plt.close(figure)


def plot_repeat_stability(
    rows: Sequence[Mapping[str, Any]],
    labels_by_id: Mapping[str, str],
    stem: Path,
    formats: Sequence[str],
    dpi: int,
) -> None:
    """Plot repeat-to-repeat F1 when multiple memberships were retained."""

    measured = [row for row in rows if row.get("status") == "measured"]
    if not measured:
        return
    plt, _np = _plot_dependencies()
    labels = [
        f"{labels_by_id[str(row['method_id'])]} r{row['repeat_a']}-r{row['repeat_b']}"
        for row in measured
    ]
    values = [float(row["pairwise_f1"]) for row in measured]
    figure, axis = plt.subplots(figsize=(11, max(5.5, 0.45 * len(labels) + 2)))
    positions = list(range(len(labels)))
    axis.barh(positions, values, color="#2B6F9C")
    axis.set_yticks(positions, labels=labels)
    axis.invert_yaxis()
    axis.set_xlim(0.0, 1.0)
    axis.set_xlabel("Pairwise F1")
    axis.set_title(
        "Repeat-to-repeat clustering stability",
        loc="left",
        fontweight="bold",
    )
    axis.grid(axis="x", alpha=0.25)
    save_figure(figure, stem, formats, dpi)
    plt.close(figure)


def _html_table(
    rows: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
    limit: Optional[int] = None,
) -> str:
    """Render selected rows as a compact escaped HTML table."""

    selected = rows if limit is None else rows[:limit]
    headings = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = []
    for row in selected:
        cells = "".join(
            f"<td>{html.escape(_format_tsv_value(row.get(field, '')))}</td>"
            for field in fields
        )
        body.append(f"<tr>{cells}</tr>")
    return (
        f"<table><thead><tr>{headings}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def write_html_report(
    path: Path,
    method_summaries: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    sentinel_rows: Sequence[Mapping[str, Any]],
    repeat_rows: Sequence[Mapping[str, Any]],
    figure_names: Sequence[str],
) -> None:
    """Write a portable HTML index for the tabular and graphical outputs."""

    pair_fields = (
        "method_a",
        "method_b",
        "pairwise_f1",
        "pairwise_jaccard",
        "adjusted_rand_index",
        "normalised_variation_of_information",
        "exact_match_member_fraction",
    )
    method_fields = (
        "method_id",
        "cluster_count",
        "singleton_cluster_fraction",
        "median_cluster_size",
        "cluster_size_p95",
        "largest_cluster_size",
    )
    sentinel_html = (
        _html_table(
            sentinel_rows,
            (
                "method_a",
                "method_b",
                "neighbour_jaccard",
                "per_sentinel_jaccard_median",
                "per_sentinel_jaccard_minimum",
            ),
        )
        if sentinel_rows
        else "<p>No sentinel identifiers were supplied.</p>"
    )
    unavailable = [row for row in repeat_rows if row.get("status") != "measured"]
    repeat_note = (
        "<p>Repeat stability could not be calculated for one or more methods "
        "because only one membership table was retained. Timing repeats alone "
        "cannot establish clustering stability.</p>"
        if unavailable
        else ""
    )
    repeat_html = _html_table(
        repeat_rows,
        ("method_id", "repeat_a", "repeat_b", "status", "pairwise_f1"),
    )
    figures = "".join(
        f'<figure><img src="../figures/{html.escape(name)}" '
        f'alt="{html.escape(Path(name).stem)}"></figure>'
        for name in figure_names
    )
    document = f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DIAMOND all-against-all clustering comparison</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 2rem auto; max-width: 1500px;
       line-height: 1.45; color: #1e2933; padding: 0 1rem; }}
h1, h2 {{ color: #174f78; }}
.caution {{ background: #fff4cf; border-left: 5px solid #d29a00;
            padding: 1rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
th, td {{ border: 1px solid #ccd4db; padding: 0.45rem; text-align: left; }}
th {{ background: #245a84; color: white; position: sticky; top: 0; }}
tr:nth-child(even) {{ background: #eef3f7; }}
figure {{ margin: 2rem 0; }}
img {{ max-width: 100%; height: auto; }}
code {{ background: #eef3f7; padding: 0.1rem 0.25rem; }}
</style>
</head>
<body>
<h1>DIAMOND all-against-all clustering comparison</h1>
<p class="caution"><strong>Interpretation boundary:</strong> these metrics
measure agreement between clusterings. They cannot determine which DIAMOND
version or clustering strategy is biologically correct.</p>
<h2>Cluster profiles</h2>
{_html_table(method_summaries, method_fields)}
<h2>All method pairs</h2>
{_html_table(pair_rows, pair_fields)}
<h2>E3 sentinel neighbourhoods</h2>
{sentinel_html}
<h2>Repeat stability</h2>
{repeat_note}
{repeat_html}
<h2>Figures</h2>
{figures}
<h2>Machine-readable outputs</h2>
<p>Complete TSV tables are in <code>../tables/</code>. Analysis provenance and
input signatures are in <code>../provenance/</code>.</p>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


def _repeat_stability_rows(
    all_inputs: Sequence[MembershipInput],
    sentinels: Set[str],
    output_directory: Path,
    temporary_root: Path,
    threads: int,
    memory_limit: str,
    small_file_limit_bytes: int,
    resume: bool,
) -> List[Dict[str, Any]]:
    """Compare retained repeats within each method or report unavailability."""

    grouped: Dict[str, List[MembershipInput]] = defaultdict(list)
    for membership in all_inputs:
        grouped[membership.method_id].append(membership)
    rows: List[Dict[str, Any]] = []
    for method_id, memberships in grouped.items():
        memberships.sort(key=lambda item: item.repeat)
        if len(memberships) < 2:
            rows.append(
                {
                    "method_id": method_id,
                    "repeat_a": memberships[0].repeat if memberships else "",
                    "repeat_b": "",
                    "status": "not_estimable_only_one_retained_membership",
                    "pairwise_f1": "",
                    "pairwise_jaccard": "",
                    "adjusted_rand_index": "",
                    "normalised_variation_of_information": "",
                }
            )
            continue
        for first in range(len(memberships) - 1):
            for second in range(first + 1, len(memberships)):
                method_a = memberships[first]
                method_b = memberships[second]
                result = run_comparison_with_checkpoint(
                    method_a,
                    method_b,
                    sentinels,
                    output_directory,
                    temporary_root,
                    threads,
                    memory_limit,
                    small_file_limit_bytes,
                    resume,
                )
                metrics = result["pair_metrics"]
                rows.append(
                    {
                        "method_id": method_id,
                        "repeat_a": method_a.repeat,
                        "repeat_b": method_b.repeat,
                        "status": "measured",
                        "pairwise_f1": metrics["pairwise_f1"],
                        "pairwise_jaccard": metrics["pairwise_jaccard"],
                        "adjusted_rand_index": metrics["adjusted_rand_index"],
                        "normalised_variation_of_information": metrics[
                            "normalised_variation_of_information"
                        ],
                    }
                )
    return rows


def _resolve_temporary_root(value: str, output_directory: Path) -> Path:
    """Resolve ``auto`` spill storage without assuming a home directory."""

    if value != "auto":
        root = Path(value).expanduser().resolve()
    elif os.environ.get("SLURM_TMPDIR"):
        root = Path(os.environ["SLURM_TMPDIR"]).resolve() / "diamond_all_pairs"
    elif os.environ.get("TMPDIR"):
        root = Path(os.environ["TMPDIR"]).resolve() / "diamond_all_pairs"
    else:
        root = output_directory / "scratch"
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def analysis_lock(output_directory: Path) -> Iterator[None]:
    """Prevent concurrent writers from using the same output directory."""

    import fcntl

    output_directory.mkdir(parents=True, exist_ok=True)
    lock_path = output_directory / ".analysis.lock"
    with lock_path.open("w", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AnalysisError(
                f"Another analysis is using {output_directory}"
            ) from error
        handle.write(f"host={socket.gethostname()} pid={os.getpid()}\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    lock_path.unlink(missing_ok=True)


def _validate_existing_output(output_directory: Path, resume: bool) -> None:
    """Protect complete or non-resumable output directories."""

    if (output_directory / "COMPLETE").exists():
        raise AnalysisError(
            f"Analysis is already complete: {output_directory}"
        )
    existing = [
        item
        for item in output_directory.iterdir()
        if item.name not in {".analysis.lock"}
    ] if output_directory.exists() else []
    if existing and not resume:
        raise AnalysisError(
            f"Output directory is not empty; use --resume: {output_directory}"
        )


def _method_summary_fields() -> Tuple[str, ...]:
    """Return the fixed schema for the method summary table."""

    return (
        "method_id",
        "display_name",
        "repeat",
        "membership_path",
        "membership_sha256",
        "member_count",
        "cluster_count",
        "singleton_cluster_count",
        "singleton_cluster_fraction",
        "mean_cluster_size",
        "median_cluster_size",
        "cluster_size_p25",
        "cluster_size_p75",
        "cluster_size_p90",
        "cluster_size_p95",
        "cluster_size_p99",
        "largest_cluster_size",
    )


def _directional_rows(pair_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Expand unordered pair metrics into source-to-target rows."""

    rows: List[Dict[str, Any]] = []
    for row in pair_rows:
        for direction in ("a_to_b", "b_to_a"):
            source = "a" if direction == "a_to_b" else "b"
            target = "b" if source == "a" else "a"
            rows.append(
                {
                    "source_method": row[f"method_{source}"],
                    "target_method": row[f"method_{target}"],
                    "repeat_source": row[f"repeat_{source}"],
                    "repeat_target": row[f"repeat_{target}"],
                    "source_cluster_count": row[f"cluster_count_{source}"],
                    "target_cluster_count": row[f"cluster_count_{target}"],
                    "same_pair_recall_in_target": row[
                        f"pair_recall_{source}_in_{target}"
                    ],
                    "split_cluster_count": row[
                        f"split_cluster_count_{source}_to_{target}"
                    ],
                    "split_cluster_fraction": row[
                        f"split_cluster_fraction_{source}_to_{target}"
                    ],
                    "members_in_split_clusters": row[
                        f"members_in_split_clusters_{source}_to_{target}"
                    ],
                    "member_fraction_in_split_clusters": row[
                        f"member_fraction_in_split_clusters_{source}_to_{target}"
                    ],
                    "best_match_jaccard_mean": row[
                        f"best_match_jaccard_mean_{source}_to_{target}"
                    ],
                    "best_match_jaccard_median": row[
                        f"best_match_jaccard_median_{source}_to_{target}"
                    ],
                    "best_match_jaccard_weighted_mean": row[
                        f"best_match_jaccard_weighted_mean_{source}_to_{target}"
                    ],
                }
            )
    return rows


def _write_manifest(
    path: Path,
    args: argparse.Namespace,
    config_path: Path,
    run_root: Path,
    memberships: Sequence[MembershipInput],
    sentinel_path: Optional[Path],
    output_files: Sequence[Path],
    elapsed_seconds: float,
    dependency_versions: Mapping[str, str],
) -> None:
    """Write machine-readable provenance after successful analysis."""

    payload = {
        "schema_version": 1,
        "script_version": SCRIPT_VERSION,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": socket.gethostname(),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
        "config": str(config_path),
        "run_root": str(run_root),
        "sentinel_ids_tsv": str(sentinel_path) if sentinel_path else None,
        "threads": args.threads,
        "memory_limit": args.memory_limit,
        "elapsed_seconds": elapsed_seconds,
        "dependency_versions": dict(dependency_versions),
        "interpretation_boundary": (
            "Similarity metrics do not establish biological correctness."
        ),
        "memberships": [item.signature() for item in memberships],
        "outputs": [str(item) for item in output_files],
    }
    atomic_json(path, payload)


def run_analysis(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the complete all-against-all analysis."""

    _require_positive(args.threads, "--threads")
    _require_positive(args.dpi, "--dpi")
    _require_positive(args.small_file_limit_bytes, "--small-file-limit-bytes")
    args.memory_limit = validate_memory_limit(args.memory_limit)
    config_path = args.config.expanduser().resolve()
    run_root = args.run_root.expanduser().resolve()
    output_directory = args.output_directory.expanduser().resolve()
    if not run_root.is_dir():
        raise AnalysisError(f"Run root does not exist: {run_root}")
    output_directory.mkdir(parents=True, exist_ok=True)
    _validate_existing_output(output_directory, args.resume)
    configure_logging(args.log_level, output_directory / "logs" / "analysis.log")
    config = load_yaml(config_path)
    quality_inputs, all_inputs, configured_sentinel = discover_memberships(
        config,
        config_path,
        run_root,
        args.quality_repeat,
    )
    sentinel_path = (
        args.sentinel_ids_tsv.expanduser().resolve()
        if args.sentinel_ids_tsv
        else configured_sentinel
    )
    sentinels = read_sentinels(sentinel_path)
    temporary_root = _resolve_temporary_root(
        args.temporary_directory,
        output_directory,
    )
    sizes = sorted(
        (item.path.stat().st_size for item in quality_inputs),
        reverse=True,
    )
    require_duckdb = sum(sizes[:2]) > args.small_file_limit_bytes
    dependency_versions = validate_runtime_dependencies(require_duckdb)
    LOGGER.info("Analysing %d methods", len(quality_inputs))
    LOGGER.info("Temporary working directory: %s", temporary_root)
    LOGGER.info("E3 sentinel identifiers: %d", len(sentinels))
    started = time.monotonic()
    method_summaries = [
        summarise_membership(
            membership,
            temporary_root / f"summary_{membership.method_id}",
            args.threads,
            args.memory_limit,
            args.small_file_limit_bytes,
        )
        for membership in quality_inputs
    ]
    pair_rows: List[Dict[str, Any]] = []
    sentinel_rows: List[Dict[str, Any]] = []
    sentinel_detail: List[Dict[str, Any]] = []
    size_stratified: List[Dict[str, Any]] = []
    pair_elapsed: List[Dict[str, Any]] = []
    for first in range(len(quality_inputs) - 1):
        for second in range(first + 1, len(quality_inputs)):
            method_a = quality_inputs[first]
            method_b = quality_inputs[second]
            result = run_comparison_with_checkpoint(
                method_a,
                method_b,
                sentinels,
                output_directory,
                temporary_root,
                args.threads,
                args.memory_limit,
                args.small_file_limit_bytes,
                args.resume,
            )
            pair_rows.append(result["pair_metrics"])
            if result.get("sentinel_metrics"):
                sentinel_rows.append(result["sentinel_metrics"])
            sentinel_detail.extend(result.get("sentinel_detail", []))
            size_stratified.extend(result.get("size_stratified", []))
            pair_elapsed.append(
                {
                    "method_a": method_a.method_id,
                    "method_b": method_b.method_id,
                    "repeat_a": method_a.repeat,
                    "repeat_b": method_b.repeat,
                    "elapsed_seconds": result.get("elapsed_seconds", ""),
                }
            )
    repeat_rows = _repeat_stability_rows(
        all_inputs,
        sentinels,
        output_directory,
        temporary_root,
        args.threads,
        args.memory_limit,
        args.small_file_limit_bytes,
        args.resume,
    )
    tables = output_directory / "tables"
    figures = output_directory / "figures"
    reports = output_directory / "reports"
    provenance = output_directory / "provenance"
    write_tsv(
        tables / "method_cluster_summary.tsv",
        method_summaries,
        _method_summary_fields(),
    )
    write_tsv(
        tables / "pairwise_method_comparisons.tsv",
        pair_rows,
        PAIR_FIELDS,
    )
    directional = _directional_rows(pair_rows)
    directional_fields = tuple(directional[0]) if directional else ()
    write_tsv(
        tables / "directional_split_merge_summary.tsv",
        directional,
        directional_fields,
    )
    sentinel_fields = SENTINEL_FIELDS
    write_tsv(
        tables / "sentinel_method_comparisons.tsv",
        sentinel_rows,
        sentinel_fields,
    )
    detail_fields = (
        tuple(sentinel_detail[0])
        if sentinel_detail
        else (
            "method_a",
            "method_b",
            "repeat_a",
            "repeat_b",
            "sequence_id",
            "cluster_a",
            "cluster_b",
            "neighbour_count_a",
            "neighbour_count_b",
            "shared_neighbour_count",
            "neighbour_jaccard",
        )
    )
    write_tsv(
        tables / "sentinel_per_sequence_comparisons.tsv",
        sentinel_detail,
        detail_fields,
    )
    size_fields = (
        "source_method",
        "target_method",
        "repeat_source",
        "repeat_target",
        "source_size_bin",
        "source_cluster_count",
        "source_member_count",
        "best_match_jaccard_mean",
        "best_match_jaccard_median",
        "best_match_jaccard_weighted_mean",
    )
    write_tsv(
        tables / "size_stratified_best_match.tsv",
        size_stratified,
        size_fields,
    )
    repeat_fields = (
        "method_id",
        "repeat_a",
        "repeat_b",
        "status",
        "pairwise_f1",
        "pairwise_jaccard",
        "adjusted_rand_index",
        "normalised_variation_of_information",
    )
    write_tsv(
        tables / "repeat_stability.tsv",
        repeat_rows,
        repeat_fields,
    )
    write_tsv(
        provenance / "comparison_timings.tsv",
        pair_elapsed,
        (
            "method_a",
            "method_b",
            "repeat_a",
            "repeat_b",
            "elapsed_seconds",
        ),
    )
    input_rows = [
        {
            **membership.signature(),
            "display_name": membership.display_name,
            "selected_for_all_method_analysis": (
                membership in quality_inputs
            ),
        }
        for membership in all_inputs
    ]
    write_tsv(
        provenance / "input_memberships.tsv",
        input_rows,
        (
            "method_id",
            "display_name",
            "repeat",
            "path",
            "size_bytes",
            "mtime_ns",
            "sha256",
            "selected_for_all_method_analysis",
        ),
    )
    method_ids = [item.method_id for item in quality_inputs]
    labels = [item.display_name for item in quality_inputs]
    labels_by_id = {
        item.method_id: item.display_name for item in quality_inputs
    }
    figure_stems: List[Path] = []
    heatmaps = (
        (
            "pairwise_f1",
            1.0,
            "All-against-all pairwise F1",
            "Pairwise F1",
            0.0,
            1.0,
            True,
        ),
        (
            "pairwise_jaccard",
            1.0,
            "All-against-all same-pair Jaccard",
            "Pairwise Jaccard",
            0.0,
            1.0,
            True,
        ),
        (
            "adjusted_rand_index",
            1.0,
            "All-against-all adjusted Rand index",
            "Adjusted Rand index",
            -1.0,
            1.0,
            True,
        ),
        (
            "normalised_variation_of_information",
            0.0,
            "All-against-all normalised variation of information",
            "Normalised variation of information",
            0.0,
            1.0,
            False,
        ),
    )
    matrices: Dict[str, List[List[float]]] = {}
    for field, diagonal, title, colour, minimum, maximum, higher in heatmaps:
        matrix = _matrix(method_ids, pair_rows, field, diagonal)
        matrices[field] = matrix
        stem = figures / field
        plot_heatmap(
            matrix,
            labels,
            title,
            colour,
            stem,
            args.formats,
            args.dpi,
            minimum,
            maximum,
            higher,
        )
        figure_stems.append(stem)
    if sentinel_rows:
        sentinel_matrix = _matrix(
            method_ids,
            sentinel_rows,
            "neighbour_jaccard",
            1.0,
        )
        stem = figures / "sentinel_neighbour_jaccard"
        plot_heatmap(
            sentinel_matrix,
            labels,
            "All-against-all E3 sentinel-neighbourhood Jaccard",
            "Sentinel-neighbourhood Jaccard",
            stem,
            args.formats,
            args.dpi,
            0.0,
            1.0,
            True,
        )
        figure_stems.append(stem)
    dendrogram_stem = figures / "method_similarity_dendrogram"
    plot_dendrogram(
        matrices["normalised_variation_of_information"],
        labels,
        dendrogram_stem,
        args.formats,
        args.dpi,
    )
    figure_stems.append(dendrogram_stem)
    cluster_stem = figures / "cluster_size_profiles"
    plot_cluster_profiles(
        method_summaries,
        labels_by_id,
        cluster_stem,
        args.formats,
        args.dpi,
    )
    figure_stems.append(cluster_stem)
    cluster_fraction = _directional_matrix(
        method_ids,
        pair_rows,
        "split_cluster_fraction_a_to_b",
        "split_cluster_fraction_b_to_a",
    )
    member_fraction = _directional_matrix(
        method_ids,
        pair_rows,
        "member_fraction_in_split_clusters_a_to_b",
        "member_fraction_in_split_clusters_b_to_a",
    )
    split_stem = figures / "directional_split_merge"
    plot_split_merge(
        cluster_fraction,
        member_fraction,
        labels,
        split_stem,
        args.formats,
        args.dpi,
    )
    figure_stems.append(split_stem)
    repeat_stem = figures / "repeat_stability"
    plot_repeat_stability(
        repeat_rows,
        labels_by_id,
        repeat_stem,
        args.formats,
        args.dpi,
    )
    if any(row.get("status") == "measured" for row in repeat_rows):
        figure_stems.append(repeat_stem)
    png_names = [f"{stem.name}.png" for stem in figure_stems if "png" in args.formats]
    write_html_report(
        reports / "all_against_all_summary.html",
        method_summaries,
        pair_rows,
        sentinel_rows,
        repeat_rows,
        png_names,
    )
    output_files = sorted(
        item
        for root in (tables, figures, reports, provenance)
        if root.exists()
        for item in root.iterdir()
        if item.is_file()
    )
    elapsed = time.monotonic() - started
    manifest_path = provenance / "analysis_manifest.json"
    _write_manifest(
        manifest_path,
        args,
        config_path,
        run_root,
        quality_inputs,
        sentinel_path,
        output_files,
        elapsed,
        dependency_versions,
    )
    (output_directory / "COMPLETE").write_text(
        f"completed_utc\t{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n",
        encoding="utf-8",
    )
    LOGGER.info("Analysis completed in %.1f seconds", elapsed)
    return {
        "output_directory": str(output_directory),
        "method_count": len(quality_inputs),
        "pair_count": len(pair_rows),
        "sentinel_pair_count": len(sentinel_rows),
        "repeat_comparisons_measured": sum(
            row.get("status") == "measured" for row in repeat_rows
        ),
        "html_report": str(reports / "all_against_all_summary.html"),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the command-line program with concise failure logging."""

    args = parse_arguments(argv)
    configure_logging(args.log_level)
    try:
        output_directory = args.output_directory.expanduser().resolve()
        with analysis_lock(output_directory):
            result = run_analysis(args)
    except (AnalysisError, OSError, ValueError) as error:
        LOGGER.error("%s", error)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
