"""Configuration shared by the command-line launcher and Streamlit UI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from e3app.errors import AppError


@dataclass(frozen=True)
class AppConfig:
    """Resolved read-only application configuration."""

    resource_duckdb: Path | None = None
    expression_duckdb: Path | None = None
    max_rows: int = 1000
    resource_parquet: Path | None = None
    resource_run_dir: Path | None = None

    @property
    def source_mode(self) -> str:
        """Return the configured resource source mode."""
        if self.resource_duckdb is not None:
            return "duckdb"
        if self.resource_parquet is not None:
            return "master_parquet"
        if self.resource_run_dir is not None:
            return "run_directory"
        return "unconfigured"

    @property
    def source_path(self) -> Path | None:
        """Return the configured primary resource path."""
        return self.resource_duckdb or self.resource_parquet or self.resource_run_dir


def parse_positive_integer(value: str, label: str, maximum: int = 100_000) -> int:
    """Parse a bounded positive integer from user-controlled text."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(f"{label} must be an integer") from exc
    if parsed < 1 or parsed > maximum:
        raise AppError(f"{label} must be between 1 and {maximum}")
    return parsed


def config_from_environment(environment: Mapping[str, str] | None = None) -> AppConfig:
    """Build configuration from documented environment variables."""
    values = os.environ if environment is None else environment
    resource_duckdb = values.get("E3_RESOURCE_DUCKDB", "").strip()
    resource_parquet = values.get("E3_RESOURCE_PARQUET", "").strip()
    resource_run_dir = values.get("E3_RESOURCE_RUN_DIR", "").strip()
    if not any((resource_duckdb, resource_parquet, resource_run_dir)):
        raise AppError(
            "One of E3_RESOURCE_DUCKDB, E3_RESOURCE_PARQUET or "
            "E3_RESOURCE_RUN_DIR is required"
        )
    expression = values.get("E3_EXPRESSION_DUCKDB", "").strip()
    max_rows = parse_positive_integer(values.get("E3_MAX_TABLE_ROWS", "1000"), "max rows")
    return AppConfig(
        resource_duckdb=(
            Path(resource_duckdb).expanduser().resolve() if resource_duckdb else None
        ),
        expression_duckdb=Path(expression).expanduser().resolve() if expression else None,
        max_rows=max_rows,
        resource_parquet=(
            Path(resource_parquet).expanduser().resolve() if resource_parquet else None
        ),
        resource_run_dir=(
            Path(resource_run_dir).expanduser().resolve() if resource_run_dir else None
        ),
    )


def validate_config(config: AppConfig) -> None:
    """Require exactly one readable resource source and bounded query sizes."""
    configured = [
        path
        for path in (
            config.resource_duckdb,
            config.resource_parquet,
            config.resource_run_dir,
        )
        if path is not None
    ]
    if len(configured) != 1:
        raise AppError(
            "Configure exactly one resource source: DuckDB, master Parquet or run directory"
        )
    if config.resource_duckdb is not None and not config.resource_duckdb.is_file():
        raise AppError(f"Resource DuckDB does not exist: {config.resource_duckdb}")
    if config.resource_parquet is not None and not config.resource_parquet.is_file():
        raise AppError(f"Resource Parquet does not exist: {config.resource_parquet}")
    if config.resource_run_dir is not None:
        if not config.resource_run_dir.is_dir():
            raise AppError(
                f"Resource run directory does not exist: {config.resource_run_dir}"
            )
        if not any(config.resource_run_dir.rglob("*.parquet")):
            raise AppError(
                f"Resource run directory contains no Parquet results: "
                f"{config.resource_run_dir}"
            )
    if config.expression_duckdb is not None and not config.expression_duckdb.is_file():
        raise AppError(f"Expression DuckDB does not exist: {config.expression_duckdb}")
    parse_positive_integer(str(config.max_rows), "max rows")
