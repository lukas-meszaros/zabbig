# Adding Metrics and Collectors

---

## Adding a New Metric

No code changes are needed to add a metric for an existing collector. Edit `metrics.yaml`, then re-provision.

### 1. Add the entry to `metrics.yaml`

```yaml
- id: disk_backup_used_percent
  enabled: true
  collector: disk
  key: host.disk.backup.used_percent
  value_type: float
  unit: "%"
  delivery: batch
  error_policy: skip
  # host_name: "remote-server-01"   # optional: override zabbix.host_name for this metric only
  # time_window_from: "0800"        # optional: only collect from 08:00
  # time_window_till: "2200"        # optional: stop collecting at 22:00
  # max_executions_per_day: 10      # optional: cap daily execution count
  # run_frequency: 2                # optional: every 2nd invocation (or "even"/"odd")
  # cache_seconds: 300              # optional: skip re-collection if value is < 5 min old
  params:
    mount: "/backup"
    mode: used_percent
```

> **Host name override:** The optional `host_name` field sends this metric to Zabbix under a different host than the global default. See [configuration-metrics.yaml.md — `host_name`](configuration-metrics.yaml.md#host_name) for details and the full priority chain.

---

## Splitting Metrics Across Multiple Files

For large deployments it is useful to split metrics into separate files organised by service or team — similar to `conf.d` / `profile.d` conventions.

Add an `include:` key at the top level of `metrics.yaml`:

```yaml
version: 1

include:
  - metrics.d/*.yaml           # loads all .yaml files in metrics.d/ (sorted)
  - /etc/zabbig/extras/*.yaml  # absolute paths are also accepted

defaults:
  delivery: batch
  timeout_seconds: 10

metrics:
  # Base metrics defined here ...
```

### Included file format

Included files support:

| Key | Supported |
|---|---|
| `metrics:` | ✓ Full metric list, same syntax |
| `defaults:` | ✓ Scoped to this file only — override main file's `defaults` |
| `collector_defaults:` | ✗ Define in main file only |
| `include:` | ✗ No recursive includes |

Example `metrics.d/postgres.yaml`:

```yaml
defaults:
  timeout_seconds: 15       # override global timeout for all metrics in this file

metrics:
  - id: pg_connections
    collector: database
    key: pg.connections.active
    value_type: int
    params:
      database: prod_pg
      sql: "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"

  - id: pg_replication_lag
    collector: database
    key: pg.replication.lag_seconds
    value_type: float
    cache_seconds: 30
    params:
      database: prod_pg
      sql: "SELECT EXTRACT(epoch FROM now() - pg_last_xact_replay_timestamp())"
```

### Rules

- Non-matching patterns warn but do not abort the run.
- Duplicate `id` or Zabbix `key` across any files is a validation error when `strict_config_validation: true` (the default).
- File order within a glob is sorted alphabetically.
- The `metrics.d/example.yaml` file shipped with the client is fully commented out and can be used as a starting template.

> **Metric scheduling:** The four optional scheduling fields (`time_window_from`, `time_window_till`, `max_executions_per_day`, `run_frequency`) control when and how often a metric is collected. All are inactive when absent and are bypassed by `--dry-run`. See [configuration-metrics.yaml.md — Scheduling fields](configuration-metrics.yaml.md#scheduling-fields) for the full reference.

See [configuration-metrics.yaml.md](configuration-metrics.yaml.md) for all common fields, and the individual collector docs for the `params` each collector accepts:

- [CPU](collector-cpu.md) — `mode`, `proc_root`
- [Memory](collector-memory.md) — `mode`, `proc_root`
- [Disk](collector-disk.md) — `mount`, `mode`
- [Service](collector-service.md) — `check_mode`, `service_name`, `process_pattern`, `proc_root`
- [Network](collector-network.md) — `interface`, `mode`, `proc_root`
- [Log](collector-log.md) — `path`, `match`, `mode`, `conditions`, `result`, `default_value`
- [Probe](collector-probe.md) — `host`, `port`, `mode`, `timeout_seconds`, `conditions`, `result`

### 2. Validate the metrics file

```bash
python3 run.py --validate
# or with a custom path:
python3 run.py --validate --metrics /path/to/metrics.yaml
```

Checks the YAML structure and every field value (including the new scheduling fields) without running any collectors or connecting to Zabbix. All issues are reported in one pass — the command always completes even when multiple errors are present.

Exit codes: `0` = valid, `1` = issues found, `2` = file not found or YAML syntax error.

### 3. Verify with a dry-run

```bash
python3 run.py --dry-run
```

This runs all collectors without sending anything to Zabbix. Check that the new metric appears in the output with the expected value.

### 4. Provision the Zabbix item

```bash
# From inside the Docker container
docker exec zabbig-client bash -c "cd /app/../zabbix_update && python3 create_trapper_items.py --config /app/client.docker.yaml"

# Or from the host
cd zabbix_update && python3 create_trapper_items.py --config ../zabbig_client/client.yaml
```

`create_trapper_items.py` is idempotent — existing items are skipped, new ones are created.

### 5. Start a real run and verify in Zabbix

```bash
docker exec zabbig-client python3 run.py --config client.docker.yaml
```

Open **Monitoring → Latest data** in Zabbix, filter by host name, and confirm the new item has a recent value.

---

## Adding a New Collector

Adding a collector that does not exist yet requires code changes in three places.

### 1. Create the collector module

Create `src/zabbig_client/collectors/my_collector.py`:

```python
from ..collector_registry import register_collector
from ..models import MetricDef, MetricResult, RESULT_OK
from .base import BaseCollector
import asyncio
import time


@register_collector("my_collector")
class MyCollector(BaseCollector):
    async def collect(self, metric: MetricDef) -> MetricResult:
        t0 = time.monotonic()
        # Run blocking work in a thread pool so the event loop is not blocked
        value = await asyncio.to_thread(_do_work, metric.params)
        return MetricResult(
            metric_id=metric.id,
            key=metric.key,
            value=str(value),
            value_type=metric.value_type,
            timestamp=int(time.time()),
            collector="my_collector",
            delivery=metric.delivery,
            status=RESULT_OK,
            duration_ms=(time.monotonic() - t0) * 1000,
            host_name=metric.host_name,   # pass through the metric-level host_name override
        )


def _do_work(params: dict):
    # All blocking I/O or computation goes here — runs in a thread pool
    return 42
```

Key points:
- Decorate the class with `@register_collector("name")` — this name is used in `metrics.yaml`.
- The `collect` method is `async`. Use `asyncio.to_thread()` for any blocking work.
- Always return a `MetricResult`. On error, raise an exception — the runner catches it and applies `error_policy`.

### 2. Register the collector name in `models.py`

Open `src/zabbig_client/models.py` and add the new name to `VALID_COLLECTORS`:

```python
VALID_COLLECTORS = {"cpu", "memory", "disk", "service", "network", "log", "probe", "my_collector"}
```

### 3. Register the collector name in `collector_registry.py`

Open `src/zabbig_client/collector_registry.py` and add an entry to `_COLLECTOR_MODULE_MAP`:

```python
_COLLECTOR_MODULE_MAP: dict[str, str] = {
    "cpu":         "cpu",
    ...
    "my_collector": "my_collector",   # add this line
}
```

That is all. The runtime imports the module on demand — only when a metric using this collector is actually scheduled. The module does not need to be imported anywhere else.

> **Note:** `_ensure_collectors_imported()` still exists for tests and tooling that need the full registry pre-populated. Any new collector registered in `_COLLECTOR_MODULE_MAP` is automatically included; no changes to that function are required.

### 4. Use the collector in `metrics.yaml`

```yaml
- id: my_metric
  collector: my_collector
  key: host.my.metric
  value_type: int
  params:
    some_param: value
```

### 5. Write tests

Add `tests/test_my_collector.py`. Follow the pattern of the existing collector tests. Run:

```bash
docker exec zabbig-client python3 -m unittest discover -s tests -v
```

### 6. Provision Zabbix

Re-run `create_trapper_items.py` to create trapper items for any new metrics added in step 4.
