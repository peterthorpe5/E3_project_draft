"""Aggregate repeats, evaluate guardrails and publish a self-contained report."""

from __future__ import annotations

import html
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from diamond_clust_benchmark.config import BenchmarkConfiguration
from diamond_clust_benchmark.io_utils import write_json, write_tsv
from diamond_clust_benchmark.membership import compare_memberships
from diamond_clust_benchmark.runner import StageMetrics, read_metrics

SUMMARY_FIELDS = [
    "case_id",
    "stage",
    "repeat_count",
    "mean_wall_seconds",
    "median_wall_seconds",
    "minimum_wall_seconds",
    "maximum_wall_seconds",
    "standard_deviation_seconds",
    "coefficient_of_variation",
    "mean_peak_rss_mib",
    "maximum_peak_rss_mib",
    "mean_cpu_equivalents",
]

QUALITY_FIELDS = [
    "case_id",
    "member_count",
    "baseline_cluster_count",
    "candidate_cluster_count",
    "pairwise_precision",
    "pairwise_recall",
    "pairwise_f1",
    "adjusted_rand_index",
    "sentinel_count",
    "matched_sentinel_count",
    "sentinel_baseline_neighbours",
    "sentinel_candidate_neighbours",
    "sentinel_recall",
    "sentinel_jaccard",
]

DECISION_FIELDS = [
    "case_id",
    "decision_stage",
    "mean_wall_seconds",
    "mean_speedup_percent",
    "paired_speedup_ci95_low",
    "paired_speedup_ci95_high",
    "pairwise_f1",
    "sentinel_recall",
    "speed_target_pass",
    "quality_guardrail_pass",
    "overall_pass",
    "is_baseline",
]


def collect_metrics(
    config: BenchmarkConfiguration,
    run_root: Path,
) -> List[StageMetrics]:
    """Read and validate metrics for every configured case and repeat.

    Args:
        config: Validated benchmark configuration.
        run_root: Benchmark output root.

    Returns:
        Complete list of stage metrics.

    Raises:
        FileNotFoundError: If any expected repeat output is absent.
    """

    records: List[StageMetrics] = []
    root = Path(run_root)
    for case in config.enabled_cases:
        for repeat in range(1, config.repeats + 1):
            case_root = root / "cases" / case.case_id / f"repeat_{repeat}"
            complete = case_root / "COMPLETE"
            metrics_path = case_root / "metrics.tsv"
            if not complete.is_file() or not metrics_path.is_file():
                raise FileNotFoundError(
                    f"Incomplete benchmark output for {case.case_id} repeat {repeat}"
                )
            records.extend(read_metrics(metrics_path))
    return records


def summarise_metrics(records: Iterable[StageMetrics]) -> List[Dict[str, object]]:
    """Summarise repeated stage metrics by case and stage.

    Args:
        records: Stage-level observations.

    Returns:
        Deterministically ordered summary rows.
    """

    grouped: Dict[Tuple[str, str], List[StageMetrics]] = defaultdict(list)
    for record in records:
        grouped[(record.case_id, record.stage)].append(record)
    summaries: List[Dict[str, object]] = []
    for (case_id, stage), values in sorted(grouped.items()):
        wall = [value.wall_seconds for value in values]
        mean_wall = statistics.fmean(wall)
        deviation = statistics.pstdev(wall) if len(wall) > 1 else 0.0
        summaries.append(
            {
                "case_id": case_id,
                "stage": stage,
                "repeat_count": len(values),
                "mean_wall_seconds": mean_wall,
                "median_wall_seconds": statistics.median(wall),
                "minimum_wall_seconds": min(wall),
                "maximum_wall_seconds": max(wall),
                "standard_deviation_seconds": deviation,
                "coefficient_of_variation": (
                    deviation / mean_wall if mean_wall else 0.0
                ),
                "mean_peak_rss_mib": statistics.fmean(
                    value.peak_rss_mib for value in values
                ),
                "maximum_peak_rss_mib": max(value.peak_rss_mib for value in values),
                "mean_cpu_equivalents": statistics.fmean(
                    value.mean_cpu_equivalents for value in values
                ),
            }
        )
    return summaries


