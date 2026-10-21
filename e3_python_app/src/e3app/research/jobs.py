"""Durable, concurrency-safe local/HPC jobs outside published scientific releases."""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Iterator, Mapping
from uuid import uuid4

from .common import ResearchError, atomic_json, file_sha256, safe_path, utc_now

LOGGER = logging.getLogger(__name__)
OPERATIONS = {
    "resolve",
    "retrieve",
    "subcluster",
    "align",
    "predict",
    "annotate",
    "taxonomy_index",
    "search",
}
JOB_ID = re.compile(r"^[a-f0-9]{32}$")


@contextmanager
def _connection(*, workspace: Path) -> Iterator[sqlite3.Connection]:
    """Open the sidecar queue with transactional locks and bounded lock waiting.

    Args:
        workspace: Operator-controlled writable workspace.

    Yields:
        Connection whose transactions are committed on normal completion.
    """
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(database=workspace / "jobs.sqlite", timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS jobs(
                job_id TEXT PRIMARY KEY, operation TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                request TEXT NOT NULL, error TEXT
            )
        """)
        with connection:
            yield connection
    finally:
        connection.close()


def job_directory(*, workspace: Path, job_id: str) -> Path:
    """Resolve a validated job identifier to its contained directory.

    Args:
        workspace: Job workspace root.
        job_id: Exact generated identifier.

    Returns:
        Contained job directory.

    Raises:
        ResearchError: If the identifier is malformed.
    """
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise ResearchError("Invalid research job identifier")
    return safe_path(root=workspace, relative=f"jobs/{job_id}")


def submit_job(
    *, workspace: Path, operation: str, parameters: Mapping[str, object], fasta: str | None = None
) -> str:
    """Persist a validated operation request without executing work in the web process.

    Args:
        workspace: Writable research sidecar.
        operation: Supported generic protein workflow.
        parameters: JSON-serialisable named scientific controls.
        fasta: Optional uploaded protein FASTA; at most 20 MB.

    Returns:
        New queued job identifier.

    Raises:
        ResearchError: If operation or request size is invalid.
    """
    if operation not in OPERATIONS:
        raise ResearchError("Unsupported research job operation")
    request = json.dumps(dict(parameters), allow_nan=False, sort_keys=True)
    if len(request) > 2_000_000 or (fasta is not None and len(fasta.encode("utf-8")) > 20_000_000):
        raise ResearchError("Research input exceeds the explicit upload/request size limit")
    job_id = uuid4().hex
    directory = job_directory(workspace=workspace, job_id=job_id)
    directory.mkdir(parents=True, mode=0o700)
    if fasta is not None:
        (directory / "input.fasta").write_text(fasta, encoding="utf-8")
    atomic_json(
        path=directory / "request.json",
        value={
            "job_id": job_id,
            "operation": operation,
            "parameters": dict(parameters),
            "input_sha256": (
                file_sha256(path=directory / "input.fasta") if fasta is not None else None
            ),
            "created_at": utc_now(),
        },
    )
    with _connection(workspace=workspace) as connection:
        connection.execute(
            (
                "INSERT INTO jobs(job_id, operation, status, created_at, request) VALUES "
                "(?,?,'QUEUED',?,?)"
            ),
            (job_id, operation, utc_now(), request),
        )
    LOGGER.info("Queued %s job %s", operation, job_id)
    return job_id


def list_jobs(*, workspace: Path, limit: int = 200) -> list[dict[str, object]]:
    """Return bounded recent job summaries without exposing request sequences or tokens.

    Args:
        workspace: Job workspace.
        limit: Maximum recent records, between one and 1,000.

    Returns:
        Newest-first job status dictionaries.

    Raises:
        ResearchError: If the result limit is invalid.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
        raise ResearchError("Job result limit must be an integer between 1 and 1000")
    with _connection(workspace=workspace) as connection:
        rows = connection.execute(
            "SELECT job_id,operation,status,created_at,started_at,finished_at,error "
            "FROM jobs ORDER BY created_at DESC,job_id LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_job(*, workspace: Path, job_id: str) -> dict[str, object]:
    """Return one exact job summary, including older jobs outside the recent list.

    Args:
        workspace: Queue workspace.
        job_id: Exact generated identifier.

    Returns:
        Status and sanitised diagnostic fields.

    Raises:
        ResearchError: If the job does not exist.
    """
    job_directory(workspace=workspace, job_id=job_id)
    with _connection(workspace=workspace) as connection:
        row = connection.execute(
            "SELECT job_id,operation,status,created_at,started_at,finished_at,error "
            "FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
    if row is None:
        raise ResearchError("Unknown research job")
    return dict(row)


def claim_job(*, workspace: Path, job_id: str | None = None) -> dict[str, object] | None:
    """Atomically claim one queued job so multiple workers cannot execute it twice.

    Args:
        workspace: Job workspace.
        job_id: Optional exact queued job; otherwise claim the oldest.

    Returns:
        Claimed request and metadata, or None if no eligible job exists.
    """
    if job_id is not None:
        job_directory(workspace=workspace, job_id=job_id)
    with _connection(workspace=workspace) as connection:
        connection.execute("BEGIN IMMEDIATE")
        predicate = " AND job_id = ?" if job_id is not None else ""
        row = connection.execute(
            "SELECT * FROM jobs WHERE status='QUEUED'" + predicate + " ORDER BY created_at LIMIT 1",
            (job_id,) if job_id is not None else (),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "UPDATE jobs SET status='RUNNING', started_at=? WHERE job_id=? AND status='QUEUED'",
            (utc_now(), row["job_id"]),
        )
    result = dict(row)
    result["parameters"] = json.loads(result.pop("request"))
    result["status"] = "RUNNING"
    return result


def finish_job(*, workspace: Path, job_id: str, error: str | None = None) -> None:
    """Complete a claimed job, retaining failure details and its partial audit files.

    Args:
        workspace: Job workspace.
        job_id: Running job identifier.
        error: Sanitised diagnostic, or None for success.

    Raises:
        ResearchError: If the job is not currently running.
    """
    job_directory(workspace=workspace, job_id=job_id)
    status = "FAILED" if error is not None else "COMPLETE"
    with _connection(workspace=workspace) as connection:
        cursor = connection.execute(
            "UPDATE jobs SET status=?,finished_at=?,error=? WHERE job_id=? AND status='RUNNING'",
            (status, utc_now(), error[:4_000] if error else error, job_id),
        )
        if cursor.rowcount != 1:
            raise ResearchError("Only a running job can be completed")
    LOGGER.info("Job %s finished with status %s", job_id, status)


def cancel_job(*, workspace: Path, job_id: str) -> None:
    """Cancel a queued job without interrupting an external tool halfway through output.

    Args:
        workspace: Job workspace.
        job_id: Queued job identifier.

    Raises:
        ResearchError: If the job has already started or does not exist.
    """
    job_directory(workspace=workspace, job_id=job_id)
    with _connection(workspace=workspace) as connection:
        cursor = connection.execute(
            "UPDATE jobs SET status='CANCELLED',finished_at=? WHERE job_id=? AND status='QUEUED'",
            (utc_now(), job_id),
        )
        if cursor.rowcount != 1:
            raise ResearchError(
                "Only queued jobs can be cancelled; running jobs need worker control"
            )


def artifact_path(*, workspace: Path, job_id: str, artifact: str) -> Path:
    """Resolve a checksummed output of a successfully completed job.

    Args:
        workspace: Job workspace.
        job_id: Completed source job.
        artifact: Exact artifact key from its manifest.

    Returns:
        Existing contained artifact, after checksum verification.

    Raises:
        ResearchError: If the job is incomplete, the key is absent or bytes changed.
    """
    directory = job_directory(workspace=workspace, job_id=job_id)
    with _connection(workspace=workspace) as connection:
        row = connection.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if row is None or row[0] != "COMPLETE":
        raise ResearchError("Source research job must be complete")
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        record = manifest["artifacts"][artifact]
        path = safe_path(root=directory, relative=record["path"])
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise ResearchError("Requested artifact is unavailable") from exc
    if not path.is_file() or file_sha256(path=path) != record["sha256"]:
        raise ResearchError("Research artifact checksum differs from its completed manifest")
    return path
