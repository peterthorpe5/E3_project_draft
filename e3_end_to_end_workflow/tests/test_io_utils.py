"""Tests for deterministic I/O and logging helpers."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from e3workflow.errors import WorkflowError
from e3workflow.io_utils import (
    atomic_write_json,
    atomic_write_text,
    close_logger,
    configure_logging,
    inventory_files,
    read_json,
    read_tsv,
    sha256_file,
    utc_now,
    write_tsv,
)


def test_time_checksum_and_errors(tmp_path: Path) -> None:
    """UTC timestamps and streamed checksums have defensive bounds."""

    path = tmp_path / "value.txt"
    path.write_text("abc", encoding="utf-8")
    assert utc_now().endswith("Z")
    assert sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    with pytest.raises(WorkflowError):
        sha256_file(path, 0)
    with pytest.raises(WorkflowError):
        sha256_file(tmp_path / "missing")


def test_atomic_json_and_text(tmp_path: Path) -> None:
    """Atomic writers replace existing content and JSON is validated."""

    text = tmp_path / "nested" / "value.txt"
    atomic_write_text(text, "first")
    atomic_write_text(text, "second")
    assert text.read_text() == "second"
    data = tmp_path / "value.json"
    atomic_write_json(data, {"b": 2, "a": 1})
    assert read_json(data) == {"a": 1, "b": 2}
    with pytest.raises(WorkflowError):
        read_json(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("[", encoding="utf-8")
    with pytest.raises(WorkflowError):
        read_json(bad)


def test_atomic_writer_cleans_failed_temporary_file(tmp_path: Path, monkeypatch: object) -> None:
    """A failed atomic replacement leaves no misleading formal or temporary file."""

    import e3workflow.io_utils

    target = tmp_path / "formal.txt"

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError(f"cannot move {source} to {destination}")

    monkeypatch.setattr(e3workflow.io_utils.os, "replace", fail_replace)
    with pytest.raises(OSError, match="cannot move"):
        atomic_write_text(target, "content")
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_tsv_round_trip_and_header_errors(tmp_path: Path) -> None:
    """TSV helpers preserve columns and reject unsafe headers."""

    path = tmp_path / "table.tsv"
    write_tsv(path, [{"a": 1, "b": "two"}], ("a", "b"))
    assert read_tsv(path) == (["a", "b"], [{"a": "1", "b": "two"}])
    with pytest.raises(WorkflowError):
        write_tsv(path, [], ())
    duplicate = tmp_path / "duplicate.tsv"
    duplicate.write_text("a\ta\n1\t2\n", encoding="utf-8")
    with pytest.raises(WorkflowError):
        read_tsv(duplicate)
    with pytest.raises(WorkflowError):
        read_tsv(tmp_path / "missing.tsv")
    malformed = tmp_path / "malformed.tsv"
    malformed.write_text("a\n1\textra\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="malformed"):
        read_tsv(malformed)
    compressed = tmp_path / "table.tsv.gz"
    write_tsv(compressed, [{"a": 1, "b": "two"}], ("a", "b"))
    assert read_tsv(compressed) == (["a", "b"], [{"a": "1", "b": "two"}])
    corrupt = tmp_path / "corrupt.tsv.gz"
    corrupt.write_bytes(b"not gzip")
    with pytest.raises(WorkflowError, match="Could not read TSV"):
        read_tsv(corrupt)


def test_logging_and_inventory(tmp_path: Path) -> None:
    """Logging reaches disk and inventories honour exclusions."""

    logger = configure_logging(tmp_path / "logs" / "run.log", verbose=True)
    logger.info("hello")
    for handler in logger.handlers:
        handler.flush()
    assert "hello" in (tmp_path / "logs" / "run.log").read_text()
    (tmp_path / "one.txt").write_text("1", encoding="utf-8")
    (tmp_path / "skip.txt").write_text("2", encoding="utf-8")
    records = inventory_files(tmp_path, frozenset({"skip.txt"}))
    assert "one.txt" in {row["path"] for row in records}
    assert "skip.txt" not in {row["path"] for row in records}
    with pytest.raises(WorkflowError):
        inventory_files(tmp_path / "none")
    close_logger(logger)
    assert not logging.getLogger("e3workflow").handlers
