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

Or to capture output to a separate file:

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

Each metric in `metrics.yaml` has a `delivery` field that controls when its value is flushed to Zabbix.

| Mode | Behaviour |
|------|-----------|
| `batch` | Collected during the batch window, then sent all together in one Zabbix call |
| `immediate` | Sent as soon as collected (or grouped in a micro-batch window), before batch metrics |

**Batch window** (`batching.batch_collection_window_seconds`, default 60 s): all batch collectors run concurrently. The client waits up to this duration for them all to finish. Collectors still running at expiry are cancelled and the metric is treated as timed-out; any results already collected are still sent.

**Immediate delivery** is designed for time-sensitive state changes (service up/down, log errors) where you want Zabbix to receive the value as fast as possible rather than waiting for the full batch window. When `flush_immediate_separately: true`, immediate results are sent in a dedicated Zabbix call before the batch send.

**Micro-batch window** (`immediate_micro_batch_window_ms`, default 200 ms): when multiple immediate-delivery collectors finish close together, this brief wait lets them be grouped into a single Zabbix call instead of one call per metric.

Use `batch` for non-urgent resource metrics (CPU %, memory, disk). Use `immediate` for service state and log alerts.

---

## Configuration Reference

### `client.yaml`

#### `zabbix` — server connection

##### `server_host`
The IP address or DNS hostname of your Zabbix server, used for the trapper (sender) connection on port 10051. This is the server that receives pushed data, not the proxy. If you send through a Zabbix proxy, point this at the proxy, not the server.

```yaml
zabbix:
  server_host: "10.0.1.50"       # direct IP — most reliable in Docker/cron
  server_host: "zabbix.corp.lan"  # DNS name — requires DNS resolution at run time
```

##### `server_port`
The Zabbix trapper port. Default is `10051`. Change only if your infrastructure uses a non-standard port.

```yaml
zabbix:
  server_port: 10051   # default
  server_port: 10061   # example: non-standard, firewall-remapped port
```

##### `host_name`
The Zabbix host name exactly as it appears in the Zabbix frontend under **Configuration → Hosts**. Values are rejected if the host name does not match. If left empty, the system hostname (`socket.gethostname()`) is used — convenient for self-monitoring setups where the hostname is already registered in Zabbix.

```yaml
zabbix:
  host_name: "prod-web-01"         # hardcoded — safe, explicit
  host_name: ""                    # auto-detect from system hostname
```

##### `host_group`
Used only by `provision_zabbix.py`. If the group does not exist in Zabbix, it is created automatically. Has no effect at metric collection time.

```yaml
zabbix:
  host_group: "zabbig Clients"     # default — all auto-provisioned hosts land here
  host_group: "Production / Web"   # put this host in a specific group
```

##### `connect_timeout_seconds` / `send_timeout_seconds`
`connect_timeout_seconds` governs how long the client waits for a TCP connection to be established. `send_timeout_seconds` covers the entire send operation including writing the payload and receiving the acknowledgement. On networks with high latency or large payloads, increase `send_timeout_seconds`.

```yaml
zabbix:
  connect_timeout_seconds: 5    # fast LAN — fail quickly if server is down
  send_timeout_seconds: 60      # slow WAN link with large batch payloads
```

---

#### `runtime` — execution behaviour

##### `overall_timeout_seconds`
Hard wall-clock limit for the entire run, including collection, batching, and sending. Should always be less than your cron interval. If the run exceeds this limit, all outstanding tasks are cancelled, partial results are sent, and the process exits with code 2.

```yaml
runtime:
  overall_timeout_seconds: 240   # default — fits under a 5-minute cron
  overall_timeout_seconds: 50    # tight — for a 1-minute cron interval
```

##### `max_concurrency`
Maximum number of collectors running at the same time. All collectors are launched as asyncio tasks, but they enter a semaphore so at most this many are running simultaneously. Reduce if the host has limited resources or if many collectors perform I/O and you want to avoid thundering-herd effects.

```yaml
runtime:
  max_concurrency: 8    # default — good for most setups
  max_concurrency: 4    # constrained host or many rate-mode network collectors
  max_concurrency: 16   # host with many independent fast collectors
```

##### `lock_file`
Path to the PID lock file. The file is created at run start and deleted at run end. Two separate hosts at `/opt/zabbig_client` on the same machine would need different lock paths.

```yaml
runtime:
  lock_file: "/tmp/zabbig_client.lock"           # default
  lock_file: "/var/run/zabbig/client.lock"       # more conventional system path
  lock_file: "/tmp/zabbig_client_prod.lock"      # if running two instances on one host
```

##### `dry_run`
When `true`, all collectors run normally and results are logged, but nothing is sent to Zabbix. Useful for validating a new `metrics.yaml` or testing on a host that does not yet have trapper items provisioned.

