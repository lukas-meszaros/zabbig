# zabbig_client — Standalone Zabbix Monitoring Client

A self-contained Python monitoring client that collects host metrics and service states, then pushes them to a Zabbix server via the trapper protocol. Designed to run under cron with no external package installation on production systems.

---

## Purpose

`zabbig_client` is a lightweight, config-driven agent that:

- Collects CPU, memory, disk, network, service, and application log metrics
- Sends values to Zabbix using the bundled `zabbix_utils` library
- Runs every 5 minutes from cron safely (PID lock prevents overlap)
- Requires **zero pip/apt/yum install** on production — all dependencies are vendored

---

## Directory Layout

```
zabbig_client/
  run.py                          # entry point — add to cron
  provision_zabbix.py             # auto-create Zabbix host + trapper items
  client.yaml                     # runtime config
  metrics.yaml                    # metric definitions

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
        disk.py                   # filesystem space + inodes
        service.py                # systemd + process-pattern checks
        network.py                # NIC throughput, errors, socket counters
        log.py                    # application log file monitoring

    zabbix_utils/                 # vendored official Zabbix Python library
    yaml/                         # vendored PyYAML pure-Python source
    requests/                     # vendored requests (used by provision script)

  tests/
    test_config_loader.py
    test_models.py
    test_result_router.py
    test_collectors.py
    test_log_writer.py            # generate test log entries for the log collector

  state/                          # state files written here by default
  logs/                           # optional: set logging.file here
```

---

## First-Time Setup

### 1. Configure client.yaml

Edit `client.yaml` — at minimum set:
- `zabbix.server_host` — IP or hostname of your Zabbix server
- `zabbix.host_name` — the host name **as it appears in the Zabbix frontend**

### 2. Provision Zabbix host and trapper items

```bash
python3 provision_zabbix.py
```

Creates the Zabbix host, host group, and all trapper items defined in `metrics.yaml` automatically via the Zabbix API. Requires `zabbix.api_url`, `zabbix.api_user`, and `zabbix.api_password` set in `client.yaml`.

Disable any metrics not applicable to this host (e.g. `svc_nginx` if nginx is not installed) before provisioning, or use `--only-enabled` to provision only currently enabled metrics.

### 3. Run a dry-run to verify

```bash
python3 run.py --dry-run
```

Runs all collectors and logs what would be sent, without touching the Zabbix server.

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
*/5 * * * * /usr/bin/python3 /opt/zabbig_client/run.py
```

Or to capture output:

```cron
*/5 * * * * /usr/bin/python3 /opt/zabbig_client/run.py >> /var/log/zabbig/client.log 2>&1
```

`overall_timeout_seconds` (default 240) is shorter than the cron interval so each run completes before the next one starts.

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

- If the lock file exists and the recorded PID is **still running**, the new instance exits with code 2 and logs an error.
- If the lock file exists but the PID is **no longer running** (stale lock from a crash), it is automatically cleared and execution continues normally.
- The lock file path is configurable via `runtime.lock_file`.

---

## Batch vs Immediate Delivery

Each metric in `metrics.yaml` has a `delivery` field:

| Mode | Behaviour |
|------|-----------|
| `batch` | Collected during the batch window, then sent all together in one call |
| `immediate` | Sent as soon as collected (or in a micro-batch), before batch metrics |

**Batch window:** `batching.batch_collection_window_seconds` (default 60 s). All batch collectors run concurrently; the client waits up to this long for them all to finish. Collectors still running at window expiry are cancelled and logged as timed-out.

**Immediate:** Immediate collectors also run concurrently. Their results are flushed first (if `flush_immediate_separately: true`) before the batch send.

- Use `batch` for non-urgent resource metrics (CPU %, memory, disk)
- Use `immediate` for state changes that need fast alerting (service up/down)

---

## Configuration Reference

### `client.yaml`

#### `zabbix` — server connection

| Key | Default | Description |
|-----|---------|-------------|
| `server_host` | `127.0.0.1` | Zabbix server IP or hostname (trapper port) |
| `server_port` | `10051` | Zabbix trapper port |
| `host_name` | system hostname | Zabbix host name as configured in the frontend |
| `host_group` | `"zabbig Clients"` | Host group; created automatically by `provision_zabbix.py` |
| `connect_timeout_seconds` | `10` | TCP connection timeout |
| `send_timeout_seconds` | `30` | Timeout for the full send operation |

#### `runtime` — execution behaviour

| Key | Default | Description |
|-----|---------|-------------|
| `overall_timeout_seconds` | `240` | Hard wall-clock limit for the entire run. Keep below cron interval. |
| `max_concurrency` | `8` | Maximum number of collectors running simultaneously |
| `lock_file` | `/tmp/zabbig_client.lock` | PID lock file to prevent overlapping cron executions |
| `dry_run` | `false` | Collect metrics but do not send to Zabbix |
| `fail_fast` | `false` | Abort immediately on any unhandled collector error |
| `proc_root` | `/proc` | Linux proc filesystem root. Override when monitoring via a bind-mount (e.g. Docker: `/host/proc`) |

#### `batching` — delivery timing

| Key | Default | Description |
|-----|---------|-------------|
| `batch_collection_window_seconds` | `60` | How long to wait for batch collectors to finish |
| `batch_send_max_size` | `250` | Maximum items per Zabbix send call |
| `flush_immediate_separately` | `true` | Send immediate metrics in a separate call before the batch |
| `immediate_micro_batch_window_ms` | `200` | Wait time (ms) to group fast immediate collectors before flushing |

#### `logging`

| Key | Default | Description |
|-----|---------|-------------|
| `level` | `INFO` | Log level: `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `format` | `text` | Output format: `text` or `json` (json recommended for ELK/Loki) |
| `file` | _(none)_ | Optional log file path. Rotated at 10 MB, 5 backups kept |
| `console` | `true` | Write logs to stderr. Set `false` to suppress console output in cron |

