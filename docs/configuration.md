# Configuration Reference

Two YAML files control the client's behaviour:

| File | Purpose |
|---|---|
| `client.yaml` | Runtime settings: server connection, timeouts, logging, state |
| `metrics.yaml` | What to collect: one entry per metric, with collector and params |

---

## client.yaml

### `zabbix` — server connection

#### `server_host`

IP address or DNS hostname of the Zabbix server, used for the trapper (sender) connection on port 10051. When sending through a Zabbix proxy, point this at the proxy.

```yaml
zabbix:
  server_host: "10.0.1.50"         # direct IP — most reliable in Docker/cron
  server_host: "zabbix-server"      # Docker DNS name (inside docker-compose network)
  server_host: "zabbix.corp.lan"    # DNS name — requires DNS resolution at run time
```

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

#### `host_group`

Used only by `provision_zabbix.py`. The group is created automatically if it does not exist. Has no effect during metric collection.

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

Maximum metric values per Zabbix trapper call. If more metrics are ready, they are split into multiple sequential calls.

```yaml
batching:
  batch_send_max_size: 250    # default
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

When `true`, the client sends five `zabbig.client.*` items at the end of every run describing its own health. Requires matching trapper items provisioned via `provision_zabbix.py`.

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

#### `name`

Short human-readable label for log output. Not sent to Zabbix.

#### `description`

Longer documentation string. Not used at runtime.

#### `enabled`

`true` (default) or `false`. Disabled metrics are skipped entirely; the corresponding Zabbix item goes stale until re-enabled.

#### `collector`

Which built-in collector handles this metric. Valid values: `cpu`, `memory`, `disk`, `service`, `network`, `log`.

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

#### `importance`

Informational label for log output: `low`, `normal`, `high`, `critical`. Controls log prominence but has no runtime effect.

#### `tags`

List of string labels for filtering. No fixed schema.

```yaml
tags: [system, cpu]
tags: [service, nginx, web]
```

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

---

### `params` field

Each collector has its own `params` block. See the individual collector documents:

- [CPU collector](collector-cpu.md)
- [Memory collector](collector-memory.md)
- [Disk collector](collector-disk.md)
- [Service collector](collector-service.md)
- [Network collector](collector-network.md)
- [Log collector](collector-log.md)
