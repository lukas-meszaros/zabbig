"""
logging_setup.py — Configure Python logging from LoggingConfig.

Supports:
  format: text   — human-readable timestamped lines
  format: json   — one JSON object per line (useful for log aggregators)

Output destinations:
  console: true  — writes to stderr
  file: <path>   — additionally rotates to a file (10 MB × 5 files)
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from typing import Optional

from .models import LoggingConfig


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj)


def setup_logging(config: LoggingConfig) -> None:
    """Configure the root logger according to LoggingConfig."""
    level = getattr(logging, config.level, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # Remove any handlers added by previous calls (important for tests)
    root.handlers.clear()

    if config.format == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    if config.console:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        root.addHandler(handler)

    if config.file:
        file_handler = logging.handlers.RotatingFileHandler(
            config.file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