#### `state` — persistence

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Write `last_run.json` to track run history and consecutive failures |
| `directory` | `"state"` | Directory for all state files. Used by the client (`last_run.json`) and the log collector (one `log_<metric_id>.json` per log metric for byte-offset tracking). Must be writable by the cron user. |

#### `features` — feature flags

| Key | Default | Description |
|-----|---------|-------------|
| `self_monitoring_metrics` | `true` | Send client health metrics to Zabbix (`zabbig.client.run.success`, `zabbig.client.duration_ms`, etc.) |
| `emit_partial_failure_metrics` | `false` | Emit a failure-state result for `mark_failed` metrics |
| `strict_config_validation` | `true` | Abort run on config errors. When `false`, errors are logged as warnings and defaults are used |
| `skip_disabled_metrics` | `true` | Skip metrics with `enabled: false`. Set `false` only for debugging. |

---

### `metrics.yaml` — per-metric fields

#### Common fields (all collectors)

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `id` | yes | — | Unique identifier. Used in logs and state file names. |
| `name` | no | — | Human-readable label shown in log output |
| `description` | no | — | Free-text description (supports YAML block scalars) |
| `enabled` | no | `true` | `false` skips the metric entirely |
| `collector` | yes | — | `cpu` / `memory` / `disk` / `service` / `network` / `log` |
| `key` | yes | — | Zabbix item key — must exactly match the trapper item in Zabbix |
| `value_type` | no | `float` | `float` / `int` / `string` — informational hint only |
| `unit` | no | `""` | Unit label (e.g. `%`, `B`, `ms`) — used in logs, not sent to Zabbix |
| `delivery` | no | collector default | `batch` or `immediate` |
| `timeout_seconds` | no | collector default | Per-metric timeout |
| `error_policy` | no | `skip` | `skip` / `fallback` / `mark_failed` |
| `fallback_value` | no | — | Required when `error_policy: fallback`. Value sent when collection fails. |
| `importance` | no | `normal` | `low` / `normal` / `high` / `critical` — informational label for logs |
| `tags` | no | `[]` | String labels for log filtering, e.g. `[system, cpu]` |
| `params` | yes | — | Collector-specific parameters (see below) |

#### Collector defaults (`collector_defaults` in `metrics.yaml`)

| Collector | `timeout_seconds` | `delivery` |
|-----------|-------------------|------------|
| `cpu` | 5 | batch |
| `memory` | 5 | batch |
| `disk` | 10 | batch |
| `service` | 8 | immediate |
| `network` | 10 | batch |
| `log` | 60 | batch |

