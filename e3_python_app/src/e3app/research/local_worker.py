"""Start an explicit app-host alignment with the existing job worker."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from threading import Thread
from typing import Mapping

from .common import ResearchConfig, ResearchError, bounded_number
from .jobs import fail_queued_job, job_directory, submit_job
from .viewer_inputs import uploaded_proteins

LOGGER = logging.getLogger(__name__)


def _wait_for_worker(
    *, process: subprocess.Popen, config: ResearchConfig, job_id: str,
) -> None:
    """Reap the worker and report a request left unclaimed.

    Args:
        process: One-shot worker process.
        config: App-host workspace profile.
        job_id: Exact job reserved for this worker.
    """
    returncode = process.wait()
    if returncode:
        LOGGER.warning("App-host alignment worker for %s exited with %s", job_id, returncode)
    fail_queued_job(
        workspace=config.workspace, job_id=job_id,
        error=f"Local worker exited with status {returncode} before claiming this job. "
        "See local_worker.log.",
    )


def submit_local_alignment(
    *, config: ResearchConfig, parameters: Mapping[str, object], fasta: str,
) -> str:
    """Snapshot the selected FASTA and start its exact job on the app host.

    Args:
        config: Research profile used by the running app.
        parameters: Selected reference, sampling and optional tree settings.
        fasta: Exact unaligned protein sequences to align.

    Returns:
        The durable alignment job ID.

    Raises:
        ResearchError: If the input, tools or local worker launch are invalid.
    """
    if not shutil.which(config.mafft):
        raise ResearchError("MAFFT is unavailable on the app machine. Install it and relaunch.")
    records = uploaded_proteins(text=fasta, maximum_records=100_000)
    sample_size = bounded_number(
        value=parameters.get("sample_size", len(records)),
        label="Alignment size", minimum=1, maximum=config.max_alignment_sequences, integer=True,
    )
    if (min(len(records), sample_size) >= 3 and parameters.get("infer_tree", True)
            and not shutil.which(config.fasttree)):
        raise ResearchError(
            "FastTree is unavailable. Untick the tree option or install FastTree."
        )
    job_id = submit_job(
        workspace=config.workspace, operation="align",
        parameters={**parameters, "execution_target": "app_host"}, fasta=fasta,
    )
    log_path = job_directory(workspace=config.workspace, job_id=job_id) / "local_worker.log"
    try:
        with log_path.open(mode="wb") as log:
            process = subprocess.Popen(
                args=[sys.executable, "-m", "e3app.research.cli", "worker", "--once",
                      "--job-id", job_id],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        diagnostic = f"Could not start local alignment worker: {exc}"
        fail_queued_job(workspace=config.workspace, job_id=job_id, error=diagnostic)
        raise ResearchError(diagnostic) from exc
    Thread(
        target=_wait_for_worker, kwargs={"process": process, "config": config, "job_id": job_id},
        daemon=True,
    ).start()
    LOGGER.info("Started app-host alignment job %s as PID %s", job_id, process.pid)
    return job_id
