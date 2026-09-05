import tempfile
import unittest
from pathlib import Path

from src.cycle_logging import get_cycle_logger


class CycleLoggingTests(unittest.TestCase):
    def test_log_is_written_in_utc_without_sensitive_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cycle.log"
            logger = get_cycle_logger(path)

            logger.info("cycle_started mode=dry_run")
            for handler in logger.handlers:
                handler.flush()

            contents = path.read_text(encoding="utf-8")
            self.assertIn("Z | INFO | cycle_started mode=dry_run", contents)
            self.assertNotIn("BINANCE_API", contents)

    def test_log_directory_is_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "cycle.log"
            logger = get_cycle_logger(path)
            logger.info("cycle_finished exit_code=0")
            for handler in logger.handlers:
                handler.flush()

            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
