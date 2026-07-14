"""DIAMOND command construction and defensive execution."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
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
    """Represent a three-component semantic version for feature checks.

    Instances are immutable and orderable, allowing direct comparison of
    installed and minimum-supported DIAMOND versions.

    Attributes:
        major: Major release component.
        minor: Minor release component.
        patch: Patch release component.
    """

    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        """Format the semantic version using dotted decimal notation.

        Returns:
            A string in ``major.minor.patch`` form.
        """

        return f"{self.major}.{self.minor}.{self.patch}"


def parse_semantic_version(text: str) -> SemanticVersion:
    """Extract the first three-component semantic version from text.

    Args:
        text: Arbitrary command output or metadata containing a version string.

    Returns:
        Parsed :class:`SemanticVersion` values.

    Raises:
        ValueError: If no ``major.minor.patch`` pattern is present.
    """

    match = _VERSION_PATTERN.search(str(text))
    if not match:
        raise ValueError(f"No semantic version found in: {text!r}")
    return SemanticVersion(*(int(value) for value in match.groups()))


def get_diamond_version(executable: str = "diamond") -> SemanticVersion:
    """Query a DIAMOND executable and parse its reported version.

    Args:
        executable: DIAMOND executable name or absolute path.

    Returns:
        Parsed semantic version reported by ``diamond version``.

    Raises:
        OSError: If the executable cannot be started.
        ExternalToolError: If the version command exits unsuccessfully.
        ValueError: If successful output contains no semantic version.
    """

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
    """Check that an installed DIAMOND version supports the identity mode.

    Args:
        version: Installed DIAMOND semantic version.
        identity_mode: Requested ``exact`` or ``approximate`` clustering mode.

    Returns:
        None.

    Raises:
        ConfigurationError: If the mode is invalid or exact identity is
            requested with DIAMOND older than 2.2.1.
    """

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
    """Construct a DIAMOND ``makedb`` argument vector.

    Args:
        executable: DIAMOND executable name or path.
        input_fasta: Combined protein FASTA used to build the database.
        output_database: Destination DIAMOND database path.
        threads: Number of DIAMOND worker threads.

    Returns:
        Command arguments suitable for ``subprocess.run`` without shell parsing.

    Raises:
        ValueError: If ``threads`` is smaller than one.
    """

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
    comp_based_stats: int = 0,
    cluster_steps: Optional[Sequence[str]] = None,
    masking: Optional[str] = None,
    extra_args: Optional[Sequence[str]] = None,
) -> List[str]:
    """Construct a validated DIAMOND DeepClust argument vector.

    The command uses exact or approximate identity as requested, applies
    explicit coverage, e-value, memory and composition-statistics settings, and
    emits the native cluster header required by DIAMOND ``realign``.

    Args:
        executable: DIAMOND executable name or path.
        database: Existing DIAMOND protein database.
        output_tsv: Destination cluster-membership TSV.
        threads: Number of DIAMOND worker threads.
        memory_limit: DIAMOND memory-limit expression, such as ``64G``.
        identity_mode: ``exact`` for ``--id`` or ``approximate`` for
            ``--approx-id``.
        identity_percent: Minimum clustering identity percentage.
        mutual_cover_percent: Minimum mutual sequence coverage percentage.
        clustering_evalue: Clustering-stage e-value threshold.
        comp_based_stats: DIAMOND composition-based statistics mode from 0 to 6.
        cluster_steps: Optional additional DeepClust step definitions.
        masking: Optional supported masking mode.
        extra_args: Optional additional argument tokens appended verbatim.

    Returns:
        Validated command arguments suitable for ``subprocess.run``.

    Raises:
        ValueError: If numeric ranges, identity mode, masking mode or
            identity/composition-statistics compatibility is invalid.
    """

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
    if not isinstance(comp_based_stats, int) or not 0 <= comp_based_stats <= 6:
        raise ValueError("comp_based_stats must be an integer from 0 to 6")
    if identity_mode == "exact" and comp_based_stats not in {0, 1}:
        raise ValueError(
            "Exact identity requires alignment traceback and is incompatible "
            "with compositionally adjusted matrix modes 2-6; use "
            "comp_based_stats 0 or 1"
        )
    allowed_masking = {None, "none", "tantan"}
    if masking not in allowed_masking:
        raise ValueError(
            "DeepClust self-alignment requires symmetric masking. "
            "Use 'tantan', 'none', or None; target-only SEG masking "
            "causes DIAMOND to fail with asymmetric masking."
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
        "--comp-based-stats",
        str(comp_based_stats),
    ]
    if cluster_steps:
        command.extend(["--cluster-steps", *cluster_steps])
    # DIAMOND 2.2.x realign requires the native clustering header.  The
    # flag-only option emits ``centroid\tmember`` for clustering output.
    command.append("--header")
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
    comp_based_stats: int = 0,
    masking: Optional[str] = None,
) -> List[str]:
    """Construct a validated DIAMOND ``realign`` argument vector.

    The command requests the identifiers, lengths, coordinates, identity,
    alignment length, e-value and bit score required for strict downstream
    classification, with a simple tabular header.

    Args:
        executable: DIAMOND executable name or path.
        database: DIAMOND database used during clustering.
        clusters_tsv: Native headered DeepClust membership table.
        output_tsv: Destination realignment TSV.
        threads: Number of DIAMOND worker threads.
        memory_limit: DIAMOND memory-limit expression.
        comp_based_stats: Traceback-compatible mode ``0`` or ``1``.
        masking: Optional supported masking mode.

    Returns:
        Validated command arguments suitable for ``subprocess.run``.

    Raises:
        ValueError: If threads, matrix mode or masking mode is invalid.
    """

    if threads < 1:
        raise ValueError("threads must be positive")
    if comp_based_stats not in {0, 1}:
        raise ValueError(
            "Realignment traceback is incompatible with compositionally "
            "adjusted matrix modes 2-6; use comp_based_stats 0 or 1"
        )
    allowed_masking = {None, "none", "tantan"}
    if masking not in allowed_masking:
        raise ValueError(
            "The production workflow uses one symmetric masking mode for "
            "DeepClust and realignment. Use 'tantan', 'none', or None."
        )
    command = [
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
        "--comp-based-stats",
        str(comp_based_stats),
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
    ]
    if masking:
        command.extend(["--masking", masking])
    return command


def read_log_tail(
    log_path: Path,
    max_lines: int = 40,
    max_characters: int = 12000,
) -> str:
    """Read a bounded tail from a UTF-8 external-tool log.

    Args:
        log_path: Path to the log file.
        max_lines: Maximum number of final lines to retain.
        max_characters: Maximum number of final characters to retain.

    Returns:
        The bounded log tail, or an empty string when the file is absent.

    Raises:
        ValueError: If either bound is smaller than one.
        OSError: If an existing log cannot be read.
    """

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


def diamond_error_hint(log_text: str) -> str:
    """Translate recognised DIAMOND failures into focused remediation guidance.

    Args:
        log_text: Full or partial DIAMOND log text.

    Returns:
        A diagnostic hint for a recognised failure, otherwise an empty string.
    """

    normalised = str(log_text).lower()
    if "traceback with adjusted matrix not supported" in normalised:
        return (
            "DIAMOND exact identity/traceback cannot be used with a "
            "compositionally adjusted matrix. Set diamond.comp_based_stats "
            "to 0 (recommended for this workflow) or 1."
        )
    if "clusters file is missing header line" in normalised:
        return (
            "DIAMOND realign requires the native clustering header. Recreate "
            "the DeepClust file with the flag-only --header option; DIAMOND "
            "2.2.x emits centroid<TAB>member."
        )
    if "asymmetric masking for self alignment" in normalised:
        return (
            "DIAMOND DeepClust performs self-alignment. SEG masks target "
            "sequences asymmetrically in DIAMOND 2.2.3, so use "
            "diamond.masking: tantan (recommended) or none."
        )
    return ""


def run_external_command(
    command: Sequence[str],
    log_path: Path,
    command_record_path: Optional[Path] = None,
    environment: Optional[Mapping[str, str]] = None,
) -> None:
    """Run an external command with persistent combined logging and provenance.

    Standard output and standard error are merged into ``log_path``. An optional
    JSON record captures the exact argument vector and working directory. A
    caller-supplied environment is merged with the current process environment.

    Args:
        command: Non-empty argument sequence; no shell interpretation is used.
        log_path: Destination for combined standard output and error.
        command_record_path: Optional JSON command-provenance destination.
        environment: Optional environment-variable overrides.

    Returns:
        None.

    Raises:
        ValueError: If ``command`` is empty.
        OSError: If the process cannot be started or logs cannot be written.
        ExternalToolError: If the command exits with a non-zero status.
    """

    if not command:
        raise ValueError("command cannot be empty")
    LOGGER.info("Running external command: %s", shlex.join(map(str, command)))
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
        hint = diamond_error_hint(log_tail)
        hint_message = f"\nDiagnostic hint: {hint}" if hint else ""
        tail_message = (
            f"\n--- log tail ---\n{log_tail}\n--- end log tail ---"
            if log_tail
            else ""
        )
        raise ExternalToolError(
            f"External command failed with exit code {completed.returncode}. "
            f"See log: {log_file}{tail_message}{hint_message}"
        )
    LOGGER.info("External command completed successfully")


def validate_expected_outputs(paths: Iterable[Path]) -> Tuple[Path, ...]:
    """Verify that all expected external-tool outputs exist and are non-empty.

    Args:
        paths: Iterable of output paths to validate.

    Returns:
        A tuple containing the validated paths in input order.

    Raises:
        ValueError: If no expected outputs are supplied.
        DataValidationError: If any expected output is absent or empty.
    """

    validated = tuple(require_nonempty_file(path) for path in paths)
    if not validated:
        raise ValueError("At least one expected output must be supplied")
    return validated
