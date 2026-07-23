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
    empty = AppConfig()
    assert empty.source_mode == "unconfigured"
    assert empty.source_path is None


def test_environment_config_and_validation(
    resource_db: Path,
    master_parquet: Path,
    run_results_dir: Path,
) -> None:
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
    parquet_config = config_from_environment(
        {"E3_RESOURCE_PARQUET": str(master_parquet)}
    )
    assert parquet_config.source_mode == "master_parquet"
    assert parquet_config.source_path == master_parquet
    validate_config(parquet_config)
    run_config = config_from_environment(
        {"E3_RESOURCE_RUN_DIR": str(run_results_dir)}
    )
    assert run_config.source_mode == "run_directory"
    validate_config(run_config)
    with pytest.raises(AppError, match="required"):
        config_from_environment({})


def test_missing_resource_and_expression(resource_db: Path, tmp_path: Path) -> None:
    """Missing database inputs and invalid limits fail before server start."""

    with pytest.raises(AppError, match="Resource"):
        validate_config(AppConfig(tmp_path / "missing"))
    with pytest.raises(AppError, match="exactly one"):
        validate_config(
            AppConfig(
                resource_duckdb=resource_db,
                resource_parquet=resource_db,
            )
        )
    with pytest.raises(AppError, match="Parquet"):
        validate_config(AppConfig(resource_parquet=tmp_path / "missing.parquet"))
    empty_run = tmp_path / "empty_run"
    empty_run.mkdir()
    with pytest.raises(AppError, match="no Parquet"):
        validate_config(AppConfig(resource_run_dir=empty_run))
    with pytest.raises(AppError, match="run directory does not exist"):
        validate_config(AppConfig(resource_run_dir=tmp_path / "missing_run"))
    with pytest.raises(AppError, match="Expression"):
        validate_config(AppConfig(resource_db, tmp_path / "missing"))
    with pytest.raises(AppError, match="between"):
        validate_config(AppConfig(resource_db, max_rows=0))
