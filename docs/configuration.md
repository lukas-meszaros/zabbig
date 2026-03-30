# Configuration Reference

> **This file has been split for easier navigation.**
> 
> | Document | Contents |
> |---|---|
> | [configuration-client.yaml.md](configuration-client.yaml.md) | `client.yaml` — server connection, timeouts, batching, logging, state, features |
> | [configuration-metrics.yaml.md](configuration-metrics.yaml.md) | `metrics.yaml` — `include:`, `defaults`, `collector_defaults`, all metric fields, scheduling, `cache_seconds` |

---

Two YAML files control the client's behaviour:

| File | Purpose |
|---|---|
| `client.yaml` | Runtime settings: server connection, timeouts, logging, state |
| `metrics.yaml` | What to collect: one entry per metric, with collector and params |

The sections below are kept for backward compatibility with existing links. For new work, use the dedicated documents above.

---

## client.yaml

### `zabbix` — server connection

#### `server_host`

An ordered list of one or more Zabbix server or proxy addresses used for the trapper (sender) connection on port 10051. The client tries each address in order — if a connection error occurs on the first, it rotates to the next. Zabbix protocol rejections (unknown item key, wrong value type) are **not** rotated; because all servers share the same database, the same data would be rejected on every server.

```yaml
# Single server — dev / simple setup
zabbix:
  server_host: ["127.0.0.1"]

# Multiple servers / proxies — prod failover
zabbix:
  server_host: ["proxy-bar", "proxy-tor"]

# Block form (equivalent)
zabbix:
  server_host:
    - "10.0.1.50"
    - "10.0.1.51"
```

A list is always required, even for a single entry. A bare string will cause a `ConfigError` at startup.

#### `server_port`

Zabbix trapper port. Default `10051`.

```yaml
zabbix:
  server_port: 10051    # default
```

#### `host_name`

The Zabbix host name exactly as it appears in **Configuration → Hosts**. Values sent with a non-matching name are silently discarded by Zabbix. Leave empty to use the system hostname (`socket.gethostname()`).

```yaml
zabbix:
  host_name: "prod-web-01"    # hardcoded — explicit and safe
  host_name: ""               # auto-detect from system hostname
```

