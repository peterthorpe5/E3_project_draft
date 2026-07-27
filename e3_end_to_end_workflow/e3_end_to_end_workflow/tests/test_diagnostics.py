"""Tests for active-install and editable-source provenance diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest

from e3workflow import __version__
from e3workflow.diagnostics import diagnose_installation, require_matching_source
from e3workflow.errors import WorkflowError


def test_diagnostics_match_the_active_source_tree(package_root: Path) -> None:
    """The development CLI must report the exact checked-out source module."""
    payload = diagnose_installation(source_root=package_root)
    assert payload["status"] == "MATCHED_SOURCE"
    assert payload["source_version"] == __version__
    assert payload["version_matches_source"] is True
    assert payload["module_matches_source"] is True
    assert require_matching_source(source_root=package_root) == payload


def test_diagnostics_reject_invalid_and_mismatched_source_roots(
    tmp_path: Path,
) -> None:
    """Missing metadata and a different source version must fail clearly."""
    with pytest.raises(WorkflowError, match="must contain"):
        diagnose_installation(source_root=tmp_path)

    source_root = tmp_path / "source"
    module_root = source_root / "src" / "e3workflow"
    module_root.mkdir(parents=True)
    (module_root / "__init__.py").write_text(
        '__version__ = "999.0.0"\n', encoding="utf-8"
    )
    (source_root / "pyproject.toml").write_text(
        '[project]\nname = "different-source"\nversion = "999.0.0"\n',
        encoding="utf-8",
    )
    payload = diagnose_installation(source_root=source_root)
    assert payload["status"] == "VERSION_MISMATCH"
    with pytest.raises(WorkflowError, match="VERSION_MISMATCH"):
        require_matching_source(source_root=source_root)
