"""Tests for cross-platform process-tree resource monitoring."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from e3_discovery.resource_monitor import (
    ProcessTreeResourceMonitor,
    ResourceUsage,
    aggregate_resource_usage_directory,
    plot_peak_ram_by_stage,
    read_resource_usage,
    summarise_resource_usage,
    write_resource_usage,
    write_resource_usage_outputs,
)


def usage(stage_name: str = "stage", peak_rss_mb: float = 12.5) -> ResourceUsage:
    """Create a deterministic resource measurement for tests.

    Args:
        stage_name: Stage label assigned to the measurement.
        peak_rss_mb: Peak RSS value in mebibytes.

    Returns:
        Populated :class:`ResourceUsage` test record.
    """

    return ResourceUsage(
        stage_name=stage_name,
        status="success",
        return_code=0,
        root_pid=123,
        started_at_utc="2026-07-14T00:00:00+00:00",
        finished_at_utc="2026-07-14T00:00:01+00:00",
        wall_seconds=1.0,
        user_cpu_seconds=0.4,
        system_cpu_seconds=0.1,
        total_cpu_seconds=0.5,
        peak_rss_bytes=int(peak_rss_mb * 1024 * 1024),
        peak_rss_mb=peak_rss_mb,
        maximum_process_count=2,
        sample_count=5,
        sampling_interval_seconds=0.2,
        platform="test-platform",
    )


class ResourceMonitorTests(unittest.TestCase):
    """Validate monitoring, serialisation, aggregation and plotting."""

    def test_resource_usage_as_record(self) -> None:
        record = usage().as_record()
        self.assertEqual(record["stage_name"], "stage")
        self.assertEqual(record["peak_rss_mb"], 12.5)

    def test_process_tree_monitor_lifecycle(self) -> None:
        monitor = ProcessTreeResourceMonitor(
            "unit-test",
            sample_interval_seconds=0.01,
        )
        monitor.start()
        time.sleep(0.03)
        measurement = monitor.stop()
        self.assertEqual(measurement.stage_name, "unit-test")
        self.assertGreaterEqual(measurement.sample_count, 2)
        self.assertGreater(measurement.peak_rss_bytes, 0)
        self.assertGreaterEqual(measurement.wall_seconds, 0.02)

    def test_process_tree_monitor_includes_child_process(self) -> None:
        monitor = ProcessTreeResourceMonitor(
            "child-test",
            sample_interval_seconds=0.01,
        )
        monitor.start()
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import time; "
                    "payload = bytearray(20 * 1024 * 1024); "
                    "time.sleep(0.2); print(len(payload))"
                ),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        child.wait(timeout=5)
        measurement = monitor.stop()
        self.assertGreaterEqual(measurement.maximum_process_count, 2)
        self.assertGreater(measurement.peak_rss_mb, 20.0)

    def test_process_tree_monitor_rejects_bad_lifecycle(self) -> None:
        with self.assertRaises(ValueError):
            ProcessTreeResourceMonitor("")
        with self.assertRaises(ValueError):
            ProcessTreeResourceMonitor("x", sample_interval_seconds=0)
        monitor = ProcessTreeResourceMonitor("x", sample_interval_seconds=0.01)
        with self.assertRaises(RuntimeError):
            monitor.stop()
        monitor.start()
        with self.assertRaises(RuntimeError):
            monitor.start()
        monitor.stop()
        with self.assertRaises(RuntimeError):
            monitor.stop()

    def test_resource_usage_roundtrip_and_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = write_resource_usage(usage("a", 10.0), root / "a.tsv")
            write_resource_usage(usage("a", 20.0), root / "b.tsv")
            hidden = root / ".hidden"
            hidden.mkdir()
            write_resource_usage(usage("ignored", 99.0), hidden / "x.tsv")
            parsed = read_resource_usage(first)
            self.assertEqual(parsed.stage_name, "a")
            records = aggregate_resource_usage_directory(root)
            self.assertEqual(len(records), 2)
            summaries = summarise_resource_usage(records)
            self.assertEqual(summaries[0]["repeat_count"], 2)
            self.assertEqual(summaries[0]["maximum_peak_rss_mb"], 20.0)

    def test_read_resource_usage_rejects_bad_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                read_resource_usage(root / "missing.tsv")
            bad = root / "bad.tsv"
            bad.write_text("stage_name\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_resource_usage(bad)
            with self.assertRaises(FileNotFoundError):
                aggregate_resource_usage_directory(root / "missing")

    def test_write_outputs_and_plot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = [usage("a", 12.0)]
            summaries = summarise_resource_usage(records)
            outputs = write_resource_usage_outputs(
                records,
                summaries,
                root / "records.tsv",
                root / "summary.tsv",
            )
            self.assertTrue(all(path.is_file() for path in outputs))
            plot_peak_ram_by_stage(
                summaries,
                root / "ram.png",
                root / "ram.pdf",
            )
            self.assertTrue((root / "ram.png").is_file())
            self.assertTrue((root / "ram.pdf").is_file())
            with self.assertRaises(ValueError):
                plot_peak_ram_by_stage([], root / "empty.png")


if __name__ == "__main__":
    unittest.main()
