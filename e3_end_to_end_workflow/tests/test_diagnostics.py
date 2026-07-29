"""Tests for active-install and editable-source provenance diagnostics."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from unittest import mock

import pytest

from e3workflow import __version__
from e3workflow.diagnostics import (
    _source_version,
    diagnose_installation,
    diagnose_slurm_executor,
    require_compatible_slurm_executor,
    require_matching_source,
)
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


def test_source_version_rejects_invalid_or_empty_metadata(tmp_path: Path) -> None:
    """Malformed and empty project versions must fail before installation diagnosis."""
    source_root = tmp_path / "source"
    module_root = source_root / "src" / "e3workflow"
    module_root.mkdir(parents=True)
    (module_root / "__init__.py").write_text(
        '__version__ = "0.11.0"\n',
        encoding="utf-8",
    )
    pyproject = source_root / "pyproject.toml"
    pyproject.write_text("[project\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="Could not read project.version"):
        _source_version(source_root=source_root)

    pyproject.write_text('[project]\nversion = ""\n', encoding="utf-8")
    with pytest.raises(WorkflowError, match="empty or invalid"):
        _source_version(source_root=source_root)


def test_installation_diagnostics_cover_absent_and_conflicting_metadata(
    package_root: Path,
) -> None:
    """Diagnostics must distinguish absent, unrelated and stale installations."""
    with mock.patch(
        "e3workflow.diagnostics.metadata.version",
        side_effect=metadata.PackageNotFoundError,
    ):
        payload = diagnose_installation()
    assert payload["status"] == "INSTALLED"
    assert payload["distribution_version"] == ""
    assert payload["distribution_matches_import"] is False

    with (
        mock.patch(
            "e3workflow.diagnostics.metadata.version",
            return_value=__version__,
        ),
        mock.patch(
            "e3workflow.diagnostics.e3workflow.__file__",
            str(package_root / "unrelated" / "__init__.py"),
        ),
    ):
        payload = diagnose_installation(source_root=package_root)
    assert payload["status"] == "DIFFERENT_INSTALL_SOURCE"

    with mock.patch(
        "e3workflow.diagnostics.metadata.version",
        return_value="999.0.0",
    ):
        payload = diagnose_installation(source_root=package_root)
    assert payload["status"] == "DISTRIBUTION_METADATA_MISMATCH"


@pytest.mark.parametrize(
    ("installed_version", "status", "compatible"),
    [
        ("2.7.1", "COMPATIBLE", True),
        ("2.8.0", "COMPATIBLE", True),
        ("2.7.0", "INCOMPATIBLE_VERSION", False),
        ("3.0.0", "INCOMPATIBLE_VERSION", False),
        ("not-a-version", "INVALID_VERSION", False),
    ],
)
def test_slurm_executor_diagnostics_validate_supported_versions(
    installed_version: str,
    status: str,
    compatible: bool,
) -> None:
    """Executor diagnostics must enforce the batch-controller compatibility range."""
    with mock.patch(
        "e3workflow.diagnostics.metadata.version",
        return_value=installed_version,
    ):
        payload = diagnose_slurm_executor()
        assert payload["status"] == status
        assert payload["compatible"] is compatible
        if compatible:
            assert require_compatible_slurm_executor() == payload
        else:
            with pytest.raises(WorkflowError, match="batch-controller mode"):
                require_compatible_slurm_executor()


def test_slurm_executor_diagnostics_reject_missing_distribution() -> None:
    """A missing Slurm executor must fail before a controller is submitted."""
    with mock.patch(
        "e3workflow.diagnostics.metadata.version",
        side_effect=metadata.PackageNotFoundError,
    ):
        payload = diagnose_slurm_executor()
        assert payload["status"] == "NOT_INSTALLED"
        assert payload["compatible"] is False
        with pytest.raises(WorkflowError, match="NOT_INSTALLED"):
            require_compatible_slurm_executor()