```yaml
runtime:
  dry_run: false    # default — production mode
  dry_run: true     # testing/debugging — no data sent
```

Can also be set with the CLI flag: `python3 run.py --dry-run`

##### `fail_fast`
When `false` (default), a single collector failure is recorded and the run continues — all other metrics are still collected and sent. When `true`, the first unhandled exception in any collector aborts the entire run immediately. Use `true` only during active debugging.

```yaml
runtime:
  fail_fast: false   # default — production safe; partial results are sent
  fail_fast: true    # debugging only — immediate abort on any exception
```

##### `proc_root`
Base path for the Linux `/proc` filesystem. Affects the `cpu`, `memory`, `network`, and `service` (process mode) collectors. Override when the client runs inside a container and the host's proc filesystem is bind-mounted at a different path.

```yaml
runtime:
  proc_root: "/proc"           # default — native Linux host
  proc_root: "/host/proc"      # Docker container with host /proc bind-mounted
  proc_root: "/mnt/remote/proc"  # remote monitoring via NFS/SSH mount
```

Individual metrics can also set `params.proc_root` to override this value for just that one metric, which is useful when monitoring multiple hosts from a single client instance.

---

#### `batching` — delivery timing

##### `batch_collection_window_seconds`
How long (in seconds) the client waits for batch-mode collectors to finish before cancelling any still-running ones. This is the primary knob controlling how long a run takes. It should be well under `overall_timeout_seconds` to leave time for the send operations.

```yaml
batching:
  batch_collection_window_seconds: 60    # default — comfortable for most collectors
  batch_collection_window_seconds: 30    # for tight overall_timeout budgets
  batch_collection_window_seconds: 90    # when many slow log collectors scan large files
```

##### `batch_send_max_size`
Maximum number of metric values per Zabbix trapper call. If more metrics are ready than this limit, they are split into multiple sequential calls. Most installations never need to change this.

```yaml
batching:
  batch_send_max_size: 250    # default
  batch_send_max_size: 100    # if Zabbix server has strict payload size limits
```

##### `flush_immediate_separately`
When `true`, immediate-delivery metrics are sent in a dedicated Zabbix call before the batch send. This ensures their delivery is not delayed. When `false`, they are merged into the batch send — saves a round-trip but loses the timing advantage.

```yaml
batching:
  flush_immediate_separately: true    # default — immediate metrics arrive first
  flush_immediate_separately: false   # reduce round-trips at the cost of timing
```

##### `immediate_micro_batch_window_ms`
When immediate collectors finish close together, this wait (in milliseconds) lets them be grouped into a single Zabbix call. Without this, a burst of service-check results could trigger many individual sends. Increase if you have many immediate collectors and want to reduce Zabbix API call frequency.

```yaml
batching:
  immediate_micro_batch_window_ms: 200    # default — 200 ms grouping window
  immediate_micro_batch_window_ms: 0      # no grouping — each result sent immediately
  immediate_micro_batch_window_ms: 1000   # aggressive grouping for many immediate metrics
```

---

#### `logging`

##### `level`
Standard Python log level. Use `INFO` in production to see run summaries and errors. Use `DEBUG` when diagnosing collector problems — it logs individual metric values, timing, and file paths.

```yaml
logging:
  level: INFO      # default — run summaries + warnings/errors
  level: DEBUG     # verbose — individual values, timing, state file paths
  level: WARNING   # quiet — only problems
```

##### `format`
`text` produces human-readable lines (`2026-03-19 18:00:00  INFO  zabbig_client.runner  Collected cpu_util = 23.4`). `json` produces structured JSON objects, one per line — preferred for log aggregation pipelines (ELK, Grafana Loki, Splunk).

```yaml
logging:
  format: text    # default — human-readable
  format: json    # structured — for log aggregation
```

##### `file`
If set, logs are written to this file **in addition to** the console (unless `console: false`). The file is automatically rotated at 10 MB, keeping 5 compressed backups. The directory must exist and be writable.

```yaml
logging:
  file: "/var/log/zabbig/client.log"   # recommended for cron setups
  # file:                              # default — no file, console only
```

##### `console`
When `true`, logs go to stderr (picked up by cron and forwarded to the cron mailer or syslog). Set `false` when using a `file` in cron to avoid duplicate output.

```yaml
logging:
  console: true     # default — logs to stderr
  console: false    # suppress stderr; use file: instead for cron
```

---

#### `state` — persistence

##### `enabled`
When `true`, a `last_run.json` file is written to `state.directory` at the end of each run. It records the run timestamp, success/failure status, number of metrics sent, and consecutive failure count. Useful for Zabbix self-monitoring items that alert when the client has not run recently.

```yaml
state:
  enabled: true     # default — write last_run.json
  enabled: false    # disable if state directory is not writable
```

