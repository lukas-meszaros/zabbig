# Metric Fields Reference

Every entry under `metrics` in `metrics.yaml` shares a common set of fields regardless of which collector is used. This document is the single reference for all of them.

Collector-specific `params` are documented in the individual collector pages. For `client.yaml` settings and the `defaults` / `collector_defaults` blocks see [configuration.md](configuration.md).

---

## Required Fields

### `id`

Unique string identifier within the file. Used in log output and as the base name for log-collector state files (`state/log_<id>.json`). Duplicate IDs are rejected at startup.

```yaml
id: cpu_util
id: disk_root_used_percent
id: log_app_error
```

### `collector`

Which built-in collector handles this metric.

Valid values: `cpu` | `memory` | `disk` | `service` | `network` | `log` | `probe`

### `key`

The Zabbix item key. Must match — including capitalisation and dots — a Trapper item on the target Zabbix host. Keys that do not match are silently discarded by Zabbix.

```yaml
key: host.cpu.util
key: host.disk.root.used_percent
key: app.log.error
```

### `params`

Collector-specific parameters. See the individual collector documents for the full list of supported params and modes.

---

## Common Optional Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | When `false`, the metric is skipped entirely on every run. |
| `delivery` | string | `batch` | `batch` or `immediate`. |
| `timeout_seconds` | float | `10` | Per-collector timeout. Overridable per metric. |
| `error_policy` | string | `skip` | What to do when the collector fails or times out. |
| `fallback_value` | string | — | Required when `error_policy: fallback`. |
| `value_type` | string | — | `float` \| `int` \| `string`. Informational only. |
| `unit` | string | — | Informational unit label (e.g. `%`, `B`, `ms`). Not sent to Zabbix. |

All of these can be set in the top-level `defaults` block or under `collector_defaults.<name>` to apply them to multiple metrics at once. A more specific scope always wins: `metric field > collector_defaults > defaults`.

### `enabled`

`true` (default) or `false`. Disabled metrics are completely skipped; the corresponding Zabbix item goes stale until re-enabled.

```yaml
- id: mem_swap
  enabled: false    # uncomment to start collecting
  collector: memory
  key: host.memory.swap_used_percent
  params:
    mode: swap_used_percent
```

### `delivery`

Controls when the collected value is sent to Zabbix.

- **`batch`** (default) — held until the batch collection window closes, then sent together with other batch metrics in one request. Lower overhead.
- **`immediate`** — sent as soon as the value is ready, before the batch window closes. Use for time-sensitive changes: service state, log alerts, probes.

```yaml
delivery: immediate    # good for service and probe metrics
```

### `timeout_seconds`

How long (in seconds) the runtime waits for the collector to return a value. If the collector does not finish in time, `error_policy` applies.

The `cpu percent` mode always takes ~200 ms due to a two-sample measurement. Rate-based network modes need at least 1 second. Set `timeout_seconds` accordingly.

```yaml
timeout_seconds: 5      # fast collectors
timeout_seconds: 30     # log collectors scanning large files
```

### `error_policy`

What happens when a collector call fails or times out:

| Value | Behaviour |
|---|---|
| `skip` | Silently discard the metric for this run. Nothing is sent to Zabbix. (default) |
| `fallback` | Send `fallback_value` to Zabbix instead of a real value. Requires `fallback_value` to be set. |
| `mark_failed` | Log an error and count the metric as failed in the run summary. Nothing is sent. |

```yaml
error_policy: fallback
fallback_value: "0"    # sent when the collector cannot produce a value
```

### `value_type` and `unit`

Both are informational and do not affect what is sent over the wire (all values are transmitted as strings). They appear in log output alongside the collected value to aid debugging.

```yaml
value_type: float
unit: "%"
```

---

## Host Name Override

### Metric-level `host_name`

By default every metric is sent to Zabbix under the `zabbix.host_name` configured in `client.yaml`. The optional `host_name` field on a metric entry overrides that for just this one metric.

```yaml
- id: cpu_util
  collector: cpu
  key: host.cpu.util
  host_name: "remote-server-01"    # overrides client.yaml for this metric only
  params:
    mode: percent
```

Useful when a single client instance monitors multiple logical hosts, routing different metrics to different Zabbix host objects.

**Priority chain:** metric `host_name` → `zabbix.host_name` in `client.yaml`

### Per-condition `host_name`

The `log` collector (in `condition` mode) and the `probe` collector (in `http_status` and `http_body` modes) support a `host_name` field on individual condition entries. When that condition matches, the resulting value is sent under the condition-level host name instead of the metric-level or global value.

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
        host_name: "app-server-critical"   # routed to a different Zabbix host
      - when: "ERROR"
        value: 2
        host_name: "app-server-errors"
      - when: "WARN"
        value: 1
        # no host_name — falls back to metric-level "app-server"
      - value: 0
