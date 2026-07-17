"""Run-level provenance and environment capture."""

from __future__ import annotations

import importlib.metadata
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .io_utils import atomic_write_json, sha256_file


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""

    return datetime.now(timezone.utc).isoformat()


def package_versions(names: list[str]) -> dict[str, str | None]:
    """Collect installed distribution versions without failing on absences.

    Args:
        names: Distribution names.

    Returns:
        Mapping of distribution name to version or ``None``.
    """

    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def capture_git_state(repository: Path | None) -> dict[str, Any]:
    """Capture Git commit and dirty state when a repository is available.

    Args:
        repository: Repository root or ``None``.

    Returns:
        Git provenance fields. Failures are recorded, not raised.
    """

    if repository is None:
        return {
            "repository": None,
            "commit": None,
            "dirty": None,
            "error": "repository_not_supplied",
        }
    root = Path(repository).expanduser().resolve()
    if not (root / ".git").exists():
        return {
            "repository": str(root),
            "commit": None,
            "dirty": None,
            "error": "not_a_git_repository",
        }
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "repository": str(root),
            "commit": None,
            "dirty": None,
            "error": f"{type(error).__name__}: {error}",
        }
    return {
        "repository": str(root),
        "commit": commit,
        "dirty": bool(status.strip()),
        "error": None,
    }


def build_run_manifest(
    input_path: Path,
    output_root: Path,
    config: dict[str, Any],
    started_at: str,
    finished_at: str,
    datasets: dict[str, list[dict[str, Any]]],
    file_manifests: list[dict[str, Any]],
    tool_versions: list[dict[str, Any]],
    git_repository: Path | None,
) -> dict[str, Any]:
    """Build the complete run provenance manifest.

    Args:
        input_path: Accession input file.
        output_root: Run output root.
        config: Effective configuration.
        started_at: UTC start timestamp.
        finished_at: UTC finish timestamp.
        datasets: In-memory output datasets.
        file_manifests: Published file records.
        tool_versions: External tool version records.
        git_repository: Optional repository root.

    Returns:
        JSON-serialisable manifest.
    """

    source = Path(input_path).expanduser().resolve()
    root = Path(output_root).expanduser().resolve()
    validation = datasets.get("validation", [])
    return {
        "resource_name": "E3 ligandability evidence",
        "resource_version": __version__,
        "scientific_interpretation": (
            "Pocket predictions and structure confidence are computational "
            "evidence. They do not prove ligand binding, E3 biochemical "
            "function or PROTAC suitability."
        ),
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "input_path": str(source),
        "input_bytes": source.stat().st_size,
        "input_sha256": sha256_file(source),
        "output_root": str(root),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "python_packages": package_versions(
            [
                "e3-ligandability-pipeline",
                "duckdb",
                "gemmi",
                "pyarrow",
                "PyYAML",
                "requests",
            ]
        ),
        "external_tool_versions": tool_versions,
        "git": capture_git_state(git_repository),
        "effective_config": config,
        "dataset_row_counts": {
            name: len(records) for name, records in datasets.items()
        },
        "validation_check_count": len(validation),
        "validation_pass_count": sum(
            record.get("status") == "PASS" for record in validation
        ),
        "file_manifest": file_manifests,
    }


def write_run_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write a run manifest atomically.

    Args:
        path: Destination JSON path.
        manifest: Run manifest object.
    """

    atomic_write_json(path, manifest)
