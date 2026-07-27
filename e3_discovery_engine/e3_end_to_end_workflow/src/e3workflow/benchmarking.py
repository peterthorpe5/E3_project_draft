"""Detailed stage resource monitoring and workflow benchmark aggregation."""

from __future__ import annotations

import csv
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import resource as _resource
except ImportError:  # pragma: no cover - unavailable on Windows.
    _resource = None

import psutil

from e3workflow import __version__
from e3workflow.config import STAGE_NAMES, WorkflowConfig
from e3workflow.errors import WorkflowError
from e3workflow.io_utils import (
    atomic_write_json,
    inventory_files,
    read_json,
    read_tsv,
    utc_now,
    write_tsv,
)

_PROCESS_EXCEPTIONS = (
    psutil.AccessDenied,
    psutil.NoSuchProcess,
    psutil.ZombieProcess,
)


@dataclass(frozen=True)
class CpuUsageSnapshot:
    """Store cumulative POSIX CPU counters for the process and its children."""

    self_user_seconds: float
    self_system_seconds: float
    children_user_seconds: float
    children_system_seconds: float


@dataclass(frozen=True)
class ProcessCounters:
    """Store cumulative counters observed for one process identity."""

    user_cpu_seconds: float = 0.0
    system_cpu_seconds: float = 0.0
    read_bytes: int = 0
    write_bytes: int = 0
    read_count: int = 0
    write_count: int = 0
    voluntary_context_switches: int = 0
    involuntary_context_switches: int = 0


@dataclass(frozen=True)
class ResourceSample:
    """Describe one process-tree sample during a workflow stage."""

    stage_name: str
    sampled_at_utc: str
    elapsed_seconds: float
    process_count: int
    thread_count: int
    rss_bytes: int
    vms_bytes: int
    cumulative_user_cpu_seconds: float
    cumulative_system_cpu_seconds: float
    cumulative_total_cpu_seconds: float
    interval_cpu_cores: float
    interval_cpu_percent_of_allocation: float
    cumulative_read_bytes: int
    cumulative_write_bytes: int

    def as_record(self) -> dict[str, object]:
        """Return a serialisable representation in field order."""
        return dict(asdict(self))


@dataclass(frozen=True)
class StageResourceUsage:
    """Describe measured process-tree resources for one complete stage execution."""

    stage_name: str
    status: str
    return_code: int
    measurement_scope: str
    root_pid: int
    started_at_utc: str
    finished_at_utc: str
    wall_seconds: float
    user_cpu_seconds: float
    system_cpu_seconds: float
    total_cpu_seconds: float
    cpu_accounting_method: str
    memory_accounting_method: str
    mean_cpu_cores: float
    mean_cpu_percent_of_one_core: float
    cpu_efficiency_percent: float
    peak_rss_bytes: int
    peak_rss_mb: float
    peak_rss_gb: float
    peak_vms_bytes: int
    peak_vms_mb: float
    maximum_process_count: int
    maximum_thread_count: int
    read_bytes: int
    write_bytes: int
    read_count: int
    write_count: int
    voluntary_context_switches: int
    involuntary_context_switches: int
    sample_count: int
    sampling_interval_seconds: float
    requested_threads: int
    requested_memory_mb: int
    requested_runtime_minutes: int
    requested_memory_used_percent: float
    hostname: str
    platform: str
    python_version: str
    package_version: str
    logical_cpu_count: int
    physical_cpu_count: int
    system_total_memory_mb: float
    scheduler: str
    slurm_job_id: str
    slurm_job_name: str
    slurm_account: str
    slurm_partition: str
    slurm_node_list: str
    slurm_cpus_per_task: str
    slurm_mem_per_node: str
    slurm_mem_per_cpu: str

    def as_record(self) -> dict[str, object]:
        """Return a serialisable representation in field order."""
        return dict(asdict(self))


def capture_cpu_usage_snapshot() -> CpuUsageSnapshot | None:
    """Capture cumulative POSIX CPU counters when supported.

    Returns:
        CPU counters for the current process and waited-for children, or ``None`` when the
        platform does not provide :func:`resource.getrusage`.
    """
    if _resource is None:
        return None
    self_usage = _resource.getrusage(_resource.RUSAGE_SELF)
    child_usage = _resource.getrusage(_resource.RUSAGE_CHILDREN)
    return CpuUsageSnapshot(
        self_user_seconds=float(self_usage.ru_utime),
        self_system_seconds=float(self_usage.ru_stime),
        children_user_seconds=float(child_usage.ru_utime),
        children_system_seconds=float(child_usage.ru_stime),
    )


