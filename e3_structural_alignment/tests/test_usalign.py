"""Tests for US-align output and transform parsing."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from e3structalign.errors import ToolExecutionError
from e3structalign.models import Transform
from e3structalign.usalign import parse_output, parse_transform, run_usalign, tool_version


def test_parse_transform_and_output(tmp_path: Path) -> None:
    """Valid matrices and standard output produce typed metrics."""
    matrix = tmp_path / "matrix.txt"
    matrix.write_text(
        "0 -10.0 1.0 0.0 0.0\n"
        "1 0.0 0.0 1.0 0.0\n"
        "2 0.0 0.0 0.0 1.0\n",
        encoding="utf-8",
    )
    transform = parse_transform(matrix)
    result = parse_output(
        "Aligned length= 2, RMSD= 0.25, Seq_ID=n_identical/n_aligned= 0.500\n"
        "TM-score= 0.80000\nTM-score= 0.75000\n",
        transform=transform,
        version="test",
    )
    assert transform.apply((10.0, 1.0, 2.0)) == (0.0, 1.0, 2.0)
    assert result.aligned_length == 2
    assert result.tm_score_reference_normalised == 0.75


def test_run_and_version(
    structural_inputs: dict[str, Path],
    tmp_path: Path,
) -> None:
    """The external executable creates retained raw output and a matrix."""
    assert tool_version(str(structural_inputs["executable"])) == "20241201"
    result = run_usalign(
        executable=str(structural_inputs["executable"]),
        mobile_path=structural_inputs["mobile"],
        reference_path=structural_inputs["reference"],
        matrix_path=tmp_path / "matrix.txt",
        stdout_path=tmp_path / "stdout.txt",
        version="20241201",
    )
    assert result.rmsd_angstrom == 0.0
    assert (tmp_path / "stdout.txt").is_file()


def test_invalid_output_and_matrix(tmp_path: Path) -> None:
    """Incomplete US-align results fail closed."""
    matrix = tmp_path / "matrix.txt"
    matrix.write_text("0 0 1 0 0\n", encoding="utf-8")
    with pytest.raises(ToolExecutionError, match="rows"):
        parse_transform(matrix)
    identity = Transform(
        translation=(0.0, 0.0, 0.0),
        rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    )
    with pytest.raises(ToolExecutionError, match="lacks"):
        parse_output("TM-score= 1\nTM-score= 1\n", identity, "test")
    with pytest.raises(ToolExecutionError, match="fewer than two"):
        parse_output(
            "Aligned length= 1, RMSD= 0.0, "
            "Seq_ID=n_identical/n_aligned= 1.0\nTM-score= 1\n",
            identity,
            "test",
        )
    with pytest.raises(ToolExecutionError, match="invalid TM-score"):
        parse_output(
            "Aligned length= 1, RMSD= 0.0, "
            "Seq_ID=n_identical/n_aligned= 1.0\n"
            "TM-score= 1.2\nTM-score= 1.0\n",
            identity,
            "test",
        )
    with pytest.raises(ToolExecutionError, match="Could not read"):
        parse_transform(tmp_path / "missing.matrix")


def test_tool_and_execution_failures(tmp_path: Path, structural_inputs: dict[str, Path]) -> None:
    """Missing, silent and failing executables produce contextual errors."""
    with pytest.raises(ToolExecutionError, match="Could not execute"):
        tool_version(str(tmp_path / "not-installed"))

    generic = tmp_path / "generic"
    generic.write_text("#!/usr/bin/env bash\nprintf 'custom build\\n'\n", encoding="utf-8")
    generic.chmod(generic.stat().st_mode | stat.S_IXUSR)
    assert tool_version(str(generic)) == "custom build"

    silent = tmp_path / "silent"
    silent.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    silent.chmod(silent.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(ToolExecutionError, match="no recognisable"):
        tool_version(str(silent))

    failing = tmp_path / "failing"
    failing.write_text(
        "#!/usr/bin/env bash\nprintf 'failure\\n' >&2\nexit 7\n",
        encoding="utf-8",
    )
    failing.chmod(failing.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(ToolExecutionError, match="returned 7"):
        run_usalign(
            executable=str(failing),
            mobile_path=structural_inputs["mobile"],
            reference_path=structural_inputs["reference"],
            matrix_path=tmp_path / "failed.matrix",
            stdout_path=tmp_path / "failed.stdout",
            version="test",
        )

    no_matrix = tmp_path / "no-matrix"
    no_matrix.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'Aligned length= 1, RMSD= 0.0, "
        "Seq_ID=n_identical/n_aligned= 1.0\\nTM-score= 1\\nTM-score= 1\\n'\n",
        encoding="utf-8",
    )
    no_matrix.chmod(no_matrix.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(ToolExecutionError, match="non-empty matrix"):
        run_usalign(
            executable=str(no_matrix),
            mobile_path=structural_inputs["mobile"],
            reference_path=structural_inputs["reference"],
            matrix_path=tmp_path / "absent.matrix",
            stdout_path=tmp_path / "no-matrix.stdout",
            version="test",
        )