```

> Sub-key items (`response_time_ms`, `ssl_check`) on the probe collector always use the metric-level `host_name` and are not affected by per-condition overrides.

**Full priority chain:** condition `host_name` → metric `host_name` → `zabbix.host_name` in `client.yaml`

---

## Scheduling Fields

All four fields are optional. Omit them (or set to `null` / `0`) to disable scheduling constraints entirely. Together they control **when** and **how often** a metric is collected within the zabbig model of "cron schedules the agent, the agent decides which metrics to collect each run".

> **Dry-run bypass:** `--dry-run` ignores all scheduling constraints and collects every enabled metric.

### `time_window_from` and `time_window_till`

Type: quoted `"HHMM"` string, 24-hour clock. Bare integers (e.g. `800`) are also accepted.

Restrict collection to a specific time-of-day window using the host's local time. Both fields must be set together.

```yaml
time_window_from: "0800"
time_window_till: "1800"    # active 08:00–18:00
```

When `time_window_from` > `time_window_till` the window wraps past midnight:

```yaml
time_window_from: "2200"
time_window_till: "0600"    # active 22:00–06:00 next day
```

Outside the window the metric is silently skipped for that run.

### `max_executions_per_day`

Type: integer ≥ 0 (`0` or absent = no limit)

Caps how many times the metric is collected within a single calendar day (midnight-to-midnight, local time). Once the quota is reached the metric is skipped for the rest of the day. The counter resets automatically at midnight and is stored in `state/schedule.json`.

```yaml
max_executions_per_day: 1     # collect at most once per day (e.g. daily snapshot)
max_executions_per_day: 48    # at most every 30 min if running every minute
```

### `run_frequency`

Type: integer ≥ 0 **or** the string `"even"` / `"odd"` (`0` or absent = no restriction)

Controls on which zabbig invocations the metric runs, using a per-day run counter that starts at 1 and increments with each cron execution:

| Value | Collected on invocation # |
|---|---|
| `0` or absent | every invocation |
| `2` | 1, 3, 5, 7, … (every other) |
| `5` | 1, 6, 11, 16, … (every fifth) |
| `"odd"` | 1, 3, 5, 7, … |
| `"even"` | 2, 4, 6, 8, … |

```yaml
run_frequency: 2        # every other invocation (halves the collection rate)
run_frequency: "even"   # even-numbered invocations only
```

The run counter resets at the start of each new calendar day (stored in `state/schedule.json`).

### Constraint evaluation order

When multiple scheduling fields are set, constraints are tested in this order: **time window → daily quota → run frequency**. The first failing constraint skips the metric; the remaining constraints are not evaluated for that run.

### Full scheduling example

```yaml
- id: cpu_util_biz
  collector: cpu
  key: host.cpu.util.biz
  value_type: float
  unit: "%"
  time_window_from: "0800"          # only during business hours
  time_window_till: "1800"
  max_executions_per_day: 48        # at most every 30 min for a 1-min cron
  run_frequency: 2                  # every other invocation within that window
  params:
    mode: percent
```

---

## Condition Engine

Used by:
- **`log` collector** — `condition` mode: conditions evaluated against log file lines
- **`probe` collector** — `http_status` mode: conditions evaluated against the response status code string; `http_body` mode: conditions evaluated against response body lines

Conditions are listed under `params.conditions`. They are evaluated **in order**; the first matching entry wins for each line (or status code).

### Condition Entry Forms

#### Form 1 — fixed value on regex match

```yaml
- when: "ERROR|FATAL"
  value: 2
```

`when` is a Python regex applied via `re.search`. Return `value` when it matches.

#### Form 2 — numeric extraction with comparison

```yaml
- extract: 'duration_ms=(\d+(?:\.\d+)?)'
  compare: gt        # gt | lt | gte | lte | eq
  threshold: 1000
  value: "$1"        # "$1" returns the captured number; use a literal to map to severity
```

`extract` must contain exactly one capture group `()`. The captured text is cast to `float` and compared against `threshold`. If the comparison passes, `value` is returned. Use `"$1"` to return the extracted number itself.

#### Form 3 — catch-all

```yaml
- value: 0
```

No `when` or `extract` — matches any line (or status code) that passed `match` but was not caught by an earlier condition. **Place this last.**

> `when` and `extract` are mutually exclusive in the same entry.

### `result` Strategies

Applies to `log` condition mode and `probe` http_body mode. Controls how multiple per-line values within a single scan window are reduced to a single scalar sent to Zabbix.

| Strategy | Behaviour |
|---|---|
| `last` | Value from the **last** matching line. Good for "most recent event" semantics. Default. |
| `first` | Value from the **first** matching line. Good for root-cause analysis. |
| `max` | Numerically **highest** value. Good for severity levels — always reports the worst event. Non-numeric values are skipped; falls back to `last` if none are numeric. |
| `min` | Numerically **lowest** value. |

```yaml
result: max    # worst severity in the scan window wins
```
