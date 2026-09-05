import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


_DEFAULT_LOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "logs"
    / "demo_bot_cycle.log"
)


def get_cycle_logger(
    log_path: Optional[Path] = None,
) -> logging.Logger:
    path = _DEFAULT_LOG_PATH if log_path is None else Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"demon.demo_cycle.{path.resolve()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = RotatingFileHandler(
            path,
            maxBytes=1_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "%(asctime)sZ | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
