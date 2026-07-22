"""Resource monitoring and benchmark aggregation tests."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

import e3workflow.benchmarking as benchmarking
from e3workflow.benchmarking import (
    SLURM_ACCOUNTING_COLUMNS,
    CpuUsageSnapshot,
    ProcessTreeResourceMonitor,
    ResourceSample,
    StageResourceUsage,
    aggregate_run_benchmarks,
    collect_slurm_accounting,
    cpu_usage_delta,
    read_stage_resource_usage,
    write_stage_resource_outputs,
)
from e3workflow.config import STAGE_NAMES, load_config
from e3workflow.control import initialise_stage_tokens
from e3workflow.errors import WorkflowError
from e3workflow.io_utils import read_tsv, write_tsv
from e3workflow.runner import execute_stage


def make_usage(**updates: object) -> StageResourceUsage:
    """Return a complete deterministic stage measurement for serialisation tests."""
    values: dict[str, object] = {
        "stage_name": "00_inputs",
        "status": "complete",
        "return_code": 0,
        "measurement_scope": "test",
        "root_pid": 123,
        "started_at_utc": "2026-07-22T10:00:00+00:00",
        "finished_at_utc": "2026-07-22T10:00:02+00:00",
        "wall_seconds": 2.0,
        "user_cpu_seconds": 1.0,
        "system_cpu_seconds": 0.5,
        "total_cpu_seconds": 1.5,
        "cpu_accounting_method": "test",
        "memory_accounting_method": "test",
        "mean_cpu_cores": 0.75,
        "mean_cpu_percent_of_one_core": 75.0,
        "cpu_efficiency_percent": 75.0,
        "peak_rss_bytes": 1024 * 1024,
        "peak_rss_mb": 1.0,
        "peak_rss_gb": 1.0 / 1024.0,
        "peak_vms_bytes": 2 * 1024 * 1024,
        "peak_vms_mb": 2.0,
        "maximum_process_count": 2,
        "maximum_thread_count": 3,
        "read_bytes": 100,
        "write_bytes": 200,
        "read_count": 4,
        "write_count": 5,
        "voluntary_context_switches": 6,
        "involuntary_context_switches": 7,
        "sample_count": 2,
        "sampling_interval_seconds": 0.1,
        "requested_threads": 1,
        "requested_memory_mb": 10,
        "requested_runtime_minutes": 30,
        "requested_memory_used_percent": 10.0,
        "hostname": "test-host",
        "platform": "test-platform",
        "python_version": "3.12",
        "package_version": "0.4.0",
        "logical_cpu_count": 8,
        "physical_cpu_count": 4,
        "system_total_memory_mb": 1024.0,
        "scheduler": "local",
        "slurm_job_id": "",
        "slurm_job_name": "",
        "slurm_account": "",
        "slurm_partition": "",
        "slurm_node_list": "",
        "slurm_cpus_per_task": "",
        "slurm_mem_per_node": "",
        "slurm_mem_per_cpu": "",
    }
    values.update(updates)
    return StageResourceUsage(**values)


def make_sample() -> ResourceSample:
    """Return one deterministic process-tree time-series sample."""
    return ResourceSample(
        stage_name="00_inputs",
        sampled_at_utc="2026-07-22T10:00:01+00:00",
        elapsed_seconds=1.0,
        process_count=1,
        thread_count=1,
        rss_bytes=1024,
        vms_bytes=2048,
        cumulative_user_cpu_seconds=0.5,
        cumulative_system_cpu_seconds=0.1,
        cumulative_total_cpu_seconds=0.6,
        interval_cpu_cores=0.6,
        interval_cpu_percent_of_allocation=60.0,
        cumulative_read_bytes=10,
        cumulative_write_bytes=20,
    )


def test_cpu_delta_and_serialisation(tmp_path: Path) -> None:
    """CPU deltas and stage resource files preserve all declared fields."""
    started = CpuUsageSnapshot(
        self_user_seconds=1.0,
        self_system_seconds=2.0,
        children_user_seconds=3.0,
        children_system_seconds=4.0,
    )
    finished = CpuUsageSnapshot(
        self_user_seconds=2.0,
        self_system_seconds=4.0,
        children_user_seconds=6.0,
        children_system_seconds=5.0,
    )
    assert cpu_usage_delta(started=started, finished=finished) == (4.0, 3.0)
    assert cpu_usage_delta(started=None, finished=finished) is None
    outputs = write_stage_resource_outputs(
        stage_root=tmp_path,
        usage=make_usage(),
        samples=[make_sample()],
    )
    assert all(path.is_file() for path in outputs.values())
    row = read_stage_resource_usage(path=outputs["summary_tsv"])
    assert row["peak_rss_mb"] == "1.0"
    _, samples = read_tsv(path=outputs["timeseries_tsv"])
    assert samples[0]["interval_cpu_cores"] == "0.6"
    payload = json.loads(outputs["summary_json"].read_text(encoding="utf-8"))
    assert payload["timeseries_rows"] == 1


def test_process_tree_monitor_observes_runtime_resources() -> None:
    """The live monitor records repeated CPU and memory observations."""
    monitor = ProcessTreeResourceMonitor(
        stage_name="child",
        requested_threads=2,
        requested_memory_mb=1024,
        requested_runtime_minutes=10,
        sample_interval_seconds=0.01,
    )
    monitor.start()
    subprocess.run(
        args=[
            sys.executable,
            "-c",
            (
                "import time; payload = bytearray(8 * 1024 * 1024); "
                "sum(range(100000)); time.sleep(0.30); print(len(payload))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    usage, samples = monitor.stop(return_code=0, status="complete")
    assert usage.maximum_process_count >= 0
    assert usage.peak_rss_mb > 0.0
    assert usage.total_cpu_seconds >= 0.0
    assert usage.sample_count == len(samples)
    assert len(samples) >= 2
    assert usage.requested_memory_used_percent > 0.0


def test_process_tree_monitor_sums_mocked_children() -> None:
    """A visible child contributes to aggregate process, memory and thread peaks."""
    memory = mock.Mock(rss=2 * 1024 * 1024, vms=4 * 1024 * 1024)
    cpu = mock.Mock(user=1.0, system=0.5)
    io_counters = mock.Mock(read_bytes=10, write_bytes=20, read_count=1, write_count=2)
    context_switches = mock.Mock(voluntary=3, involuntary=4)

    def fake_process(pid: int, created: float) -> mock.Mock:
        """Return one deterministic psutil-like process mock."""
        process = mock.Mock()
        process.pid = pid
        process.create_time.return_value = created
        process.memory_info.return_value = memory
        process.cpu_times.return_value = cpu
        process.num_threads.return_value = 2
        process.io_counters.return_value = io_counters
        process.num_ctx_switches.return_value = context_switches
        return process

    monitor = ProcessTreeResourceMonitor(
        stage_name="mock-tree",
        requested_threads=2,
        requested_memory_mb=100,
        requested_runtime_minutes=1,
        sample_interval_seconds=1.0,
    )
    root = fake_process(pid=100, created=1.0)
    child = fake_process(pid=101, created=2.0)
    root.children.return_value = [child]
    monitor._root_process = root
    monitor.start()
    usage, _ = monitor.stop()
    assert usage.maximum_process_count == 2
    assert usage.maximum_thread_count == 4
    assert usage.peak_rss_mb == 4.0


def test_monitor_validation_lifecycle_and_fallback() -> None:
    """Invalid monitor settings and repeated lifecycle calls fail clearly."""
    with pytest.raises(ValueError, match="stage_name"):
        ProcessTreeResourceMonitor(
            stage_name="",
            requested_threads=1,
            requested_memory_mb=1,
            requested_runtime_minutes=1,
            sample_interval_seconds=1.0,
        )
    with pytest.raises(ValueError, match="requested_threads"):
        ProcessTreeResourceMonitor(
            stage_name="x",
            requested_threads=0,
            requested_memory_mb=1,
            requested_runtime_minutes=1,
            sample_interval_seconds=1.0,
        )
    with pytest.raises(ValueError, match="sample_interval"):
        ProcessTreeResourceMonitor(
            stage_name="x",
            requested_threads=1,
            requested_memory_mb=1,
            requested_runtime_minutes=1,
            sample_interval_seconds=0.0,
        )
    monitor = ProcessTreeResourceMonitor(
        stage_name="lifecycle",
        requested_threads=1,
        requested_memory_mb=1,
        requested_runtime_minutes=1,
        sample_interval_seconds=0.01,
    )
    with pytest.raises(RuntimeError, match="not been started"):
        monitor.stop()
    with mock.patch.object(benchmarking, "capture_cpu_usage_snapshot", return_value=None):
        monitor.start()
        with pytest.raises(RuntimeError, match="already been started"):
            monitor.start()
        time.sleep(0.02)
        usage, _ = monitor.stop()
    assert usage.cpu_accounting_method == "psutil_sampled_process_tree_delta"
    with pytest.raises(RuntimeError, match="already been stopped"):
        monitor.stop()


def test_scheduler_context_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slurm environment values are copied into stage measurements."""
    monkeypatch.setenv("SLURM_JOB_ID", "12345")
    monkeypatch.setenv("SLURM_JOB_NAME", "e3_stage")
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "4")
    monitor = ProcessTreeResourceMonitor(
        stage_name="slurm",
        requested_threads=4,
        requested_memory_mb=100,
        requested_runtime_minutes=1,
        sample_interval_seconds=0.01,
    )
    monitor.start()
    usage, _ = monitor.stop()
    assert usage.scheduler == "slurm"
    assert usage.slurm_job_id == "12345"
    assert usage.slurm_cpus_per_task == "4"


def test_slurm_accounting_unavailable_failure_and_success() -> None:
    """Optional Slurm enrichment reports unavailable, failed and successful states."""
    status, rows = collect_slurm_accounting(job_ids=[])
    assert status["status"] == "not_applicable"
    assert rows == []
    with mock.patch.object(benchmarking.shutil, "which", return_value=None):
        status, rows = collect_slurm_accounting(job_ids=["1"])
    assert status["status"] == "unavailable"
    assert rows == []
    failed = subprocess.CompletedProcess(
        args=["sacct"],
        returncode=1,
        stdout="",
        stderr="accounting unavailable",
    )
    with (
        mock.patch.object(benchmarking.shutil, "which", return_value="/usr/bin/sacct"),
        mock.patch.object(benchmarking.subprocess, "run", return_value=failed),
    ):
        status, rows = collect_slurm_accounting(job_ids=["1"])
    assert status["status"] == "failed"
    assert rows == []
    header = "|".join(SLURM_ACCOUNTING_COLUMNS)
    values = ["1", "stage", "COMPLETED", "0:0", "2", "00:00:01", "4"]
    values.extend([""] * (len(SLURM_ACCOUNTING_COLUMNS) - len(values)))
    completed = subprocess.CompletedProcess(
        args=["sacct"],
        returncode=0,
        stdout=header + "\n" + "|".join(values) + "\n",
        stderr="",
    )
    with (
        mock.patch.object(benchmarking.shutil, "which", return_value="/usr/bin/sacct"),
        mock.patch.object(benchmarking.subprocess, "run", return_value=completed),
    ):
        status, rows = collect_slurm_accounting(job_ids=["1", "1"])
    assert status["status"] == "collected"
    assert rows[0]["State"] == "COMPLETED"


