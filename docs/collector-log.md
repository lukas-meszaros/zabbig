# Log Collector

Monitors application log files by scanning for matching lines and returning derived values. Supports incremental scanning with offset tracking (`condition` mode) and full-file line counting (`count` mode).

---

## Key Behaviours

**Memory safety:** files are opened in binary mode and scanned line-by-line after seeking to the stored byte offset. The full file is never loaded into memory. Cost in `condition` mode is proportional only to new bytes added since the last run.

**Rotation and truncation detection:** on each run the collector compares the current inode and file size to stored values. An inode mismatch (new file after rotation) or a smaller file size (in-place truncation via `copytruncate`) both reset the offset to 0, ensuring no lines are missed and no lines are double-counted.

**Partial line safety:** if the last byte in the file is not a newline (a line is currently being written), the offset is left at the start of that line so it is re-read in full on the next run.

---

## Params

| Param | Required | Description |
|---|---|---|
| `path` | yes | Path to the log file. The **filename portion only** may be a Python regex. The directory is always a literal path. When multiple files match, the most recently modified one is used. |
| `match` | yes | Python regex applied to every line. Lines that do not match are skipped entirely before any condition evaluation. This is the primary performance filter — make it as specific as possible. |
| `mode` | no | `condition` (default) or `count` |
| `encoding` | no | File character encoding. Default: `utf-8` |
| `result` | no | `last` (default) / `first` / `max` / `min` — how to reduce multiple per-line values into a single result. Applies to `condition` mode only. |
| `default_value` | no | Value sent to Zabbix when no line in the scan window matched `match`. Default: `0` |
| `conditions` | required for `condition` mode | Ordered list of condition entries. The first matching entry provides the value for that line. |
| `state_dir` | no | Override the state directory for this metric. Defaults to `state.directory` from `client.yaml`. |

---

## Modes

### `condition` mode (default)

Scans only the new bytes appended since the last run (incremental, offset-tracked). For each line that passes `match`, evaluates the `conditions` list and produces a value. The `result` strategy reduces all per-line values to a single scalar sent to Zabbix.

State is stored in `<state_dir>/log_<metric_id>.json` across runs.

### `count` mode

Scans the **entire file** from byte 0 on every run and returns the total number of lines that match `match`. No state file is used. Suitable for cumulative error totals where you want a monotonically increasing counter. Configure the Zabbix item with **Delta** preprocessing to get a rate-per-interval graph.

> **Cost warning:** `count` mode reads the whole file on every run. Avoid it on files larger than ~100 MB with short collection intervals.

---

## `result` Strategies (condition mode)

| Strategy | Behaviour |
|---|---|
| `last` | Returns the value from the **last** matching line in the scan window. Good for "latest event" semantics. |
| `first` | Returns the value from the **first** matching line. Good for "root cause" scenarios where the first error is most relevant. |
| `max` | Returns the **highest** numeric value. Good for severity levels — always reports the worst event in the window. Non-numeric values are skipped. |
| `min` | Returns the **lowest** numeric value. |

---

## Condition Entry Forms

Each entry in `conditions` is evaluated against every line that passed `match`. Evaluation stops at the first matching entry.

### Form 1 — fixed value on regex match

```yaml
- when: "ERROR|FATAL"
  value: 2
```

`when` is a Python regex. If it matches anywhere in the line, `value` is returned for that line.

### Form 2 — numeric extraction with comparison

```yaml
- extract: 'duration_ms=(\d+(?:\.\d+)?)'
  compare: gt        # gt | lt | gte | lte | eq
  threshold: 1000
  value: "$1"        # "$1" returns the captured number; or use a fixed literal
```

`extract` must contain exactly one capture group `()`. The captured text is cast to `float` and compared against `threshold`. If the comparison passes, `value` is returned. Use `"$1"` to return the extracted number itself, or a literal to map it to a severity level.

### Form 3 — catch-all

```yaml
- value: 0
```

No `when` or `extract` — matches any line that passed `match` but was not matched by an earlier condition. Place this last.

> `when` and `extract` are mutually exclusive in the same entry.

---

## Per-condition `host_name`

