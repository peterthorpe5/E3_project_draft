"""File-and-console logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(*, log_path: Path | None, verbose: bool) -> logging.Logger:
    """Configure package logging without accumulating duplicate handlers.

    Args:
        log_path: Optional log file. ``None`` configures console logging only.
        verbose: Enable DEBUG logging when true.

    Returns:
        Configured package logger.
    """

    logger = logging.getLogger("e3orthology")
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)
    if log_path is not None:
        destination = Path(log_path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(destination, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger
