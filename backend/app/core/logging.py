from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = " | ".join([
    "%(asctime)s.%(msecs)03d",
    "%(levelname)-5s",
    "%(name)s",
    "%(message)s",
])
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)


def setup_logging(
    log_level: str = "INFO",
    log_file: str | Path | None = None,
    log_max_bytes: int = 5 * 1024 * 1024,
    log_backup_count: int = 3,
) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    fmt = _build_formatter()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_path), maxBytes=log_max_bytes, backupCount=log_backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
