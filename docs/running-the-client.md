# Running the Client

`run.py` is the single entry point for the zabbig monitoring client. It loads configuration, runs all enabled collectors, and sends the results to Zabbix via the Zabbix Trapper protocol.

---

## Basic Usage

```bash
python3 run.py [options]
```

Default paths for both config files are resolved relative to the location of `run.py`, so `run.py` can be invoked from any working directory:

```bash
# From inside zabbig_client/
python3 run.py

# From anywhere
python3 /path/to/zabbig_client/run.py
```

---

## Options

| Option | Default | Description |
|---|---|---|
| `--config PATH` | `client.yaml` | Path to `client.yaml`. See [configuration-client.yaml.md](configuration-client.yaml.md). |
| `--metrics PATH` | `metrics.yaml` | Path to `metrics.yaml`. See [configuration-metrics.yaml.md](configuration-metrics.yaml.md) and the collector docs. |
| `--dry-run` | off | Collect all metrics but do not connect to or send anything to Zabbix. Useful for testing new metric definitions. |
| `--log-level LEVEL` | from `client.yaml` | Override `logging.level`. Choices: `DEBUG` `INFO` `WARNING` `ERROR`. |
| `--validate` | off | Check `metrics.yaml` for structural and value errors without running any collectors or connecting to Zabbix. Does **not** require `--config`. |
| `--output PATH` | off | Write all collected values to a file after collection. Format controlled by `--output-format`. |
| `--output-format` | `json` | Format for `--output`. Choices: `json` \| `csv` \| `table`. |

### `--config`

```bash
python3 run.py --config /etc/zabbig/client.yaml
python3 run.py --config client.docker.yaml   # Docker variant
```

### `--metrics`

```bash
python3 run.py --metrics /etc/zabbig/metrics.yaml
python3 run.py --metrics metrics-staging.yaml
```

### `--dry-run`

Runs every enabled collector and prints the values that would be sent, but makes no connection to Zabbix. Scheduling constraints are ignored — every enabled metric is collected regardless of `time_window_from`, `time_window_till`, `max_executions_per_day`, or `run_frequency`.

```bash
python3 run.py --dry-run
python3 run.py --dry-run --metrics metrics-new.yaml
```

### `--log-level`

Overrides `logging.level` in `client.yaml` for this invocation only. Useful for debugging without editing the config file.

```bash
python3 run.py --log-level DEBUG
```

### `--validate`

Parses and validates `metrics.yaml` (or the path given by `--metrics`) and reports all detected issues in a single pass. Does not run collectors, does not load `client.yaml`, does not contact Zabbix.

```bash
python3 run.py --validate
python3 run.py --validate --metrics /path/to/metrics.yaml
```

Output example for a file with issues:

```
Validating: metrics.yaml

Metrics parsed (3):
  cpu_util    cpu     host.cpu.util
  mem_used    memory  host.memory.used_percent
  bad_metric  cpu     host.cpu.bad

Issues found (1):
  [1] Metric 'bad_metric': time_window_from='2599' has invalid minutes (99)

Validation complete: 3 metric(s) parsed, 1 issue(s) found.
```

### `--output` / `--output-format`

Dump all collected metric values to a file after the run completes. Only _sendable_ results (`status=ok` or `status=fallback`) are written.

```bash
# Default JSON format
python3 run.py --output /tmp/metrics.json

# CSV (for spreadsheets / awk)
python3 run.py --output /tmp/metrics.csv --output-format csv

# Human-readable table (for quick inspection)
python3 run.py --dry-run --output /tmp/metrics.txt --output-format table
```

Combine with `--dry-run` for a fast inventory of what the client would send:

```bash
python3 run.py --dry-run --output /tmp/preview.json
```

---

## Exit Codes

### Normal run

| Code | Meaning |
|---|---|
| `0` | All metrics collected and sent successfully |
| `1` | Partial failure — some collectors or sends failed |
| `2` | Fatal error — config file invalid, lock file conflict, overall timeout hit |

### `--validate`

| Code | Meaning |
|---|---|
| `0` | File is valid — no issues found |
| `1` | File parsed but one or more issues were found |
| `2` | File not found or YAML syntax error |

---

## Running from Cron

The most common deployment is a cron job that fires every 1–5 minutes. `run.py` acquires a lock file on startup so overlapping invocations are harmlessly rejected rather than doubling data.

```cron
# Run every minute, log output to file
* * * * * cd /home/user/zabbig_client && python3 run.py --config client.yaml >> /var/log/zabbig/client.log 2>&1

# Run every 5 minutes
*/5 * * * * cd /home/user/zabbig_client && python3 run.py --config client.yaml >> /var/log/zabbig/client.log 2>&1
```

---

## Performance Tuning

For cron-based deployments — especially where a hard process-kill limit applies — these are the most impactful settings. Full details in [configuration-performance.md](configuration-performance.md).