def percentile(values: Sequence[float], probability: float) -> float:
    """Calculate a linearly interpolated percentile.

    Args:
        values: Non-empty numeric values.
        probability: Quantile probability in ``[0, 1]``.

    Returns:
        Interpolated percentile.
    """

    if not values:
        raise ValueError("values cannot be empty")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def paired_speedup_interval(
    baseline_seconds: Mapping[int, float],
    candidate_seconds: Mapping[int, float],
    iterations: int,
    seed: int = 20260921,
) -> Tuple[float, float, float]:
    """Estimate mean paired speed-up and a bootstrap 95% interval.

    Args:
        baseline_seconds: Baseline seconds keyed by repeat.
        candidate_seconds: Candidate seconds keyed by repeat.
        iterations: Positive bootstrap resample count.
        seed: Deterministic random seed.

    Returns:
        Mean speed-up percentage and lower/upper percentile bounds.

    Raises:
        ValueError: If repeat sets differ, values are invalid or iterations
            are not positive.
    """

    if iterations < 1:
        raise ValueError("iterations must be positive")
    if not baseline_seconds or baseline_seconds.keys() != candidate_seconds.keys():
        raise ValueError("Paired benchmark repeats must be complete and identical")
    speedups = []
    for repeat in sorted(baseline_seconds):
        baseline = float(baseline_seconds[repeat])
        candidate = float(candidate_seconds[repeat])
        if baseline <= 0 or candidate <= 0:
            raise ValueError("Benchmark seconds must be positive")
        speedups.append(100.0 * (baseline - candidate) / baseline)
    mean_speedup = statistics.fmean(speedups)
    generator = random.Random(seed)
    bootstrapped = [
        statistics.fmean(generator.choice(speedups) for _ in speedups)
        for _ in range(iterations)
    ]
    return (
        mean_speedup,
        percentile(bootstrapped, 0.025),
        percentile(bootstrapped, 0.975),
    )


def calculate_quality(
    config: BenchmarkConfiguration,
    run_root: Path,
) -> List[Dict[str, object]]:
    """Compare each retained quality repeat with the configured baseline.

    Args:
        config: Validated benchmark configuration.
        run_root: Benchmark output root.

    Returns:
        One quality row per enabled case.
    """

    root = Path(run_root)
    repeat = config.quality_repeat
    baseline_path = (
        root
        / "cases"
        / config.baseline_case_id
        / f"repeat_{repeat}"
        / "clusters.tsv"
    )
    if not baseline_path.is_file():
        raise FileNotFoundError(
            f"Retained baseline clusters are missing: {baseline_path}"
        )
    rows: List[Dict[str, object]] = []
    for case in config.enabled_cases:
        candidate_path = (
            root / "cases" / case.case_id / f"repeat_{repeat}" / "clusters.tsv"
        )
        if not candidate_path.is_file():
            raise FileNotFoundError(
                f"Retained candidate clusters are missing: {candidate_path}"
            )
        metrics = compare_memberships(
            baseline_path,
            candidate_path,
            config.sentinel_ids_tsv,
        )
        rows.append({"case_id": case.case_id, **metrics})
    return rows


