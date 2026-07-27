"""Cross-platform process-tree CPU and memory monitoring."""

from __future__ import annotations

import csv
import logging
import os
import platform
import statistics

try:
    import resource as _resource
except ImportError:  # pragma: no cover - unavailable on Windows.
    _resource = None
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

import matplotlib.pyplot as plt
import psutil

from e3_discovery.io_utils import write_tsv

LOGGER = logging.getLogger(__name__)

_PROCESS_EXCEPTIONS = (
    psutil.AccessDenied,
    psutil.NoSuchProcess,
    psutil.ZombieProcess,
)


@dataclass(frozen=True)
class CpuUsageSnapshot:
    """Store cumulative POSIX CPU counters at one point in time.

    Attributes:
        self_user_seconds: User CPU consumed by the current process.
        self_system_seconds: System CPU consumed by the current process.
        children_user_seconds: User CPU consumed by waited-for child processes.
        children_system_seconds: System CPU consumed by waited-for children.
    """

    self_user_seconds: float
    self_system_seconds: float
    children_user_seconds: float
    children_system_seconds: float


def capture_cpu_usage_snapshot() -> CpuUsageSnapshot | None:
    """Capture cumulative POSIX process and child CPU counters.

    Returns:
        A :class:`CpuUsageSnapshot` on POSIX platforms supporting
        :func:`resource.getrusage`, otherwise ``None``.
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
    """Calculate user and system CPU consumed between two snapshots.

    The calculation combines the current Python process with waited-for child
    processes. This captures DIAMOND CPU time after ``subprocess.run`` has
    returned and avoids losing CPU consumed by child processes that terminate
    between psutil sampling points.

    Args:
        started: Baseline cumulative CPU counters.
        finished: Final cumulative CPU counters.

    Returns:
        ``(user_seconds, system_seconds)`` when both snapshots are available,
        otherwise ``None``.
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


@dataclass(frozen=True)
class ResourceUsage:
    """Describe measured resource use for one workflow stage.

    Attributes:
        stage_name: Stable name of the monitored workflow stage.
        status: Completion state such as ``success`` or ``failed``.
        return_code: Integer process or workflow return code.
        root_pid: Process identifier used as the process-tree root.
        started_at_utc: ISO-8601 UTC timestamp when monitoring began.
        finished_at_utc: ISO-8601 UTC timestamp when monitoring ended.
        wall_seconds: Elapsed wall-clock time in seconds.
        user_cpu_seconds: Summed maximum user CPU time observed per process.
        system_cpu_seconds: Summed maximum system CPU time observed per process.
        total_cpu_seconds: User plus system CPU time in seconds.
        cpu_accounting_method: Method used to calculate final CPU totals.
        peak_rss_bytes: Maximum aggregate resident memory observed across the
            process tree.
        peak_rss_mb: ``peak_rss_bytes`` converted to mebibytes.
        maximum_process_count: Largest number of simultaneously observed
            processes in the monitored tree.
        sample_count: Number of process-tree samples collected.
        sampling_interval_seconds: Requested interval between samples.
        platform: Operating-system platform reported by :mod:`psutil`.
    """

    stage_name: str
    status: str
    return_code: int
    root_pid: int
    started_at_utc: str
    finished_at_utc: str
    wall_seconds: float
    user_cpu_seconds: float
    system_cpu_seconds: float
    total_cpu_seconds: float
    cpu_accounting_method: str
    peak_rss_bytes: int
    peak_rss_mb: float
    maximum_process_count: int
    sample_count: int
    sampling_interval_seconds: float
    platform: str

    def as_record(self) -> Dict[str, object]:
        """Convert the measurement to a serialisable dictionary.

        Returns:
            Dictionary containing every dataclass field in declaration order.
        """

        return dict(asdict(self))


