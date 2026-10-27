"""LoL-align through Foldseek, with explicit score and transform semantics.

Foldseek's u/t transform moves the target onto the query. The reference is
therefore the query and the mobile model the target. The transform and TM
metrics are computed by Foldseek from the LoL-align residue correspondence;
the LoL alignment itself is local and is not a TM-align alignment.
"""

from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from e3structalign.errors import NoAlignmentFoundError, ToolExecutionError
from e3structalign.models import Transform, USAlignResult

LOGGER = logging.getLogger("e3structalign")
OUTPUT_FIELDS = (
    "query", "target", "qlen", "tlen", "qaln", "taln", "qtmscore", "ttmscore",
    "rmsd", "evalue", "prob", "u", "t",
)


def foldseek_version(*, executable: str) -> str:
    """Check Foldseek's installed version and explicit LoL-align capability.

    Args:
        executable: Configured Foldseek executable.

    Returns:
        Version or source revision reported by Foldseek.

    Raises:
        ToolExecutionError: If execution fails or LoL-align is unsupported.
    """
    try:
        version = subprocess.run(
            args=[executable, "version"], check=False, capture_output=True,
            text=True, timeout=30,
        )
        help_result = subprocess.run(
            args=[executable, "easy-search", "-h"], check=False,
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolExecutionError(f"Could not inspect Foldseek {executable!r}: {exc}") from exc
    text = version.stdout.strip()
    if version.returncode != 0 or not text or len(text.splitlines()) != 1:
        raise ToolExecutionError("Foldseek did not report one valid version line")
    if help_result.returncode != 0 or "--lolalign-multidomain" not in (
        help_result.stdout + help_result.stderr
    ):
        raise ToolExecutionError(
            "This Foldseek binary lacks LoL-align support; install a LoL-enabled build"
        )
    LOGGER.info("Foldseek LoL-align capability verified: %s", text)
    return text


def _finite_numbers(*, text: str, count: int, field: str) -> tuple[float, ...]:
    """Parse a fixed-size, finite numeric vector from one Foldseek TSV cell.

    Args:
        text: Comma-delimited vector emitted inside a tab-delimited tool record.
        count: Required number of numeric values.
        field: Field name for error messages.

    Returns:
        Parsed values in tool order.

    Raises:
        ToolExecutionError: If the vector is malformed or non-finite.
    """
    try:
        values = tuple(float(value) for value in text.split(","))
    except ValueError as exc:
        raise ToolExecutionError(f"Invalid LoL-align numeric field {field}") from exc
    if len(values) != count or not all(math.isfinite(value) for value in values):
        raise ToolExecutionError(f"Invalid LoL-align numeric field {field}")
    return values


def parse_lolalign_output(*, text: str, version: str) -> USAlignResult:
    """Parse exactly one LoL-align hit and validate its mobile-to-reference transform.

    Args:
        text: Raw TSV using OUTPUT_FIELDS, without a header.
        version: Validated Foldseek version/revision.

    Returns:
        Alignment correspondence metrics, a rigid transform and separate LoL scores.

    Raises:
        ToolExecutionError: For missing, ambiguous or malformed alignments.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise NoAlignmentFoundError("LoL-align returned no local residue correspondence")
    if len(lines) != 1:
        raise ToolExecutionError(
            f"Expected one LoL-align pairwise result; found {len(lines)}. "
            "Check monomer inputs and tool logs."
        )
    cells = lines[0].split("\t")
    if len(cells) != len(OUTPUT_FIELDS):
        raise ToolExecutionError("LoL-align TSV column count differs from the requested schema")
    row = dict(zip(OUTPUT_FIELDS, cells, strict=True))
    try:
        query_length, target_length = int(row["qlen"]), int(row["tlen"])
    except ValueError as exc:
        raise ToolExecutionError("LoL-align reported invalid model lengths") from exc
    query, target = row["qaln"], row["taln"]
    if (
        min(query_length, target_length) < 1 or not query or len(query) != len(target)
        or not row["query"] or not row["target"]
        or any(first == second == "-" for first, second in zip(query, target, strict=True))
        or len(query.replace("-", "")) > query_length
        or len(target.replace("-", "")) > target_length
    ):
        raise ToolExecutionError("LoL-align returned inconsistent residue correspondences")
    pairs = [(first, second) for first, second in zip(query, target, strict=True)
             if first != "-" and second != "-"]
    if not pairs:
        raise ToolExecutionError("LoL-align returned no aligned residue pairs")
    metrics = {
        name: _finite_numbers(text=row[name], count=1, field=name)[0]
        for name in ("qtmscore", "ttmscore", "rmsd", "evalue", "prob")
    }
    if any(not 0 <= metrics[name] <= 1 for name in ("qtmscore", "ttmscore", "prob")):
        raise ToolExecutionError("LoL-align returned an invalid normalised TM-score or probability")
    if metrics["rmsd"] < 0 or metrics["evalue"] > 1.00001:
        raise ToolExecutionError("LoL-align returned an invalid RMSD or normalised LoL score")
    rotation_values = _finite_numbers(text=row["u"], count=9, field="u")
    translation = _finite_numbers(text=row["t"], count=3, field="t")
    rotation = tuple(tuple(rotation_values[3 * i:3 * i + 3]) for i in range(3))
    for first in range(3):
        for second in range(3):
            dot = sum(rotation[first][i] * rotation[second][i] for i in range(3))
            if not math.isclose(dot, float(first == second), abs_tol=0.005):
                raise ToolExecutionError("LoL-align rotation is not orthonormal")
    determinant = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if not math.isclose(determinant, 1.0, abs_tol=0.01):
        raise ToolExecutionError("LoL-align returned an improper rotation")
    return USAlignResult(
        aligned_length=len(pairs), rmsd_angstrom=metrics["rmsd"],
        sequence_identity=sum(first.upper() == second.upper() for first, second in pairs)
        / len(pairs),
        tm_score_mobile_normalised=metrics["ttmscore"],
        tm_score_reference_normalised=metrics["qtmscore"],
        transform=Transform(translation=translation, rotation=rotation),
        version=version, alignment_scope="local",
        lol_normalised_score=metrics["evalue"],
        lol_homology_probability=metrics["prob"],
    )


def run_lolalign(
    *, executable: str, mobile_path: Path, reference_path: Path,
    matrix_path: Path, stdout_path: Path, version: str,
    multidomain: bool = True, timeout_seconds: int = 7200,
) -> USAlignResult:
    """Run an exhaustive one-reference/one-mobile LoL-align comparison.

    Args:
        executable: LoL-enabled Foldseek binary.
        mobile_path: Mobile monomer model, supplied as the Foldseek target.
        reference_path: Reference monomer model, supplied as the Foldseek query.
        matrix_path: Published mobile-to-reference transform path.
        stdout_path: Tool log path; adjacent TSV retains raw alignment output.
        version: Previously verified Foldseek version.
        multidomain: Use the documented multi-domain LoL scoring mode.
        timeout_seconds: Maximum wall time for this pairwise invocation.

    Returns:
        Validated alignment result with separate LoL scores.

    Raises:
        ToolExecutionError: If inputs, execution or result validation fail.
        NoAlignmentFoundError: If a successful command reports no alignment.
    """
    if (
        not isinstance(multidomain, bool) or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int) or timeout_seconds <= 0
    ):
        raise ToolExecutionError("Invalid LoL-align mode or timeout")
    for path in (mobile_path, reference_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise ToolExecutionError(f"Missing or empty LoL-align model: {path}")
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_path.unlink(missing_ok=True)
    alignment_path = stdout_path.with_suffix(".alignment.tsv")
    alignment_path.unlink(missing_ok=True)
    with TemporaryDirectory(prefix="lolalign_", dir=stdout_path.parent) as temporary:
        argv = [
            executable, "easy-search", str(reference_path), str(mobile_path),
            str(alignment_path), temporary,
            "--alignment-type", "3", "--lolalign-multidomain", str(int(multidomain)),
            "--exhaustive-search", "1", "--threads", "1", "--max-seqs", "1",
            "-e", "1e30", "-a", "1", "--format-output", ",".join(OUTPUT_FIELDS),
        ]
        LOGGER.info("Running LoL-align: %s", " ".join(argv))
        try:
            completed = subprocess.run(
                args=argv, check=False, capture_output=True, text=True, timeout=timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            stdout_path.write_text(data=f"LoL-align execution failed: {exc}\n", encoding="utf-8")
            raise ToolExecutionError(f"LoL-align execution failed: {exc}") from exc
        stdout_path.write_text(
            data="Command: " + " ".join(argv) + "\n" + completed.stdout
            + "\n[stderr]\n" + completed.stderr,
            encoding="utf-8",
        )
        if completed.returncode != 0:
            raise ToolExecutionError(
                f"LoL-align returned {completed.returncode}; see {stdout_path}"
            )
        if not alignment_path.is_file():
            raise ToolExecutionError(f"LoL-align did not create {alignment_path}")
        parsed = parse_lolalign_output(
            text=alignment_path.read_text(encoding="utf-8"), version=version,
        )
    lines = ["# Mobile target to reference query: x_reference = t + u * x_mobile"]
    for index in range(3):
        values = (parsed.transform.translation[index], *parsed.transform.rotation[index])
        lines.append(f"{index}\t" + "\t".join(f"{value:.12g}" for value in values))
    matrix_path.write_text(data="\n".join(lines) + "\n", encoding="utf-8")
    return parsed