def build_decisions(
    config: BenchmarkConfiguration,
    records: Iterable[StageMetrics],
    quality_rows: Iterable[Mapping[str, object]],
) -> List[Dict[str, object]]:
    """Apply speed and scientific-concordance acceptance criteria.

    Args:
        config: Validated benchmark configuration.
        records: All stage observations.
        quality_rows: Case quality comparisons.

    Returns:
        One decision row per enabled case.
    """

    selected: Dict[str, Dict[int, float]] = defaultdict(dict)
    for record in records:
        if record.stage == config.decision_stage:
            selected[record.case_id][record.repeat] = record.wall_seconds
    baseline = selected[config.baseline_case_id]
    quality = {str(row["case_id"]): row for row in quality_rows}
    decisions = []
    for case in config.enabled_cases:
        case_times = selected[case.case_id]
        speedup, interval_low, interval_high = paired_speedup_interval(
            baseline,
            case_times,
            config.bootstrap_iterations,
        )
        quality_row = quality[case.case_id]
        pairwise_f1 = float(quality_row["pairwise_f1"])
        sentinel_value = quality_row.get("sentinel_recall", "")
        sentinel_pass = (
            True
            if sentinel_value in {None, ""}
            else float(sentinel_value) >= config.minimum_sentinel_recall
        )
        quality_pass = (
            pairwise_f1 >= config.minimum_pairwise_f1 and sentinel_pass
        )
        is_baseline = case.case_id == config.baseline_case_id
        speed_pass = (
            True if is_baseline else speedup >= config.minimum_speedup_percent
        )
        decisions.append(
            {
                "case_id": case.case_id,
                "decision_stage": config.decision_stage,
                "mean_wall_seconds": statistics.fmean(case_times.values()),
                "mean_speedup_percent": speedup,
                "paired_speedup_ci95_low": interval_low,
                "paired_speedup_ci95_high": interval_high,
                "pairwise_f1": pairwise_f1,
                "sentinel_recall": sentinel_value,
                "speed_target_pass": speed_pass,
                "quality_guardrail_pass": quality_pass,
                "overall_pass": speed_pass and quality_pass,
                "is_baseline": is_baseline,
            }
        )
    return decisions


def _format_seconds(value: object) -> str:
    """Format seconds compactly for the HTML report."""

    seconds = float(value)
    if seconds >= 3600:
        return f"{seconds / 3600:.2f} h"
    if seconds >= 60:
        return f"{seconds / 60:.2f} min"
    return f"{seconds:.2f} s"


def _speedup_svg(decisions: Sequence[Mapping[str, object]]) -> str:
    """Render a compact inline SVG speed-up chart."""

    rows = [row for row in decisions if not bool(row["is_baseline"])]
    if not rows:
        return ""
    width = 900
    label_width = 300
    plot_width = 540
    row_height = 42
    height = 55 + row_height * len(rows)
    maximum = max(10.0, max(abs(float(row["mean_speedup_percent"])) for row in rows))
    fragments = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Mean paired speed-up by benchmark case">',
        '<style>text{font-family:Arial,sans-serif;font-size:13px}'
        '.axis{stroke:#555;stroke-width:1}</style>',
        f'<line class="axis" x1="{label_width}" y1="30" '
        f'x2="{label_width + plot_width}" y2="30"/>',
    ]
    for index, row in enumerate(rows):
        y = 50 + index * row_height
        speedup = float(row["mean_speedup_percent"])
        bar_width = abs(speedup) / maximum * plot_width
        colour = "#1b7f5a" if speedup >= 0 else "#b0443c"
        fragments.append(
            f'<text x="0" y="{y + 14}">{html.escape(str(row["case_id"]))}</text>'
        )
        fragments.append(
            f'<rect x="{label_width}" y="{y}" width="{bar_width:.1f}" '
            f'height="22" fill="{colour}" rx="2"/>'
        )
        fragments.append(
            f'<text x="{label_width + bar_width + 8:.1f}" y="{y + 16}">'
            f'{speedup:.2f}%</text>'
        )
    fragments.append("</svg>")
    return "".join(fragments)


def render_html(
    config: BenchmarkConfiguration,
    decisions: Sequence[Mapping[str, object]],
) -> str:
    """Render a self-contained decision-focused benchmark report.

    Args:
        config: Validated benchmark configuration.
        decisions: Decision rows.

    Returns:
        Complete UTF-8 HTML document.
    """

    passing = [
        row for row in decisions if row["overall_pass"] and not row["is_baseline"]
    ]
    fastest = (
        min(passing, key=lambda row: float(row["mean_wall_seconds"]))
        if passing
        else None
    )
    conclusion = (
        f"Fastest passing strategy: {html.escape(str(fastest['case_id']))}."
        if fastest
        else "No candidate currently meets both the speed and concordance criteria."
    )
    body_rows = []
    for row in decisions:
        body_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row['case_id']))}</td>"
            f"<td>{_format_seconds(row['mean_wall_seconds'])}</td>"
            f"<td>{float(row['mean_speedup_percent']):.2f}%</td>"
            f"<td>{float(row['paired_speedup_ci95_low']):.2f}% to "
            f"{float(row['paired_speedup_ci95_high']):.2f}%</td>"
            f"<td>{float(row['pairwise_f1']):.6f}</td>"
            f"<td>{'PASS' if row['overall_pass'] else 'FAIL'}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DIAMOND clustering benchmark</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1120px;margin:0 auto;
