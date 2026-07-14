"""Software, hardware, and run-manifest provenance capture."""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence

from e3_discovery.io_utils import atomic_text_writer, sha256_file

LOGGER = logging.getLogger(__name__)


def capture_command_version(command: Sequence[str]) -> str:
    """Run a version command and capture a concise diagnostic string.

    The helper never raises for an unavailable executable or non-zero exit; it
    records the status so provenance generation can continue.

    Args:
        command: Executable and argument sequence used to request a version.

    Returns:
        Text containing the exit status and first non-empty output line, or an
        ``unavailable`` diagnostic when the process cannot be started.
    """

    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        return f"unavailable: {error}"
    text = (completed.stdout or completed.stderr).strip()
    first_line = text.splitlines()[0] if text else "no version output"
    return f"exit={completed.returncode}; {first_line}"


def capture_software_versions(
    tools: Mapping[str, Sequence[str]] | None = None,
) -> Dict[str, str]:
    """Capture Python, platform and selected external-tool versions.

    Args:
        tools: Optional mapping from display name to version-command arguments.
            Defaults to DIAMOND, Snakemake and DuckDB command-line clients.

    Returns:
        Mapping from software or platform name to captured version diagnostics.
    """

    selected = tools or {
        "diamond": ("diamond", "version"),
        "snakemake": ("snakemake", "--version"),
        "duckdb": ("duckdb", "--version"),
    }
    versions = {
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
    }
    for name, command in selected.items():
        executable = shutil.which(command[0])
        if executable is None:
            versions[name] = "unavailable: executable not found"
        else:
            versions[name] = capture_command_version((executable, *command[1:]))
    return versions


def build_file_manifest(paths: Iterable[Path]) -> Dict[str, Dict[str, object]]:
    """Record existence, size and SHA-256 checksum for workflow files.

    Duplicate paths are removed and paths are sorted after absolute resolution.
    Missing paths are retained with ``exists`` set to false.

    Args:
        paths: Input and output file paths to describe.

    Returns:
        Mapping from absolute path string to file-provenance metadata.

    Raises:
        OSError: If an existing file cannot be read or inspected.
    """

    manifest: Dict[str, Dict[str, object]] = {}
    for path in sorted({Path(item).resolve() for item in paths}):
        if not path.is_file():
            manifest[str(path)] = {"exists": False}
            continue
        manifest[str(path)] = {
            "exists": True,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return manifest


def write_run_manifest(
    output_path: Path,
    configuration: Mapping[str, object],
    files: Iterable[Path],
    additional_metadata: Mapping[str, object] | None = None,
) -> Dict[str, object]:
    """Write a JSON manifest describing configuration, software and workflow files.

    Args:
        output_path: Destination JSON path.
        configuration: Resolved workflow configuration to record.
        files: Input and output paths included in the file manifest.
        additional_metadata: Optional extra run-level metadata.

    Returns:
        The complete manifest dictionary written to disk.

    Raises:
        TypeError: If configuration or metadata is not JSON serialisable.
        OSError: If files cannot be inspected or the manifest cannot be written.
    """

    LOGGER.info("Writing run provenance manifest: %s", output_path)
    record: Dict[str, object] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": dict(configuration),
        "software_versions": capture_software_versions(),
        "files": build_file_manifest(files),
    }
    if additional_metadata:
        record["additional_metadata"] = dict(additional_metadata)
    with atomic_text_writer(output_path, newline="\n") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    LOGGER.info("Wrote provenance for %d files", len(record["files"]))
    return record
