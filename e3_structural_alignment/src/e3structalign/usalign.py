"""TM-score structural-aligner execution and strict output parsing."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from e3structalign.errors import ToolExecutionError
from e3structalign.models import Transform, USAlignResult

LOGGER = logging.getLogger("e3structalign")

ALIGNED_PATTERN = re.compile(
    r"Aligned\s+length=\s*(?P<length>\d+),\s*"
    r"RMSD=\s*(?P<rmsd>[0-9.eE+-]+),\s*"
    r"Seq_ID=n_identical/n_aligned=\s*(?P<identity>[0-9.eE+-]+)"
)
TM_SCORE_PATTERN = re.compile(r"TM-score=\s*([0-9.eE+-]+)")
VERSION_PATTERN = re.compile(
    r"(?:US-align|USalign|TM-align|TMalign)\s*\(Version\s+([^)]+)\)",
    re.IGNORECASE,
)
MATRIX_ROW_PATTERN = re.compile(
    r"^\s*([0-2])\s+"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*$"
)


def parse_transform(path: Path) -> Transform:
    """Parse a US-align/TM-align ``-m`` rotation/translation matrix."""
    source = Path(path).expanduser().resolve()
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ToolExecutionError(
            f"Could not read structural-alignment matrix {source}: {exc}"
        ) from exc
    rows: dict[int, tuple[float, tuple[float, float, float]]] = {}
    for line in lines:
        match = MATRIX_ROW_PATTERN.match(line)
        if match is None:
            continue
        row = int(match.group(1))
        rows[row] = (
            float(match.group(2)),
            (
                float(match.group(3)),
                float(match.group(4)),
                float(match.group(5)),
            ),
        )
    if set(rows) != {0, 1, 2}:
        raise ToolExecutionError(
            f"Structural-alignment matrix does not contain exactly rows 0, 1 and 2: {source}"
        )
    return Transform(
        translation=tuple(rows[row][0] for row in range(3)),
        rotation=tuple(rows[row][1] for row in range(3)),
    )


def parse_output(
    text: str,
    transform: Transform,
    version: str,
) -> USAlignResult:
    """Parse global metrics shared by US-align and TM-align standard output."""
    aligned = ALIGNED_PATTERN.search(text)
    if aligned is None:
        raise ToolExecutionError("US-align output lacks aligned length, RMSD and identity")
    scores = [float(match.group(1)) for match in TM_SCORE_PATTERN.finditer(text)]
    if len(scores) < 2:
        raise ToolExecutionError("US-align output contains fewer than two TM-scores")
    for score in scores[:2]:
        if not 0.0 <= score <= 1.0:
            raise ToolExecutionError(f"US-align reported an invalid TM-score: {score}")
    return USAlignResult(
        aligned_length=int(aligned.group("length")),
        rmsd_angstrom=float(aligned.group("rmsd")),
        sequence_identity=float(aligned.group("identity")),
        tm_score_mobile_normalised=scores[0],
        tm_score_reference_normalised=scores[1],
        transform=transform,
        version=version,
    )


def tool_version(executable: str, tool_name: str = "US-align") -> str:
    """Return the version printed by one configured structural aligner."""
    try:
        result = subprocess.run(
            args=[executable],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolExecutionError(
            f"Could not execute {tool_name} binary {executable!r}: {exc}"
        ) from exc
    text = result.stdout + "\n" + result.stderr
    match = VERSION_PATTERN.search(text)
    if match is not None:
        return match.group(1).strip()
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line:
        return first_line[:120]
    raise ToolExecutionError(
        f"{tool_name} executable produced no recognisable version output: {executable}"
    )


def run_usalign(
    *,
    executable: str,
    mobile_path: Path,
    reference_path: Path,
    matrix_path: Path,
    stdout_path: Path,
    version: str,
    tool_name: str = "US-align",
) -> USAlignResult:
    """Run one pairwise TM-score aligner and validate all outputs."""
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    matrix_path.unlink(missing_ok=True)
    argv = [
        executable,
        str(mobile_path),
        str(reference_path),
        "-m",
        str(matrix_path),
    ]
    LOGGER.info("Running %s: %s", tool_name, " ".join(argv))
    try:
        result = subprocess.run(
            args=argv,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ToolExecutionError(f"Could not start {tool_name}: {exc}") from exc
    combined = result.stdout
    if result.stderr:
        combined += "\n[stderr]\n" + result.stderr
    stdout_path.write_text(combined, encoding="utf-8")
    if result.returncode != 0:
        raise ToolExecutionError(
            f"{tool_name} returned {result.returncode}; see {stdout_path}"
        )
    if not matrix_path.is_file() or matrix_path.stat().st_size == 0:
        raise ToolExecutionError(
            f"{tool_name} did not create a non-empty matrix: {matrix_path}"
        )
    transform = parse_transform(matrix_path)
    return parse_output(result.stdout, transform=transform, version=version)
