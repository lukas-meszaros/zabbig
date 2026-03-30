# CPU Collector

Reads CPU utilisation, load averages, and system uptime from the Linux `/proc` filesystem.

**Platform:** Linux only. Reads `/proc/stat`, `/proc/loadavg`, and `/proc/uptime`.

---

## Params

| Param | Required | Description |
|---|---|---|
| `mode` | yes | Which CPU metric to return (see modes table below) |
| `proc_root` | no | Override `runtime.proc_root` for this metric only |

---

## Modes

| Mode | Source | Returns |
|---|---|---|
| `percent` | `/proc/stat` | Total CPU utilisation 0–100, averaged across all cores. Computed from two reads 200 ms apart. |
| `load1` | `/proc/loadavg` | 1-minute load average. On a 4-core machine a value of 4.0 means all cores are saturated. |
| `load5` | `/proc/loadavg` | 5-minute load average. More stable indicator for sustained load. |
| `load15` | `/proc/loadavg` | 15-minute load average. Useful for detecting long-running saturation trends. |
| `uptime` | `/proc/uptime` | Seconds since last boot. Useful for detecting unexpected reboots (value drops suddenly). |

> **Note on `percent` timing:** the `percent` mode takes ~200–250 ms per call because it sleeps between two `/proc/stat` reads to compute a delta. Factor this into `timeout_seconds`.

---

## Scenarios

### Basic CPU utilisation alert

```yaml
- id: cpu_util
  name: CPU utilisation percent
  collector: cpu
  key: host.cpu.util
  value_type: float
  unit: "%"
  params:
    mode: percent
```

Create a Zabbix trigger: alert when `last(host.cpu.util) > 90`.

---

### All three load averages for trend monitoring

```yaml
- id: load_avg_1
  collector: cpu
  key: host.cpu.load1
  value_type: float
  params:
    mode: load1

- id: load_avg_5
  collector: cpu
  key: host.cpu.load5
  value_type: float
  params:
    mode: load5

- id: load_avg_15
  collector: cpu
  key: host.cpu.load15
  value_type: float
  params:
    mode: load15
```

---

### Reboot detection

```yaml
- id: uptime
  name: System uptime
  collector: cpu
  key: host.system.uptime
  value_type: float
  unit: "s"
  importance: high
  params:
    mode: uptime
```

In Zabbix, trigger on `change(host.system.uptime) < 0` or `last(host.system.uptime) < 300` (rebooted within last 5 minutes).

---

### Monitoring host CPU from inside a Docker container

When the container has the host's `/proc` bind-mounted:

```yaml
- id: cpu_util
  collector: cpu
  key: host.cpu.util
  value_type: float
  unit: "%"
  params:
    mode: percent
    proc_root: "/host/proc"
```

Or set `runtime.proc_root: "/host/proc"` in `client.yaml` to apply to all collectors.

---

For `host_name` override, scheduling fields (`time_window_from`, `time_window_till`, `max_executions_per_day`, `run_frequency`), and all other common metric fields see [configuration-metrics.yaml.md](configuration-metrics.yaml.md).