class ProcessTreeResourceMonitor:
    """Sample CPU time and aggregate RSS for a process and its descendants.

    The monitor runs in a daemon thread. CPU accounting retains the highest
    cumulative value observed for each process identity, so terminated child
    processes still contribute to the final total. Peak RSS is the largest
    simultaneous sum observed across the process tree.

    Attributes:
        stage_name: Name attached to the final measurement.
        sample_interval_seconds: Delay between sampling attempts.
        root_pid: Process identifier at the root of the monitored tree.
    """

    def __init__(
        self,
        stage_name: str,
        sample_interval_seconds: float = 0.2,
        root_pid: int | None = None,
    ) -> None:
        """Initialise an inactive resource monitor.

        Args:
            stage_name: Non-empty workflow-stage label.
            sample_interval_seconds: Positive interval between samples.
            root_pid: Optional process identifier; defaults to the current
                Python process.

        Returns:
            None.

        Raises:
            ValueError: If the stage name is blank, the interval is not
                positive or the process identifier is invalid.
            psutil.NoSuchProcess: If ``root_pid`` does not exist.
        """

        if not str(stage_name).strip():
            raise ValueError("stage_name must be a non-empty string")
        if sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be positive")
        selected_pid = os.getpid() if root_pid is None else int(root_pid)
        if selected_pid < 1:
            raise ValueError("root_pid must be a positive integer")
        self.stage_name = str(stage_name)
        self.sample_interval_seconds = float(sample_interval_seconds)
        self.root_pid = selected_pid
        self._root_process = psutil.Process(selected_pid)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started_monotonic: float | None = None
        self._started_at_utc: str | None = None
        self._cpu_snapshot_started: CpuUsageSnapshot | None = None
        self._peak_rss_bytes = 0
        self._maximum_process_count = 0
        self._sample_count = 0
        self._cpu_by_process: MutableMapping[
            Tuple[int, float], Tuple[float, float]
        ] = {}

    def start(self) -> None:
        """Start asynchronous process-tree sampling.

        Returns:
            None.

        Raises:
            RuntimeError: If the monitor has already been started.
        """

        if self._thread is not None:
            raise RuntimeError("The resource monitor has already been started")
        self._started_monotonic = time.monotonic()
        self._started_at_utc = datetime.now(timezone.utc).isoformat()
        self._cpu_snapshot_started = capture_cpu_usage_snapshot()
        self._sample_once()
        self._thread = threading.Thread(
            target=self._sampling_loop,
            name=f"resource-monitor-{self.stage_name}",
            daemon=True,
        )
        self._thread.start()

    def _sampling_loop(self) -> None:
        """Collect samples until the stop event is set.

        Returns:
            None.
        """

        while not self._stop_event.wait(self.sample_interval_seconds):
            self._sample_once()

    def _sample_once(self) -> None:
        """Collect one best-effort process-tree sample.

        Returns:
            None.
        """

        try:
            processes = [self._root_process]
            processes.extend(self._root_process.children(recursive=True))
        except _PROCESS_EXCEPTIONS:
            processes = []

        current_rss = 0
        observed_count = 0
        cpu_updates: Dict[Tuple[int, float], Tuple[float, float]] = {}
        for process in processes:
            try:
                identity = (process.pid, process.create_time())
                memory = process.memory_info()
                cpu = process.cpu_times()
            except _PROCESS_EXCEPTIONS:
                continue
            current_rss += int(memory.rss)
            observed_count += 1
            cpu_updates[identity] = (float(cpu.user), float(cpu.system))

        with self._lock:
            self._sample_count += 1
            self._peak_rss_bytes = max(self._peak_rss_bytes, current_rss)
            self._maximum_process_count = max(
                self._maximum_process_count,
                observed_count,
            )
            for identity, observed in cpu_updates.items():
                previous = self._cpu_by_process.get(identity, (0.0, 0.0))
                self._cpu_by_process[identity] = (
                    max(previous[0], observed[0]),
                    max(previous[1], observed[1]),
                )

    def stop(
        self,
        return_code: int = 0,
        status: str | None = None,
    ) -> ResourceUsage:
        """Stop sampling and return the final resource measurement.

        Args:
            return_code: Integer workflow-stage return code.
            status: Optional explicit status; defaults to ``success`` for zero
                and ``failed`` otherwise.

        Returns:
            Immutable :class:`ResourceUsage` measurement.

        Raises:
            RuntimeError: If monitoring has not been started or was already
                stopped.
        """

        if self._thread is None or self._started_monotonic is None:
            raise RuntimeError("The resource monitor has not been started")
        if self._stop_event.is_set():
            raise RuntimeError("The resource monitor has already been stopped")
        self._stop_event.set()
        self._thread.join(timeout=max(1.0, self.sample_interval_seconds * 5))
        self._sample_once()
        finished_monotonic = time.monotonic()
        finished_at_utc = datetime.now(timezone.utc).isoformat()
        finished_cpu_snapshot = capture_cpu_usage_snapshot()
        with self._lock:
            sampled_user_cpu = sum(
                value[0] for value in self._cpu_by_process.values()
            )
            sampled_system_cpu = sum(
                value[1] for value in self._cpu_by_process.values()
            )
            peak_rss = self._peak_rss_bytes
            maximum_process_count = self._maximum_process_count
            sample_count = self._sample_count
        exact_cpu = cpu_usage_delta(
            self._cpu_snapshot_started,
            finished_cpu_snapshot,
        )
        if exact_cpu is None:
            user_cpu = sampled_user_cpu
            system_cpu = sampled_system_cpu
            cpu_accounting_method = "psutil_sampled_process_tree"
        else:
            user_cpu, system_cpu = exact_cpu
            cpu_accounting_method = "posix_rusage_self_and_children_delta"
        resolved_status = status or (
            "success" if int(return_code) == 0 else "failed"
        )
        return ResourceUsage(
            stage_name=self.stage_name,
            status=resolved_status,
            return_code=int(return_code),
            root_pid=self.root_pid,
            started_at_utc=str(self._started_at_utc),
            finished_at_utc=finished_at_utc,
            wall_seconds=finished_monotonic - self._started_monotonic,
            user_cpu_seconds=user_cpu,
            system_cpu_seconds=system_cpu,
            total_cpu_seconds=user_cpu + system_cpu,
            cpu_accounting_method=cpu_accounting_method,
            peak_rss_bytes=peak_rss,
            peak_rss_mb=peak_rss / (1024.0 * 1024.0),
            maximum_process_count=maximum_process_count,
            sample_count=sample_count,
            sampling_interval_seconds=self.sample_interval_seconds,
            platform=platform.platform(),
        )


