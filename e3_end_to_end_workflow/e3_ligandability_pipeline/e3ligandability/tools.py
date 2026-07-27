"""External FPocket and P2Rank command execution with explicit provenance."""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

from .io_utils import atomic_write_text


_LOGGER = logging.getLogger("e3ligandability.tools")


class ExternalToolError(RuntimeError):
    """Raised when an external structural tool cannot be run safely."""


def resolve_executable(executable: str) -> Path:
    """Resolve an executable from an explicit path or ``PATH`` lookup.

    Args:
        executable: Executable name or path.

    Returns:
        Resolved executable path.

    Raises:
        ExternalToolError: If the executable cannot be found or executed.
    """

    candidate = Path(executable).expanduser()
    if candidate.parent != Path(".") or "/" in executable:
        resolved = candidate.resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ExternalToolError(
                f"Executable is absent or not executable: {resolved}"
            )
        return resolved

    located = shutil.which(executable)
    if located is None:
        raise ExternalToolError(f"Executable not found on PATH: {executable}")
    return Path(located).resolve()


def capture_tool_version(
    executable: Path,
    version_arguments: Sequence[str] | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Capture version output without assuming stdout versus stderr.

    Args:
        executable: Resolved executable path.
        version_arguments: Arguments used to request version information.
        timeout_seconds: Command timeout.

    Returns:
        Version command provenance record.
    """

    arguments = list(version_arguments or ["--version"])
    command = [str(executable), *arguments]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    combined = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part.strip()
    )
    return {
        "executable": str(executable),
        "command": shlex.join(command),
        "return_code": completed.returncode,
        "version_output": combined,
    }


def check_required_version(
    version_record: dict[str, Any],
    required_prefix: str,
    tool_name: str,
) -> None:
    """Enforce an optional required version substring.

    Args:
        version_record: Output from :func:`capture_tool_version`.
        required_prefix: Required version substring; empty disables checking.
        tool_name: Human-readable tool name.

    Raises:
        ExternalToolError: If version output is unavailable or mismatched.
    """

    return_code = int(version_record.get("return_code", 1))
    if return_code != 0:
        raise ExternalToolError(
            f"{tool_name} version command returned {return_code}: "
            f"{version_record.get('command', '')}"
        )
    if not required_prefix:
        return
    output = str(version_record.get("version_output", ""))
    if required_prefix not in output:
        raise ExternalToolError(
            f"{tool_name} version output does not contain required value "
            f"{required_prefix!r}: {output!r}"
        )


def run_command(
    command: Sequence[str],
    working_directory: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: float,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run one command with persistent logs and fail on non-zero exit.

    Args:
        command: Command and arguments without shell interpolation.
        working_directory: Existing command working directory.
        stdout_path: Persistent standard-output log.
        stderr_path: Persistent standard-error log.
        timeout_seconds: Hard timeout.
        environment: Optional environment additions.

    Returns:
        Command provenance record.

    Raises:
        ExternalToolError: If the command times out or returns non-zero.
    """

    cwd = Path(working_directory).expanduser().resolve()
    if not cwd.is_dir():
        raise ExternalToolError(f"Working directory does not exist: {cwd}")
    stdout_file = Path(stdout_path).expanduser().resolve()
    stderr_file = Path(stderr_path).expanduser().resolve()
    stdout_file.parent.mkdir(parents=True, exist_ok=True)
    stderr_file.parent.mkdir(parents=True, exist_ok=True)

    merged_environment = os.environ.copy()
    if environment:
        merged_environment.update(environment)

    started = time.monotonic()
    _LOGGER.info("Running external command: %s", shlex.join(command))
    try:
        with (
            stdout_file.open("w", encoding="utf-8") as stdout_handle,
            stderr_file.open("w", encoding="utf-8") as stderr_handle,
        ):
            completed = subprocess.run(
                list(command),
                cwd=cwd,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=merged_environment,
            )
    except subprocess.TimeoutExpired as error:
        elapsed = time.monotonic() - started
        raise ExternalToolError(
            f"Command timed out after {elapsed:.1f} seconds: "
            f"{shlex.join(command)}"
        ) from error

    elapsed = time.monotonic() - started
    record = {
        "command": shlex.join(command),
        "working_directory": str(cwd),
        "stdout_path": str(stdout_file),
        "stderr_path": str(stderr_file),
        "return_code": completed.returncode,
        "elapsed_seconds": elapsed,
    }
    if completed.returncode != 0:
        raise ExternalToolError(
            f"Command returned {completed.returncode}: {shlex.join(command)}; "
            f"see {stderr_file}"
        )
    return record


def write_single_model_dataset(path: Path, model_path: Path) -> None:
    """Write the one-line dataset expected by P2Rank ``fpocket-rescore``.

    Args:
        path: Dataset destination.
        model_path: Absolute model CIF path.
    """

    resolved_model = Path(model_path).expanduser().resolve()
    if not resolved_model.is_file():
        raise FileNotFoundError(f"Model does not exist: {resolved_model}")
    atomic_write_text(path, f"{resolved_model}\n")


def run_fpocket_rescore(
    accession: str,
    model_path: Path,
    output_directory: Path,
    fpocket_executable: Path,
    p2rank_executable: Path,
    p2rank_model: str,
    threads: int,
    keep_fpocket_output: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Run P2Rank's official FPocket-and-rescore workflow for one model.

    External tools write into a unique staging directory. The directory is
    published to the requested accession path only after the command succeeds
    and both an FPocket info file and a P2Rank predictions file are present.
    This prevents stale outputs from a previous run being mistaken for new
    results. A failed staging directory is retained for diagnosis.

    Args:
        accession: Protein accession for log and dataset naming.
        model_path: Validated model mmCIF.
        output_directory: Final accession-specific tool-output directory.
        fpocket_executable: Resolved FPocket executable.
        p2rank_executable: Resolved P2Rank ``prank`` executable.
        p2rank_model: P2Rank rescoring configuration name.
        threads: P2Rank worker threads.
        keep_fpocket_output: Retain raw FPocket output files.
        timeout_seconds: Command timeout.

    Returns:
        Command provenance record with final published paths.

    Raises:
        ExternalToolError: If the command fails or required outputs are absent.
    """

    final_directory = Path(output_directory).expanduser().resolve()
    final_directory.parent.mkdir(parents=True, exist_ok=True)
    staging_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{final_directory.name}.running.",
            dir=final_directory.parent,
        )
    )
    dataset_path = staging_directory / f"{accession}.ds"
    write_single_model_dataset(dataset_path, model_path)

    command = [
        str(p2rank_executable),
        "fpocket-rescore",
        str(dataset_path),
        "-c",
        p2rank_model,
        "-o",
        str(staging_directory),
        "-threads",
        str(threads),
        "-fpocket_command",
        str(fpocket_executable),
        "-fpocket_keep_output",
        "1" if keep_fpocket_output else "0",
    ]
    record = run_command(
        command=command,
        working_directory=staging_directory,
        stdout_path=staging_directory / "p2rank_fpocket_rescore.stdout.log",
        stderr_path=staging_directory / "p2rank_fpocket_rescore.stderr.log",
        timeout_seconds=timeout_seconds,
    )

    info_files = sorted(staging_directory.rglob("*_info.txt"))
    prediction_files = sorted(staging_directory.rglob("*_predictions.csv"))
    if not info_files or not prediction_files:
        raise ExternalToolError(
            "P2Rank/FPocket command returned zero but required output files "
            f"were not found in {staging_directory}; info_files={len(info_files)}, "
            f"prediction_files={len(prediction_files)}"
        )

    backup_directory = final_directory.with_name(
        f".{final_directory.name}.previous"
    )
    if backup_directory.exists():
        shutil.rmtree(backup_directory)
    published = False
    try:
        if final_directory.exists():
            final_directory.replace(backup_directory)
        staging_directory.replace(final_directory)
        published = True
    except Exception:
        if backup_directory.exists() and not final_directory.exists():
            backup_directory.replace(final_directory)
        raise
    finally:
        if published and backup_directory.exists():
            shutil.rmtree(backup_directory)

    record["accession"] = accession
    record["dataset_path"] = str(final_directory / dataset_path.name)
    record["fpocket_executable"] = str(fpocket_executable)
    record["p2rank_executable"] = str(p2rank_executable)
    record["p2rank_model"] = p2rank_model
    record["published_output_directory"] = str(final_directory)
    record["staging_output_directory"] = str(staging_directory)
    record["stdout_path"] = str(
        final_directory / "p2rank_fpocket_rescore.stdout.log"
    )
    record["stderr_path"] = str(
        final_directory / "p2rank_fpocket_rescore.stderr.log"
    )
    return record