---

### Collector `params`

#### `cpu`

| Param | Required | Description |
|-------|----------|-------------|
| `mode` | yes | `percent` / `load1` / `load5` / `load15` / `uptime` |
| `proc_root` | no | Override `runtime.proc_root` for this metric |

| Mode | Returns |
|------|---------|
| `percent` | Total CPU utilization 0–100 (two `/proc/stat` reads, 200 ms apart) |
| `load1` | 1-minute load average from `/proc/loadavg` |
| `load5` | 5-minute load average |
| `load15` | 15-minute load average |
| `uptime` | System uptime in seconds from `/proc/uptime` |

#### `memory`

| Param | Required | Description |
|-------|----------|-------------|
| `mode` | yes | `used_percent` / `available_bytes` / `swap_used_percent` |
| `proc_root` | no | Override `runtime.proc_root` for this metric |

| Mode | Returns |
|------|---------|
| `used_percent` | `(MemTotal - MemAvailable) / MemTotal × 100` |
| `available_bytes` | `MemAvailable` field from `/proc/meminfo` |
| `swap_used_percent` | Swap in use %; returns `0.0` when no swap is configured |

#### `disk`

| Param | Required | Description |
|-------|----------|-------------|
| `mount` | yes | Absolute path to the mount point, e.g. `/` or `/data` |
| `mode` | yes | See below |

| Mode | Returns |
|------|---------|
| `used_percent` | Filesystem blocks used % |
| `used_bytes` | Bytes in use (total − available to non-root) |
| `free_bytes` | Bytes available to non-root users |
| `inodes_used_percent` | Inode slots used %; `0.0` on filesystems with dynamic inodes |
| `inodes_used` | Inode slots in use |
| `inodes_free` | Free inode slots |
| `inodes_total` | Total inode slots |

#### `service`

| Param | Required | Description |
|-------|----------|-------------|
| `check_mode` | yes | `systemd` or `process` |
| `service_name` | when `check_mode: systemd` | systemd unit name (without `.service`) |
| `process_pattern` | when `check_mode: process` | Python regex matched against `/proc/*/cmdline` |
| `proc_root` | no | Override `runtime.proc_root` (only used by `process` mode) |

Returns `1` (running / active) or `0` (not running).

#### `network`

Reads from `/proc/net/dev` and `/proc/net/sockstat`. Linux only.

| Param | Required | Description |
|-------|----------|-------------|
| `interface` | for traffic/error modes | NIC name from `/proc/net/dev`, e.g. `eth0`. Use `total` to aggregate all non-loopback interfaces. Not required for socket modes. |
| `mode` | yes | See below |
| `proc_root` | no | Override `runtime.proc_root` for this metric |

| Mode | Type | Description |
|------|------|-------------|
| `rx_bytes_per_sec` | rate | Inbound bytes/sec (two reads, 1 s apart — set `timeout_seconds >= 3`) |
| `tx_bytes_per_sec` | rate | Outbound bytes/sec |
| `rx_bytes` | counter | Total bytes received since boot |
| `tx_bytes` | counter | Total bytes transmitted since boot |
| `rx_packets` | counter | Total packets received |
| `tx_packets` | counter | Total packets transmitted |
| `rx_errors` | counter | Total receive errors |
| `tx_errors` | counter | Total transmit errors |
| `rx_dropped` | counter | Total receive drops |
| `tx_dropped` | counter | Total transmit drops |
| `tcp_inuse` | socket | Currently open TCP sockets |
| `tcp_timewait` | socket | Sockets in `TIME_WAIT` state |
| `tcp_orphans` | socket | Orphaned TCP sockets (no file descriptor) |
| `udp_inuse` | socket | Currently open UDP sockets |

#### `log`

Monitors application log files incrementally. Files are read line-by-line from the last stored byte offset — the full file is never loaded into memory. Rotation and truncation are detected automatically via inode and file size checks.