### Python interpreter flags (`start.sh`)

| Flag | Effect |
|---|---|
| `-s` | Skip user site-packages scan — saves a filesystem stat on every invocation |
| `-O` | Strip `assert` statements and set `__debug__ = False` — small memory saving |
| `PYTHONPATH` | Pre-set in the shell so the `sys.path.insert` in `run.py` is a no-op |

These are already included in the `start.sh` wrapper shipped with the client (see [Creating a `start.sh` Wrapper](#creating-a-startsh-wrapper)).

### `client.yaml` — key performance parameters

| Parameter | Default | Recommendation |
|---|---|---|
| `runtime.overall_timeout_seconds` | `240` | Set to `(cron_interval − 10)` or `(admin_kill_limit − 10)`, whichever is smaller. Ensures a clean finish before any hard kill. |
| `runtime.max_concurrency` | `8` | Reduce to `4` on constrained hosts; increase on hosts with many metrics and a strong CPU. |
| `batching.batch_collection_window_seconds` | `60` | Must be ≤ `overall_timeout_seconds`. Set to at least the slowest collector's `timeout_seconds`. |
| `zabbix.connect_timeout_seconds` | `10` | Reduce to `3–5` on a reliable LAN to fail fast if the Zabbix server is unreachable. |
| `batching.flush_immediate_separately` | `true` | Set to `false` if none of your metrics use `delivery: immediate`, to save a second send call. |

### `metrics.yaml` — reducing work per invocation

| Field | Where | Effect |
|---|---|---|
| `enabled: false` | per metric | Metric is skipped entirely; its collector module is not imported. |
| `run_frequency: N` | per metric | Collect only on every Nth cron invocation. `run_frequency: 3` on a 5-min cron = every 15 min. |
| `max_executions_per_day: N` | per metric | Hard cap on daily collections regardless of how often cron fires. |
| `time_window_from/till` | per metric | Restrict collection to a time-of-day window. |
| `check_mode: process` | service metrics | Avoids a `subprocess` + `systemctl` fork; scans `/proc` instead. Faster and lighter. |
| `delivery: batch` | per metric | Default. Use `immediate` only for genuinely time-sensitive checks; each `immediate` metric causes an extra send call. |

### Lazy module loading (automatic)

The client only imports the Python modules needed by collectors that are actually scheduled in a given run. If no database metrics are scheduled, `pg8000`, `pyaes`, and `db_loader` are never imported. If no probe metrics are scheduled, `requests` and the SSL context are never loaded. No configuration is required.

---

## Creating a `start.sh` Wrapper

A small wrapper script lets you invoke the client without specifying the Python path or the location of `run.py` each time. It is also the recommended pattern when using an embedded (standalone) Python.

The wrapper below includes three startup optimisations (see [configuration-performance.md](configuration-performance.md) for details):

```bash
cat > start.sh << 'EOF'
#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$DIR/python/bin/python3" -s -O "$DIR/run.py" "$@"
EOF
chmod +x start.sh
```

| Flag | Effect |
|---|---|
| `-s` | Skip user site-packages scan — saves a filesystem stat on every run |
| `-O` | Remove `assert` statements, set `__debug__ = False` — small memory and parse saving |
| `PYTHONPATH` | Pre-set so the `sys.path.insert` in `run.py` becomes a no-op |

`$@` forwards all arguments, so every `run.py` option works unchanged:

```bash
./start.sh                          # normal run with default config
./start.sh --dry-run                # dry-run
./start.sh --validate               # validate metrics.yaml
./start.sh --config /etc/zabbig/client.yaml --log-level DEBUG
```

Using the system Python instead:

```bash
cat > start.sh << 'EOF'
#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -s -O "$DIR/run.py" "$@"
EOF
chmod +x start.sh
```

Cron with `start.sh`:

```cron
* * * * * /home/user/zabbig_client/start.sh >> /var/log/zabbig/client.log 2>&1
```

---

## Using an Embedded Python

On servers where Python is absent or too old, you can ship a self-contained Python binary alongside the client. See [embedded-python.md](embedded-python.md) for the full download and setup instructions.

Once the embedded Python is in place at `python/bin/python3`, the wrapper above picks it up automatically:

```bash
./python/bin/python3 run.py --dry-run    # direct invocation
./start.sh --dry-run                     # via wrapper (same thing)
```

---

## Running Inside Docker

When running inside the `zabbig-client` container, `exec` into it and invoke `run.py` with the Docker-specific config:

```bash
# One-off run
docker exec zabbig-client python3 run.py --config client.docker.yaml

# Dry-run (useful for testing new metrics)
docker exec zabbig-client python3 run.py --config client.docker.yaml --dry-run

# Validate metrics.yaml (no config needed)
docker exec zabbig-client python3 run.py --validate
```

See [client-setup.md](client-setup.md) for full Docker setup instructions.
