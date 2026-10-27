"""Tests of the pinned Foldseek installer without network requests."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_foldseek_lolalign.sh"
SUPPORTED_HOST = (
    platform.system() == "Linux" and platform.machine() == "x86_64"
    and Path("/proc/cpuinfo").is_file()
    and "avx2" in Path("/proc/cpuinfo").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("arguments", [[], ["--prefix"], ["--prefix", "relative"], ["--bad"]])
def test_installer_rejects_bad_arguments(*, arguments: list[str]) -> None:
    """Invalid named options must fail before any download is attempted."""
    result = subprocess.run(args=["bash", str(SCRIPT), *arguments], capture_output=True, text=True)
    assert result.returncode == 2
    assert "ERROR" in result.stderr


def test_installer_help_and_existing_prefix(*, tmp_path: Path) -> None:
    """Explain usage and protect existing installations."""
    help_result = subprocess.run(
        args=["bash", str(SCRIPT), "--help"], capture_output=True, text=True,
    )
    assert help_result.returncode == 0 and "--archive" in help_result.stdout
    result = subprocess.run(
        args=["bash", str(SCRIPT), "--prefix", str(tmp_path)], capture_output=True, text=True,
    )
    assert result.returncode == 2 and "already exists" in result.stderr


@pytest.mark.skipif(not SUPPORTED_HOST, reason="Pinned installer requires Linux AVX2")
def test_installer_rejects_bad_checksum(*, tmp_path: Path) -> None:
    """Do not install an archive that differs from the pinned bytes."""
    archive = tmp_path / "bad.tar.gz"
    archive.write_bytes(data=b"invalid archive")
    prefix = tmp_path / "foldseek"
    result = subprocess.run(
        args=["bash", str(SCRIPT), "--prefix", str(prefix), "--archive", str(archive)],
        capture_output=True, text=True,
    )
    assert result.returncode == 2 and "checksum" in result.stderr
    assert not prefix.exists()
    assert not list(tmp_path.glob(".foldseek-install.*"))


@pytest.mark.skipif(
    not os.environ.get("FOLDSEEK_ARCHIVE") or not SUPPORTED_HOST,
    reason="Requires the pinned local archive and Linux AVX2",
)
def test_installer_real_archive_offline(*, tmp_path: Path) -> None:
    """The tested archive installs offline and records its exact provenance."""
    prefix = tmp_path / "foldseek"
    result = subprocess.run(
        args=["bash", str(SCRIPT), "--prefix", str(prefix),
              "--archive", os.environ["FOLDSEEK_ARCHIVE"]],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (prefix / "bin" / "foldseek").is_file()
    assert "463739e0014a1549a527de589102cde98f802f37" in (
        prefix / "INSTALL_PROVENANCE.tsv"
    ).read_text(encoding="utf-8")