| Param | Required | Description |
|-------|----------|-------------|
| `path` | yes | Path to the log file. The basename may be a Python regex; the directory is a literal path. The most recently modified match is used. |
| `match` | yes | Python regex applied to every line. Only matching lines are processed. |
| `mode` | no | `condition` (default) or `count` — see below |
| `encoding` | no | File encoding. Default: `utf-8` |
| `result` | no | `last` (default) / `first` / `max` / `min` — how to collapse multiple matches per scan window into one value |
| `default_value` | no | Value sent when no line matched `match` in this scan window. Default: `0` |
| `conditions` | required for `condition` mode | Ordered list of sub-conditions (see below) |
| `state_dir` | no | Override `state.directory` from `client.yaml` for this metric only |

**Modes:**

| Mode | Description |
|------|-------------|
| `condition` | Incremental scan from the last stored offset to EOF. Evaluates `conditions` against each matching line, returns one value per run. Byte offset and inode are persisted between runs. |
| `count` | Full-file scan from byte 0 on every run. Returns total count of lines matching `match`. No state file is written. Grows monotonically — use Zabbix "Delta per second" preprocessing for rate graphs. Avoid on files > ~100 MB with short intervals. |

**Condition entries (evaluated in order; first match wins):**

```yaml
# Form 1 — regex match → fixed value
- when: "ERROR|FATAL"
  value: 2

# Form 2 — numeric extraction + comparison → fixed value or captured number
- extract: 'response_time=(\d+(?:\.\d+)?)'
  compare: gt          # gt | lt | gte | lte | eq
  threshold: 500
  value: "$1"          # "$1" returns the captured number; or use a literal

# Form 3 — catch-all (no when/extract; place last)
- value: 0
```

**Example — return 1 on any ERROR line, 0 otherwise:**

```yaml
params:
  path: "/var/log/myapp/app.log"
  match: "ERROR"
  mode: condition
  default_value: 0
  conditions:
    - value: 1
```

**Example — severity level (max across scan window):**

```yaml
params:
  path: "/var/log/myapp/app.log"
  match: "WARN|ERROR|FATAL"
  mode: condition
  result: max
  default_value: 0
  conditions:
    - when: "FATAL"
      value: 3
    - when: "ERROR"
      value: 2
    - when: "WARN"
      value: 1
    - value: 0
```

---

## How to Add a New Metric

Add an entry to `metrics.yaml` (no code changes needed for existing collectors):

```yaml
- id: my_metric
  name: My custom metric
  enabled: true
  collector: cpu
  key: host.my.custom.key   # must match a trapper item in Zabbix
  value_type: float
  delivery: batch
  timeout_seconds: 5
  error_policy: skip
  tags: [system]
  params:
    mode: percent
```

Then re-run `provision_zabbix.py` to create the new trapper item in Zabbix.

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
    # blocking work goes here — runs in a thread pool
    return 42
```

2. Import it in `collector_registry.py`'s `_ensure_collectors_imported()`.
3. Add `"my_collector"` to `VALID_COLLECTORS` in `models.py`.
4. Use `collector: my_collector` in `metrics.yaml`.

---

## Vendored Dependencies

| Package | Location | Notes |
|---------|----------|-------|
| `zabbix_utils` | `src/zabbix_utils/` | Official Zabbix Python library |
| `yaml` (PyYAML) | `src/yaml/` | Pure-Python only; no C extension |
| `requests` | `src/requests/` | Used by `provision_zabbix.py` for API calls |
| `urllib3`, `certifi`, `charset_normalizer`, `idna` | `src/` | `requests` transitive dependencies |

**Why vendored?** Production servers may lack internet access or package managers. Committing the `.py` source files directly means the client works from a plain `git clone`.

---

## Limitations

- **Linux only for CPU / memory / network / service collectors** — these read from `/proc`, which is Linux-specific. Disk metrics work on macOS too.
- **systemd required for service `check_mode: systemd`** — use `check_mode: process` on non-systemd hosts.
- **No TLS** — connections to Zabbix use plain TCP. Add TLS via a `socket_wrapper` to the `Sender` constructor in `sender_manager.py` if needed.
- **No active agent protocol** — this client only pushes trapper items. It does not respond to Zabbix server polls.
- **Log collector cost scales with file size in `count` mode** — avoid `mode: count` on files larger than ~100 MB with short collection intervals.
