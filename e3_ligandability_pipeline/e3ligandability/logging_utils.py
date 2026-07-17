"""Logging utilities shared by command-line entry points and pipeline stages."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def configure_logging(log_path: Path, verbose: bool = False) -> logging.Logger:
    """Configure deterministic file and console logging.

    Args:
        log_path: Destination log file.
        verbose: Emit debug-level messages when true.

    Returns:
        Configured package logger.
    """

    resolved_path = Path(log_path).expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("e3ligandability")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(
        resolved_path,
        mode="a",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.debug("Logging configured: %s", resolved_path)
    return logger
