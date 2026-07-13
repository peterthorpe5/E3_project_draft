"""DIAMOND command construction and defensive execution."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from e3_discovery.exceptions import ConfigurationError, ExternalToolError
from e3_discovery.io_utils import ensure_parent, require_nonempty_file

LOGGER = logging.getLogger(__name__)

_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True, order=True)
class SemanticVersion:
    """Small semantic-version representation suitable for feature checks."""

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        """Return the conventional dotted semantic-version representation."""

        return f"{self.major}.{self.minor}.{self.patch}"


def parse_semantic_version(text: str) -> SemanticVersion:
    """Extract the first three-component semantic version from text."""

    match = _VERSION_PATTERN.search(str(text))
    if not match:
        raise ValueError(f"No semantic version found in: {text!r}")
    return SemanticVersion(*(int(value) for value in match.groups()))


def get_diamond_version(executable: str = "diamond") -> SemanticVersion:
    """Run ``diamond version`` and return its parsed semantic version."""

    completed = subprocess.run(
        [executable, "version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        LOGGER.error(
            "Could not determine DIAMOND version; exit code %d",
            completed.returncode,
        )
        raise ExternalToolError(
            f"Could not determine DIAMOND version: {completed.stderr.strip()}"
        )
    return parse_semantic_version(completed.stdout or completed.stderr)


def require_diamond_features(
    version: SemanticVersion,
    identity_mode: str,
) -> None:
    """Validate that the selected DIAMOND version supports requested features."""

    if identity_mode == "exact" and version < SemanticVersion(2, 2, 1):
        raise ConfigurationError(
            "Exact clustering identity (--id) requires DIAMOND >= 2.2.1"
        )
    if identity_mode not in {"exact", "approximate"}:
        raise ConfigurationError(
            "identity_mode must be either 'exact' or 'approximate'"
        )


def build_makedb_command(
    executable: str,
    input_fasta: Path,
    output_database: Path,
    threads: int,
) -> List[str]:
    """Build a DIAMOND ``makedb`` command."""

    if threads < 1:
        raise ValueError("threads must be positive")
    return [
        executable,
        "makedb",
        "--in",
        str(input_fasta),
        "--db",
        str(output_database),
        "--threads",
        str(threads),
    ]


def build_deepclust_command(
    executable: str,
    database: Path,
    output_tsv: Path,
    threads: int,
    memory_limit: str,
    identity_mode: str,
    identity_percent: float,
    mutual_cover_percent: float,
    clustering_evalue: float,
    cluster_steps: Optional[Sequence[str]] = None,
    masking: Optional[str] = None,
    extra_args: Optional[Sequence[str]] = None,
) -> List[str]:
    """Build a DIAMOND DeepClust command with explicit core parameters."""

    if threads < 1:
        raise ValueError("threads must be positive")
    if not 0 < identity_percent <= 100:
        raise ValueError("identity_percent must be in (0, 100]")
    if not 0 < mutual_cover_percent <= 100:
        raise ValueError("mutual_cover_percent must be in (0, 100]")
    if clustering_evalue <= 0:
        raise ValueError("clustering_evalue must be positive")
    if identity_mode not in {"exact", "approximate"}:
        raise ValueError(
            "identity_mode must be either 'exact' or 'approximate'"
        )
    allowed_masking = {None, "none", "seg", "seg-all", "tantan"}
    if masking not in allowed_masking:
        raise ValueError(
            "masking must be one of: none, seg, seg-all, tantan, or None"
        )
    identity_option = "--id" if identity_mode == "exact" else "--approx-id"
    command = [
        executable,
        "deepclust",
        "--db",
        str(database),
        "--out",
        str(output_tsv),
        "--threads",
        str(threads),
        "--memory-limit",
        str(memory_limit),
        identity_option,
        str(identity_percent),
        "--mutual-cover",
        str(mutual_cover_percent),
        "--evalue",
        str(clustering_evalue),
        "--header",
    ]
    if cluster_steps:
        command.extend(["--cluster-steps", *cluster_steps])
    if masking:
        command.extend(["--masking", masking])
    if extra_args:
        command.extend(str(value) for value in extra_args)
    return command


def build_realign_command(
    executable: str,
    database: Path,
    clusters_tsv: Path,
    output_tsv: Path,
    threads: int,
    memory_limit: str,
) -> List[str]:
    """Build a realignment command with exact identity and length fields."""

    if threads < 1:
        raise ValueError("threads must be positive")
    return [
        executable,
        "realign",
        "--db",
        str(database),
        "--clusters",
        str(clusters_tsv),
        "--out",
        str(output_tsv),
        "--threads",
        str(threads),
        "--memory-limit",
        str(memory_limit),
        "--outfmt",
        "6",
        "qseqid",
        "sseqid",
        "pident",
        "qlen",
        "slen",
        "qstart",
        "qend",
        "sstart",
        "send",
        "length",
        "evalue",
        "bitscore",
        "--header",
    ]


def read_log_tail(
    log_path: Path,
    max_lines: int = 40,
    max_characters: int = 12000,
) -> str:
    """Return a bounded tail of a UTF-8 log file for error reporting."""

    if max_lines < 1:
        raise ValueError("max_lines must be positive")
    if max_characters < 1:
        raise ValueError("max_characters must be positive")
    path = Path(log_path)
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-max_lines:])
    if len(tail) > max_characters:
        tail = tail[-max_characters:]
    return tail


def run_external_command(
    command: Sequence[str],
    log_path: Path,
    command_record_path: Optional[Path] = None,
    environment: Optional[Mapping[str, str]] = None,
) -> None:
    """Run a command with combined stdout/stderr logging and command capture."""

    if not command:
        raise ValueError("command cannot be empty")
    LOGGER.info("Running external command: %s", " ".join(map(str, command)))
    log_file = ensure_parent(Path(log_path))
    if command_record_path is not None:
        record = ensure_parent(Path(command_record_path))
        record.write_text(
            json.dumps(
                {
                    "command": list(command),
                    "working_directory": os.getcwd(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    merged_environment = os.environ.copy()
    if environment:
        merged_environment.update({str(k): str(v) for k, v in environment.items()})
    with log_file.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            list(command),
            check=False,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=merged_environment,
        )
    if completed.returncode != 0:
        LOGGER.error(
            "External command failed with exit code %d; see %s",
            completed.returncode,
            log_file,
        )
        log_tail = read_log_tail(log_file)
        tail_message = (
            f"\n--- log tail ---\n{log_tail}\n--- end log tail ---"
            if log_tail
            else ""
        )
        raise ExternalToolError(
            f"External command failed with exit code {completed.returncode}. "
            f"See log: {log_file}{tail_message}"
        )
    LOGGER.info("External command completed successfully")


def validate_expected_outputs(paths: Iterable[Path]) -> Tuple[Path, ...]:
    """Validate expected outputs and return them as a tuple."""

    validated = tuple(require_nonempty_file(path) for path in paths)
    if not validated:
        raise ValueError("At least one expected output must be supplied")
    return validated
