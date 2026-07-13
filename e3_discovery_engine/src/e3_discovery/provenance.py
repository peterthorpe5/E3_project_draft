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
    """Return the first non-empty version line or a diagnostic string."""

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
    """Capture Python and external-tool versions without failing on absence."""

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
    """Build checksums and sizes for named input/output files."""

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
    """Write a deterministic JSON run manifest with provenance information."""

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
