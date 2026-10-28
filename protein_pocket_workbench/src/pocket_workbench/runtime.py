"""Execution-host diagnostics shared by the UI, CLI and persisted workers."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
from pathlib import Path


def available_cpus() -> int:
    """Return the CPU count allowed by affinity and any Slurm allocation."""
    try:
        count = len(os.sched_getaffinity(0))
    except AttributeError:
        count = os.cpu_count() or 1
    for name in ("SLURM_CPUS_PER_TASK", "POCKET_WORKBENCH_MAX_THREADS"):
        try:
            count = min(count, max(1, int(os.getenv(name, str(count)))))
        except ValueError:
            continue
    return max(1, count)


def execution_info(*, root: Path | None = None) -> dict:
    """Describe the actual server, available tools and result location.

    Args:
        root: Optional open project directory.

    Returns:
        JSON-compatible execution and dependency diagnostics.
    """
    tools = {
        "USalign": os.getenv("POCKET_WORKBENCH_USALIGN", "USalign"),
        "TMalign": os.getenv("POCKET_WORKBENCH_TMALIGN", "TMalign"),
        "fpocket": os.getenv("POCKET_WORKBENCH_FPOCKET", "fpocket"),
        "P2Rank": os.getenv("POCKET_WORKBENCH_P2RANK", "prank"),
        "MAFFT": os.getenv("POCKET_WORKBENCH_MAFFT", "mafft"),
    }
    return {
        "execution_mode": "local workers on the Streamlit server",
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.executable,
        "python_version": platform.python_version(),
        "environment": os.getenv("CONDA_DEFAULT_ENV", ""),
        "available_cpus": available_cpus(),
        "slurm_job_id": os.getenv("SLURM_JOB_ID"),
        "project_directory": str(root.resolve()) if root else None,
        "free_disk_gib": (
            round(shutil.disk_usage(root).free / 1024**3, 2)
            if root and root.exists()
            else None
        ),
        "tools": {
            name: {"configured": executable, "resolved": shutil.which(executable)}
            for name, executable in tools.items()
        },
    }
