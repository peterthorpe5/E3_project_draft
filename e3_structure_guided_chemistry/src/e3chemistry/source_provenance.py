"""Capture the exact tracked source revision used for a chemistry run."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _git(*, working_dir: Path, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Run one bounded, non-interactive Git inspection command."""
    return subprocess.run(
        ("git", "-C", str(working_dir), *arguments),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def capture_source_provenance(package_root: Path | None = None) -> dict[str, Any]:
    """Return Git commit and tracked package-source state when available.

    Args:
        package_root: Package checkout directory. The installed package root is
            inferred when omitted.

    Returns:
        A JSON-serialisable source-provenance record. Untracked files are
        deliberately ignored because they cannot alter imported package code.
    """
    source = (
        package_root.expanduser().resolve()
        if package_root is not None
        else Path(__file__).resolve().parents[2]
    )
    try:
        root_result = _git(working_dir=source, arguments=("rev-parse", "--show-toplevel"))
    except (OSError, subprocess.TimeoutExpired):
        return {
            "available": False,
            "git_commit": "",
            "tracked_source_state": "UNAVAILABLE",
            "package_path": str(source),
        }
    if root_result.returncode != 0:
        return {
            "available": False,
            "git_commit": "",
            "tracked_source_state": "UNAVAILABLE",
            "package_path": str(source),
        }
    repository_root = Path(root_result.stdout.strip()).resolve()
    try:
        package_relative = source.relative_to(repository_root)
    except ValueError:
        package_relative = Path(".")
    try:
        commit_result = _git(working_dir=source, arguments=("rev-parse", "HEAD"))
        status_result = _git(
            working_dir=repository_root,
            arguments=(
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
                "--",
                str(package_relative),
            ),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "available": False,
            "git_commit": "",
            "tracked_source_state": "UNAVAILABLE",
            "package_path": str(source),
        }
    if commit_result.returncode != 0 or status_result.returncode != 0:
        return {
            "available": False,
            "git_commit": "",
            "tracked_source_state": "UNAVAILABLE",
            "package_path": str(source),
        }
    changes = [line for line in status_result.stdout.splitlines() if line.strip()]
    return {
        "available": True,
        "git_commit": commit_result.stdout.strip(),
        "tracked_source_state": "DIRTY" if changes else "CLEAN",
        "tracked_change_count": len(changes),
        "repository_root": str(repository_root),
        "package_path": str(package_relative),
    }
