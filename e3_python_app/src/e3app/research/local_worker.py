"""Start one-shot research jobs on the machine hosting the app."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from threading import Thread
from typing import Mapping

from .common import ResearchConfig, ResearchError, bounded_number
from .jobs import (
    artifact_path,
    fail_queued_job,
    get_job,
    is_external_provider_request,
    job_directory,
    queued_external_provider_job,
    submit_job,
)
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
        LOGGER.warning("App-host worker for %s exited with %s", job_id, returncode)
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
    _start_local_job(config=config, job_id=job_id, label="alignment")
    return job_id


def submit_local_tree(*, config: ResearchConfig, alignment_job: str) -> str:
    """Start FastTree on the checksummed FASTA of a completed alignment.

    Args:
        config: Research profile used by the app and its one-shot worker.
        alignment_job: Exact completed alignment job ID.

    Returns:
        The durable tree job ID.

    Raises:
        ResearchError: If FastTree, the source alignment or worker launch is unavailable.
    """
    if not shutil.which(config.fasttree):
        raise ResearchError("FastTree is unavailable on the machine running the app.")
    if get_job(workspace=config.workspace, job_id=alignment_job)["operation"] != "align":
        raise ResearchError("Select a completed protein alignment job")
    artifact_path(workspace=config.workspace, job_id=alignment_job, artifact="alignment.fasta")
    job_id = submit_job(
        workspace=config.workspace, operation="tree",
        parameters={"source_job": alignment_job, "execution_target": "app_host"},
    )
    _start_local_job(config=config, job_id=job_id, label="tree")
    return job_id


def submit_local_provider_job(
    *,
    config: ResearchConfig,
    operation: str,
    parameters: Mapping[str, object],
    fasta: str | None = None,
    interproscan_email: str | None = None,
) -> str:
    """Save and start one consented external analysis on the app host.

    Args:
        config: App-host research profile.
        operation: Annotation or structure prediction.
        parameters: Selected hosted provider, consent and protein input controls.
        fasta: Optional uploaded protein FASTA.
        interproscan_email: Optional private contact for the EBI request.

    Returns:
        Durable job ID for tracking results.

    Raises:
        ResearchError: If the provider or worker launch cannot be used.
    """
    if not is_external_provider_request(operation=operation, parameters=parameters):
        raise ResearchError("Choose an external provider and allow sequence submission")
    job_id = submit_job(
        workspace=config.workspace,
        operation=operation,
        parameters={**parameters, "execution_target": "app_host"},
        fasta=fasta,
        interproscan_email=interproscan_email,
    )
    _start_local_job(config=config, job_id=job_id, label="external analysis")
    return job_id


def start_queued_provider_job(*, config: ResearchConfig, job_id: str) -> None:
    """Start an existing consented external request with its original job ID.

    Args:
        config: App-host research profile.
        job_id: Exact queued request to claim.

    Raises:
        ResearchError: If the request is ineligible or the worker cannot start.
    """
    if not queued_external_provider_job(workspace=config.workspace, job_id=job_id):
        raise ResearchError("Select a queued external request with sequence-submission consent")
    _start_local_job(config=config, job_id=job_id, label="external analysis")


def _start_local_job(*, config: ResearchConfig, job_id: str, label: str) -> None:
    """Launch the app-host worker for one reserved job.

    Args:
        config: Workspace profile used for the job.
        job_id: Exact queued request to claim.
        label: Analysis name for launch diagnostics.

    Raises:
        ResearchError: If the worker could not start.
    """
    log_path = job_directory(workspace=config.workspace, job_id=job_id) / "local_worker.log"
    try:
        with log_path.open(mode="ab") as log:
            process = subprocess.Popen(
                args=[sys.executable, "-m", "e3app.research.cli", "worker", "--once",
                      "--job-id", job_id],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as exc:
        diagnostic = f"Could not start local {label} worker: {exc}"
        fail_queued_job(workspace=config.workspace, job_id=job_id, error=diagnostic)
        raise ResearchError(diagnostic) from exc
    Thread(
        target=_wait_for_worker, kwargs={"process": process, "config": config, "job_id": job_id},
        daemon=True,
    ).start()
    LOGGER.info("Started app-host %s job %s as PID %s", label, job_id, process.pid)
