"""
logging_setup.py — Configure Python logging from LoggingConfig.

Supports:
  format: text   — human-readable timestamped lines
  format: json   — one JSON object per line (useful for log aggregators)

Output destinations:
  console: true         — writes to stderr
  file:
    path: <path>        — additionally rotates to a file
    max_size_mb: 10     — rotate when the file reaches this size (default 10 MB)
    max_backups: 5      — keep this many rotated files (default 5)
    compress: true      — gzip-compress rotated backups (default true)
"""
from __future__ import annotations

import gzip
import json
import logging
import logging.handlers
import os
import shutil
import sys

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


def _make_gz_namer(base_name: str):
    """Return a namer function that appends .gz to rotated backup file names."""
    def namer(name: str) -> str:
        return name + ".gz"
    return namer


def _gz_rotator(source: str, dest: str) -> None:
    """Rotate source → dest by gzip-compressing, then remove source."""
    with open(source, "rb") as f_in:
        with gzip.open(dest, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(source)


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
        fc = config.file
        file_handler = logging.handlers.RotatingFileHandler(
            fc.path,
            maxBytes=fc.max_size_mb * 1024 * 1024,
            backupCount=fc.max_backups,
            encoding="utf-8",
        )
        if fc.compress:
            file_handler.namer = _make_gz_namer(fc.path)
            file_handler.rotator = _gz_rotator
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
