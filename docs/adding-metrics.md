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
  params:
    mount: "/backup"
    mode: used_percent
```

> **Host name override:** The optional `host_name` field sends this metric to Zabbix under a different host than the global default. See [configuration.md — Metric-level `host_name`](configuration.md#metric-level-host_name) for details and the full priority chain.

> **Metric scheduling:** The four optional scheduling fields (`time_window_from`, `time_window_till`, `max_executions_per_day`, `run_frequency`) control when and how often a metric is collected. All are inactive when absent and are bypassed by `--dry-run`. See [configuration.md — Metric scheduling fields](configuration.md#metric-scheduling-fields) for the full reference.

See [configuration.md](configuration.md) for all common fields, and the individual collector docs for the `params` each collector accepts:

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

### 3. Import the module in `collector_registry.py`

Open `src/zabbig_client/collector_registry.py` and add the import inside `_ensure_collectors_imported()`:

```python
def _ensure_collectors_imported() -> None:
    from .collectors import cpu, memory, disk, service, network, log
    from .collectors import my_collector  # add this line
```

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
