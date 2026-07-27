import logging
import tempfile
import unittest
from pathlib import Path

from e3_discovery.logging_utils import get_logger, setup_logging


class LoggingUtilsTests(unittest.TestCase):
    def test_setup_logging_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "test.log"
            logger = setup_logging(log_file, verbose=True, logger_name="test_logger")
            logger.debug("debug message")
            for handler in logger.handlers:
                handler.flush()
            self.assertIn("debug message", log_file.read_text())

    def test_repeated_setup_does_not_duplicate_handlers(self):
        logger = setup_logging(logger_name="repeat_logger")
        first_count = len(logger.handlers)
        logger = setup_logging(logger_name="repeat_logger")
        self.assertEqual(len(logger.handlers), first_count)

    def test_get_logger_returns_named_logger(self):
        self.assertIsInstance(get_logger("abc"), logging.Logger)
        self.assertEqual(get_logger("abc").name, "abc")


if __name__ == "__main__":
    unittest.main()
