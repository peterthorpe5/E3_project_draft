"""Execute isolated DIAMOND benchmark cases with resource monitoring."""

from __future__ import annotations

import csv
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from diamond_clust_benchmark.commands import (
    build_cluster_command,
    build_makedb_command,
    build_realign_command,
    command_as_text,
    get_version,
)
from diamond_clust_benchmark.config import (
    BenchmarkCase,
    BenchmarkConfiguration,
    configuration_to_dict,
)
from diamond_clust_benchmark.exceptions import ExternalCommandError
from diamond_clust_benchmark.io_utils import write_json, write_tsv
from diamond_clust_benchmark.membership import summarise_membership

LOGGER = logging.getLogger(__name__)

METRIC_FIELDS = [
    "case_id",
    "repeat",
    "stage",
    "wall_seconds",
    "user_cpu_seconds",
    "system_cpu_seconds",
    "mean_cpu_equivalents",
    "peak_rss_mib",
    "read_bytes",
    "write_bytes",
    "maximum_processes",
    "exit_code",
]


@dataclass(frozen=True)
class StageMetrics:
    """Observed resources for one command or derived pipeline stage."""

    case_id: str
    repeat: int
    stage: str
    wall_seconds: float
    user_cpu_seconds: float
    system_cpu_seconds: float
    mean_cpu_equivalents: float
    peak_rss_mib: float
    read_bytes: int
    write_bytes: int
    maximum_processes: int
    exit_code: int


def _sample_process_tree(process, psutil_module) -> Dict[str, float]:
    """Sample aggregate resources for a process and its descendants."""

    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except psutil_module.Error:
        pass
    rss = 0
    user_cpu = 0.0
    system_cpu = 0.0
    read_bytes = 0
    write_bytes = 0
    observed = 0
    for item in processes:
        try:
            memory = item.memory_info()
            cpu = item.cpu_times()
            rss += int(memory.rss)
            user_cpu += float(cpu.user)
            system_cpu += float(cpu.system)
            try:
                io_counters = item.io_counters()
                read_bytes += int(io_counters.read_bytes)
                write_bytes += int(io_counters.write_bytes)
            except (psutil_module.AccessDenied, AttributeError):
                pass
            observed += 1
        except (psutil_module.NoSuchProcess, psutil_module.AccessDenied):
            continue
    return {
        "rss": rss,
        "user_cpu": user_cpu,
        "system_cpu": system_cpu,
        "read_bytes": read_bytes,
        "write_bytes": write_bytes,
        "processes": observed,
    }


def _log_tail(path: Path, maximum_lines: int = 50) -> str:
    """Read a bounded tail from a UTF-8 command log."""

    if maximum_lines < 1:
        raise ValueError("maximum_lines must be positive")
    if not Path(path).is_file():
        return ""
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-maximum_lines:])


