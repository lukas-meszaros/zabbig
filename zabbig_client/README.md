# zabbig_client — Standalone Zabbix Monitoring Client

A self-contained Python monitoring client that collects host metrics and service states, then pushes them to a Zabbix server via the trapper protocol. Designed to run under cron with no external package installation on production systems.

---

## Purpose

`zabbig_client` is a lightweight, config-driven agent that:

- Collects CPU, memory, disk, and service metrics from the local host
- Sends values to Zabbix using the bundled `zabbix_utils` library
- Runs every 5 minutes from cron safely (PID lock prevents overlap)
- Requires **zero pip/apt/yum install** on production — all dependencies are vendored

---

## Directory Layout

```
zabbig_client/
  run.py                          # entry point — add to cron
  client.yaml                     # runtime config (copy from client.yaml.example)
  metrics.yaml                    # metric definitions (copy from metrics.yaml.example)
  client.yaml.example             # annotated reference config
  metrics.yaml.example            # annotated reference metrics

  src/
    zabbig_client/                # main application package
      __init__.py
      main.py                     # orchestrator
      config_loader.py            # YAML config loading + validation
      models.py                   # dataclasses (MetricDef, MetricResult, …)
      runner.py                   # async collector runner
      sender_manager.py           # Zabbix send wrapper
      result_router.py            # routes results to batch/immediate queues
      collector_registry.py       # maps collector names to classes
      locking.py                  # cron-safe PID file lock
      logging_setup.py            # configures Python logging
      state_manager.py            # optional run-state persistence (JSON)
      collectors/
        __init__.py
        base.py                   # BaseCollector ABC
        cpu.py                    # CPU util, load avg, uptime
        memory.py                 # RAM and swap
        disk.py                   # filesystem used/free
        service.py                # systemd + process-pattern checks

    zabbix_utils/                 # vendored official Zabbix Python library
    yaml/                         # vendored PyYAML pure-Python source

  scripts/
    vendor_yaml.py                # run once to (re)vendor PyYAML

  tests/
    test_config_loader.py
    test_models.py
    test_result_router.py
    test_collectors.py

  logs/                           # optional: set logging.file here
  state/                          # optional: set state.directory here
```

---

## First-Time Setup

### 1. Copy example configs

```bash
cd zabbig_client
cp client.yaml.example client.yaml
cp metrics.yaml.example metrics.yaml
```

Edit `client.yaml` — at minimum set:
- `zabbix.server_host` — IP or hostname of your Zabbix server
- `zabbix.host_name` — the host name **as it appears in the Zabbix frontend**

Edit `metrics.yaml` — disable any metrics whose services are not present on this host (e.g. disable `svc_nginx` if nginx is not installed).

### 2. Provision Zabbix host and trapper items

The host and all item keys must be configured in Zabbix before metrics will be accepted.  Use `scripts/bootstrap.py` (or configure manually via the web UI).

### 3. Run a dry-run to verify

```bash
python3 run.py --dry-run
```

This runs all collectors and logs what would be sent, without touching the Zabbix server.

---

## Running the Client

### One-off run

```bash
python3 run.py
```

### With overrides

```bash
python3 run.py --config /etc/zabbig/client.yaml --metrics /etc/zabbig/metrics.yaml
python3 run.py --dry-run --log-level DEBUG
```

### Cron entry (every 5 minutes)

```cron
*/5 * * * * /usr/bin/python3 /opt/zabbig_client/run.py >> /var/log/zabbig/client.log 2>&1
```

Or, if you use the `logging.file` setting in `client.yaml`:

```cron
*/5 * * * * /usr/bin/python3 /opt/zabbig_client/run.py
```

**Note:** `overall_timeout_seconds` (default 240) is shorter than the cron interval so each run completes before the next one starts.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0`  | All metrics collected and sent successfully |
| `1`  | Partial failure — some collectors failed or some sends were rejected |
| `2`  | Fatal error — config invalid, lock conflict, or overall timeout |

---

## Lock File Behaviour

`run.py` creates a PID lock file (default: `/tmp/zabbig_client.lock`) when it starts and removes it on exit.

- If the lock file exists and the recorded PID is **still running**, the new instance exits with code 2 and logs an error. No metrics are collected.
- If the lock file exists but the PID is **no longer running** (stale lock from a crash), it is automatically cleared and the new instance proceeds normally.
- The lock file path is configurable via `runtime.lock_file`.

---

## Batch vs Immediate Delivery

Each metric in `metrics.yaml` has a `delivery` field:

| Mode | Behaviour |
|------|-----------|
| `batch` | Collected during the batch window, then sent all together in one call |
| `immediate` | Sent as soon as collected (or in a micro-batch), before batch metrics |

**Batch window:** `batching.batch_collection_window_seconds` (default 60s). All batch collectors run concurrently; the client waits up to this long for them all to finish. Collectors still running at window expiry are cancelled and logged as timed-out.

**Immediate:** Immediate collectors also run concurrently. Their results are flushed first (if `flush_immediate_separately: true`) before the batch send.

**When to use each:**
- Use `batch` for non-urgent resource metrics (CPU %, memory, disk)
- Use `immediate` for state changes that need fast alerting (service up/down)

---

## Configuration Reference

### `client.yaml`

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| `zabbix` | `server_host` | `127.0.0.1` | Zabbix server IP/hostname |
| `zabbix` | `server_port` | `10051` | Zabbix trapper port |
| `zabbix` | `host_name` | system hostname | Zabbix host name |
| `runtime` | `overall_timeout_seconds` | `240` | Hard run time limit |
| `runtime` | `max_concurrency` | `8` | Max parallel collectors |
| `runtime` | `lock_file` | `/tmp/zabbig_client.lock` | PID lock path |
| `runtime` | `dry_run` | `false` | Collect but don't send |
| `batching` | `batch_collection_window_seconds` | `60` | Batch window |
| `logging` | `level` | `INFO` | Log level |
| `logging` | `format` | `text` | `text` or `json` |
| `logging` | `file` | _(none)_ | Optional log file |
| `state` | `enabled` | `false` | Persist run state |
| `features` | `self_monitoring_metrics` | `true` | Send client self-metrics |

### `metrics.yaml` — per-metric fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Unique identifier |
| `name` | yes | Human-readable label |
| `enabled` | yes | `true` / `false` — easy on/off switch |
| `collector` | yes | `cpu` / `memory` / `disk` / `service` |
| `key` | yes | Zabbix item key (must match the trapper item key in Zabbix) |
| `delivery` | no | `batch` or `immediate` (inherits from collector_defaults or defaults) |
| `timeout_seconds` | no | Collector timeout (inherits from collector_defaults or defaults) |
| `error_policy` | no | `skip` / `fallback` / `mark_failed` |
| `fallback_value` | no | Value to send when `error_policy: fallback` |
| `params` | depends | Collector-specific parameters (see below) |

### Collector `params`

**cpu:**
- `mode: percent` — CPU utilization %
- `mode: load1` — 1-min load average
- `mode: load5` — 5-min load average
- `mode: load15` — 15-min load average
- `mode: uptime` — uptime in seconds

**memory:**
- `mode: used_percent` — RAM used %
- `mode: available_bytes` — MemAvailable in bytes
- `mode: swap_used_percent` — swap used %

**disk:**
- `mount: /path` — filesystem to inspect (**required**)
- `mode: used_percent` — disk used %
- `mode: free_bytes` — free bytes available to non-root

**service:**
- `check_mode: systemd` + `service_name: <name>` — uses `systemctl is-active`
- `check_mode: process` + `process_pattern: <regex>` — scans `/proc/*/cmdline`
- Returns `1` (running) or `0` (not running)

---

## How to Add a New Metric

Add an entry to `metrics.yaml`:

```yaml
- id: my_metric
  name: My custom metric
  enabled: true
  collector: cpu           # use an existing collector
  key: host.my.custom.key  # must match a trapper item in Zabbix
  value_type: float
  delivery: batch
  timeout_seconds: 5
  error_policy: skip
  params:
    mode: percent          # or whichever mode the collector supports
```

No code changes needed for new metrics using existing collectors.

---

## How to Add a New Collector

1. Create `src/zabbig_client/collectors/my_collector.py`:

```python
from ..collector_registry import register_collector
from ..models import MetricDef, MetricResult, RESULT_OK
from .base import BaseCollector
import asyncio, time

@register_collector("my_collector")
class MyCollector(BaseCollector):
    async def collect(self, metric: MetricDef) -> MetricResult:
        t0 = time.monotonic()
        value = await asyncio.to_thread(_do_work, metric.params)
        return MetricResult(
            metric_id=metric.id, key=metric.key, value=str(value),
            value_type=metric.value_type, timestamp=int(time.time()),
            collector="my_collector", delivery=metric.delivery,
            status=RESULT_OK, duration_ms=(time.monotonic()-t0)*1000,
        )

def _do_work(params):
    # blocking work goes here - runs in thread pool
    return 42
```

2. Import it in `collector_registry.py`'s `_ensure_collectors_imported()`.

3. Add `"my_collector"` to `VALID_COLLECTORS` in `models.py`.

4. Use `collector: my_collector` in `metrics.yaml`.

---

## Vendored Dependencies

| Package | Location | Version | Notes |
|---------|----------|---------|-------|
| `zabbix_utils` | `src/zabbix_utils/` | 2.0.4 | Official Zabbix Python library |
| `yaml` (PyYAML) | `src/yaml/` | 6.x | Pure-Python files only, no C extension |

**Why vendored?**  Production servers may not have internet access or package managers available. By committing the `.py` source files directly, the client works from a plain `git clone`.

**Re-vendoring PyYAML** (e.g. to upgrade):
```bash
python3 scripts/vendor_yaml.py
```

The C extension (`_yaml.so`) is deliberately excluded. PyYAML falls back to its pure-Python implementation transparently when the C extension is absent.

---

## Future Extension: Log Regex Monitoring

The collector plugin design supports adding log-based metrics without touching existing code:

1. Create `src/zabbig_client/collectors/log_regex.py` with a `LogRegexCollector` class.
2. `params` would include: `log_file`, `pattern`, `match_value`, `no_match_value`.
3. The collector opens the log file, seeks to the last known offset (stored in state), scans new lines for the regex, and returns a match count or boolean.
4. State management for file offsets already has a hook via `state_manager.py`.

No changes to `runner.py`, `sender_manager.py`, or `result_router.py` needed.

---

## Limitations

- **Linux only for CPU/memory/service collectors** — reads from `/proc` which is Linux-specific. Disk metrics work on macOS too.
- **systemd required for service `check_mode: systemd`** — use `check_mode: process` on non-systemd hosts.
- **No TLS** — connections to Zabbix are plain TCP. Add TLS via a `socket_wrapper` to the `Sender` constructor in `sender_manager.py` if needed.
- **No active agent protocol** — this client only pushes trapper items. It does not respond to Zabbix server polls.
