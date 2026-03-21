"""
test_collector_network.py — Tests for the network collector.
"""
import time
from unittest.mock import patch

import pytest

from conftest import make_metric
from zabbig_client.collectors.network import (
    NetworkCollector,
    _parse_net_dev,
    _get_counters,
    _net_counter,
    _net_rate,
    _sockstat,
)
from zabbig_client.models import RESULT_OK


# Minimal fake /proc/net/dev content
_NET_DEV_CONTENT = """\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:   12345       100    0    0    0     0          0         0    12345       100    0    0    0     0       0          0
  eth0: 1000000      8000   10    5    0     0          0         0   500000      4000    2    1    0     0       0          0
  eth1:  200000      1000    0    0    0     0          0         0   100000       500    0    0    0     0       0          0
"""

_SOCKSTAT_CONTENT = """\
sockets: used 320
TCP: inuse 12 orphan 2 tw 5 alloc 25 mem 4
UDP: inuse 7 mem 2
UDPLITE: inuse 0
RAW: inuse 0
FRAG: inuse 0 memory 0
"""


def _write_net_dev(tmp_path, content=_NET_DEV_CONTENT):
    net_dir = tmp_path / "net"
    net_dir.mkdir(exist_ok=True)
    (net_dir / "dev").write_text(content)
    return str(tmp_path)


def _write_sockstat(tmp_path, content=_SOCKSTAT_CONTENT):
    net_dir = tmp_path / "net"
    net_dir.mkdir(exist_ok=True)
    (net_dir / "sockstat").write_text(content)
    return str(tmp_path)


class TestParseNetDev:
    def test_parses_interfaces(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        data = _parse_net_dev(proc_root)
        assert "eth0" in data
        assert "eth1" in data
        assert "lo" in data

    def test_loopback_bytes(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        data = _parse_net_dev(proc_root)
        assert data["lo"][0] == 12345  # rx_bytes

    def test_eth0_rx_bytes(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        data = _parse_net_dev(proc_root)
        assert data["eth0"][0] == 1000000


class TestGetCounters:
    def test_single_interface(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        data = _parse_net_dev(proc_root)
        # col 0 = rx_bytes for eth0
        val = _get_counters(data, "eth0", 0)
        assert val == 1000000

    def test_total_sums_non_loopback(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        data = _parse_net_dev(proc_root)
        # rx_bytes: eth0=1000000 + eth1=200000 = 1200000 (lo excluded)
        val = _get_counters(data, "total", 0)
        assert val == 1200000

    def test_missing_interface_raises(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        data = _parse_net_dev(proc_root)
        with pytest.raises(ValueError, match="not found in /proc/net/dev"):
            _get_counters(data, "wlan99", 0)


class TestNetCounter:
    @pytest.mark.parametrize("mode,expected", [
        ("rx_bytes",   1000000),
        ("tx_bytes",   500000),
        ("rx_packets", 8000),
        ("tx_packets", 4000),
        ("rx_errors",  10),
        ("tx_errors",  2),
        ("rx_dropped", 5),
        ("tx_dropped", 1),
    ])
    def test_counter_modes(self, tmp_path, mode, expected):
        proc_root = _write_net_dev(tmp_path)
        val = _net_counter("eth0", mode, proc_root)
        assert val == expected

    def test_total_interface(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        val = _net_counter("total", "rx_bytes", proc_root)
        assert val == 1200000  # eth0 + eth1


class TestNetRate:
    def test_rate_returns_float(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        # Patch time.sleep and make two identical reads → rate = 0
        with patch("time.sleep"):
            val = _net_rate("eth0", "rx_bytes_per_sec", proc_root)
        assert isinstance(val, float)
        assert val >= 0.0

    def test_rate_with_counter_increase(self, tmp_path):
        net_dir = tmp_path / "net"
        net_dir.mkdir(exist_ok=True)
        dev_path = net_dir / "dev"

        def fake_parse(path):
            # First call returns 1000, second call returns 2000
            if not hasattr(fake_parse, "_count"):
                fake_parse._count = 0
            fake_parse._count += 1
            if fake_parse._count == 1:
                return {"eth0": [1000] + [0] * 15}
            return {"eth0": [2000] + [0] * 15}

        with patch("zabbig_client.collectors.network._parse_net_dev", side_effect=fake_parse), \
             patch("time.sleep"):
            val = _net_rate("eth0", "rx_bytes_per_sec", str(tmp_path))
        assert val == 1000.0


class TestSockstat:
    def test_tcp_inuse(self, tmp_path):
        proc_root = _write_sockstat(tmp_path)
        assert _sockstat("tcp_inuse", proc_root) == 12

    def test_tcp_timewait(self, tmp_path):
        proc_root = _write_sockstat(tmp_path)
        assert _sockstat("tcp_timewait", proc_root) == 5

    def test_tcp_orphans(self, tmp_path):
        proc_root = _write_sockstat(tmp_path)
        assert _sockstat("tcp_orphans", proc_root) == 2

    def test_udp_inuse(self, tmp_path):
        proc_root = _write_sockstat(tmp_path)
        assert _sockstat("udp_inuse", proc_root) == 7

    def test_missing_field_raises(self, tmp_path):
        _write_sockstat(tmp_path, "TCP: inuse 5 tw 1\n")
        # "orphan" is missing from this content
        with pytest.raises(RuntimeError, match="not found in"):
            _sockstat("tcp_orphans", str(tmp_path))


class TestNetworkCollector:
    @pytest.mark.parametrize("mode", [
        "rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
        "rx_errors", "tx_errors", "rx_dropped", "tx_dropped",
    ])
    async def test_counter_modes(self, mode, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        metric = make_metric(
            collector="network", key=f"host.net.{mode}",
            params={"interface": "eth0", "mode": mode, "proc_root": proc_root},
        )
        result = await NetworkCollector().collect(metric)
        assert result.status == RESULT_OK
        assert int(result.value) >= 0

    @pytest.mark.parametrize("mode", ["tcp_inuse", "tcp_timewait", "tcp_orphans", "udp_inuse"])
    async def test_sockstat_modes(self, mode, tmp_path):
        proc_root = _write_sockstat(tmp_path)
        metric = make_metric(
            collector="network", key=f"host.net.{mode}",
            params={"mode": mode, "proc_root": proc_root},
        )
        result = await NetworkCollector().collect(metric)
        assert result.status == RESULT_OK

    async def test_rate_mode(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        with patch("time.sleep"):
            metric = make_metric(
                collector="network", key="host.net.rx_rate",
                params={"interface": "eth0", "mode": "rx_bytes_per_sec", "proc_root": proc_root},
            )
            result = await NetworkCollector().collect(metric)
        assert result.status == RESULT_OK

    async def test_unknown_mode_raises(self):
        metric = make_metric(
            collector="network", key="host.net.x",
            params={"mode": "unknown_metric"},
        )
        with pytest.raises(ValueError, match="Unknown network collector mode"):
            await NetworkCollector().collect(metric)

    async def test_result_collector_field(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        metric = make_metric(
            collector="network", key="host.net.rx_bytes",
            params={"interface": "eth0", "mode": "rx_bytes", "proc_root": proc_root},
        )
        result = await NetworkCollector().collect(metric)
        assert result.collector == "network"

    async def test_total_interface(self, tmp_path):
        proc_root = _write_net_dev(tmp_path)
        metric = make_metric(
            collector="network", key="host.net.rx_total",
            params={"interface": "total", "mode": "rx_bytes", "proc_root": proc_root},
        )
        result = await NetworkCollector().collect(metric)
        assert int(result.value) == 1200000
