"""Tests for persistent and console logging configuration."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from e3parquet.logging_utils import close_logger, configure_logging


class TestLoggingConfiguration(unittest.TestCase):
    """Verify handler levels and persistent output."""

    def test_configure_logging_replaces_handlers_and_writes_file(self) -> None:
        """Repeated configuration should not duplicate messages or handlers."""
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "logs" / "run.log"
            logger = configure_logging(log_path, verbose=True)
            logger.info("assurance message")
            for handler in logger.handlers:
                handler.flush()

            self.assertEqual(logger.level, logging.DEBUG)
            owned_handlers = [
                handler
                for handler in logger.handlers
                if getattr(handler, "_e3parquet_owned", False)
            ]
            self.assertEqual(len(owned_handlers), 2)
            self.assertTrue(
                all(handler.level == logging.DEBUG for handler in owned_handlers)
            )
            self.assertIn(
                "assurance message",
                log_path.read_text(encoding="utf-8"),
            )

            logger = configure_logging(log_path, verbose=False)
            console_handlers = [
                handler
                for handler in logger.handlers
                if isinstance(handler, logging.StreamHandler)
                and not isinstance(handler, logging.FileHandler)
                and getattr(handler, "_e3parquet_owned", False)
            ]
            self.assertEqual(len(console_handlers), 1)
            self.assertEqual(console_handlers[0].level, logging.INFO)
            close_logger(logger)
            self.assertFalse(
                any(
                    getattr(handler, "_e3parquet_owned", False)
                    for handler in logger.handlers
                )
            )


if __name__ == "__main__":
    unittest.main()