def cpu_usage_delta(
    started: CpuUsageSnapshot | None,
    finished: CpuUsageSnapshot | None,
) -> tuple[float, float] | None:
    """Return user and system CPU consumed between two POSIX snapshots.

    Args:
        started: CPU counters collected before the stage.
        finished: CPU counters collected after the stage.

    Returns:
        ``(user_seconds, system_seconds)`` or ``None`` when either snapshot is unavailable.
    """
    if started is None or finished is None:
        return None
    user_seconds = (
        finished.self_user_seconds
        + finished.children_user_seconds
        - started.self_user_seconds
        - started.children_user_seconds
    )
    system_seconds = (
        finished.self_system_seconds
        + finished.children_system_seconds
        - started.self_system_seconds
        - started.children_system_seconds
    )
    return max(0.0, user_seconds), max(0.0, system_seconds)


def rusage_peak_rss_bytes() -> int:
    """Return a labelled-fallback peak RSS estimate from POSIX resource counters.

    Returns:
        Sum of current-process and child-process ``ru_maxrss`` values in bytes, or zero when POSIX
        resource counters are unavailable. The value is a fallback and is not interpreted as a
        sampled simultaneous process-tree peak.
    """
    if _resource is None:
        return 0
    self_peak = int(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss)
    children_peak = int(_resource.getrusage(_resource.RUSAGE_CHILDREN).ru_maxrss)
    multiplier = 1 if platform.system() == "Darwin" else 1024
    return max(0, self_peak + children_peak) * multiplier


def _utc_now_precise() -> str:
    """Return a timezone-aware UTC timestamp with microsecond precision."""
    return datetime.now(timezone.utc).isoformat()


def _maximum_counters(first: ProcessCounters, second: ProcessCounters) -> ProcessCounters:
    """Return component-wise maxima for two cumulative process snapshots."""
    return ProcessCounters(
        user_cpu_seconds=max(first.user_cpu_seconds, second.user_cpu_seconds),
        system_cpu_seconds=max(first.system_cpu_seconds, second.system_cpu_seconds),
        read_bytes=max(first.read_bytes, second.read_bytes),
        write_bytes=max(first.write_bytes, second.write_bytes),
        read_count=max(first.read_count, second.read_count),
        write_count=max(first.write_count, second.write_count),
        voluntary_context_switches=max(
            first.voluntary_context_switches,
            second.voluntary_context_switches,
        ),
        involuntary_context_switches=max(
            first.involuntary_context_switches,
            second.involuntary_context_switches,
        ),
    )


def _counter_delta(observed: ProcessCounters, baseline: ProcessCounters) -> ProcessCounters:
    """Subtract a baseline from cumulative process counters without returning negatives."""
    return ProcessCounters(
        user_cpu_seconds=max(0.0, observed.user_cpu_seconds - baseline.user_cpu_seconds),
        system_cpu_seconds=max(0.0, observed.system_cpu_seconds - baseline.system_cpu_seconds),
        read_bytes=max(0, observed.read_bytes - baseline.read_bytes),
        write_bytes=max(0, observed.write_bytes - baseline.write_bytes),
        read_count=max(0, observed.read_count - baseline.read_count),
        write_count=max(0, observed.write_count - baseline.write_count),
        voluntary_context_switches=max(
            0,
            observed.voluntary_context_switches - baseline.voluntary_context_switches,
        ),
        involuntary_context_switches=max(
            0,
            observed.involuntary_context_switches - baseline.involuntary_context_switches,
        ),
    )


def _sum_counters(counters: Sequence[ProcessCounters]) -> ProcessCounters:
    """Sum cumulative counters across process identities."""
    return ProcessCounters(
        user_cpu_seconds=sum(item.user_cpu_seconds for item in counters),
        system_cpu_seconds=sum(item.system_cpu_seconds for item in counters),
        read_bytes=sum(item.read_bytes for item in counters),
        write_bytes=sum(item.write_bytes for item in counters),
        read_count=sum(item.read_count for item in counters),
        write_count=sum(item.write_count for item in counters),
        voluntary_context_switches=sum(item.voluntary_context_switches for item in counters),
        involuntary_context_switches=sum(
            item.involuntary_context_switches for item in counters
        ),
    )


def _scheduler_context() -> dict[str, str]:
    """Return stable scheduler metadata from the current environment."""
    job_id = os.environ.get("SLURM_JOB_ID", "")
    return {
        "scheduler": "slurm" if job_id else "local",
        "slurm_job_id": job_id,
        "slurm_job_name": os.environ.get("SLURM_JOB_NAME", ""),
        "slurm_account": os.environ.get("SLURM_JOB_ACCOUNT", ""),
        "slurm_partition": os.environ.get("SLURM_JOB_PARTITION", ""),
        "slurm_node_list": os.environ.get("SLURM_JOB_NODELIST", ""),
        "slurm_cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK", ""),
        "slurm_mem_per_node": os.environ.get("SLURM_MEM_PER_NODE", ""),
        "slurm_mem_per_cpu": os.environ.get("SLURM_MEM_PER_CPU", ""),
    }


class ProcessTreeResourceMonitor:
    """Sample CPU, memory, process, thread and I/O use for a process tree."""

    def __init__(
        self,
        *,
        stage_name: str,
        requested_threads: int,
        requested_memory_mb: int,
        requested_runtime_minutes: int,
        sample_interval_seconds: float,
        root_pid: int | None = None,
    ) -> None:
        """Initialise an inactive resource monitor.

        Args:
            stage_name: Stable workflow-stage label.
            requested_threads: Configured CPU allocation for the stage.
            requested_memory_mb: Configured memory allocation in MiB.
            requested_runtime_minutes: Configured runtime limit in minutes.
            sample_interval_seconds: Positive delay between process-tree samples.
            root_pid: Optional process-tree root; defaults to the current process.

        Raises:
            ValueError: If any label or numeric setting is invalid.
        """
        if not str(stage_name).strip():
            raise ValueError("stage_name must be a non-empty string")
        for value, label in (
            (requested_threads, "requested_threads"),
            (requested_memory_mb, "requested_memory_mb"),
            (requested_runtime_minutes, "requested_runtime_minutes"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{label} must be a positive integer")
        if sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be positive")
        selected_pid = os.getpid() if root_pid is None else int(root_pid)
        if selected_pid < 1:
            raise ValueError("root_pid must be a positive integer")
        self.stage_name = str(stage_name)
        self.requested_threads = requested_threads
        self.requested_memory_mb = requested_memory_mb
        self.requested_runtime_minutes = requested_runtime_minutes
        self.sample_interval_seconds = float(sample_interval_seconds)
        self.root_pid = selected_pid
        try:
            self._root_process: psutil.Process | None = psutil.Process(selected_pid)
        except _PROCESS_EXCEPTIONS:
            self._root_process = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started_monotonic: float | None = None
        self._started_at_utc: str | None = None
        self._cpu_snapshot_started: CpuUsageSnapshot | None = None
        self._initial_sample = True
        self._baselines: dict[tuple[int, float], ProcessCounters] = {}
        self._maximum_counters: dict[tuple[int, float], ProcessCounters] = {}
        self._peak_rss_bytes = 0
        self._peak_vms_bytes = 0
        self._maximum_process_count = 0
        self._maximum_thread_count = 0
        self._samples: list[ResourceSample] = []
        self._previous_sample_elapsed = 0.0
        self._previous_sample_cpu = 0.0

    def start(self) -> None:
        """Start asynchronous process-tree sampling.

        Raises:
            RuntimeError: If the monitor has already been started.
        """
        if self._thread is not None:
            raise RuntimeError("The resource monitor has already been started")
        self._started_monotonic = time.monotonic()
        self._started_at_utc = _utc_now_precise()
        self._cpu_snapshot_started = capture_cpu_usage_snapshot()
        self._sample_once()
        self._thread = threading.Thread(
            target=self._sampling_loop,
            name=f"resource-monitor-{self.stage_name}",
            daemon=True,
        )
        self._thread.start()

    def _sampling_loop(self) -> None:
        """Collect samples until the stop event is set."""
        while not self._stop_event.wait(self.sample_interval_seconds):
            self._sample_once()

    @staticmethod
    def _read_process(
        process: psutil.Process,
    ) -> tuple[tuple[int, float], ProcessCounters, int, int, int] | None:
        """Read one best-effort process snapshot.

        Args:
            process: Process to inspect.

        Returns:
            Identity, cumulative counters, RSS, VMS and thread count, or ``None`` when the process
            disappears or access is denied during sampling.
        """
        try:
            identity = (process.pid, process.create_time())
            memory = process.memory_info()
            cpu = process.cpu_times()
            thread_count = process.num_threads()
            try:
                io_counters = process.io_counters()
            except (AttributeError, NotImplementedError, OSError, *_PROCESS_EXCEPTIONS):
                io_counters = None
            try:
                context_switches = process.num_ctx_switches()
            except (AttributeError, NotImplementedError, OSError, *_PROCESS_EXCEPTIONS):
                context_switches = None
        except (OSError, *_PROCESS_EXCEPTIONS):
            return None
        counters = ProcessCounters(
            user_cpu_seconds=float(cpu.user),
            system_cpu_seconds=float(cpu.system),
            read_bytes=int(getattr(io_counters, "read_bytes", 0)),
            write_bytes=int(getattr(io_counters, "write_bytes", 0)),
            read_count=int(getattr(io_counters, "read_count", 0)),
            write_count=int(getattr(io_counters, "write_count", 0)),
            voluntary_context_switches=int(getattr(context_switches, "voluntary", 0)),
            involuntary_context_switches=int(getattr(context_switches, "involuntary", 0)),
        )
        return identity, counters, int(memory.rss), int(memory.vms), int(thread_count)

    def _relative_totals(self) -> ProcessCounters:
        """Return cumulative counters relative to processes present at monitor start."""
        values = []
        for identity, observed in self._maximum_counters.items():
            baseline = self._baselines.get(identity, ProcessCounters())
            values.append(_counter_delta(observed, baseline))
        return _sum_counters(values)

    def _sample_once(self) -> None:
        """Collect one best-effort process-tree sample."""
        if self._started_monotonic is None:
            return
        try:
            if self._root_process is None:
                processes = []
            else:
                processes = [self._root_process]
                processes.extend(self._root_process.children(recursive=True))
        except _PROCESS_EXCEPTIONS:
            processes = []
        current_rss = 0
        current_vms = 0
        process_count = 0
        thread_count = 0
        observed: list[tuple[tuple[int, float], ProcessCounters]] = []
        for process in processes:
            snapshot = self._read_process(process=process)
            if snapshot is None:
                continue
            identity, counters, rss_bytes, vms_bytes, threads = snapshot
            observed.append((identity, counters))
            current_rss += rss_bytes
            current_vms += vms_bytes
            process_count += 1
            thread_count += threads
        with self._lock:
            for identity, counters in observed:
                if self._initial_sample:
                    self._baselines[identity] = counters
                self._maximum_counters[identity] = _maximum_counters(
                    self._maximum_counters.get(identity, ProcessCounters()),
                    counters,
                )
            self._initial_sample = False
            self._peak_rss_bytes = max(self._peak_rss_bytes, current_rss)
            self._peak_vms_bytes = max(self._peak_vms_bytes, current_vms)
            self._maximum_process_count = max(self._maximum_process_count, process_count)
            self._maximum_thread_count = max(self._maximum_thread_count, thread_count)
            elapsed = max(0.0, time.monotonic() - self._started_monotonic)
            totals = self._relative_totals()
            total_cpu = totals.user_cpu_seconds + totals.system_cpu_seconds
            interval_wall = elapsed - self._previous_sample_elapsed
            interval_cpu = total_cpu - self._previous_sample_cpu
            interval_cores = max(0.0, interval_cpu / interval_wall) if interval_wall > 0 else 0.0
            allocation_percent = 100.0 * interval_cores / self.requested_threads
            self._samples.append(
                ResourceSample(
                    stage_name=self.stage_name,
                    sampled_at_utc=_utc_now_precise(),
                    elapsed_seconds=elapsed,
                    process_count=process_count,
                    thread_count=thread_count,
                    rss_bytes=current_rss,
                    vms_bytes=current_vms,
                    cumulative_user_cpu_seconds=totals.user_cpu_seconds,
                    cumulative_system_cpu_seconds=totals.system_cpu_seconds,
                    cumulative_total_cpu_seconds=total_cpu,
                    interval_cpu_cores=interval_cores,
                    interval_cpu_percent_of_allocation=allocation_percent,
                    cumulative_read_bytes=totals.read_bytes,
                    cumulative_write_bytes=totals.write_bytes,
                )
            )
            self._previous_sample_elapsed = elapsed
            self._previous_sample_cpu = total_cpu

    def stop(
        self,
        *,
        return_code: int = 0,
        status: str | None = None,
    ) -> tuple[StageResourceUsage, tuple[ResourceSample, ...]]:
        """Stop sampling and return the summary plus detailed samples.

        Args:
            return_code: Stage or external-process return code.
            status: Explicit completion status; inferred from the return code when omitted.

        Returns:
            Stage summary and immutable ordered resource samples.

        Raises:
            RuntimeError: If monitoring was not started or was already stopped.
        """
        if self._thread is None or self._started_monotonic is None:
            raise RuntimeError("The resource monitor has not been started")
        if self._stop_event.is_set():
            raise RuntimeError("The resource monitor has already been stopped")
        self._stop_event.set()
        self._thread.join(timeout=max(1.0, self.sample_interval_seconds * 5.0))
        self._sample_once()
        finished_monotonic = time.monotonic()
        finished_cpu_snapshot = capture_cpu_usage_snapshot()
        exact_cpu = cpu_usage_delta(self._cpu_snapshot_started, finished_cpu_snapshot)
        with self._lock:
            sampled_totals = self._relative_totals()
            peak_rss = self._peak_rss_bytes
            peak_vms = self._peak_vms_bytes
            maximum_process_count = self._maximum_process_count
            maximum_thread_count = self._maximum_thread_count
            samples = tuple(self._samples)
        if exact_cpu is None:
            user_cpu = sampled_totals.user_cpu_seconds
            system_cpu = sampled_totals.system_cpu_seconds
            cpu_method = "psutil_sampled_process_tree_delta"
        else:
            user_cpu, system_cpu = exact_cpu
            cpu_method = "posix_rusage_self_and_children_delta"
        wall_seconds = max(0.0, finished_monotonic - self._started_monotonic)
        total_cpu = user_cpu + system_cpu
        mean_cpu_cores = total_cpu / wall_seconds if wall_seconds > 0 else 0.0
        peak_rss_mb = peak_rss / (1024.0**2)
        if peak_rss > 0:
            memory_method = "psutil_sampled_process_tree"
        else:
            peak_rss = rusage_peak_rss_bytes()
            peak_rss_mb = peak_rss / (1024.0**2)
            memory_method = (
                "posix_rusage_self_plus_children_peak_fallback"
                if peak_rss > 0
                else "unavailable"
            )
        scheduler = _scheduler_context()
        resolved_status = status or ("complete" if int(return_code) == 0 else "failed")
        usage = StageResourceUsage(
            stage_name=self.stage_name,
            status=resolved_status,
            return_code=int(return_code),
            measurement_scope="stage_execution_before_checksum_inventory_and_atomic_publication",
            root_pid=self.root_pid,
            started_at_utc=str(self._started_at_utc),
            finished_at_utc=_utc_now_precise(),
            wall_seconds=wall_seconds,
            user_cpu_seconds=user_cpu,
            system_cpu_seconds=system_cpu,
            total_cpu_seconds=total_cpu,
            cpu_accounting_method=cpu_method,
            memory_accounting_method=memory_method,
            mean_cpu_cores=mean_cpu_cores,
            mean_cpu_percent_of_one_core=mean_cpu_cores * 100.0,
            cpu_efficiency_percent=mean_cpu_cores * 100.0 / self.requested_threads,
            peak_rss_bytes=peak_rss,
            peak_rss_mb=peak_rss_mb,
            peak_rss_gb=peak_rss / (1024.0**3),
            peak_vms_bytes=peak_vms,
            peak_vms_mb=peak_vms / (1024.0**2),
            maximum_process_count=maximum_process_count,
            maximum_thread_count=maximum_thread_count,
            read_bytes=sampled_totals.read_bytes,
            write_bytes=sampled_totals.write_bytes,
            read_count=sampled_totals.read_count,
            write_count=sampled_totals.write_count,
            voluntary_context_switches=sampled_totals.voluntary_context_switches,
            involuntary_context_switches=sampled_totals.involuntary_context_switches,
            sample_count=len(samples),
            sampling_interval_seconds=self.sample_interval_seconds,
            requested_threads=self.requested_threads,
            requested_memory_mb=self.requested_memory_mb,
            requested_runtime_minutes=self.requested_runtime_minutes,
            requested_memory_used_percent=100.0 * peak_rss_mb / self.requested_memory_mb,
            hostname=socket.gethostname(),
            platform=platform.platform(),
            python_version=platform.python_version(),
            package_version=__version__,
            logical_cpu_count=int(psutil.cpu_count(logical=True) or 0),
            physical_cpu_count=int(psutil.cpu_count(logical=False) or 0),
            system_total_memory_mb=psutil.virtual_memory().total / (1024.0**2),
            **scheduler,
        )
        return usage, samples


def write_stage_resource_outputs(
    *,
    stage_root: Path,
    usage: StageResourceUsage,
    samples: Sequence[ResourceSample],
) -> dict[str, Path]:
    """Write one stage summary, JSON metadata and compressed time series.

    Args:
        stage_root: Temporary or formal stage directory.
        usage: Completed stage-level resource measurement.
        samples: Ordered process-tree resource samples.

    Returns:
        Named resolved output paths.
    """
    benchmark_root = Path(stage_root) / "benchmark"
    summary_tsv = benchmark_root / "stage_resource_usage.tsv"
    summary_json = benchmark_root / "stage_resource_usage.json"
    timeseries_tsv = benchmark_root / "stage_resource_timeseries.tsv.gz"
    write_tsv(
        path=summary_tsv,
        rows=[usage.as_record()],
        columns=tuple(usage.as_record()),
    )
    sample_records = [sample.as_record() for sample in samples]
    sample_columns = tuple(ResourceSample.__dataclass_fields__)
    write_tsv(path=timeseries_tsv, rows=sample_records, columns=sample_columns)
    atomic_write_json(
        path=summary_json,
        payload={
            "resource_usage": usage.as_record(),
            "timeseries_path": timeseries_tsv.name,
            "timeseries_rows": len(samples),
        },
    )
    return {
        "summary_tsv": summary_tsv.resolve(),
        "summary_json": summary_json.resolve(),
        "timeseries_tsv": timeseries_tsv.resolve(),
    }


def read_stage_resource_usage(path: Path) -> dict[str, str]:
    """Read and minimally validate one stage resource summary.

    Args:
        path: One-row resource-summary TSV.

    Returns:
        String-valued resource record.

    Raises:
        WorkflowError: If the table is missing, malformed or incomplete.
    """
    columns, rows = read_tsv(path=path)
    required = set(StageResourceUsage.__dataclass_fields__)
    missing = required.difference(columns)
    if missing:
        raise WorkflowError(
            f"Stage resource table lacks columns {', '.join(sorted(missing))}: {path}"
        )
    if len(rows) != 1:
        raise WorkflowError(f"Stage resource table must contain exactly one row: {path}")
    return rows[0]


def _float_value(record: Mapping[str, str], key: str) -> float:
    """Return one required finite-enough numeric field from a TSV record."""
    raw = str(record.get(key, "")).strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise WorkflowError(f"Benchmark field {key!r} is not numeric: {raw!r}") from exc


SLURM_ACCOUNTING_COLUMNS = (
    "JobIDRaw",
    "JobName",
    "State",
    "ExitCode",
    "ElapsedRaw",
    "TotalCPU",
    "AllocCPUS",
    "ReqMem",
    "MaxRSS",
    "MaxVMSize",
    "AveRSS",
    "AveVMSize",
    "MaxDiskRead",
    "MaxDiskWrite",
    "NNodes",
    "NTasks",
    "NodeList",
)


def collect_slurm_accounting(
    job_ids: Sequence[str],
) -> tuple[dict[str, object], list[dict[str, str]]]:
    """Collect best-effort Slurm accounting rows for completed stage jobs.

    Args:
        job_ids: Slurm allocation identifiers captured inside stages.

    Returns:
        Status metadata and raw ``sacct`` rows. Scheduler unavailability does not raise because
        process-tree and runner measurements remain authoritative observed metrics.
    """
    unique_ids = sorted({str(job_id).strip() for job_id in job_ids if str(job_id).strip()})
    executable = shutil.which("sacct")
    if not unique_ids:
        return {"status": "not_applicable", "message": "No Slurm job IDs were recorded."}, []
    if executable is None:
        return {"status": "unavailable", "message": "sacct is not on PATH."}, []
    command = [
        executable,
        "--jobs",
        ",".join(unique_ids),
        "--parsable2",
        "--units=M",
        "--format=" + ",".join(SLURM_ACCOUNTING_COLUMNS),
    ]
    completed = subprocess.run(
        args=command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or f"sacct returned {completed.returncode}"
        return {"status": "failed", "message": message}, []
    reader = csv.DictReader(completed.stdout.splitlines(), delimiter="|")
    rows = [
        {column: str(row.get(column, "")) for column in SLURM_ACCOUNTING_COLUMNS}
        for row in reader
        if str(row.get("JobIDRaw", "")).strip()
    ]
    return {
        "status": "collected",
        "message": f"Collected {len(rows)} allocation and step records.",
    }, rows


def _workflow_metrics(records: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    """Calculate run-level metrics without conflating parallel and summed wall time."""
    starts = [datetime.fromisoformat(record["started_at_utc"]) for record in records]
    finishes = [datetime.fromisoformat(record["finished_at_utc"]) for record in records]
    summed_wall = sum(_float_value(record=record, key="wall_seconds") for record in records)
    summed_runner_wall = sum(
        _float_value(record=record, key="runner_wall_seconds") for record in records
    )
    observed_span = (max(finishes) - min(starts)).total_seconds()
    total_cpu = sum(_float_value(record=record, key="total_cpu_seconds") for record in records)
    total_read = sum(int(record["read_bytes"]) for record in records)
    total_write = sum(int(record["write_bytes"]) for record in records)
    requested_core_seconds = sum(
        _float_value(record=record, key="wall_seconds")
        * _float_value(record=record, key="requested_threads")
        for record in records
    )
    peak_rss = max(_float_value(record=record, key="peak_rss_mb") for record in records)
    peak_memory_fraction = max(
        _float_value(record=record, key="requested_memory_used_percent")
        for record in records
    )
    maximum_processes = max(int(record["maximum_process_count"]) for record in records)
    maximum_threads = max(int(record["maximum_thread_count"]) for record in records)
    total_samples = sum(int(record["sample_count"]) for record in records)
    output_bytes = sum(int(record["output_bytes"]) for record in records)
    metrics = [
        (
            "stage_count",
            len(records),
            "stages",
            "Number of completed or explicitly skipped workflow stages.",
        ),
        (
            "workflow_observed_span_seconds",
            observed_span,
            "seconds",
            "Earliest retained stage start to latest finish; includes concurrency and resume gaps.",
        ),
        (
            "sum_stage_wall_seconds",
            summed_wall,
            "seconds",
            "Sum of stage wall times; exceeds elapsed time when branches overlap.",
        ),
        (
            "sum_stage_runner_wall_seconds",
            summed_runner_wall,
            "seconds",
            "Sum of broader per-stage runner times through checksum inventory.",
        ),
        (
            "sum_stage_orchestration_overhead_seconds",
            max(0.0, summed_runner_wall - summed_wall),
            "seconds",
            "Runner time outside the sampled scientific-stage scope, summed across stages.",
        ),
        (
            "parallelisation_factor",
            summed_wall / observed_span if observed_span > 0 else 0.0,
            "ratio",
            "Summed stage wall time divided by retained authority span; use a fresh full run.",
        ),
        (
            "total_cpu_seconds",
            total_cpu,
            "seconds",
            "Sum of monitored user and system CPU time across stages.",
        ),
        (
            "requested_cpu_efficiency_percent",
            100.0 * total_cpu / requested_core_seconds if requested_core_seconds > 0 else 0.0,
            "percent",
            (
                "CPU time divided by configured thread-seconds; values above 100 indicate "
                "oversubscription."
            ),
        ),
        (
            "maximum_individual_stage_peak_rss_mb",
            peak_rss,
            "MiB",
            "Largest sampled process-tree peak RSS for any one stage; not concurrent workflow RAM.",
        ),
        (
            "maximum_stage_memory_request_used_percent",
            peak_memory_fraction,
            "percent",
            "Largest observed stage peak RSS as a percentage of that stage's memory request.",
        ),
        (
            "maximum_individual_stage_process_count",
            maximum_processes,
            "processes",
            "Largest sampled visible process-tree count for any one stage.",
        ),
        (
            "maximum_individual_stage_thread_count",
            maximum_threads,
            "threads",
            "Largest sampled visible thread count for any one stage.",
        ),
        (
            "total_process_tree_samples",
            total_samples,
            "samples",
            "Number of detailed process-tree observations retained across all stages.",
        ),
        (
            "total_sampled_read_bytes",
            total_read,
            "bytes",
            "Sum of sampled stage process-tree read counters.",
        ),
        (
            "total_sampled_write_bytes",
            total_write,
            "bytes",
            "Sum of sampled stage process-tree write counters.",
        ),
        (
            "total_published_output_bytes",
            output_bytes,
            "bytes",
            "Sum of checksummed files recorded in all stage manifests.",
        ),
    ]
    return [
        {"metric": name, "value": value, "unit": unit, "interpretation": interpretation}
        for name, value, unit, interpretation in metrics
    ]


def aggregate_run_benchmarks(
    *,
    config: WorkflowConfig,
    output_dir: Path,
) -> dict[str, object]:
    """Merge stage, Snakemake, manifest and optional Slurm benchmark evidence.

    Args:
        config: Validated workflow configuration.
        output_dir: Formal benchmark-summary directory.

    Returns:
        Machine-readable paths and record counts.

    Raises:
        WorkflowError: If any completed stage lacks required benchmark or manifest evidence.
    """
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    merged_records: list[dict[str, str]] = []
    slurm_job_ids: list[str] = []
    for stage_name in STAGE_NAMES:
        stage_root = config.run_root / stage_name
        usage = read_stage_resource_usage(
            path=stage_root / "benchmark" / "stage_resource_usage.tsv"
        )
        if usage["stage_name"] != stage_name:
            raise WorkflowError(
                f"Stage benchmark identity differs for {stage_name}: {usage['stage_name']}"
            )
        manifest = read_json(path=stage_root / "stage_manifest.json")
        record = dict(usage)
        outputs = manifest.get("outputs")
        if not isinstance(outputs, list):
            raise WorkflowError(f"Stage manifest has no output inventory: {stage_name}")
        record["configuration_digest"] = str(manifest.get("configuration_digest", ""))
        runner_started = str(manifest.get("started_at_utc", ""))
        runner_finished = str(manifest.get("finished_at_utc", ""))
        raw_runner_wall = manifest.get("runner_wall_seconds")
        if raw_runner_wall is None:
            try:
                runner_wall = (
                    datetime.fromisoformat(runner_finished)
                    - datetime.fromisoformat(runner_started)
                ).total_seconds()
            except ValueError as exc:
                raise WorkflowError(
                    f"Stage manifest has invalid execution timestamps: {stage_name}"
                ) from exc
        else:
            try:
                runner_wall = float(raw_runner_wall)
            except (TypeError, ValueError) as exc:
                raise WorkflowError(
                    f"Stage manifest has invalid runner wall time: {stage_name}"
                ) from exc
        record["runner_started_at_utc"] = runner_started
        record["runner_finished_at_utc"] = runner_finished
        record["runner_wall_seconds"] = str(max(0.0, runner_wall))
        record["output_file_count"] = str(len(outputs))
        record["output_bytes"] = str(
            sum(int(output.get("size_bytes", 0)) for output in outputs if isinstance(output, dict))
        )
        record["stage_manifest"] = str(stage_root / "stage_manifest.json")
        record["process_timeseries"] = str(
            stage_root / "benchmark" / "stage_resource_timeseries.tsv.gz"
        )
        slurm_job_ids.append(record.get("slurm_job_id", ""))
        merged_records.append(record)
    usage_columns = list(StageResourceUsage.__dataclass_fields__)
    extra_columns = [
        "configuration_digest",
        "runner_started_at_utc",
        "runner_finished_at_utc",
        "runner_wall_seconds",
        "output_file_count",
        "output_bytes",
        "stage_manifest",
        "process_timeseries",
    ]
    record_columns = tuple(usage_columns + extra_columns)
    stage_summary = destination / "stage_resource_summary.tsv"
    workflow_summary = destination / "workflow_resource_summary.tsv"
    slurm_status_path = destination / "slurm_accounting_status.tsv"
    slurm_records_path = destination / "slurm_accounting.tsv"
    completion_path = destination / "benchmark_complete.tsv"
    manifest_path = destination / "benchmark_manifest.json"
    write_tsv(path=stage_summary, rows=merged_records, columns=record_columns)
    write_tsv(
        path=workflow_summary,
        rows=_workflow_metrics(records=merged_records),
        columns=("metric", "value", "unit", "interpretation"),
    )
    if config.benchmarking.collect_slurm_accounting:
        slurm_status, slurm_records = collect_slurm_accounting(job_ids=slurm_job_ids)
    else:
        slurm_status = {"status": "disabled", "message": "Disabled by workflow configuration."}
        slurm_records = []
    write_tsv(
        path=slurm_status_path,
        rows=[
            {
                **slurm_status,
                "queried_job_count": len({job_id for job_id in slurm_job_ids if job_id}),
            }
        ],
        columns=("status", "message", "queried_job_count"),
    )
    write_tsv(
        path=slurm_records_path,
        rows=slurm_records,
        columns=SLURM_ACCOUNTING_COLUMNS,
    )
    write_tsv(
        path=completion_path,
        rows=[
            {
                "status": "complete",
                "stage_count": len(merged_records),
                "configuration_digest": config.digest,
                "finished_at_utc": utc_now(),
            }
        ],
        columns=("status", "stage_count", "configuration_digest", "finished_at_utc"),
    )
    outputs = inventory_files(root=destination, excluded_names=frozenset({manifest_path.name}))
    atomic_write_json(
        path=manifest_path,
        payload={
            "status": "complete",
            "package_version": __version__,
            "configuration": str(config.source_path),
            "configuration_digest": config.digest,
            "run_root": str(config.run_root),
            "stage_count": len(merged_records),
            "slurm_accounting_status": slurm_status,
            "outputs": outputs,
        },
    )
    return {
        "status": "complete",
        "stage_count": len(merged_records),
        "stage_resource_summary": str(stage_summary),
        "workflow_resource_summary": str(workflow_summary),
        "slurm_accounting": str(slurm_records_path),
        "manifest": str(manifest_path),
    }
