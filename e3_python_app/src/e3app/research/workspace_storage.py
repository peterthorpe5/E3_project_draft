"""Preview and remove disposable indexes from completed research jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import stat

from .common import ResearchError, safe_path
from .jobs import JOB_ID, completed_jobs_before

LOGGER = logging.getLogger(__name__)
INTERMEDIATE_INDEXES = {
    "align": ("input.sqlite",),
    "annotate": ("input.sqlite", "selection.sqlite"),
    "import_cluster": ("import.sqlite",),
    "predict": ("input.sqlite", "selection.sqlite"),
    "retrieve": ("member_identity.sqlite",),
    "search": ("queries.sqlite", "selection.sqlite"),
    "subcluster": ("input.sqlite",),
}


@dataclass(frozen=True, kw_only=True)
class JobIntermediate:
    """A disposable job file identified by its location and previewed metadata.

    Attributes:
        job_id: Completed job that created the file.
        name: Exact intermediate filename.
        size: File size in bytes.
        modified_ns: Modification timestamp in nanoseconds.
        identity: Device, inode and change timestamp for replacement detection.
    """

    job_id: str
    name: str
    size: int
    modified_ns: int
    identity: tuple[int, int, int]


def _file_snapshot(*, directory: Path, name: str) -> JobIntermediate | None:
    """Identify a regular index file without following symbolic links.

    Args:
        directory: Owned directory of a completed job.
        name: Exact intermediate filename.

    Returns:
        File metadata, or None for a missing, shared or non-regular file.
    """
    try:
        info = (directory / name).lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        return None
    return JobIntermediate(
        job_id=directory.name, name=name, size=info.st_size, modified_ns=info.st_mtime_ns,
        identity=(info.st_dev, info.st_ino, info.st_ctime_ns),
    )


def _published_paths(*, directory: Path) -> set[Path]:
    """Resolve manifest paths so an intermediate published as an artifact is protected.

    Args:
        directory: Owned directory of a completed job.

    Returns:
        Files recorded in the completed manifest.

    Raises:
        ResearchError: If the manifest is not a supported job record.
    """
    path = directory / "manifest.json"
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ResearchError("Expected a regular job manifest")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("job_id") != directory.name
        or manifest.get("schema_version") != 1
        or not isinstance(manifest.get("artifacts"), dict)
    ):
        raise ResearchError("Unsupported job manifest")
    return {
        safe_path(root=directory, relative=record["path"])
        for record in manifest["artifacts"].values()
    }


def preview_job_cleanup(*, workspace: Path, retention_days: int) -> tuple[JobIntermediate, ...]:
    """Find old disposable indexes in completed jobs with usable manifests.

    Args:
        workspace: Active research workspace on this host.
        retention_days: Minimum age of both the file and its completed job.

    Returns:
        Snapshot of eligible files for review before deletion.

    Raises:
        ResearchError: If the retention period is invalid.
    """
    if type(retention_days) is not int or retention_days < 1:
        raise ResearchError("Enter a positive whole number of days")
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    except OverflowError as exc:
        raise ResearchError("Retention period is too large") from exc
    jobs_root = workspace.resolve() / "jobs"
    if jobs_root.is_symlink():
        return ()
    cutoff_ns = int(cutoff.timestamp() * 1_000_000_000)
    candidates = []
    for job_id, operation in completed_jobs_before(
        workspace=workspace, cutoff=cutoff.isoformat()
    ):
        names = INTERMEDIATE_INDEXES.get(operation, ())
        if not names or not JOB_ID.fullmatch(job_id):
            continue
        directory = jobs_root / job_id
        try:
            if not stat.S_ISDIR(directory.lstat().st_mode):
                continue
            published = _published_paths(directory=directory)
            for name in names:
                if directory / name in published:
                    continue
                item = _file_snapshot(directory=directory, name=name)
                if item is not None and item.modified_ns < cutoff_ns:
                    candidates.append(item)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            LOGGER.warning("Skipping intermediate cleanup for job %s: %s", job_id, exc)
    return tuple(candidates)


def clear_job_intermediates(
    *, workspace: Path, retention_days: int, preview: tuple[JobIntermediate, ...],
) -> tuple[JobIntermediate, ...]:
    """Remove only previously previewed files that still pass all cleanup checks.

    Args:
        workspace: Same research workspace used for the preview.
        retention_days: Same minimum age used for the preview.
        preview: Exact files shown to the user.

    Returns:
        Files successfully removed. Missing, changed and inaccessible files are skipped.
    """
    eligible = set(preview_job_cleanup(workspace=workspace, retention_days=retention_days))
    jobs_root = workspace.resolve() / "jobs"
    removed = []
    for item in preview:
        if item not in eligible:
            continue
        directory = jobs_root / item.job_id
        try:
            if directory.resolve() == directory and _file_snapshot(
                directory=directory, name=item.name,
            ) == item:
                (directory / item.name).unlink()
                removed.append(item)
        except OSError as exc:
            LOGGER.warning("Could not clear %s for job %s: %s", item.name, item.job_id, exc)
    LOGGER.info("Cleared %d research intermediates from %s", len(removed), workspace)
    return tuple(removed)