##### `directory`
Directory for all state files. This covers two distinct uses:
1. **`last_run.json`** — written by the client itself when `state.enabled: true`
2. **`log_<metric_id>.json`** — written by the log collector for every `mode: condition` metric, storing the last byte offset and inode number so incremental scans resume correctly

The directory must be writable by the user running the cron job. Relative paths are resolved from the working directory at run time (which is `zabbig_client/` when using the standard cron setup).

```yaml
state:
  directory: "state"               # default — relative to working directory
  directory: "/var/lib/zabbig"     # absolute — better for systemd service setups
  directory: "/tmp/zabbig_state"   # temporary — acceptable for testing
```

---

#### `features` — feature flags

##### `self_monitoring_metrics`
When `true`, the client sends five additional Zabbix items describing its own health at the end of every run:

| Key | Description |
|-----|-------------|
| `zabbig.client.run.success` | `1` if the run completed without fatal errors, `0` otherwise |
| `zabbig.client.collectors.total` | Total number of metrics attempted |
| `zabbig.client.collectors.failed` | Number of metrics that failed or timed out |
| `zabbig.client.duration_ms` | Total run time in milliseconds |
| `zabbig.client.metrics.sent` | Number of values successfully accepted by Zabbix |

These require matching Zabbix Trapper items configured for the host.

```yaml
features:
  self_monitoring_metrics: true    # default — send client health to Zabbix
  self_monitoring_metrics: false   # disable if trapper items are not configured
```

##### `emit_partial_failure_metrics`
When `true`, metrics with `error_policy: mark_failed` emit a special failure-state result rather than sending nothing. Rarely needed outside custom Zabbix trigger setups.

```yaml
features:
  emit_partial_failure_metrics: false   # default
  emit_partial_failure_metrics: true    # custom failure-state handling in Zabbix
```

##### `strict_config_validation`
When `true` (default), any validation error in `metrics.yaml` or `client.yaml` aborts the run immediately with exit code 2. When `false`, errors are logged as warnings and execution continues with built-in defaults. Set `false` only as a temporary measure when gradually migrating a config.

```yaml
features:
  strict_config_validation: true    # default — fail loudly on config errors
  strict_config_validation: false   # lenient — warn and continue (not recommended)
```

##### `skip_disabled_metrics`
When `true` (default), metrics with `enabled: false` are not collected. When `false`, disabled metrics are collected and sent anyway — useful for temporarily overriding `enabled: false` without editing `metrics.yaml`, e.g. during collector development.

```yaml
features:
  skip_disabled_metrics: true    # default — normal operation
  skip_disabled_metrics: false   # collect everything regardless of enabled flag
```

---

### `metrics.yaml` — per-metric fields

#### Common fields (all collectors)

##### `id`
Unique string identifier for this metric within the file. Must be unique — the config loader rejects duplicates. Used in log output and as the base name for log collector state files (`state/log_<id>.json`). Convention: `lowercase_with_underscores`, prefixed by collector type.

```yaml
id: cpu_util
id: disk_data_used_percent
id: svc_postgresql
id: log_app_error
```

##### `name`
Short human-readable label printed in log output and run summaries. Not sent to Zabbix.

```yaml
name: "CPU utilization percent"
name: "PostgreSQL service state"
name: "Application log error detected"
```

##### `description`
Longer prose description. Supports YAML block scalars. Not used at runtime — purely for documentation in the file.

```yaml
description: Percentage of RAM in use, calculated from /proc/meminfo.

description: >
  Returns 1 if the sshd service is active, 0 otherwise.
  Uses systemctl is-active — requires systemd.
```

##### `enabled`
`true` (default) or `false`. Setting `false` is the cleanest way to temporarily disable a metric without deleting its definition — the Zabbix item still exists after provisioning, it just stops receiving data.

```yaml
enabled: true    # collected and sent every run
enabled: false   # skipped entirely — item goes stale in Zabbix
```

##### `collector`
Which built-in collector handles this metric. Valid values: `cpu`, `memory`, `disk`, `service`, `network`, `log`.

##### `key`
The Zabbix item key. Must exactly match — including case, dots, and brackets — a Trapper item configured on the corresponding host in Zabbix. If the key doesn't match, Zabbix silently discards the value. Convention: `host.<collector>.<detail>` for system metrics, `app.<service>.<detail>` for application metrics.

```yaml
key: host.cpu.util
key: host.disk.root.used_percent
key: host.service.nginx
key: app.log.error
key: "app.log.payment.calls.total"   # quote if key contains special chars
```

##### `value_type`
Informational hint: `float`, `int`, or `string`. Used in log output and can be matched to the Zabbix item's value type. Does not affect the wire format — all values are sent as strings.

##### `unit`
Informational unit label (e.g. `%`, `B`, `B/s`, `ms`, `s`). Printed in log output alongside the value. Not sent to Zabbix.

