"""
test_logging_setup.py — Tests for logging_setup.py.
"""
import json
import logging

import pytest

from zabbig_client.logging_setup import setup_logging, _JsonFormatter
from zabbig_client.models import LoggingConfig


class TestSetupLogging:
    def teardown_method(self):
        # Clean root logger after each test
        root = logging.getLogger()
        root.handlers.clear()

    def test_text_format_console(self):
        cfg = LoggingConfig(level="DEBUG", format="text", console=True, file=None)
        setup_logging(cfg)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.StreamHandler)

    def test_json_format_console(self):
        cfg = LoggingConfig(level="INFO", format="json", console=True, file=None)
        setup_logging(cfg)
        root = logging.getLogger()
        assert isinstance(root.handlers[0].formatter, _JsonFormatter)

    def test_no_console_no_handler(self):
        cfg = LoggingConfig(level="INFO", format="text", console=False, file=None)
        setup_logging(cfg)
        root = logging.getLogger()
        assert len(root.handlers) == 0

    def test_file_handler_added(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        cfg = LoggingConfig(level="INFO", format="text", console=False, file=log_file)
        setup_logging(cfg)
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.handlers.RotatingFileHandler)

    def test_file_and_console(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        cfg = LoggingConfig(level="INFO", format="text", console=True, file=log_file)
        setup_logging(cfg)
        root = logging.getLogger()
        assert len(root.handlers) == 2

    def test_clears_existing_handlers(self):
        root = logging.getLogger()
        root.addHandler(logging.StreamHandler())
        root.addHandler(logging.StreamHandler())
        cfg = LoggingConfig(level="INFO", format="text", console=True)
        setup_logging(cfg)
        assert len(root.handlers) == 1

    def test_log_level_warning(self):
        cfg = LoggingConfig(level="WARNING", console=False)
        setup_logging(cfg)
        assert logging.getLogger().level == logging.WARNING

    def test_log_level_error(self):
        cfg = LoggingConfig(level="ERROR", console=False)
        setup_logging(cfg)
        assert logging.getLogger().level == logging.ERROR

    def test_second_call_replaces_handlers(self):
        cfg1 = LoggingConfig(level="INFO", console=True)
        cfg2 = LoggingConfig(level="DEBUG", console=True)
        setup_logging(cfg1)
        setup_logging(cfg2)
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert root.level == logging.DEBUG


class TestJsonFormatter:
    def test_formats_to_json(self):
        fmt = _JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["msg"] == "hello world"
        assert data["logger"] == "test"
        assert "ts" in data

    def test_formats_with_args(self):
        fmt = _JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.DEBUG,
            pathname="", lineno=0,
            msg="value=%s", args=("42",), exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert "value=42" in data["msg"]


# Import needed for isinstance check in test_file_handler_added
import logging.handlers
