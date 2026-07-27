"""Installation-provenance diagnostics for the E3 workflow command."""

from __future__ import annotations

import shutil
import sys
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

import e3workflow
from e3workflow import __version__
from e3workflow.errors import WorkflowError

PACKAGE_DISTRIBUTION = "e3-end-to-end-workflow"
SLURM_EXECUTOR_DISTRIBUTION = "snakemake-executor-plugin-slurm"
MINIMUM_SLURM_EXECUTOR_VERSION = Version("2.7.1")


def _source_version(source_root: Path) -> str:
    """Read the project version from one package source root.

    Args:
        source_root: Directory containing ``pyproject.toml`` and ``src/e3workflow``.

    Returns:
        Validated project version string.

    Raises:
        WorkflowError: If the source tree or version metadata is unavailable.
    """
    root = Path(source_root).expanduser().resolve()
    pyproject_path = root / "pyproject.toml"
    module_path = root / "src" / "e3workflow" / "__init__.py"
    if not pyproject_path.is_file() or not module_path.is_file():
        raise WorkflowError(
            "Source root must contain pyproject.toml and src/e3workflow/__init__.py: "
            f"{root}"
        )
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        version = payload["project"]["version"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise WorkflowError(
            f"Could not read project.version from {pyproject_path}: {exc}"
        ) from exc
    if not isinstance(version, str) or not version.strip():
        raise WorkflowError(f"project.version is empty or invalid in {pyproject_path}")
    return version.strip()


def diagnose_installation(*, source_root: Path | None = None) -> dict[str, Any]:
    """Report the Python, distribution, command and source tree actually in use.

    Args:
        source_root: Optional expected editable-install package root.

    Returns:
        Machine-readable installation and source-provenance fields.
    """
    try:
        distribution_version = metadata.version(PACKAGE_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        distribution_version = ""
    imported_module_path = Path(e3workflow.__file__).resolve()
    payload: dict[str, Any] = {
        "status": "INSTALLED",
        "python_executable": str(Path(sys.executable).resolve()),
        "cli_executable": shutil.which("e3-workflow") or "",
        "imported_module_path": str(imported_module_path),
        "imported_version": __version__,
        "distribution_version": distribution_version,
        "distribution_matches_import": (
            bool(distribution_version) and distribution_version == __version__
        ),
    }
    if source_root is None:
        return payload
    root = Path(source_root).expanduser().resolve()
    source_version = _source_version(root)
    expected_module_path = (root / "src" / "e3workflow" / "__init__.py").resolve()
    version_matches_source = source_version == __version__
    module_matches_source = imported_module_path == expected_module_path
    if not version_matches_source:
        status = "VERSION_MISMATCH"
    elif not module_matches_source:
        status = "DIFFERENT_INSTALL_SOURCE"
    elif distribution_version and distribution_version != source_version:
        status = "DISTRIBUTION_METADATA_MISMATCH"
    else:
        status = "MATCHED_SOURCE"
    payload.update(
        {
            "status": status,
            "source_root": str(root),
            "source_version": source_version,
            "expected_module_path": str(expected_module_path),
            "version_matches_source": version_matches_source,
            "module_matches_source": module_matches_source,
        }
    )
    return payload


def require_matching_source(*, source_root: Path) -> dict[str, Any]:
    """Require the active CLI import to originate from the supplied source tree.

    Args:
        source_root: Expected editable-install package root.

    Returns:
        Successful installation diagnostic.

    Raises:
        WorkflowError: If the active command imports another version or source tree.
    """
    payload = diagnose_installation(source_root=source_root)
    if payload["status"] != "MATCHED_SOURCE":
        raise WorkflowError(
            "Installed workflow does not match the requested source tree: "
            f"status={payload['status']}, source_version={payload['source_version']}, "
            f"imported_version={payload['imported_version']}, "
            f"imported_module_path={payload['imported_module_path']}"
        )
    return payload


def diagnose_slurm_executor() -> dict[str, Any]:
    """Report whether the installed Slurm executor is safe for batch controllers.

    Returns:
        Machine-readable executor version and compatibility fields.
    """
    try:
        installed_text = metadata.version(SLURM_EXECUTOR_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return {
            "status": "NOT_INSTALLED",
            "distribution": SLURM_EXECUTOR_DISTRIBUTION,
            "installed_version": "",
            "minimum_version": str(MINIMUM_SLURM_EXECUTOR_VERSION),
            "compatible": False,
        }
    try:
        installed_version = Version(installed_text)
    except InvalidVersion:
        return {
            "status": "INVALID_VERSION",
            "distribution": SLURM_EXECUTOR_DISTRIBUTION,
            "installed_version": installed_text,
            "minimum_version": str(MINIMUM_SLURM_EXECUTOR_VERSION),
            "compatible": False,
        }
    compatible = (
        installed_version >= MINIMUM_SLURM_EXECUTOR_VERSION
        and installed_version.major < 3
    )
    return {
        "status": "COMPATIBLE" if compatible else "INCOMPATIBLE_VERSION",
        "distribution": SLURM_EXECUTOR_DISTRIBUTION,
        "installed_version": installed_text,
        "minimum_version": str(MINIMUM_SLURM_EXECUTOR_VERSION),
        "compatible": compatible,
    }


def require_compatible_slurm_executor() -> dict[str, Any]:
    """Require a Slurm executor version safe for a controller inside Slurm.

    Returns:
        Successful executor diagnostic.

    Raises:
        WorkflowError: If the executor is missing, invalid or outside the supported range.
    """
    payload = diagnose_slurm_executor()
    if not payload["compatible"]:
        raise WorkflowError(
            "The Slurm executor is not compatible with the batch-controller mode: "
            f"status={payload['status']}, installed_version="
            f"{payload['installed_version'] or 'NOT_INSTALLED'}, required="
            f">={payload['minimum_version']},<3"
        )
    return payload
