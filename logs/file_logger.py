# logs/file_logger.py
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_file_logger(
    name: str,
    *,
    level: int = logging.INFO,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
) -> logging.Logger:
    """
    Return a dedicated file-only logger.
    - name: used both as logger name and as the log filename (e.g. "composite" → logs/composite.log)
    - Does not propagate to console/root.
    - Safe to call multiple times (no duplicate handlers).
    """
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger_name = f"file.{name}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        handler = RotatingFileHandler(
            log_dir / f"{name}.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger