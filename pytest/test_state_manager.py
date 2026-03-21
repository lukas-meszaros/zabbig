"""
test_state_manager.py — Tests for state_manager.py.
"""
import json
import os

import pytest

from zabbig_client.models import ClientConfig, RunSummary, StateConfig
from zabbig_client.state_manager import STATE_FILE, load_state, save_state


def make_config(enabled=True, directory=None, tmp_path=None):
    cfg = ClientConfig()
    cfg.state = StateConfig(
        enabled=enabled,
        directory=directory or (str(tmp_path) if tmp_path else "state"),
    )
    return cfg


class TestSaveState:
    def test_save_creates_file(self, tmp_path):
        cfg = make_config(enabled=True, directory=str(tmp_path))
        summary = RunSummary(success=True, duration_ms=500.0, sent_batch=5, sent_immediate=2)
        save_state(cfg, summary)
        state_file = tmp_path / STATE_FILE
        assert state_file.exists()

    def test_save_content(self, tmp_path):
        cfg = make_config(enabled=True, directory=str(tmp_path))
        summary = RunSummary(
            success=True,
            duration_ms=1234.5,
            enabled=10,
            collected_ok=8,
            collected_failed=1,
            collected_timeout=1,
            sent_batch=6,
            sent_immediate=2,
            sender_failures=0,
        )
        save_state(cfg, summary)
        data = json.loads((tmp_path / STATE_FILE).read_text())
        assert data["success"] is True
        assert data["metrics_sent"] == 8  # sent_batch + sent_immediate
        assert data["collectors_failed"] == 2  # collected_failed + collected_timeout
        assert data["consecutive_failures"] == 0

    def test_disabled_does_nothing(self, tmp_path):
        cfg = make_config(enabled=False, directory=str(tmp_path))
        save_state(cfg, RunSummary())
        assert not (tmp_path / STATE_FILE).exists()

    def test_consecutive_failures_incremented(self, tmp_path):
        cfg = make_config(enabled=True, directory=str(tmp_path))
        save_state(cfg, RunSummary(success=False))
        save_state(cfg, RunSummary(success=False))
        data = json.loads((tmp_path / STATE_FILE).read_text())
        assert data["consecutive_failures"] == 2

    def test_consecutive_failures_reset_on_success(self, tmp_path):
        cfg = make_config(enabled=True, directory=str(tmp_path))
        save_state(cfg, RunSummary(success=False))
        save_state(cfg, RunSummary(success=False))
        save_state(cfg, RunSummary(success=True))
        data = json.loads((tmp_path / STATE_FILE).read_text())
        assert data["consecutive_failures"] == 0

    def test_creates_directory(self, tmp_path):
        state_dir = str(tmp_path / "deep" / "state")
        cfg = make_config(enabled=True, directory=state_dir)
        save_state(cfg, RunSummary(success=True))
        assert os.path.isfile(os.path.join(state_dir, STATE_FILE))

    def test_timestamp_is_recent(self, tmp_path):
        import time
        cfg = make_config(enabled=True, directory=str(tmp_path))
        save_state(cfg, RunSummary(success=True))
        data = json.loads((tmp_path / STATE_FILE).read_text())
        assert abs(data["last_run_ts"] - int(time.time())) <= 2


class TestLoadState:
    def test_disabled_returns_empty(self, tmp_path):
        cfg = make_config(enabled=False, directory=str(tmp_path))
        assert load_state(cfg) == {}

    def test_load_after_save(self, tmp_path):
        cfg = make_config(enabled=True, directory=str(tmp_path))
        save_state(cfg, RunSummary(success=True, duration_ms=100.0))
        state = load_state(cfg)
        assert state["success"] is True

    def test_missing_file_returns_empty(self, tmp_path):
        cfg = make_config(enabled=True, directory=str(tmp_path))
        state = load_state(cfg)
        assert state == {}

    def test_corrupt_file_returns_empty(self, tmp_path):
        cfg = make_config(enabled=True, directory=str(tmp_path))
        (tmp_path / STATE_FILE).write_text("NOT JSON {{{{")
        state = load_state(cfg)
        assert state == {}

    def test_roundtrip_multiple_fields(self, tmp_path):
        cfg = make_config(enabled=True, directory=str(tmp_path))
        summary = RunSummary(
            success=False,
            duration_ms=99.9,
            sent_batch=10,
            sent_immediate=3,
            collected_failed=1,
            sender_failures=2,
        )
        save_state(cfg, summary)
        state = load_state(cfg)
        assert state["success"] is False
        assert state["sender_failures"] == 2
