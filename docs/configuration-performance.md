# Performance & Resource Consumption

This document collects every performance-relevant setting, workflow, and internal
mechanism in one place. The goal is to help you tune zabbig for short-lived
cron invocations where startup time and server resource consumption matter.

---

## Table of contents

1. [Cron-mode constraints](#1-cron-mode-constraints)
2. [Startup time](#2-startup-time)
3. [Collector execution time](#3-collector-execution-time)
4. [Scheduling: run fewer collectors per invocation](#4-scheduling-run-fewer-collectors-per-invocation)
5. [Concurrency and timeouts](#5-concurrency-and-timeouts)
6. [Network: batching and sending](#6-network-batching-and-sending)
7. [Internal caches (automatic, no config needed)](#7-internal-caches-automatic-no-config-needed)
8. [Deployment environment](#8-deployment-environment)
9. [Recommended settings for a 5-minute cron](#9-recommended-settings-for-a-5-minute-cron)

---

## 1. Cron-mode constraints

zabbig is designed to run as a short-lived process invoked by a scheduler such
as cron. Each invocation starts fresh, collects metrics, sends them to Zabbix,
and exits. There is no daemon, no persistent in-memory state, and no background
thread.

Key implications:

- **Python startup cost is paid on every invocation.** Keep the number of
  imported modules small (see [§2](#2-startup-time)).
- **A hard wall-clock kill may arrive** if your sysadmin enforces a maximum
  process lifetime. Set `runtime.overall_timeout_seconds` comfortably below
  that limit so the client can finish cleanly before being killed.
- **Overlapping runs are prevented** by a PID lock file
  (`state/zabbig_client.lock`). If a previous invocation is still running when
  the next one starts, the second exits immediately with code 2. Size your
  `overall_timeout_seconds` to be well below the cron interval.

---

## 2. Startup time

### Lazy collector and library imports

The client only imports the Python modules (and their heavy dependencies) needed
for the collectors that are actually *scheduled* in a given invocation.
Collectors that are disabled, outside their time window, or skipped by
`run_frequency` do not cause their module or its dependencies to be loaded.

Two layers of laziness apply:

**Layer 1 — collector modules** (`load_collectors_for` in `collector_registry.py`):
Only the collector modules needed by the scheduled metrics are imported.

**Layer 2 — heavy libraries inside those modules**:

| Collector / module | Heavy dependency | When it is loaded |
|---|---|---|
| `probe` collector | `requests`, `urllib3`, SSL context | Only when a probe metric is scheduled |
| `database` collector + `db_loader` | `pg8000` (PostgreSQL driver), `pyaes` (decryption) | Only when a database metric is scheduled *and* a `databases.yaml` exists |
| `service` collector (systemd mode) | `subprocess` | Only when a service metric with `check_mode: systemd` is scheduled |
| `cpu`, `memory`, `disk`, `network` | stdlib only | Always fast, no heavy deps |
| `zabbix_utils` (`Sender`) | Zabbix sender protocol | Loaded once at send time, never at startup |

**Practical example:** on a run where only `cpu`, `memory`, and `disk` metrics
are scheduled — because all database metrics have `run_frequency: 12` and this
is run #3 — none of `requests`, `pg8000`, `pyaes`, or `ssl` are imported.

This happens automatically — no configuration is required.

### Keeping startup fast

- Set `run_frequency` on slow or heavy collectors so they only run every Nth
  invocation (see [§4](#4-scheduling-run-fewer-collectors-per-invocation)).
- Ensure the Python bytecode cache (`__pycache__/`) is writable. When it is not,
  Python recompiles every `.py` file on each run, adding 50–150 ms of startup
  overhead. See [§8](#8-deployment-environment).

---

## 3. Collector execution time

### Collectors with a built-in sleep

Two collectors read hardware counters twice with a deliberate pause to calculate
a rate:

| Collector | Mode | Built-in pause | `timeout_seconds` minimum |
|---|---|---|---|
| `cpu` | `percent` | 200 ms (<nobr>`/proc/stat` × 2</nobr>) | 2 s |
| `network` | `rx_bytes_per_sec`, `tx_bytes_per_sec` | 1 000 ms (<nobr>`/proc/net/dev` × 2</nobr>) | 3 s |

These sleeps run inside a thread pool (`asyncio.to_thread`), so they do not
block the event loop or delay other collectors.

### Choosing delivery mode

`delivery` in `metrics.yaml` controls when a metric is sent relative to the
batch window:

| Value | Behaviour | Best for |
|---|---|---|
| `batch` (default) | Collected within `batch_collection_window_seconds`; all sent together at the end. | Most metrics. |
| `immediate` | Sent as soon as the value is ready, before the batch window closes. | Time-sensitive checks (e.g. service up/down). |

Prefer `batch` unless a metric genuinely needs to arrive ahead of the rest.
Unnecessary `immediate` metrics create extra network round-trips.

### Per-metric timeout

```yaml
# metrics.yaml
- id: slow_query
  collector: database
  timeout_seconds: 20   # override the default (10 s)
```

`timeout_seconds` caps how long a single collector may run. A timed-out
collector produces no value; `error_policy` then applies. Set it high enough
that the collector can finish under normal load, and low enough that a hung
collector does not hold up the rest of the run.

---

## 4. Scheduling: run fewer collectors per invocation

These fields are set **per metric** in `metrics.yaml`. They reduce how often
a metric is collected, lowering CPU usage, I/O, and — for database or HTTP
probe metrics — external connection overhead.

### `run_frequency`

Controls which global invocation cycle includes this metric.

```yaml
- id: disk_usage
  run_frequency: 3   # collect only on every 3rd cron invocation
```

| Value | Runs on … |
|---|---|
| `0` or absent | Every invocation |
| `N` (integer ≥ 2) | 1st, (N+1)th, (2N+1)th, … invocations of the day |
| `"even"` | Even-numbered invocations (2nd, 4th, 6th, …) |
| `"odd"` | Odd-numbered invocations (1st, 3rd, 5th, …) |

The run counter is 1-based and resets automatically at midnight. State is kept
in `state/schedule.json`.

**Tip for 5-minute cron:** `run_frequency: 3` means the metric runs every
15 minutes. `run_frequency: 6` → every 30 minutes. `run_frequency: 12` → hourly.

### `max_executions_per_day`

Caps the total number of times the metric runs within a calendar day.

```yaml
- id: expensive_db_query
  max_executions_per_day: 48   # at most once every 30 min on a 5-min cron
```

Once the quota is reached the metric is skipped for the rest of the day.
Counter resets at midnight. State is kept in `state/schedule.json`.

### `time_window_from` / `time_window_till`

Restricts collection to a specific daily time window.

```yaml
- id: business_hours_check
  time_window_from: "0800"
  time_window_till: "1800"
```

Both fields must be set together. The value is a quoted 4-digit string
(`"HHMM"`) or a bare integer (`800`). When `from` > `till` the window wraps
past midnight (e.g. `"2200"` – `"0600"` = overnight window).

### Combining scheduling fields

All four scheduling constraints are evaluated independently. A metric runs only
when all applicable constraints pass. Example — a metric that:
- runs at most 4 times a day, only between 06:00 and 22:00, on every 3rd cycle:

```yaml
- id: network_throughput
  run_frequency: 3
  max_executions_per_day: 4
  time_window_from: "0600"
  time_window_till: "2200"
```

### Collector-level skipping via `enabled`

```yaml
- id: unused_metric
  enabled: false
```

Disabled metrics are skipped before scheduling is even evaluated. Their
collector module is not imported (see [§2](#2-startup-time)).

---

## 5. Concurrency and timeouts

All settings below are in `client.yaml` under the `runtime` section.

### `runtime.overall_timeout_seconds`

Hard wall-clock limit for the entire client run.

```yaml
runtime:
  overall_timeout_seconds: 110   # for a 2-minute admin kill limit
```

- Should always be **less than your cron interval** to prevent invocation
  overlap.
- Should be **less than any hard process-kill limit** imposed by your system
  administrator, so the client can complete and write its state files before
  being killed.
- When the overall timeout fires, the run exits with code 2, `schedule.json` is
  written, but results collected before the timeout are **not** sent.

**Rule of thumb:** set to `(cron_interval_seconds - 10)` for a comfortable
margin, and to `(admin_kill_seconds - 10)` if that is smaller.

### `runtime.max_concurrency`

Maximum number of collectors running simultaneously.

```yaml
runtime:
  max_concurrency: 8   # default
```

Higher values finish faster on systems with many metrics and a strong CPU, but
use more memory and generate more concurrent I/O. Lower values are safer on
constrained hosts. In practice, most collectors spend their time waiting for
I/O (reading `/proc`, making a TCP connection), so a value of 4–8 already
saturates most systems.

### `batching.batch_collection_window_seconds`

How long to wait for `batch`-mode collectors to finish before cancelling the
stragglers.

```yaml
batching:
  batch_collection_window_seconds: 60   # default
```

Collectors still running when this window closes are cancelled and recorded as
timed-out. Their `error_policy` applies. Set this to at least the slowest
expected batch collector's `timeout_seconds`.

### `zabbix.connect_timeout_seconds` and `zabbix.send_timeout_seconds`

TCP-level timeouts for the Zabbix connection itself.

```yaml
zabbix:
  connect_timeout_seconds: 10   # default
  send_timeout_seconds: 30      # default
```

Reduce `connect_timeout_seconds` on a reliable LAN (e.g. to `3`) to fail fast
if the Zabbix server is unreachable, rather than waiting 10 seconds.

---

## 6. Network: batching and sending

### `batching.batch_send_max_size`

Maximum number of `ItemValue` entries per Zabbix send call. Results larger than
this are automatically split and sent in parallel chunks.

```yaml
batching:
  batch_send_max_size: 250   # default
```

Zabbix has a practical limit per request. The default of 250 is safe for all
standard configurations. Only reduce this if your Zabbix proxy or server rejects
large payloads.

### `batching.flush_immediate_separately`

When `true` (default), `immediate`-delivery metrics are sent in a separate call
before batch metrics. When `false`, all metrics go in one combined call.

```yaml
batching:
  flush_immediate_separately: true   # default
```

Set to `false` if you have no `immediate` metrics — it removes the overhead of
a second send call per run.

### `batching.immediate_micro_batch_window_ms`

How long (in milliseconds) to wait for additional `immediate` metrics before
flushing. This groups several fast collectors into a single send call.

```yaml
batching:
  immediate_micro_batch_window_ms: 200   # default
```

Reduce to `0` if you have only one immediate metric and want it sent as fast as
possible. Increase to `500` if you have many immediate metrics and want to
group them more aggressively.

---

## 7. Internal caches (automatic, no config needed)

The following caches are maintained for the lifetime of a single process
invocation. They require no configuration.

### `/proc/*/cmdline` scan cache — service collector (process mode)

When `check_mode: process` is used, the first service metric in a run scans
`/proc/*/cmdline` and caches the result in memory. Subsequent service metrics
in the same run reuse the cache, so the filesystem scan runs only once per
invocation regardless of how many process-mode service metrics are defined.

### HTTP session cache — probe collector

One `requests.Session` is created per `(scheme, host, port)` combination and
reused across all HTTP probe metrics in the same invocation. This amortises TCP
connection setup and TLS handshake cost across multiple checks to the same host.

### Database connection cache — database collector

A single `pg8000` connection per named database is opened on the first query and
reused for all subsequent queries to the same database in the same run. All
connections are closed explicitly when collection finishes, before the send
phase begins.

---

## 8. Deployment environment

### Writable `__pycache__`

Python caches compiled bytecode in `__pycache__/` directories adjacent to each
`.py` file. If the directory is not writable by the cron user, Python falls back
to recompiling every source file on every invocation, adding 50–150 ms of
startup overhead.

**Check:**
```bash
ls -la /path/to/zabbig_client/src/zabbig_client/__pycache__/
```

**Fix** (run as root or the owner of the installation):
```bash
chmod -R 775 /path/to/zabbig_client/src/
```

Alternatively, set `PYTHONDONTWRITEBYTECODE=0` explicitly in the cron
environment to ensure bytecode writing is not globally suppressed.

### Avoid `PYTHONDONTWRITEBYTECODE=1` in the cron environment

Some system-wide shell profiles set `PYTHONDONTWRITEBYTECODE=1` to keep
installations clean. This disables bytecode caching and measurably slows down
every Python invocation. Check your cron user's environment:

```bash
env | grep PYTHONDONTWRITEBYTECODE
```

If it is set to `1`, unset it for the zabbig cron entry:

```cron
*/5 * * * * PYTHONDONTWRITEBYTECODE= /path/to/run.py --config ...
```

### `proc_root` for containerised deployments

If zabbig monitors the *host* from inside a container, bind-mount the host's
`/proc` and set:

```yaml
runtime:
  proc_root: "/host/proc"
```

This applies globally to all `/proc`-based collectors (`cpu`, `memory`,
`network`, `service/process`). Individual metrics can override it via
`params.proc_root`.

---

## 9. Recommended settings for a 5-minute cron

The table below gives concrete starting values for a host where the system
administrator enforces a 2-minute process lifetime.

### `client.yaml`

```yaml
runtime:
  overall_timeout_seconds: 110   # 10 s margin before the 2-min kill

  # Lower if you only have a few metrics and want to save threads.
  max_concurrency: 4

zabbix:
  connect_timeout_seconds: 5     # fail fast on unreachable server

batching:
  batch_collection_window_seconds: 90   # fits within overall_timeout
  flush_immediate_separately: false     # only if you have no immediate metrics
```

### `metrics.yaml` — per-metric adjustments

```yaml
defaults:
  timeout_seconds: 10

metrics:
  # CPU percent requires a 0.2 s sleep — give it headroom.
  - id: cpu_util
    collector: cpu
    timeout_seconds: 3

  # Network rate requires a 1 s sleep per metric.
  - id: net_rx
    collector: network
    timeout_seconds: 5
    run_frequency: 3    # every 15 min on a 5-min cron

  # Disk and memory are instantaneous reads — default timeout is fine.
  - id: disk_root
    collector: disk
    run_frequency: 6    # every 30 min

  # Service checks — use process mode to avoid a subprocess fork.
  - id: sshd_running
    collector: service
    params:
      check_mode: process
      process_pattern: "sshd"

  # Database queries — run infrequently; they open a real TCP connection.
  - id: db_row_count
    collector: database
    run_frequency: 12   # once per hour on a 5-min cron
    timeout_seconds: 15
```
