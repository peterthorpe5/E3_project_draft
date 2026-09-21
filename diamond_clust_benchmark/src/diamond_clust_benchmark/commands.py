"""Construct shell-free DIAMOND commands for each benchmark case."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Sequence, Tuple

from diamond_clust_benchmark.config import BenchmarkCase
from diamond_clust_benchmark.exceptions import ExternalCommandError

_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def command_prefix(case: BenchmarkCase) -> List[str]:
    """Build the executable prefix for a direct or Conda-managed case.

    Args:
        case: Validated benchmark case.

    Returns:
        Argument vector ending with the configured DIAMOND executable.
    """

    if case.conda_environment:
        return [
            "conda",
            "run",
            "--no-capture-output",
            "--name",
            case.conda_environment,
            case.executable,
        ]
    return [case.executable]


def parse_version(text: str) -> Tuple[int, int, int]:
    """Extract a three-component version from DIAMOND output.

    Args:
        text: Version command output.

    Returns:
        Integer ``major``, ``minor`` and ``patch`` components.

    Raises:
        ValueError: If no semantic version is present.
    """

    match = _VERSION_PATTERN.search(str(text))
    if not match:
        raise ValueError(f"No semantic version found in: {text!r}")
    return tuple(int(value) for value in match.groups())


def get_version(case: BenchmarkCase) -> str:
    """Return and validate the installed DIAMOND version for a case.

    Args:
        case: Validated benchmark case.

    Returns:
        Exact dotted DIAMOND version string.

    Raises:
        ExternalCommandError: If the executable fails or the version differs.
    """

    command = [*command_prefix(case), "version"]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ExternalCommandError(
            f"Could not query DIAMOND for {case.case_id}: {detail}"
        )
    output = completed.stdout or completed.stderr
    try:
        parsed = ".".join(str(value) for value in parse_version(output))
    except ValueError as error:
        raise ExternalCommandError(
            f"Could not parse DIAMOND version for {case.case_id}: {output!r}"
        ) from error
    if parsed != case.expected_version:
        raise ExternalCommandError(
            f"{case.case_id} requires DIAMOND {case.expected_version}, "
            f"but {parsed} was resolved"
        )
    if case.identity_mode == "exact" and parse_version(parsed) < (2, 2, 1):
        raise ExternalCommandError(
            f"{case.case_id}: exact DeepClust identity requires DIAMOND >=2.2.1"
        )
    return parsed


def build_makedb_command(
    case: BenchmarkCase,
    input_fasta: Path,
    output_database: Path,
    threads: int,
) -> List[str]:
    """Construct a DIAMOND ``makedb`` argument vector.

    Args:
        case: Benchmark case providing executable information.
        input_fasta: Protein FASTA input.
        output_database: Destination database prefix or path.
        threads: Positive worker-thread count.

    Returns:
        Shell-free command argument vector.

    Raises:
        ValueError: If ``threads`` is not positive.
    """

    if threads < 1:
        raise ValueError("threads must be positive")
    return [
        *command_prefix(case),
        "makedb",
        "--in",
        str(input_fasta),
        "--db",
        str(output_database),
        "--threads",
        str(threads),
    ]


def build_cluster_command(
    case: BenchmarkCase,
    database: Path,
    output_tsv: Path,
    threads: int,
    memory_limit: str,
    temporary_directory: Path,
) -> List[str]:
    """Construct a DeepClust or LinClust benchmark command.

    Args:
        case: Validated benchmark case.
        database: Existing DIAMOND database.
        output_tsv: Destination membership table.
        threads: Positive worker-thread count.
        memory_limit: DIAMOND memory-limit expression.
        temporary_directory: Case-specific temporary directory.

    Returns:
        Shell-free command argument vector.

    Raises:
        ValueError: If ``threads`` is not positive.
    """

    if threads < 1:
        raise ValueError("threads must be positive")
    identity_flag = "--id" if case.identity_mode == "exact" else "--approx-id"
    command = [
        *command_prefix(case),
        case.command,
        "--db",
        str(database),
        "--out",
        str(output_tsv),
        "--threads",
        str(threads),
        "--memory-limit",
        memory_limit,
        identity_flag,
        str(case.identity_percent),
        "--mutual-cover",
        str(case.mutual_cover_percent),
        "--evalue",
        str(case.evalue),
        "--comp-based-stats",
        str(case.comp_based_stats),
        "--header",
        "--tmpdir",
        str(temporary_directory),
    ]
    if case.masking:
        command.extend(["--masking", case.masking])
    if case.cluster_steps:
        command.extend(["--cluster-steps", *case.cluster_steps])
    if case.no_reassign:
        command.append("--no-reassign")
    command.extend(case.extra_args)
    return command


def build_realign_command(
    case: BenchmarkCase,
    database: Path,
    clusters_tsv: Path,
    output_tsv: Path,
    threads: int,
    memory_limit: str,
    temporary_directory: Path,
) -> List[str]:
    """Construct an exact representative-member realignment command.

    Args:
        case: Validated benchmark case.
        database: Existing DIAMOND database.
        clusters_tsv: Native headered cluster-membership table.
        output_tsv: Destination realignment table.
        threads: Positive worker-thread count.
        memory_limit: DIAMOND memory-limit expression.
        temporary_directory: Case-specific temporary directory.

    Returns:
        Shell-free command argument vector.

    Raises:
        ValueError: If ``threads`` is not positive.
    """

    if threads < 1:
        raise ValueError("threads must be positive")
    command = [
        *command_prefix(case),
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
        memory_limit,
        "--comp-based-stats",
        "0",
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
        "simple",
        "--tmpdir",
        str(temporary_directory),
    ]
    if case.masking:
        command.extend(["--masking", case.masking])
    return command


def command_as_text(command: Sequence[str]) -> str:
    """Format a command for human-readable logging without executing a shell.

    Args:
        command: Argument vector.

    Returns:
        Safely quoted command text.
    """

    import shlex

    return shlex.join(str(token) for token in command)