def test_full_synthetic_benchmark_aggregation(synthetic_config: Path) -> None:
    """All stage measurements join into complete run-level benchmark authorities."""
    config = load_config(path=synthetic_config)
    initialise_stage_tokens(config=config)
    for stage_name in STAGE_NAMES:
        execute_stage(config=config, stage_name=stage_name)
    payload = aggregate_run_benchmarks(
        config=config,
        output_dir=config.run_root / "benchmark_summary",
    )
    assert payload["stage_count"] == len(STAGE_NAMES)
    _, stages = read_tsv(path=Path(payload["stage_resource_summary"]))
    assert len(stages) == len(STAGE_NAMES)
    assert float(stages[0]["runner_wall_seconds"]) > 0.0
    assert int(stages[0]["output_file_count"]) >= 4
    _, workflow = read_tsv(path=Path(payload["workflow_resource_summary"]))
    metrics = {row["metric"]: row for row in workflow}
    assert float(metrics["parallelisation_factor"]["value"]) > 0.0
    assert metrics["maximum_individual_stage_peak_rss_mb"]["unit"] == "MiB"
    _, slurm_status = read_tsv(
        path=config.run_root / "benchmark_summary" / "slurm_accounting_status.tsv"
    )
    assert slurm_status[0]["status"] == "disabled"
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    assert manifest["configuration_digest"] == config.digest


def test_aggregation_rejects_mismatched_stage_identity(synthetic_config: Path) -> None:
    """A benchmark cannot be silently attached to the wrong workflow stage."""
    config = load_config(path=synthetic_config)
    initialise_stage_tokens(config=config)
    for stage_name in STAGE_NAMES:
        execute_stage(config=config, stage_name=stage_name)
    path = config.run_root / "00_inputs" / "benchmark" / "stage_resource_usage.tsv"
    columns, rows = read_tsv(path=path)
    rows[0]["stage_name"] = "wrong"
    write_tsv(path=path, rows=rows, columns=columns)
    with pytest.raises(WorkflowError, match="identity differs"):
        aggregate_run_benchmarks(config=config, output_dir=config.run_root / "summary")