This is the **global default** used for all metrics. Individual metrics can override it — see [Metric-level `host_name`](#metric-level-host_name) below.

#### `host_group`

Used only by `zabbix_update/create_trapper_items.py`. The group is created automatically if it does not exist. Has no effect during metric collection.

```yaml
zabbix:
  host_group: "zabbig Clients"      # default
  host_group: "Production / Web"
```

#### `connect_timeout_seconds` / `send_timeout_seconds`

`connect_timeout_seconds` is how long to wait for the TCP connection to be established. `send_timeout_seconds` covers the full send: writing the payload and reading the acknowledgement.

```yaml
zabbix:
  connect_timeout_seconds: 10    # default
  send_timeout_seconds: 30       # default
```

---

### `runtime` — execution behaviour

#### `overall_timeout_seconds`

Hard wall-clock limit for the entire run. Should be less than your cron interval. When exceeded, outstanding tasks are cancelled, partial results are sent, and the process exits with code 2.

```yaml
runtime:
  overall_timeout_seconds: 240    # default — fits a 5-minute cron
```

#### `max_concurrency`

Maximum number of collectors running simultaneously. All collectors are launched as asyncio tasks, limited by a semaphore to this number.

```yaml
runtime:
  max_concurrency: 8    # default
```

#### `lock_file`

PID lock file path. Created at run start, removed at run end. Prevents overlapping cron executions. Kept in the state directory by default so all runtime files are in one place.

```yaml
runtime:
  lock_file: "state/zabbig_client.lock"    # default
```

#### `dry_run`

When `true`, all collectors run and results are logged, but nothing is sent to Zabbix.

```yaml
runtime:
  dry_run: false    # default
```

Also set via CLI: `python3 run.py --dry-run`

#### `fail_fast`

When `false` (default), collector failures are recorded and the run continues. When `true`, the first unhandled exception aborts the run immediately. Use `true` only during active debugging.

```yaml
runtime:
  fail_fast: false    # default
```

#### `proc_root`

Base path for the Linux `/proc` filesystem. Affects the `cpu`, `memory`, `network`, and `service` (process mode) collectors.

```yaml
runtime:
  proc_root: "/proc"           # default — native Linux host
  proc_root: "/host/proc"      # Docker container with host /proc bind-mounted
```

Individual metrics can override this with `params.proc_root`.

---

### `batching` — delivery timing

#### `batch_collection_window_seconds`

How long the client waits for batch-mode collectors to finish before cancelling any that are still running. Should be well under `overall_timeout_seconds`.

```yaml
batching:
  batch_collection_window_seconds: 60    # default
```

#### `batch_send_max_size`

Maximum metric values per Zabbix trapper call. If more metrics are ready, they are split into multiple chunks and sent in parallel (see `batch_chunk_size`).

```yaml
batching:
  batch_send_max_size: 250    # default
```

#### `batch_chunk_size`

The Zabbix sender `chunk_size` parameter — controls how many `ItemValue` objects are packed into each individual trapper packet within a single send call. Increase if your Zabbix server accepts larger payloads; decrease if you see protocol errors.

```yaml
batching:
  batch_chunk_size: 250    # default
```

#### `flush_immediate_separately`

When `true`, `immediate`-delivery metrics are sent in a dedicated Zabbix call before the batch send, ensuring faster delivery.

```yaml
batching:
  flush_immediate_separately: true    # default
```

#### `immediate_micro_batch_window_ms`

When multiple immediate collectors finish close together, this wait groups them into a single Zabbix call.

```yaml
batching:
  immediate_micro_batch_window_ms: 200    # default
```

---

### `logging`

#### `level`

Standard Python log level. `INFO` in production, `DEBUG` for troubleshooting.

```yaml
logging:
  level: INFO      # default
  level: DEBUG     # verbose — individual values, timing, file paths
  level: WARNING   # quiet — only problems
```

#### `format`

`text` produces human-readable lines. `json` produces structured JSON objects (one per line), suitable for log aggregation.

```yaml
logging:
  format: text    # default
  format: json    # for ELK, Loki, Splunk etc.
```

#### `file`

If set, logs are written to this file in addition to the console. Automatically rotated at 10 MB, keeping 5 compressed backups.

```yaml
logging:
  file: "/var/log/zabbig/client.log"
```

#### `console`

When `true`, logs go to stderr. Set `false` when using `file` in a cron setup to avoid duplicates.

```yaml
logging:
  console: true     # default
```

---

### `state`

#### `enabled`

When `true`, a `last_run.json` file is written at the end of each run. Records timestamp, success/failure, metrics sent, and consecutive failure count.

```yaml
state:
  enabled: true    # default
```

#### `directory`

Directory for all state files:
- `last_run.json` — written by the client itself
- `log_<metric_id>.json` — written by the log collector for each condition-mode metric (stores byte offset and inode for incremental scanning)

```yaml
state:
  directory: "state"               # default — relative to working directory
  directory: "/var/lib/zabbig"     # absolute path
```

---

### `features`

#### `self_monitoring_metrics`

When `true`, the client sends five `zabbig.client.*` items at the end of every run describing its own health. Requires matching trapper items provisioned via `zabbix_update/create_trapper_items.py`.

```yaml
features:
  self_monitoring_metrics: true    # default
```

#### `strict_config_validation`

When `true` (default), any validation error in a config file aborts the run with exit code 2. When `false`, errors are logged as warnings and execution continues.

```yaml
features:
  strict_config_validation: true    # default
```

#### `skip_disabled_metrics`

When `true` (default), metrics with `enabled: false` are not collected. Set `false` to temporarily collect all metrics regardless of their `enabled` flag.

```yaml
features:
  skip_disabled_metrics: true    # default
```

---

## metrics.yaml

### Top-level structure

```yaml
version: 1

defaults:
  # global defaults — apply to every metric unless overridden

collector_defaults:
  cpu:
    # overrides for all cpu metrics
  log:
    timeout_seconds: 120

metrics:
  - id: cpu_util
    # ...
```

Resolution order (most specific wins):

```
metric field  >  collector_defaults.<name>  >  defaults
```

---

### Common metric fields

These fields apply to every collector type.

#### `id`

Unique string identifier. Used in log output and as the base name for log collector state files (`state/log_<id>.json`). Duplicate IDs are rejected at startup.

```yaml
id: cpu_util
id: disk_root_used_percent
id: log_app_error
```

#### `enabled`

`true` (default) or `false`. Disabled metrics are skipped entirely; the corresponding Zabbix item goes stale until re-enabled.

#### `collector`

Which built-in collector handles this metric. Valid values: `cpu`, `memory`, `disk`, `service`, `network`, `log`, `probe`.

#### `key`

The Zabbix item key. Must exactly match — including case and dots — a Trapper item on the corresponding Zabbix host. Non-matching keys are silently discarded by Zabbix.

```yaml
key: host.cpu.util
key: host.disk.root.used_percent
key: app.log.error
```

#### `value_type`

`float`, `int`, or `string`. Informational — used in log output. Does not affect the wire format.

#### `unit`

Informational unit label (e.g. `%`, `B`, `B/s`, `ms`). Printed in log output alongside the value.

#### `delivery`

`batch` or `immediate`. Overrides the `collector_defaults` for this metric.

- **`batch`** — collected within the batch window, sent together at the end.
- **`immediate`** — sent as soon as the value is ready, before the batch window closes.

Use `immediate` for time-sensitive state changes (service up/down, log alerts).

#### `timeout_seconds`

Per-metric timeout in seconds. The collector is cancelled if it does not return a value in time.

#### `error_policy`

What to do when a collector fails or times out:

| Value | Behaviour |
|---|---|
| `skip` | Silently discard. Nothing sent to Zabbix. |
| `fallback` | Send `fallback_value` to Zabbix. Requires `fallback_value` to be set. |
| `mark_failed` | Log an error, count as failed in run summary. Nothing sent. |

---

### Metric-level `host_name`

Optional. Override the Zabbix host name for a specific metric.

When set, the metric is sent to Zabbix under this host name instead of the global `zabbix.host_name` from `client.yaml`. Useful for routing metrics to different Zabbix host objects from a single client instance.

```yaml
- id: cpu_util
  collector: cpu
  key: host.cpu.util
  host_name: "remote-server-01"     # overrides client.yaml for this metric only
  params:
    mode: percent
```

**Priority chain:** `host_name` on the metric entry overrides `zabbix.host_name` in `client.yaml`.

For collectors that use the `conditions` engine (`log` in `condition` mode, `probe` in `http_status` and `http_body` modes), a per-condition `host_name` can further override at the individual condition level:

```yaml
- id: app_log_severity
  collector: log
  key: app.log.severity
  host_name: "app-server"           # metric-level fallback
  params:
    path: /var/log/myapp/app.log
    match: "CRITICAL|ERROR|WARN"
    conditions:
      - when: "CRITICAL"
        value: 3
        host_name: "app-server-critical"   # sent under this host when CRITICAL matched
      - when: "ERROR"
        value: 2
        host_name: "app-server-errors"     # sent under this host when ERROR matched
      - when: "WARN"
        value: 1
        # no host_name — falls back to metric-level "app-server"
      - value: 0
```

**Full priority chain:** condition `host_name` → metric `host_name` → `zabbix.host_name` in `client.yaml`

---

### Metric scheduling fields

Every metric entry supports four optional scheduling fields. Together they control **when** and **how often** a metric is collected. All four default to "no restriction" when absent.

> **Dry-run bypass:** when `--dry-run` is passed on the command line, all scheduling constraints are ignored and every enabled metric is always collected.

#### `time_window_from`

Type: string `"HHMM"` (4 digits, 24-hour clock)

The metric is only collected when the current local time is **on or after** this value. Activates the metric from the specified time until midnight.

```yaml
time_window_from: "0800"    # collect from 08:00 onwards
```

#### `time_window_till`

Type: string `"HHMM"` (4 digits, 24-hour clock)

The metric is only collected when the current local time is **before** this value. Activates the metric from midnight until the specified time.

```yaml
time_window_till: "1800"    # collect until 18:00
```

#### Combined time window

Use both fields together to restrict to a specific period of the day:

```yaml
time_window_from: "0800"
time_window_till: "1800"    # active 08:00–18:00
```

> **Overnight windows** (e.g. 22:00–06:00) require two separate metric entries with the same Zabbix key.

#### `max_executions_per_day`

Type: integer ≥ 0 (`0` or absent = no limit)

Caps how many times the metric is collected per calendar day. Once the daily quota is reached, the metric is skipped for the rest of the day. The counter resets automatically at midnight (tracked in `state/schedule.json`).

```yaml
max_executions_per_day: 5    # collect at most 5 times today
```

#### `run_frequency`

Type: integer ≥ 0 **or** the string `"even"` / `"odd"` (`0` or absent = no limit)

Controls on which zabbig invocations the metric runs, relative to a per-day run counter that starts at 1 and increments with every cron execution:

| Value | Executes on invocation # |
|---|---|
| `0` or absent | every invocation |
| `1` | every invocation |
| `2` | 1, 3, 5, 7, … |
| `5` | 1, 6, 11, 16, … |
| `"odd"` | 1, 3, 5, 7, … |
| `"even"` | 2, 4, 6, 8, … |

```yaml
run_frequency: 2        # every second invocation
run_frequency: "even"   # even-numbered invocations only
```

The run counter resets to 1 at the start of each new calendar day (stored in `state/schedule.json`).

#### Full example — all four fields combined

```yaml
- id: cpu_util_biz
  collector: cpu
  key: host.cpu.util.biz
  value_type: float
  unit: "%"
  time_window_from: "0800"          # only during business hours
  time_window_till: "1800"
  max_executions_per_day: 48        # at most 48 times per day
  run_frequency: 2                  # every other invocation
  params:
    mode: percent
```

Constraints are evaluated in this order: time window → daily quota → run frequency. The first failing constraint skips the metric for that run; the remaining constraints are not evaluated.

---

### `collector_defaults` built-in values

| Collector | `timeout_seconds` | `delivery` |
|---|---|---|
| `cpu` | 5 | batch |
| `memory` | 5 | batch |
| `disk` | 10 | batch |
| `service` | 8 | immediate |
| `network` | 10 | batch |
| `log` | 60 | batch |
| `probe` | 10 | immediate |

---

### `params` field

Each collector has its own `params` block. See the individual collector documents:

- [CPU collector](collector-cpu.md)
- [Memory collector](collector-memory.md)
- [Disk collector](collector-disk.md)
- [Service collector](collector-service.md)
- [Network collector](collector-network.md)
- [Log collector](collector-log.md)
- [Probe collector](collector-probe.md)