##### `delivery`
`batch` or `immediate`. Overrides the collector-level default. See the [Batch vs Immediate Delivery](#batch-vs-immediate-delivery) section for details.

```yaml
delivery: batch        # non-urgent resource metric
delivery: immediate    # time-sensitive state change
```

##### `timeout_seconds`
Per-metric timeout. If the collector does not return a value within this time, it is cancelled and `error_policy` applies. Set higher for slow collectors (log file scans, rate-mode network reads). Set lower for fast collectors if you want them to fail quickly.

```yaml
timeout_seconds: 5      # cpu, memory — should be near-instant
timeout_seconds: 30     # log condition scan — plenty of time for large files
timeout_seconds: 3      # network rate mode — 1 s sleep + margin
```

##### `error_policy`
What to do when the collector fails or times out:

| Value | Behaviour |
|-------|-----------|
| `skip` | Silently discard the metric for this run. Nothing is sent to Zabbix. The item goes stale if no successful value arrives within the item's "No data" period. Best for optional metrics. |
| `fallback` | Send `fallback_value` to Zabbix. Use when a known-sentinel value is more useful than silence (e.g. `0` for swap on a host with no swap configured). |
| `mark_failed` | Log an error and count the metric as failed in the run summary. Nothing is sent. Combined with `features.self_monitoring_metrics`, this causes `zabbig.client.collectors.failed` to increment, which can trigger a Zabbix alert. |

```yaml
# Optional metric — silence is fine
error_policy: skip

# Service check — treat "cannot check" as "service is down"
error_policy: fallback
fallback_value: "0"

# Critical metric — failure should be visible in Zabbix run summary
error_policy: mark_failed
```

##### `importance`
Informational label for log output: `low`, `normal`, `high`, `critical`. Affects how prominently failures are logged. Does not change any runtime behaviour.

##### `tags`
List of string labels for filtering in log output. No fixed schema — use whatever grouping makes sense for your setup.

```yaml
tags: [system, cpu]
tags: [service, web]
tags: [app, log]
tags: [database, postgres]
```

---

#### Collector defaults (`collector_defaults` in `metrics.yaml`)

These per-collector defaults apply to every metric using that collector, unless overridden at the metric level. They sit between the global `defaults` and the per-metric fields in the resolution order:

```
metric field  >  collector_defaults  >  defaults (global)
```

| Collector | `timeout_seconds` | `delivery` |
|-----------|-------------------|------------|
| `cpu`     | 5                 | batch      |
| `memory`  | 5                 | batch      |
| `disk`    | 10                | batch      |
| `service` | 8                 | immediate  |
| `network` | 10                | batch      |
| `log`     | 60                | batch      |

You can add any field that is valid at the metric level:

```yaml
collector_defaults:
  log:
    timeout_seconds: 120   # extra time for large log files
    delivery: immediate    # make all log metrics immediate by default
    error_policy: skip
```

---

### Collector `params`

---

#### `cpu` collector

Reads from `/proc/stat`, `/proc/loadavg`, and `/proc/uptime`. Linux only (reads from the host proc; on Docker use `proc_root: "/host/proc"`).

**Params:**

| Param | Required | Description |
|-------|----------|-------------|
| `mode` | yes | Which CPU metric to return (see below) |
| `proc_root` | no | Override `runtime.proc_root` for this metric only |

**Modes:**

| Mode | Source | Returns |
|------|--------|---------|
| `percent` | `/proc/stat` | Total CPU utilisation 0–100, averaged across all cores. Computed from two reads 200 ms apart — this is why even a fast CPU util check takes ~200–250 ms. |
| `load1` | `/proc/loadavg` | 1-minute load average. On a 4-core machine, a value of 4.0 means all cores are fully occupied. |
| `load5` | `/proc/loadavg` | 5-minute load average. More stable indicator for sustained load. |
| `load15` | `/proc/loadavg` | 15-minute load average. Useful for detecting long-running saturation. |
| `uptime` | `/proc/uptime` | Seconds since last boot. Useful for detecting unexpected reboots when the value drops suddenly. |

**Scenario examples:**

```yaml
# Basic CPU usage alert
- id: cpu_util
  collector: cpu
  key: host.cpu.util
  value_type: float
  unit: "%"
  params:
    mode: percent

# All three load averages for trend analysis
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

# Reboot detection — alert in Zabbix when value suddenly drops
- id: uptime
  collector: cpu
  key: host.system.uptime
  value_type: float
  unit: "s"
  importance: high
  params:
    mode: uptime

# Monitor a container's host CPU through a bind-mounted /proc
- id: host_cpu_util_from_container
  collector: cpu
  key: host.cpu.util
  value_type: float
  params:
    mode: percent
    proc_root: "/host/proc"     # /proc from the container host, bind-mounted
```

---

#### `memory` collector

Reads from `/proc/meminfo`. Linux only.

**Params:**

| Param | Required | Description |
|-------|----------|-------------|
| `mode` | yes | Which memory metric to return |
| `proc_root` | no | Override `runtime.proc_root` for this metric only |

**Modes:**

| Mode | Formula | Returns |
|------|---------|---------|
| `used_percent` | `(MemTotal − MemAvailable) / MemTotal × 100` | RAM in use as a percentage. Uses `MemAvailable` (not `MemFree`) so it correctly accounts for reclaimable caches. |
| `available_bytes` | `MemAvailable` from `/proc/meminfo` | Bytes available for new allocations without swapping. More actionable than free bytes alone. |
| `swap_used_percent` | `(SwapTotal − SwapFree) / SwapTotal × 100` | Swap in use %. Returns `0.0` gracefully when no swap is configured (SwapTotal = 0). |

**Scenario examples:**

```yaml
# Standard RAM alert — alert at 90%
- id: mem_used_percent
  collector: memory
  key: host.memory.used_percent
  value_type: float
  unit: "%"
  importance: high
  params:
    mode: used_percent

# Available bytes — useful for capacity planning graphs
- id: mem_available_bytes
  collector: memory
  key: host.memory.available_bytes
  value_type: int
  unit: "B"
  params:
    mode: available_bytes

# Swap monitoring with fallback=0 for hosts with no swap
# (avoids the item going stale on swap-free servers)
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

#### `disk` collector

Uses `os.statvfs()`. Works on both Linux and macOS.

**Params:**

| Param | Required | Description |
|-------|----------|-------------|
| `mount` | yes | Absolute path to the mount point to inspect, e.g. `/`, `/data`, `/var` |
| `mode` | yes | Which disk metric to return |

**Modes:**

| Mode | Returns |
|------|---------|
| `used_percent` | Percentage of filesystem blocks in use (non-root perspective) |
| `used_bytes` | Bytes currently used (total − available to non-root) |
| `free_bytes` | Bytes available to non-root users (`statvfs.f_bavail × f_frsize`) |
| `inodes_used_percent` | Inode slots in use as % of total. Returns `0.0` on btrfs/tmpfs where total inodes = 0 |
| `inodes_used` | Number of inode slots in use |
| `inodes_free` | Number of free inode slots |
| `inodes_total` | Total inode slots on the filesystem |

Inode exhaustion (running out of inodes while space is still available) is a common prod incident — especially on filesystems with many small files (mail queues, session stores, log directories). Monitor both `used_percent` and `inodes_used_percent`.

**Scenario examples:**

```yaml
# Root partition capacity — alert at 85%
- id: disk_root_used_percent
  collector: disk
  key: host.disk.root.used_percent
  value_type: float
  unit: "%"
  importance: high
  params:
    mount: "/"
    mode: used_percent

# Free bytes — useful for capacity planning when % alone is not enough
- id: disk_root_free_bytes
  collector: disk
  key: host.disk.root.free_bytes
  value_type: int
  unit: "B"
  params:
    mount: "/"
    mode: free_bytes

# Separate data partition
- id: disk_data_used_percent
  collector: disk
  key: host.disk.data.used_percent
  value_type: float
  unit: "%"
  params:
    mount: "/data"
    mode: used_percent

# Inode monitoring — catch "no space left on device" when df shows space free
- id: disk_root_inodes_used_percent
  collector: disk
  key: host.disk.root.inodes_used_percent
  value_type: float
  unit: "%"
  importance: high
  params:
    mount: "/"
    mode: inodes_used_percent

# Absolute inode counts for trending boards
- id: disk_root_inodes_free
  collector: disk
  key: host.disk.root.inodes_free
  value_type: int
  params:
    mount: "/"
    mode: inodes_free

# /var partition — common inode exhaustion target (logs, dpkg, etc.)
- id: disk_var_inodes_used_percent
  enabled: false    # enable if /var is on its own partition
  collector: disk
  key: host.disk.var.inodes_used_percent
  value_type: float
  unit: "%"
  params:
    mount: "/var"
    mode: inodes_used_percent
```

---

#### `service` collector

Checks whether a service or process is running. Returns `1` (running) or `0` (not running).

**Params:**

| Param | Required | Description |
|-------|----------|-------------|
| `check_mode` | yes | `systemd` or `process` |
| `service_name` | when `systemd` | systemd unit name, without the `.service` suffix |
| `process_pattern` | when `process` | Python regex matched against the full cmdline string of each process in `/proc/*/cmdline` |
| `proc_root` | no | Override `runtime.proc_root`. Only used by `process` mode. |

**`check_mode: systemd`** — runs `systemctl is-active --quiet <service_name>`. Returns `1` if exit code is 0 (active). Returns `0` for any non-zero exit code (inactive, failed, activating, etc.). Requires systemd; use `process` mode on hosts with SysV init or OpenRC.

**`check_mode: process`** — scans `/proc/*/cmdline` (each process's full command line, NUL-separated and joined with spaces) and matches the `process_pattern` regex against it. Returns `1` if at least one process matches, `0` otherwise. Works anywhere Linux `/proc` is available — no systemd required.

**Scenario examples:**

```yaml
# Critical service — use mark_failed so zabbig.client.collectors.failed counts it
- id: svc_postgresql
  collector: service
  key: host.service.postgresql
  value_type: int
  delivery: immediate
  importance: critical
  error_policy: mark_failed
  params:
    check_mode: systemd
    service_name: postgresql

# Web server — treat "cannot check" as "service is down" via fallback
- id: svc_nginx
  collector: service
  key: host.service.nginx
  value_type: int
  delivery: immediate
  importance: critical
  error_policy: fallback
  fallback_value: "0"
  params:
    check_mode: systemd
    service_name: nginx

# Process check — no systemd required
# Matches: python3 /opt/myapp/server.py, python /srv/app.py, etc.
- id: svc_myapp_process
  collector: service
  key: host.service.myapp.process
  value_type: int
  delivery: immediate
  importance: high
  params:
    check_mode: process
    process_pattern: "python.*myapp"

# Strict nginx master process check (avoids matching worker processes)
- id: svc_nginx_process
  collector: service
  key: host.service.nginx.process
  value_type: int
  params:
    check_mode: process
    process_pattern: "nginx: master process"

# Monitor cron inside a Docker container (no systemd available)
- id: svc_crond
  collector: service
  key: host.service.cron.process
  value_type: int
  params:
    check_mode: process
    process_pattern: "crond|cron"
    proc_root: "/host/proc"   # host /proc bind-mounted into container
```

---

#### `network` collector

Reads `/proc/net/dev` for interface traffic/error counters and `/proc/net/sockstat` for socket counts. Linux only — on macOS and other systems `error_policy: skip` applies.

**Params:**

| Param | Required | Description |
|-------|----------|-------------|
| `interface` | for traffic/error modes | Name of the NIC as listed in `/proc/net/dev` (e.g. `eth0`, `ens3`, `enp1s0`). Use the special value `total` to aggregate all non-loopback interfaces. Not required for socket modes. |
| `mode` | yes | Which metric to collect |
| `proc_root` | no | Override `runtime.proc_root` for this metric |

**Modes — rate (two reads, 1 second apart):**

These modes sleep for 1 second between reads to compute a per-second rate. Set `timeout_seconds >= 3` to give them enough headroom.

| Mode | Returns |
|------|---------|
| `rx_bytes_per_sec` | Inbound throughput in bytes/second |
| `tx_bytes_per_sec` | Outbound throughput in bytes/second |

**Modes — cumulative counters (single read, resets on reboot):**

| Mode | Returns |
|------|---------|
| `rx_bytes` | Total bytes received since boot |
| `tx_bytes` | Total bytes transmitted since boot |
| `rx_packets` | Total packets received since boot |
| `tx_packets` | Total packets transmitted since boot |
| `rx_errors` | Total receive errors since boot |
| `tx_errors` | Total transmit errors since boot |
| `rx_dropped` | Total receive drops since boot (kernel ring buffer overruns) |
| `tx_dropped` | Total transmit drops since boot |

Configure the Zabbix item with **Delta (speed per second)** preprocessing to convert cumulative byte counters into throughput graphs without needing the rate-mode collector.

**Modes — socket counters (from `/proc/net/sockstat`, no `interface` param):**

| Mode | Returns |
|------|---------|
| `tcp_inuse` | Open TCP sockets (ESTABLISHED + others) |
| `tcp_timewait` | Sockets in TIME_WAIT — high persistent values suggest connection churn or port exhaustion |
| `tcp_orphans` | Orphaned TCP sockets (not attached to any file descriptor) — growing value indicates a socket leak |
| `udp_inuse` | Open UDP sockets |

**Scenario examples:**

```yaml
# Real-time throughput monitoring (read twice, 1 second apart)
- id: net_rx_bytes_per_sec
  collector: network
  key: host.net.rx_bytes_per_sec
  value_type: float
  unit: "B/s"
  timeout_seconds: 5        # must be > 1 s sleep + overhead
  params:
    interface: total         # aggregate all non-loopback NICs
    mode: rx_bytes_per_sec

# Per-NIC throughput
- id: net_eth0_rx_bytes_per_sec
  collector: network
  key: host.net.eth0.rx_bytes_per_sec
  value_type: float
  unit: "B/s"
  timeout_seconds: 5
  params:
    interface: eth0
    mode: rx_bytes_per_sec

# Cumulative bytes — use Zabbix Delta preprocessing for throughput graphs
# without the 1-second sleep cost
- id: net_rx_bytes
  collector: network
  key: host.net.rx_bytes
  value_type: int
  unit: "B"
  params:
    interface: total
    mode: rx_bytes

# Error and drop monitoring — alert when these increase (indicate NIC/cable issues)
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

# TIME_WAIT monitoring — useful for high-traffic APIs with connection churn
- id: net_tcp_timewait
  collector: network
  key: host.net.tcp_timewait
  value_type: int
  params:
    mode: tcp_timewait

# Socket leak detection — orphaned TCP sockets should be near 0
- id: net_tcp_orphans
  collector: network
  key: host.net.tcp_orphans
  value_type: int
  importance: high
  params:
    mode: tcp_orphans
```

---

#### `log` collector

Monitors application log files by scanning for matching lines and returning derived values. Two modes: `condition` (incremental, offset-tracked) and `count` (full-file cumulative count).

**Large-file safety:** files are opened in binary mode and iterated line-by-line with `readline()` after seeking to the stored byte offset. The full file is never loaded into memory. For `condition` mode, cost is proportional only to new bytes written since the last run. For `count` mode, cost scales with the entire file.

**Rotation and truncation detection:** on each run, the collector checks the current inode number against the stored value and compares the file size to the stored offset. An inode mismatch (log was rotated to a new file) or a smaller file size (in-place truncation or logrotate `copytruncate`) both reset the offset to 0, ensuring no lines are missed and no lines are re-processed.

**Partial line safety:** if the last line in the file does not end with a newline (i.e. a line is being written), the offset is left at the start of that line so it is re-read in full on the next run.

**Params:**

| Param | Required | Description |
|-------|----------|-------------|
| `path` | yes | Path to the log file. The **basename** (filename part only) may be a Python regex. The directory portion is always a literal path. When multiple files match, the most recently modified one is used. |
| `match` | yes | Python regex applied to every line in the scan window. Lines that do not match are skipped entirely — they are never forwarded to condition evaluation or counted. This is the primary performance filter: make it as narrow as possible. |
| `mode` | no | `condition` (default) or `count` |
| `encoding` | no | File character encoding. Default: `utf-8` |
| `result` | no | `last` (default) / `first` / `max` / `min` — how to reduce multiple per-line values from one scan window into a single Zabbix value. Only applies to `condition` mode. |
| `default_value` | no | Value sent to Zabbix when no line in the scan window matched `match`. Prevents the Zabbix item from going stale between events. Default: `0` |
| `conditions` | required for `condition` mode | Ordered list of sub-condition entries. The first matching entry provides the value for that line. |
| `state_dir` | no | Override the state directory (`state.directory` from `client.yaml`) for this specific metric. Rarely needed. |

**`result` strategies (condition mode only):**

When multiple lines in one scan window all pass `match` and produce a value, `result` determines which value is reported:

| Strategy | Behaviour |
|----------|-----------|
| `last` | Returns the value from the **last** matching line. Good for "latest state" semantics. |
| `first` | Returns the value from the **first** matching line. Good for "first occurrence" semantics. |
| `max` | Returns the numerically **highest** value across all matching lines. Good for severity levels — always reports the worst event in the window. Non-numeric values are skipped; falls back to `last` if no numeric values exist. |
| `min` | Returns the numerically **lowest** value. Good for "best case in window" scenarios. |

**Condition entry forms:**

Each entry in the `conditions` list is evaluated against every line that passed `match`. Evaluation stops at the first matching entry.

**Form 1 — regex match → fixed value:**
```yaml
- when: "ERROR|FATAL"
  value: 2
```
`when` is a Python regex applied via `re.search()`. If it matches anywhere in the line, `value` is returned for that line.

**Form 2 — numeric extraction + comparison:**
```yaml
- extract: 'duration_ms=(\d+(?:\.\d+)?)'
  compare: gt        # gt | lt | gte | lte | eq
  threshold: 1000
  value: "$1"        # return the captured number, or use a fixed literal
```
`extract` runs `re.search()` and must contain exactly one capture group `()`. The captured text is cast to `float` and compared against `threshold` using `compare`. If the comparison passes, `value` is returned. Use `"$1"` as the value to return the extracted number itself (e.g. the actual response time), or a fixed literal to map it to a severity level.

**Form 3 — catch-all:**
```yaml
- value: 0
```
No `when` or `extract` — matches any line that passed `match` but was not matched by an earlier condition. Always place this last.

**`when` and `extract` are mutually exclusive.** A condition entry can use one or the other, not both.

**Scenario examples:**

```yaml
# -----------------------------------------------------------------------
# Simplest possible: return 1 when any ERROR appears, 0 when clean
# -----------------------------------------------------------------------
- id: log_app_error
  collector: log
  key: app.log.error
  value_type: int
  delivery: immediate
  importance: high
  params:
    path: "/var/log/myapp/app.log"
    match: "ERROR"
    mode: condition
    default_value: 0
    conditions:
      - value: 1    # catch-all: any line that matched 'ERROR' → returns 1

# -----------------------------------------------------------------------
# Severity level: returns the worst event in the scan window
# result: max ensures FATAL beats ERROR which beats WARN in the same window
# -----------------------------------------------------------------------
- id: log_app_severity
  collector: log
  key: app.log.severity
  value_type: int
  delivery: immediate
  importance: high
  params:
    path: "/var/log/myapp/app.log"
    match: "WARN|ERROR|FATAL|OutOfMemory"
    mode: condition
    result: max          # highest severity in window wins
    default_value: 0
    conditions:
      - when: "FATAL|OutOfMemory"
        value: 3
      - when: "ERROR"
        value: 2
      - when: "WARN"
        value: 1
      - value: 0

# -----------------------------------------------------------------------
# Numeric extraction: max response time in the scan window
# Returns the actual ms value, not a fixed integer
# -----------------------------------------------------------------------
- id: log_api_response_time_max
  collector: log
  key: app.log.api.response_time_max_ms
  value_type: float
  unit: "ms"
  params:
    path: "/var/log/myapp/access.log"
    match: "response_time="
    mode: condition
    result: max          # highest response time in window
    default_value: 0
    conditions:
      - extract: 'response_time=(\d+(?:\.\d+)?)'
        compare: gt
        threshold: 0     # always passes — captures any positive value
        value: "$1"      # return the actual captured number

# -----------------------------------------------------------------------
# Response time with severity bucketing — returns a severity level,
# not the raw time. 3=critical (>5s), 2=slow (>1s), 1=acceptable, 0=ok
# -----------------------------------------------------------------------
- id: log_api_response_severity
  collector: log
  key: app.log.api.response_severity
  value_type: int
  params:
    path: "/var/log/myapp/access.log"
    match: "response_time="
    mode: condition
    result: max
    default_value: 0
    conditions:
      - extract: 'response_time=(\d+)'
        compare: gt
        threshold: 5000
        value: 3
      - extract: 'response_time=(\d+)'
        compare: gt
        threshold: 1000
        value: 2
      - extract: 'response_time=(\d+)'
        compare: gt
        threshold: 0
        value: 1
      - value: 0

# -----------------------------------------------------------------------
# Cumulative count — total error lines ever written to the file.
# Configure Zabbix item with "Delta per second" preprocessing for a rate graph.
# No state file is maintained — always reads from byte 0.
# -----------------------------------------------------------------------
- id: log_app_error_total
  collector: log
  key: app.log.error.total
  value_type: int
  timeout_seconds: 60
  params:
    path: "/var/log/myapp/app.log"
    match: "ERROR|FATAL"
    mode: count

# -----------------------------------------------------------------------
# Rotating log file — basename is a regex matching dated filenames
# e.g. app-20260319.log, app-20260320.log
# The most recently modified matching file is always used.
# -----------------------------------------------------------------------
- id: log_app_daily_errors
  collector: log
  key: app.log.daily.errors
  value_type: int
  params:
    path: '/var/log/myapp/app-\d{8}\.log'
    match: "ERROR"
    mode: count

# -----------------------------------------------------------------------
# First occurrence mode — report the first type of error seen in the window,
# useful when errors are sequential and the first one is the root cause
# -----------------------------------------------------------------------
- id: log_app_first_error
  collector: log
  key: app.log.first_error_code
  value_type: int
  params:
    path: "/var/log/myapp/app.log"
    match: "ERROR"
    mode: condition
    result: first   # first error in window, not the last
    default_value: 0
    conditions:
      - when: "ConnectionRefused"
        value: 10
      - when: "Timeout"
        value: 20
      - when: "OutOfMemory"
        value: 30
      - value: 99    # unknown error type

# -----------------------------------------------------------------------
# HTTP 5xx detection in an nginx access log
# -----------------------------------------------------------------------
- id: log_nginx_5xx
  collector: log
  key: app.nginx.5xx_detected
  value_type: int
  delivery: immediate
  importance: high
  params:
    path: "/var/log/nginx/access.log"
    match: '" 5\d\d '
    mode: condition
    default_value: 0
    conditions:
      - value: 1
```

---

## How to Add a New Metric

Add an entry to `metrics.yaml` (no code changes needed for existing collectors), then re-run `provision_zabbix.py` to create the corresponding trapper item in Zabbix.

```yaml
- id: disk_backup_used_percent
  name: Backup volume used percent
  enabled: true
  collector: disk
  key: host.disk.backup.used_percent
  value_type: float
  unit: "%"
  delivery: batch
  importance: high
  error_policy: skip
  tags: [system, disk]
  params:
    mount: "/backup"
    mode: used_percent
```

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
