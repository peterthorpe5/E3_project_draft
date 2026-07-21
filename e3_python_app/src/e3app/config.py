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

    resource_duckdb: Path
    expression_duckdb: Path | None = None
    max_rows: int = 1000


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
    resource = values.get("E3_RESOURCE_DUCKDB", "").strip()
    if not resource:
        raise AppError("E3_RESOURCE_DUCKDB is required")
    expression = values.get("E3_EXPRESSION_DUCKDB", "").strip()
    max_rows = parse_positive_integer(values.get("E3_MAX_TABLE_ROWS", "1000"), "max rows")
    return AppConfig(
        resource_duckdb=Path(resource).expanduser().resolve(),
        expression_duckdb=Path(expression).expanduser().resolve() if expression else None,
        max_rows=max_rows,
    )


def validate_config(config: AppConfig) -> None:
    """Require readable DuckDB inputs and a bounded preview size."""

    if not config.resource_duckdb.is_file():
        raise AppError(f"Resource DuckDB does not exist: {config.resource_duckdb}")
    if config.expression_duckdb is not None and not config.expression_duckdb.is_file():
        raise AppError(f"Expression DuckDB does not exist: {config.expression_duckdb}")
    parse_positive_integer(str(config.max_rows), "max rows")

