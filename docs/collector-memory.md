# Memory Collector

Reads RAM and swap usage from `/proc/meminfo`. Linux only.

---

## Params

| Param | Required | Description |
|---|---|---|
| `mode` | yes | Which memory metric to return (see modes table below) |
| `proc_root` | no | Override `runtime.proc_root` for this metric only |

---

## Modes

| Mode | Formula | Returns |
|---|---|---|
| `used_percent` | `(MemTotal − MemAvailable) / MemTotal × 100` | RAM in use as a percentage. Uses `MemAvailable` (not `MemFree`) so it correctly accounts for reclaimable page cache. |
| `available_bytes` | `MemAvailable` from `/proc/meminfo` | Bytes available for new allocations without swapping. More actionable than free bytes alone. |
| `swap_used_percent` | `(SwapTotal − SwapFree) / SwapTotal × 100` | Swap used as a percentage. Returns `0.0` gracefully when no swap is configured (SwapTotal = 0). |

---

## Scenarios

### RAM utilisation — most common alert

```yaml
- id: mem_used_percent
  name: Memory used percent
  collector: memory
  key: host.memory.used_percent
  value_type: float
  unit: "%"
  importance: high
  params:
    mode: used_percent
```

Create a Zabbix trigger: alert when `last(host.memory.used_percent) > 90`.

---

### Available bytes — for capacity planning graphs

Tracking available bytes alongside used-percent helps distinguish between a host that is simply caching heavily and one that is genuinely running out of memory.

```yaml
- id: mem_available_bytes
  name: Memory available bytes
  collector: memory
  key: host.memory.available_bytes
  value_type: int
  unit: "B"
  params:
    mode: available_bytes
```

---

### Swap monitoring (with graceful fallback on swap-free hosts)

Setting `error_policy: fallback` with `fallback_value: "0"` ensures this metric sends `0` on hosts with no swap configured, rather than going stale.

```yaml
- id: swap_used_percent
  name: Swap used percent
  collector: memory
  key: host.memory.swap_used_percent
  value_type: float
  unit: "%"
  error_policy: fallback
  fallback_value: "0"
  params:
    mode: swap_used_percent
```

---

### All three together — full memory dashboard

```yaml
- id: mem_used_percent
  collector: memory
  key: host.memory.used_percent
  value_type: float
  unit: "%"
  params:
    mode: used_percent

- id: mem_available_bytes
  collector: memory
  key: host.memory.available_bytes
  value_type: int
  unit: "B"
  params:
    mode: available_bytes

- id: swap_used_percent
  collector: memory
  key: host.memory.swap_used_percent
  value_type: float
  unit: "%"
  error_policy: fallback
  fallback_value: "0"
  params:
    mode: swap_used_percent
```

---

## Host Name Override

All metrics support the optional top-level `host_name` field. When set, the metric is sent to Zabbix under that host name instead of the global `zabbix.host_name` from `client.yaml`. Useful when a single client instance reports memory metrics for multiple Zabbix host objects.

```yaml
- id: mem_used_percent
  collector: memory
  key: host.memory.used_percent
  host_name: "remote-server-01"    # override for this metric only
  params:
    mode: used_percent
```

See [configuration.md](configuration.md#metric-level-host_name) for the full priority chain.
