"""Tests for Python application configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from e3app.config import AppConfig, config_from_environment, parse_positive_integer, validate_config
from e3app.errors import AppError


def test_positive_integer_parser() -> None:
    """Valid values parse and type/range failures are clear."""

    assert parse_positive_integer("12", "rows") == 12
    for value in ("x", "0", "100001"):
        with pytest.raises(AppError):
            parse_positive_integer(value, "rows")


def test_environment_config_and_validation(resource_db: Path) -> None:
    """Documented environment variables resolve into validated paths."""

    config = config_from_environment(
        {"E3_RESOURCE_DUCKDB": str(resource_db), "E3_MAX_TABLE_ROWS": "42"}
    )
    assert config.max_rows == 42
    validate_config(config)
    expression_config = config_from_environment(
        {
            "E3_RESOURCE_DUCKDB": str(resource_db),
            "E3_EXPRESSION_DUCKDB": str(resource_db),
        }
    )
    assert expression_config.expression_duckdb == resource_db
    validate_config(expression_config)
    with pytest.raises(AppError, match="required"):
        config_from_environment({})


def test_missing_resource_and_expression(resource_db: Path, tmp_path: Path) -> None:
    """Missing database inputs and invalid limits fail before server start."""

    with pytest.raises(AppError, match="Resource"):
        validate_config(AppConfig(tmp_path / "missing"))
    with pytest.raises(AppError, match="Expression"):
        validate_config(AppConfig(resource_db, tmp_path / "missing"))
    with pytest.raises(AppError, match="between"):
        validate_config(AppConfig(resource_db, max_rows=0))
