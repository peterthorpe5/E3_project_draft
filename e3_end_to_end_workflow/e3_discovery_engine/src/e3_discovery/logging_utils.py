"""Consistent console and file logging for all workflow entry points."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_file: Optional[Path] = None,
    verbose: bool = False,
    logger_name: Optional[str] = None,
) -> logging.Logger:
    """Configure deterministic console and optional persistent file logging.

    Existing handlers on the selected logger are closed and replaced to prevent
    duplicate messages during repeated CLI calls and tests. Console verbosity is
    controlled by ``verbose``; file logging always captures debug-level records.

    Args:
        log_file: Optional path for append-mode UTF-8 file logging.
        verbose: Enable debug-level console and logger output when true.
        logger_name: Logger name, or ``None`` for the root logger.

    Returns:
        The configured :class:`logging.Logger` instance.

    Raises:
        OSError: If the log directory or file cannot be created.
    """

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_file is not None:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Retrieve a named logger without altering logging configuration.

    Args:
        name: Logger name, normally the calling module's ``__name__``.

    Returns:
        The corresponding :class:`logging.Logger` instance.
    """

    return logging.getLogger(name)
