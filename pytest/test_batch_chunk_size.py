"""
test_batch_chunk_size.py — Tests for configurable batch_chunk_size in BatchingConfig
and parallel chunk sends in SenderManager.
"""
import asyncio
import textwrap
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from zabbig_client.config_loader import load_client_config
from zabbig_client.models import BatchingConfig, ClientConfig, MetricResult, RunSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(tmp_path, filename, content):
    p = tmp_path / filename
    p.write_text(textwrap.dedent(content))
    return str(p)


def _make_result(key="host.test", value="1"):
    return MetricResult(
        metric_id=key,
        key=key,
        value=value,
        value_type="float",
        timestamp=1000000,
        collector="cpu",
        delivery="batch",
        status="ok",
    )


# ---------------------------------------------------------------------------
# BatchingConfig: batch_chunk_size field
# ---------------------------------------------------------------------------

class TestBatchChunkSizeDefault:
    def test_default_is_250(self):
        cfg = BatchingConfig()
        assert cfg.batch_chunk_size == 250

    def test_custom_value(self):
        cfg = BatchingConfig(batch_chunk_size=50)
        assert cfg.batch_chunk_size == 50


class TestBatchChunkSizeFromConfig:
    def test_parsed_from_yaml(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "myhost"
            batching:
              batch_chunk_size: 100
        """)
        cfg = load_client_config(path)
        assert cfg.batching.batch_chunk_size == 100

    def test_default_when_absent(self, tmp_path):
        path = write_yaml(tmp_path, "client.yaml", """
            zabbix:
              host_name: "myhost"
        """)
        cfg = load_client_config(path)
        assert cfg.batching.batch_chunk_size == 250


# ---------------------------------------------------------------------------
# SenderManager: parallel chunk sends
# ---------------------------------------------------------------------------

class TestSenderManagerParallelChunks:
    """
    Verify that send_batch() fires asyncio.gather when there are multiple chunks.
    """

    def _make_sender(self, batch_send_max_size=2, batch_chunk_size=250, dry_run=True):
        from zabbig_client.sender_manager import SenderManager
        config = ClientConfig()
        config.batching.batch_send_max_size = batch_send_max_size
        config.batching.batch_chunk_size = batch_chunk_size
        config.runtime.dry_run = dry_run
        return SenderManager(config)

    def test_single_chunk_sends_normally(self):
        sender = self._make_sender(batch_send_max_size=10)
        results = [_make_result(f"host.m{i}") for i in range(3)]
        summary = RunSummary()
        asyncio.run(sender.send_batch(results, summary))
        assert summary.sent_batch == 3
        assert summary.sender_failures == 0

    def test_multiple_chunks_all_sent(self):
        # max_size=1 means each item is its own chunk
        sender = self._make_sender(batch_send_max_size=1)
        results = [_make_result(f"host.m{i}") for i in range(4)]
        summary = RunSummary()
        asyncio.run(sender.send_batch(results, summary))
        assert summary.sent_batch == 4
        assert summary.sender_failures == 0

    def test_empty_results_noop(self):
        sender = self._make_sender()
        summary = RunSummary()
        asyncio.run(sender.send_batch([], summary))
        assert summary.sent_batch == 0
        assert summary.sender_failures == 0

    def test_chunk_size_passed_to_Sender(self):
        """_do_send creates Sender(chunk_size=batch_chunk_size)."""
        from zabbig_client.sender_manager import SenderManager
        config = ClientConfig()
        config.batching.batch_chunk_size = 42
        config.runtime.dry_run = False
        config.zabbix.server_hosts = ["192.0.2.1"]  # non-routable — fails fast
        sender = SenderManager(config)

        calls = []
        original_Sender = sender._Sender

        class CaptureSender:
            def __init__(self, **kwargs):
                calls.append(kwargs)
                raise ConnectionRefusedError("test")

        sender._Sender = CaptureSender
        summary = RunSummary()
        results = [_make_result()]
        asyncio.run(sender.send_batch(results, summary))
        assert calls[0]["chunk_size"] == 42
