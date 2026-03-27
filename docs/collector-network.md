# Network Collector

Reads NIC traffic counters and error statistics from `/proc/net/dev`, and socket counts from `/proc/net/sockstat`. Linux only.

---

## Params

| Param | Required | Description |
|---|---|---|
| `interface` | for traffic/error modes | NIC name as listed in `/proc/net/dev` (e.g. `eth0`, `ens3`, `enp1s0`). Use `total` to aggregate all non-loopback interfaces. Not required for socket modes. |
| `mode` | yes | Which metric to collect (see modes below) |
| `proc_root` | no | Override `runtime.proc_root` for this metric only |

---

## Modes

### Rate modes — two reads, 1 second apart

These modes sleep for 1 second between reads to compute a per-second rate. Set `timeout_seconds` ≥ 3 to give them enough headroom.

| Mode | Returns |
|---|---|
| `rx_bytes_per_sec` | Inbound throughput in bytes/second |
| `tx_bytes_per_sec` | Outbound throughput in bytes/second |

### Cumulative counter modes — single read

These modes return the cumulative total since last boot. The counter resets on reboot.

| Mode | Returns |
|---|---|
| `rx_bytes` | Total bytes received since boot |
| `tx_bytes` | Total bytes transmitted since boot |
| `rx_packets` | Total packets received since boot |
| `tx_packets` | Total packets transmitted since boot |
| `rx_errors` | Total receive errors since boot |
| `tx_errors` | Total transmit errors since boot |
| `rx_dropped` | Total receive drops (kernel ring buffer overruns) |
| `tx_dropped` | Total transmit drops |

> **Tip:** use cumulative byte counters with Zabbix's **Delta (speed per second)** preprocessing to get throughput graphs without the 1-second sleep cost of the rate modes.

### Socket counter modes — single read, no `interface` param

Reads from `/proc/net/sockstat`.

| Mode | Returns |
|---|---|
| `tcp_inuse` | Open TCP sockets (ESTABLISHED and others) |
| `tcp_timewait` | Sockets in TIME_WAIT. Persistently high values suggest connection churn or port exhaustion. |
| `tcp_orphans` | Orphaned TCP sockets (not attached to any file descriptor). A growing value indicates a socket leak. |
| `udp_inuse` | Open UDP sockets |

---

## Scenarios

### Real-time throughput monitoring

```yaml
- id: net_rx_bytes_per_sec
  name: Network inbound bytes/sec
  collector: network
  key: host.net.rx_bytes_per_sec
  value_type: float
  unit: "B/s"
  timeout_seconds: 5    # must be > 1 s sleep + overhead
  params:
    interface: total    # aggregate all non-loopback NICs
    mode: rx_bytes_per_sec

- id: net_tx_bytes_per_sec
  name: Network outbound bytes/sec
  collector: network
  key: host.net.tx_bytes_per_sec
  value_type: float
  unit: "B/s"
  timeout_seconds: 5
  params:
    interface: total
    mode: tx_bytes_per_sec
```

---

### Per-NIC throughput

```yaml
- id: net_eth0_rx_bytes_per_sec
  collector: network
  key: host.net.eth0.rx_bytes_per_sec
  value_type: float
  unit: "B/s"
  timeout_seconds: 5
  params:
    interface: eth0
    mode: rx_bytes_per_sec
```

---

### Cumulative bytes with Zabbix Delta preprocessing

No 1-second sleep — lower collection cost. Configure the Zabbix item with **Delta (speed per second)** preprocessing to convert byte totals into a throughput graph.

```yaml
- id: net_rx_bytes
  collector: network
  key: host.net.rx_bytes
  value_type: int
  unit: "B"
  params:
    interface: total
    mode: rx_bytes

- id: net_tx_bytes
  collector: network
  key: host.net.tx_bytes
  value_type: int
  unit: "B"
  params:
    interface: total
    mode: tx_bytes
```

---

### Error and drop monitoring

Alert when these increase — they indicate NIC driver issues, cable problems, or kernel buffer overruns.

```yaml
- id: net_rx_errors
  collector: network
  key: host.net.rx_errors
  value_type: int
  importance: high
  params:
    interface: total
    mode: rx_errors

- id: net_rx_dropped
  collector: network
  key: host.net.rx_dropped
  value_type: int
  importance: high
  params:
    interface: total
    mode: rx_dropped
```

---

### TIME_WAIT monitoring — high-traffic APIs

```yaml
- id: net_tcp_timewait
  name: TCP TIME_WAIT sockets
  collector: network
  key: host.net.tcp_timewait
  value_type: int
  params:
    mode: tcp_timewait
```

---

### Socket leak detection

Orphaned TCP sockets should remain near zero. A growing count indicates a file descriptor or socket leak in an application.

```yaml
- id: net_tcp_orphans
  name: Orphaned TCP sockets
  collector: network
  key: host.net.tcp_orphans
  value_type: int
  importance: high
  params:
    mode: tcp_orphans
```

---

### Active TCP connection count

```yaml
- id: net_tcp_inuse
  name: TCP sockets in use
  collector: network
  key: host.net.tcp_inuse
  value_type: int
  params:
    mode: tcp_inuse
```

---

## Host Name Override

All metrics support the optional top-level `host_name` field. When set, the metric is sent to Zabbix under that host name instead of the global `zabbix.host_name` from `client.yaml`. Useful when a single client instance reports network metrics for multiple Zabbix host objects.

```yaml
- id: net_rx_bytes
  collector: network
  key: host.net.rx_bytes
  host_name: "remote-server-01"    # override for this metric only
  params:
    interface: eth0
    mode: rx_bytes
```

See [configuration.md](configuration.md#metric-level-host_name) for the full priority chain.

---

## Metric Scheduling

Every network metric supports four optional scheduling fields that control when and how often the metric is collected. All four are inactive when absent.

```yaml
- id: eth0_rx_biz
  collector: network
  key: host.net.eth0.rx_bytes_per_sec.biz
  value_type: float
  unit: "B/s"
  time_window_from: "0800"
  time_window_till: "1800"
  max_executions_per_day: 120
  run_frequency: 2
  params:
    interface: eth0
    mode: rx_bytes_per_sec
```

See [configuration.md](configuration.md#metric-scheduling-fields) for the full field reference, value rules, and evaluation order.