def run_monitored_command(
    command: Sequence[str],
    log_path: Path,
    case_id: str,
    repeat: int,
    stage: str,
    sampling_interval_seconds: float,
    environment: Optional[Mapping[str, str]] = None,
) -> StageMetrics:
    """Run an external command and sample its complete process tree.

    Args:
        command: Non-empty shell-free argument vector.
        log_path: Combined stdout and stderr log.
        case_id: Benchmark case identifier.
        repeat: One-based repeat number.
        stage: Stage label.
        sampling_interval_seconds: Positive polling interval.
        environment: Optional environment overrides.

    Returns:
        Observed stage metrics.

    Raises:
        ValueError: If arguments are invalid.
        ExternalCommandError: If the command exits unsuccessfully.
    """

    if not command:
        raise ValueError("command cannot be empty")
    if repeat < 1:
        raise ValueError("repeat must be positive")
    if sampling_interval_seconds <= 0:
        raise ValueError("sampling_interval_seconds must be positive")
    try:
        import psutil
    except ImportError as error:
        raise RuntimeError("psutil is required for benchmark monitoring") from error
    destination = Path(log_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    merged_environment = os.environ.copy()
    if environment:
        merged_environment.update(
            {str(key): str(value) for key, value in environment.items()}
        )
    LOGGER.info("Running %s: %s", stage, command_as_text(command))
    started = time.perf_counter()
    peak_rss = 0
    maximum_processes = 0
    user_cpu = 0.0
    system_cpu = 0.0
    read_bytes = 0
    write_bytes = 0
    with destination.open("w", encoding="utf-8") as handle:
        completed_process = subprocess.Popen(
            list(command),
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=merged_environment,
        )
        monitored = psutil.Process(completed_process.pid)
        while True:
            sample = _sample_process_tree(monitored, psutil)
            peak_rss = max(peak_rss, int(sample["rss"]))
            maximum_processes = max(
                maximum_processes,
                int(sample["processes"]),
            )
            user_cpu = max(user_cpu, float(sample["user_cpu"]))
            system_cpu = max(system_cpu, float(sample["system_cpu"]))
            read_bytes = max(read_bytes, int(sample["read_bytes"]))
            write_bytes = max(write_bytes, int(sample["write_bytes"]))
            exit_code = completed_process.poll()
            if exit_code is not None:
                break
            time.sleep(sampling_interval_seconds)
    wall_seconds = time.perf_counter() - started
    cpu_seconds = user_cpu + system_cpu
    metrics = StageMetrics(
        case_id=case_id,
        repeat=repeat,
        stage=stage,
        wall_seconds=wall_seconds,
        user_cpu_seconds=user_cpu,
        system_cpu_seconds=system_cpu,
        mean_cpu_equivalents=(cpu_seconds / wall_seconds if wall_seconds else 0.0),
        peak_rss_mib=peak_rss / (1024 * 1024),
        read_bytes=read_bytes,
        write_bytes=write_bytes,
        maximum_processes=maximum_processes,
        exit_code=int(exit_code),
    )
    if exit_code != 0:
        tail = _log_tail(destination)
        raise ExternalCommandError(
            f"{stage} failed with exit code {exit_code}; log: {destination}"
            + (f"\n--- log tail ---\n{tail}" if tail else "")
        )
    return metrics


def combine_metrics(
    metrics: Iterable[StageMetrics],
    case_id: str,
    repeat: int,
    stage: str,
) -> StageMetrics:
    """Combine sequential stage metrics into one derived interval.

    Args:
        metrics: One or more successful sequential stages.
        case_id: Benchmark case identifier.
        repeat: One-based repeat number.
        stage: Derived stage label.

    Returns:
        Combined wall/CPU/I/O totals and maximum peak resources.

    Raises:
        ValueError: If no metrics are supplied or identifiers conflict.
    """

    records = list(metrics)
    if not records:
        raise ValueError("At least one stage metric is required")
    if any(record.case_id != case_id or record.repeat != repeat for record in records):
        raise ValueError("Cannot combine metrics from different cases or repeats")
    wall = sum(record.wall_seconds for record in records)
    user_cpu = sum(record.user_cpu_seconds for record in records)
    system_cpu = sum(record.system_cpu_seconds for record in records)
    return StageMetrics(
        case_id=case_id,
        repeat=repeat,
        stage=stage,
        wall_seconds=wall,
        user_cpu_seconds=user_cpu,
        system_cpu_seconds=system_cpu,
        mean_cpu_equivalents=(
            (user_cpu + system_cpu) / wall if wall else 0.0
        ),
        peak_rss_mib=max(record.peak_rss_mib for record in records),
        read_bytes=sum(record.read_bytes for record in records),
        write_bytes=sum(record.write_bytes for record in records),
        maximum_processes=max(record.maximum_processes for record in records),
        exit_code=max(record.exit_code for record in records),
    )


def _resolve_scratch_root(config: BenchmarkConfiguration) -> Path:
    """Choose configured, scheduler or package-local scratch."""

    if config.scratch_root:
        root = config.scratch_root
    else:
        scheduler_value = os.environ.get("SLURM_TMPDIR") or os.environ.get("TMPDIR")
        root = (
            Path(scheduler_value).expanduser().resolve()
            if scheduler_value
            else config.output_root / "scratch"
        )
    root.mkdir(parents=True, exist_ok=True)
    if root == Path(root.anchor):
        raise ValueError("Scratch root cannot be a filesystem root")
    return root


def _archive_existing_output(
    output_directory: Path,
    failed_root: Path,
) -> None:
    """Move an incomplete prior output aside without deleting it."""

    destination = Path(output_directory)
    if not destination.exists():
        return
    if (destination / "COMPLETE").is_file():
        raise FileExistsError(f"Benchmark case is already complete: {destination}")
    failed_root = Path(failed_root)
    failed_root.mkdir(parents=True, exist_ok=True)
    archived = failed_root / (
        f"{destination.parent.name}_{destination.name}_"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{uuid.uuid4().hex[:8]}"
    )
    destination.replace(archived)


def _case_manifest(
    config: BenchmarkConfiguration,
    case: BenchmarkCase,
    repeat: int,
    diamond_version: str,
    commands: Mapping[str, Sequence[str]],
    membership_summary: Mapping[str, object],
    retained_clusters: Optional[Path],
) -> Dict[str, object]:
    """Build the immutable provenance manifest for one case repeat."""

    return {
        "schema_version": "1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "package_version": "0.1.0",
        "configuration": configuration_to_dict(config),
        "case": asdict(case),
        "repeat": repeat,
        "diamond_version": diamond_version,
        "commands": {name: list(value) for name, value in commands.items()},
        "membership_summary": dict(membership_summary),
        "retained_clusters": (
            str(retained_clusters.resolve()) if retained_clusters else None
        ),
        "platform": {
            "hostname": platform.node(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            "slurm_cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
        },
    }


def run_case(
    config: BenchmarkConfiguration,
    case_id: str,
    repeat: int,
    output_directory: Path,
    retain_clusters: bool,
) -> Path:
    """Run a complete isolated ``makedb``/cluster/realign benchmark case.

    Args:
        config: Validated benchmark configuration.
        case_id: Enabled case identifier.
        repeat: One-based repeat number.
        output_directory: Persistent case-repeat output directory.
        retain_clusters: Preserve the membership table for quality comparison.

    Returns:
        Path to the completed output directory.

    Raises:
        ValueError: If ``repeat`` exceeds the configured design.
        ExternalCommandError: If DIAMOND fails.
    """

    if repeat < 1 or repeat > config.repeats:
        raise ValueError(f"repeat must be from 1 to {config.repeats}")
    case = config.case_by_id(case_id)
    diamond_version = get_version(case)
    destination = Path(output_directory).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    _archive_existing_output(destination, config.output_root / "failed")
    staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    scratch_root = _resolve_scratch_root(config)
    scratch = Path(
        tempfile.mkdtemp(
            prefix=f"diamond-benchmark-{case.case_id}-r{repeat}-",
            dir=scratch_root,
        )
    )
    commands: Dict[str, Sequence[str]] = {}
    stage_metrics: List[StageMetrics] = []
    retained_path: Optional[Path] = None
    durable_retained_path: Optional[Path] = None
    try:
        database = scratch / "database" / "proteins.dmnd"
        cluster_tsv = scratch / "clusters" / "clusters.tsv"
        realignment_tsv = scratch / "clusters" / "realignments.tsv"
        temporary_directory = scratch / "diamond_tmp"
        for path in (database.parent, cluster_tsv.parent, temporary_directory):
            path.mkdir(parents=True, exist_ok=True)
        commands["makedb"] = build_makedb_command(
            case,
            config.input_fasta,
            database,
            config.threads,
        )
        stage_metrics.append(
            run_monitored_command(
                commands["makedb"],
                staging / "logs" / "makedb.log",
                case.case_id,
                repeat,
                "makedb",
                config.sampling_interval_seconds,
            )
        )
        commands["cluster"] = build_cluster_command(
            case,
            database,
            cluster_tsv,
            config.threads,
            config.memory_limit,
            temporary_directory,
        )
        cluster_metric = run_monitored_command(
            commands["cluster"],
            staging / "logs" / "cluster.log",
            case.case_id,
            repeat,
            "cluster",
            config.sampling_interval_seconds,
        )
        stage_metrics.append(cluster_metric)
        pairwise_parts = [cluster_metric]
        if case.run_realign:
            commands["realign"] = build_realign_command(
                case,
                database,
                cluster_tsv,
                realignment_tsv,
                config.threads,
                config.memory_limit,
                temporary_directory,
            )
            realign_metric = run_monitored_command(
                commands["realign"],
                staging / "logs" / "realign.log",
                case.case_id,
                repeat,
                "realign",
                config.sampling_interval_seconds,
            )
            stage_metrics.append(realign_metric)
            pairwise_parts.append(realign_metric)
        pairwise_metric = combine_metrics(
            pairwise_parts,
            case.case_id,
            repeat,
            "pairwise_pipeline",
        )
        total_metric = combine_metrics(
            [stage_metrics[0], *pairwise_parts],
            case.case_id,
            repeat,
            "total_pipeline",
        )
        stage_metrics.extend([pairwise_metric, total_metric])
        membership_summary = summarise_membership(cluster_tsv)
        membership_summary.update(
            {
                "case_id": case.case_id,
                "repeat": repeat,
                "retained": retain_clusters,
            }
        )
        if config.expected_sequences is not None:
            observed = int(membership_summary["membership_rows"])
            if observed != config.expected_sequences:
                raise ExternalCommandError(
                    f"{case.case_id} produced {observed} memberships; "
                    f"expected {config.expected_sequences}"
                )
        write_tsv(
            staging / "metrics.tsv",
            [asdict(metric) for metric in stage_metrics],
            METRIC_FIELDS,
        )
        write_tsv(
            staging / "cluster_summary.tsv",
            [membership_summary],
            list(membership_summary),
        )
        if retain_clusters:
            retained_path = staging / "clusters.tsv"
            durable_retained_path = destination / "clusters.tsv"
            shutil.copy2(cluster_tsv, retained_path)
        manifest = _case_manifest(
            config,
            case,
            repeat,
            diamond_version,
            commands,
            membership_summary,
            durable_retained_path,
        )
        write_json(staging / "case_manifest.json", manifest)
        (staging / "COMPLETE").write_text(
            f"{datetime.now(timezone.utc).isoformat()}\n",
            encoding="utf-8",
        )
        os.replace(staging, destination)
    except BaseException as error:
        write_json(
            staging / "failure.json",
            {
                "case_id": case.case_id,
                "repeat": repeat,
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
        failed_root = config.output_root / "failed"
        failed_root.mkdir(parents=True, exist_ok=True)
        failed_path = failed_root / (
            f"{case.case_id}_repeat_{repeat}_{uuid.uuid4().hex[:8]}"
        )
        os.replace(staging, failed_path)
        raise
    finally:
        if scratch.exists() and scratch.parent == scratch_root:
            shutil.rmtree(scratch)
    return destination


def read_metrics(path: Path) -> List[StageMetrics]:
    """Read typed stage metrics from a package TSV.

    Args:
        path: ``metrics.tsv`` path.

    Returns:
        Ordered stage metrics.
    """

    records: List[StageMetrics] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != METRIC_FIELDS:
            raise ValueError(f"Unexpected metrics columns in {path}")
        for row in reader:
            records.append(
                StageMetrics(
                    case_id=row["case_id"],
                    repeat=int(row["repeat"]),
                    stage=row["stage"],
                    wall_seconds=float(row["wall_seconds"]),
                    user_cpu_seconds=float(row["user_cpu_seconds"]),
                    system_cpu_seconds=float(row["system_cpu_seconds"]),
                    mean_cpu_equivalents=float(row["mean_cpu_equivalents"]),
                    peak_rss_mib=float(row["peak_rss_mib"]),
                    read_bytes=int(row["read_bytes"]),
                    write_bytes=int(row["write_bytes"]),
                    maximum_processes=int(row["maximum_processes"]),
                    exit_code=int(row["exit_code"]),
                )
            )
    return records


def validate_runtime(config: BenchmarkConfiguration) -> Dict[str, object]:
    """Validate every enabled DIAMOND executable before expensive work.

    Args:
        config: Validated benchmark configuration.

    Returns:
        Runtime audit suitable for JSON output.
    """

    rows = []
    for case in config.enabled_cases:
        rows.append(
            {
                "case_id": case.case_id,
                "expected_version": case.expected_version,
                "observed_version": get_version(case),
                "executable": case.executable,
                "conda_environment": case.conda_environment,
                "status": "PASS",
            }
        )
    return {
        "status": "PASS",
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "cases": rows,
    }