Any condition entry can include an optional `host_name` field. When a line matches that condition, the resulting metric value is sent to Zabbix under the override host name instead of the metric-level or global host.

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
        host_name: "app-server-critical"   # this condition routes to a different host
      - when: "ERROR"
        value: 2
        host_name: "app-server-errors"
      - when: "WARN"
        value: 1
        # no host_name — uses metric-level "app-server"
      - value: 0
```

**Priority chain:** condition `host_name` → metric `host_name` → `zabbix.host_name` in `client.yaml`

---

## Scenarios

### Simplest: return 1 when any ERROR appears, 0 when clean

```yaml
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
      - value: 1    # catch-all: any line matching 'ERROR' → 1
```

---

### Severity level: worst event in the scan window

`result: max` ensures the highest severity code wins when multiple events occur between runs. If the window contains both a WARN and an ERROR, Zabbix receives `2`.

```yaml
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
    result: max
    default_value: 0
    conditions:
      - when: "FATAL|OutOfMemory"
        value: 3
      - when: "ERROR"
        value: 2
      - when: "WARN"
        value: 1
      - value: 0
```

---

### Numeric extraction: max response time in the scan window

Returns the actual millisecond value rather than a severity bucket.

```yaml
- id: log_api_response_time_max
  collector: log
  key: app.log.api.response_time_max_ms
  value_type: float
  unit: "ms"
  params:
    path: "/var/log/myapp/access.log"
    match: "response_time="
    mode: condition
    result: max
    default_value: 0
    conditions:
      - extract: 'response_time=(\d+(?:\.\d+)?)'
        compare: gt
        threshold: 0        # always passes — captures any positive value
        value: "$1"         # return the actual number
```

---

### Response time with severity bucketing

Returns a severity level instead of a raw time value. Useful when you want a single Zabbix trigger threshold rather than a graduated alert.

```yaml
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
        value: 3           # critical: > 5 s
      - extract: 'response_time=(\d+)'
        compare: gt
        threshold: 1000
        value: 2           # slow: > 1 s
      - extract: 'response_time=(\d+)'
        compare: gt
        threshold: 0
        value: 1           # acceptable: > 0
      - value: 0
```

---

### Cumulative error count (count mode)

Returns the total number of matching lines in the file. Configure the Zabbix item with **Delta per second** preprocessing to graph the error rate over time.

```yaml
- id: log_app_error_total
  collector: log
  key: app.log.error.total
  value_type: int
  timeout_seconds: 60
  params:
    path: "/var/log/myapp/app.log"
    match: "ERROR|FATAL"
    mode: count
```

---

### Rotating log file — filename is a regex

The date-stamped filename is matched by the regex. The most recently modified matching file is always used.

```yaml
- id: log_app_daily_errors
  collector: log
  key: app.log.daily.errors
  value_type: int
  params:
    path: '/var/log/myapp/app-\d{8}\.log'
    match: "ERROR"
    mode: count
```

---

### First occurrence mode — root cause analysis

When you want the first type of error in the window (typically the root cause rather than its cascading effects).

```yaml
- id: log_app_first_error
  collector: log
  key: app.log.first_error_code
  value_type: int
  params:
    path: "/var/log/myapp/app.log"
    match: "ERROR"
    mode: condition
    result: first
    default_value: 0
    conditions:
      - when: "ConnectionRefused"
        value: 10
      - when: "Timeout"
        value: 20
      - when: "OutOfMemory"
        value: 30
      - value: 99    # unknown error type
```

---

### HTTP 5xx detection in an nginx access log

```yaml
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

### Payment API call counter

Counts POST requests to a specific endpoint since the last run.

```yaml
- id: log_payment_api_calls
  collector: log
  key: app.log.payment.calls
  value_type: int
  params:
    path: "/var/log/myapp/access.log"
    match: 'POST /api/v1/payment'
    mode: count
```

---

## Metric Scheduling

Every log metric supports four optional scheduling fields that control when and how often the metric is collected. All four are inactive when absent.

```yaml
- id: log_errors_biz
  collector: log
  key: app.log.errors.biz
  value_type: int
  time_window_from: "0800"         # only monitor during business hours
  time_window_till: "1800"
  max_executions_per_day: 48
  run_frequency: 2                 # every other invocation
  params:
    path: "/var/log/myapp/app.log"
    match: "ERROR"
    mode: count
```

See [configuration.md](configuration.md#metric-scheduling-fields) for the full field reference, value rules, and evaluation order.
