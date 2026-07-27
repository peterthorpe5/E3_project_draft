"""Tests for typed table and path utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from e3structalign.errors import InputValidationError
from e3structalign.io_utils import (
    output_inventory,
    read_records,
    require_columns,
    safe_filename,
    write_table,
)


def test_table_roundtrip_and_inventory(tmp_path: Path) -> None:
    """Typed Parquet output round-trips and inventory excludes named files."""
    records = [{"name": "alpha", "value": 2}]
    write_table(
        tsv_path=tmp_path / "table.tsv",
        parquet_path=tmp_path / "table.parquet",
        records=records,
        schema=(("name", "VARCHAR"), ("value", "BIGINT")),
    )
    assert read_records(tmp_path / "table.parquet") == records
    inventory = output_inventory(tmp_path, frozenset({"table.tsv"}))
    assert [row["path"] for row in inventory] == ["table.parquet"]
    assert safe_filename("../group name") == "_group_name"
    assert safe_filename("...") == "item"


def test_table_input_failures(tmp_path: Path) -> None:
    """Missing columns and unsupported table extensions fail with context."""
    with pytest.raises(InputValidationError, match="contains no rows"):
        require_columns([], ("a",), "input")
    with pytest.raises(InputValidationError, match="missing required"):
        require_columns([{"a": 1}], ("a", "b"), "input")
    unsupported = tmp_path / "table.csv"
    unsupported.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="Unsupported table"):
        read_records(unsupported)
