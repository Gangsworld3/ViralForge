from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler


def setup_logging(config) -> logging.Logger:
    logger = logging.getLogger("viralforge")
    expected_log_file = str(config.log_dir / "viralforge.log")
    for handler in list(logger.handlers):
        handler_path = getattr(handler, "baseFilename", None)
        if handler_path and str(handler_path) != expected_log_file:
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    log_file = config.log_dir / "viralforge.log"
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(handler)
    logger.addHandler(console)
    logger.propagate = False
    return logger
