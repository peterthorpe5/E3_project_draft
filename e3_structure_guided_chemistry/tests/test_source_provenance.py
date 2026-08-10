"""Tracked Git source-provenance tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import e3chemistry.source_provenance as source_module
from e3chemistry.source_provenance import capture_source_provenance


def test_source_provenance_records_checkout_commit(package_root: Path) -> None:
    """A checkout must expose its commit and tracked package state."""
    provenance = capture_source_provenance(package_root)

    assert provenance["available"] is True
    assert len(str(provenance["git_commit"])) == 40
    assert provenance["tracked_source_state"] in {"CLEAN", "DIRTY"}
    assert provenance["package_path"] == "e3_structure_guided_chemistry"


def test_source_provenance_handles_non_repository(tmp_path: Path) -> None:
    """A wheel-like directory without Git metadata must remain explicit."""
    provenance = capture_source_provenance(tmp_path)

    assert provenance["available"] is False
    assert provenance["tracked_source_state"] == "UNAVAILABLE"


def test_source_provenance_handles_git_execution_failure(
    package_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable Git executable must not crash reporting."""
    monkeypatch.setattr(
        source_module,
        "_git",
        lambda **kwargs: (_ for _ in ()).throw(OSError("git unavailable")),
    )

    assert capture_source_provenance(package_root)["available"] is False


def test_source_provenance_handles_late_git_failure(
    package_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commit/status failures after root discovery must remain explicit."""
    calls = 0

    def fake_git(**kwargs: object) -> subprocess.CompletedProcess[str]:
        """Return root discovery, then fail the commit inspection."""
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(
                args=("git",),
                returncode=0,
                stdout=str(package_root.parent) + "\n",
                stderr="",
            )
        raise subprocess.TimeoutExpired(cmd="git", timeout=10)

    monkeypatch.setattr(source_module, "_git", fake_git)

    assert capture_source_provenance(package_root)["available"] is False