def write_resource_usage(usage: ResourceUsage, output_path: Path) -> Path:
    """Write one resource measurement as a one-row TSV file.

    Args:
        usage: Measurement to serialise.
        output_path: Destination TSV path.

    Returns:
        Resolved output path.

    Raises:
        OSError: If the destination cannot be written.
    """

    output = Path(output_path)
    write_tsv([usage.as_record()], output)
    return output.resolve()


def read_resource_usage(input_path: Path) -> ResourceUsage:
    """Read a one-row resource-monitor TSV file.

    Args:
        input_path: Resource-monitor TSV path.

    Returns:
        Parsed :class:`ResourceUsage` record.

    Raises:
        FileNotFoundError: If ``input_path`` does not exist.
        ValueError: If the file does not contain exactly one valid data row.
        UnicodeDecodeError: If the file is not UTF-8 text.
    """

    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != 1:
        raise ValueError(
            f"Resource file must contain exactly one data row: {path}"
        )
    row = rows[0]
    try:
        return ResourceUsage(
            stage_name=row["stage_name"],
            status=row["status"],
            return_code=int(row["return_code"]),
            root_pid=int(row["root_pid"]),
            started_at_utc=row["started_at_utc"],
            finished_at_utc=row["finished_at_utc"],
            wall_seconds=float(row["wall_seconds"]),
            user_cpu_seconds=float(row["user_cpu_seconds"]),
            system_cpu_seconds=float(row["system_cpu_seconds"]),
            total_cpu_seconds=float(row["total_cpu_seconds"]),
            cpu_accounting_method=row.get(
                "cpu_accounting_method",
                "legacy_psutil_sampled_process_tree",
            ),
            peak_rss_bytes=int(row["peak_rss_bytes"]),
            peak_rss_mb=float(row["peak_rss_mb"]),
            maximum_process_count=int(row["maximum_process_count"]),
            sample_count=int(row["sample_count"]),
            sampling_interval_seconds=float(
                row["sampling_interval_seconds"]
            ),
            platform=row["platform"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Malformed resource-monitor file: {path}") from error


def aggregate_resource_usage_directory(input_dir: Path) -> List[ResourceUsage]:
    """Read all visible resource-monitor TSV files below a directory.

    Args:
        input_dir: Directory recursively searched for ``*.tsv`` files.

    Returns:
        Measurements ordered by stage name and start time.

    Raises:
        FileNotFoundError: If ``input_dir`` is not a directory.
        ValueError: If a visible resource file is malformed.
    """

    root = Path(input_dir)
    if not root.is_dir():
        raise FileNotFoundError(root)
    records = []
    for path in sorted(root.rglob("*.tsv")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        records.append(read_resource_usage(path))
    return sorted(
        records,
        key=lambda item: (item.stage_name, item.started_at_utc),
    )


def summarise_resource_usage(
    records: Sequence[ResourceUsage],
) -> List[Dict[str, object]]:
    """Summarise repeated resource measurements by workflow stage.

    Args:
        records: Individual resource-monitor measurements.

    Returns:
        One dictionary per stage with repeat count, wall/CPU means and peak-RSS
        mean and maximum values.
    """

    grouped: Dict[str, List[ResourceUsage]] = {}
    for record in records:
        grouped.setdefault(record.stage_name, []).append(record)
    summaries = []
    for stage_name in sorted(grouped):
        values = grouped[stage_name]
        summaries.append(
            {
                "stage_name": stage_name,
                "repeat_count": len(values),
                "successful_repeats": sum(
                    record.status == "success" for record in values
                ),
                "mean_wall_seconds": statistics.fmean(
                    record.wall_seconds for record in values
                ),
                "mean_total_cpu_seconds": statistics.fmean(
                    record.total_cpu_seconds for record in values
                ),
                "cpu_accounting_methods": ";".join(
                    sorted(
                        {
                            record.cpu_accounting_method
                            for record in values
                        }
                    )
                ),
                "mean_peak_rss_mb": statistics.fmean(
                    record.peak_rss_mb for record in values
                ),
                "maximum_peak_rss_mb": max(
                    record.peak_rss_mb for record in values
                ),
                "maximum_process_count": max(
                    record.maximum_process_count for record in values
                ),
            }
        )
    return summaries


def write_resource_usage_outputs(
    records: Sequence[ResourceUsage],
    summaries: Sequence[Mapping[str, object]],
    records_tsv: Path,
    summary_tsv: Path,
) -> Tuple[Path, Path]:
    """Write detailed and stage-summary resource-monitor tables.

    Args:
        records: Individual measurements.
        summaries: Stage-level summary dictionaries.
        records_tsv: Destination for detailed records.
        summary_tsv: Destination for summaries.

    Returns:
        Resolved detailed and summary output paths.

    Raises:
        OSError: If either table cannot be written.
    """

    write_tsv([record.as_record() for record in records], records_tsv)
    write_tsv(summaries, summary_tsv)
    return Path(records_tsv).resolve(), Path(summary_tsv).resolve()


def plot_peak_ram_by_stage(
    summaries: Sequence[Mapping[str, object]],
    output_png: Path,
    output_pdf: Path | None = None,
) -> None:
    """Plot maximum measured peak RSS by workflow stage.

    Args:
        summaries: Stage summaries containing ``maximum_peak_rss_mb``.
        output_png: Destination raster figure.
        output_pdf: Optional destination vector figure.

    Returns:
        None.

    Raises:
        ValueError: If no summary records are supplied.
        OSError: If a requested figure cannot be written.
    """

    if not summaries:
        raise ValueError("summaries cannot be empty")
    ordered = sorted(
        summaries,
        key=lambda row: float(row["maximum_peak_rss_mb"]),
        reverse=True,
    )
    labels = [str(row["stage_name"]) for row in ordered]
    values = [float(row["maximum_peak_rss_mb"]) for row in ordered]
    figure, axis = plt.subplots(figsize=(10, max(4, 0.45 * len(labels))))
    positions = list(range(len(labels)))
    axis.barh(positions, values)
    axis.set_yticks(positions, labels=labels)
    axis.invert_yaxis()
    axis.set_xlabel("Peak resident memory (MiB)")
    axis.set_title("E3 discovery workflow peak RAM by stage")
    figure.tight_layout()
    Path(output_png).parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_png, dpi=300, bbox_inches="tight")
    if output_pdf is not None:
        Path(output_pdf).parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_pdf, bbox_inches="tight")
    plt.close(figure)
