"""
test_logging_setup.py — Tests for logging_setup.py.
"""
import json
import logging

import pytest

from zabbig_client.logging_setup import setup_logging, _JsonFormatter, _gz_rotator
from zabbig_client.models import LogFileConfig, LoggingConfig


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
        cfg = LoggingConfig(level="INFO", format="text", console=False,
                            file=LogFileConfig(path=log_file))
        setup_logging(cfg)
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.handlers.RotatingFileHandler)

    def test_file_and_console(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        cfg = LoggingConfig(level="INFO", format="text", console=True,
                            file=LogFileConfig(path=log_file))
        setup_logging(cfg)
        root = logging.getLogger()
        assert len(root.handlers) == 2

    def test_file_max_size_mb(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        cfg = LoggingConfig(console=False, file=LogFileConfig(path=log_file, max_size_mb=25))
        setup_logging(cfg)
        handler = logging.getLogger().handlers[0]
        assert handler.maxBytes == 25 * 1024 * 1024

    def test_file_max_backups(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        cfg = LoggingConfig(console=False, file=LogFileConfig(path=log_file, max_backups=3))
        setup_logging(cfg)
        handler = logging.getLogger().handlers[0]
        assert handler.backupCount == 3

    def test_file_compress_true_sets_namer_and_rotator(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        cfg = LoggingConfig(console=False, file=LogFileConfig(path=log_file, compress=True))
        setup_logging(cfg)
        handler = logging.getLogger().handlers[0]
        assert handler.namer is not None
        assert handler.rotator is _gz_rotator
        # namer appends .gz
        assert handler.namer("test.log.1") == "test.log.1.gz"

    def test_file_compress_false_leaves_namer_default(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        cfg = LoggingConfig(console=False, file=LogFileConfig(path=log_file, compress=False))
        setup_logging(cfg)
        handler = logging.getLogger().handlers[0]
        # RotatingFileHandler.namer defaults to None when not set
        assert handler.namer is None
        assert handler.rotator is None

    def test_gz_rotator_compresses_and_removes_source(self, tmp_path):
        import gzip
        source = tmp_path / "app.log.1"
        dest = tmp_path / "app.log.1.gz"
        source.write_text("some log content")
        _gz_rotator(str(source), str(dest))
        assert not source.exists()
        assert dest.exists()
        with gzip.open(str(dest), "rt") as f:
            assert f.read() == "some log content"

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