padding:32px;color:#1f2933}}
h1,h2{{color:#111827}} .lead{{font-size:1.1rem;line-height:1.55}}
table{{border-collapse:collapse;width:100%;margin:18px 0 30px}}
th{{background:#183b56;color:white;text-align:left}}
th,td{{border:1px solid #d9d9d9;padding:10px}}
tbody tr:nth-child(even){{background:#f3f7fa}} .meta{{color:#52606d}}
.pass{{color:#176b45;font-weight:700}} .fail{{color:#9b2c2c;font-weight:700}}
</style>
</head>
<body>
<h1>DIAMOND clustering benchmark</h1>
<p class="lead">{conclusion}</p>
<p class="meta">Baseline: {html.escape(config.baseline_case_id)}. Decision stage:
{html.escape(config.decision_stage)}. Required mean speed-up: at least
{config.minimum_speedup_percent:.2f}%. Required pairwise F1: at least
{config.minimum_pairwise_f1:.4f}. Each case has {config.repeats} repeats.</p>
<h2>Decision table</h2>
<table>
<thead><tr><th>Case</th><th>Mean time</th><th>Mean speed-up</th>
<th>Paired bootstrap 95% interval</th><th>Pairwise F1</th><th>Decision</th></tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>
<h2>Speed comparison</h2>
{_speedup_svg(decisions)}
<h2>Interpretation</h2>
<p>A speed result passes only when the configured sequence-clustering
concordance guardrail also passes. The interval describes repeat-to-repeat
uncertainty; it is reported for interpretation but the configured decision is
based on mean paired speed-up. This report does not claim that a faster method
is biologically interchangeable beyond the measured membership and sentinel
neighbourhood tests.</p>
</body>
</html>
"""


def generate_report(
    config: BenchmarkConfiguration,
    run_root: Path,
) -> Dict[str, object]:
    """Generate machine-readable summaries and a self-contained HTML report.

    Args:
        config: Validated benchmark configuration.
        run_root: Benchmark output root.

    Returns:
        Report manifest containing output paths and the fastest passing case.
    """

    root = Path(run_root)
    report_root = root / "reports"
    table_root = root / "tables"
    records = collect_metrics(config, root)
    summaries = summarise_metrics(records)
    quality = calculate_quality(config, root)
    decisions = build_decisions(config, records, quality)
    write_tsv(table_root / "benchmark_summary.tsv", summaries, SUMMARY_FIELDS)
    write_tsv(table_root / "quality_summary.tsv", quality, QUALITY_FIELDS)
    write_tsv(table_root / "decision_summary.tsv", decisions, DECISION_FIELDS)
    report_path = report_root / "benchmark_summary.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_html(config, decisions), encoding="utf-8")
    passing = [
        row for row in decisions if row["overall_pass"] and not row["is_baseline"]
    ]
    fastest = (
        min(passing, key=lambda row: float(row["mean_wall_seconds"]))
        if passing
        else None
    )
    manifest = {
        "status": "COMPLETE",
        "benchmark_summary_tsv": str((table_root / "benchmark_summary.tsv").resolve()),
        "quality_summary_tsv": str((table_root / "quality_summary.tsv").resolve()),
        "decision_summary_tsv": str((table_root / "decision_summary.tsv").resolve()),
        "html_report": str(report_path.resolve()),
        "fastest_passing_case": fastest["case_id"] if fastest else None,
    }
    write_json(report_root / "report_manifest.json", manifest)
    return manifest
