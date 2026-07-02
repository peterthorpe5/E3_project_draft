"""Logging helpers for E3 PROTAC source-to-Parquet scripts."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure_logging(log_path: Path, verbose: bool = False) -> logging.Logger:
    """Configure console and file logging.

    Parameters
    ----------
    log_path:
        File path for the persistent log.
    verbose:
        If true, console logging is DEBUG level. Otherwise INFO level.

    Returns
    -------
    logging.Logger
        Configured root logger.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
