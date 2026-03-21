# pytest — Automated Test Suite

This document describes the automated test suite for the `zabbig` project,
covering every script in `zabbig_client/` and `zabbix_update/`.  It also
serves as a reference for GitHub Copilot when generating additional tests.

---

## Overview

| Item | Value |
|---|---|
| Test folder | `pytest/` (project root) |
| Python venv | `pytest-venv/` (project root — gitignored) |
| Framework | pytest 9.0+ with pytest-asyncio 1.3+ |
| Async mode | `asyncio_mode = auto` (no `@pytest.mark.asyncio` needed) |
| Run command | `pytest-venv/bin/pytest pytest/ -v` |

The suite contains **471 tests** across 19 files as of March 2026.

---

## Quick Start

### 1. Create the virtual environment

Run the setup script once from the project root:

```bash
bash pytest/setup-pytest-venv.sh
```

This creates `pytest-venv/` and installs `pytest` and `pytest-asyncio`.  
Re-running the script is safe — it skips venv creation if it already exists and upgrades packages.

### 2. Run all tests

```bash
pytest-venv/bin/pytest pytest/ -v
```

### 3. Run a single file or test

```bash
# One file
pytest-venv/bin/pytest pytest/test_collector_cpu.py -v

# One test class
pytest-venv/bin/pytest pytest/test_collector_cpu.py::TestCpuCollector -v

# One test method
pytest-venv/bin/pytest pytest/test_collector_cpu.py::TestCpuCollector::test_mode_uptime -v
```

### 4. Run tests matching a keyword

```bash
pytest-venv/bin/pytest pytest/ -k "disk or network" -v
```

---

## Directory Structure

```
pytest/
├── setup-pytest-venv.sh      # One-time venv bootstrap script
├── pytest.ini                # asyncio_mode = auto
├── conftest.py               # sys.path setup + shared fixtures
│
├── test_models.py            # MetricDef, MetricResult, all constants/dataclasses
├── test_config_loader.py     # load_client_config, load_metrics_config
├── test_collector_registry.py
├── test_locking.py
├── test_state_manager.py
├── test_logging_setup.py
├── test_result_router.py
├── test_runner.py            # run_all_collectors, error policies, timeout
│
├── test_collector_cpu.py
├── test_collector_memory.py
├── test_collector_disk.py
├── test_collector_service.py
├── test_collector_network.py
├── test_collector_log.py
├── test_collector_probe.py
│
├── test_zabbix_common.py         # ZabbixAPI, load_yaml, load_metrics, credentials
├── test_zabbix_item_builders.py  # _build_item_defs, self_mon, additional_items
├── test_zabbix_trigger_builder.py
└── test_zabbix_dashboard_builder.py
```

---

## conftest.py — Fixtures and Path Setup

`pytest/conftest.py` does two things:

### sys.path configuration

Four paths are inserted so all project modules are importable without installation:

| Variable | Path | Purpose |
|---|---|---|
| `_CLIENT_SRC` | `zabbig_client/src` | `zabbig_client`, `zabbix_utils`, vendored `yaml`/`requests` |
| `_CLIENT_DIR` | `zabbig_client/` | Fallback / package root |
| `_PYTEST_DIR` | `pytest/` | Makes conftest importable by test files |
| `_ZABBIX_UPDATE` | `zabbix_update/` | `_common`, `create_*` scripts |

### Shared fixtures and helpers

```python
# Helper functions — call directly in tests, not via fixture injection
make_metric(id, collector, key, delivery, timeout_seconds, error_policy,
            value_type, params, fallback_value, enabled) -> MetricDef

make_result(metric_id, key, value, status, delivery, ...) -> MetricResult

# Fixtures — inject via function argument matching the name
def test_something(minimal_metric, minimal_result): ...
```

`minimal_metric` is a `MetricDef` with collector=`cpu`, key=`host.cpu`, delivery=`batch`.  
`minimal_result` is a `MetricResult` with status=`ok`, value=`"1.0"`.

---

## Test Patterns

### Testing a collector

Each collector test file follows the same two-class layout:

```python
class TestCollectorHelpers:
    """Unit tests for the module-level helper functions."""
    def test_some_helper(self, tmp_path): ...

class TestCollectorClass:
    """Integration tests for the async collect() method."""
    async def test_mode_x(self): ...        # async is fine — asyncio_mode=auto
    async def test_unknown_mode_raises(self): ...
    async def test_result_fields(self): ...
```

### Mocking /proc files

Use `tmp_path` to write fake proc files, then pass the directory as `proc_root` via `params`:

```python
def test_read_something(self, tmp_path):
    (tmp_path / "loadavg").write_text("0.5 1.0 1.5 1/100 1234\n")
    value = _load_avg(str(tmp_path / "loadavg"), "load1")
    assert value == 0.5

async def test_collector_with_proc(self, tmp_path):
    net_dir = tmp_path / "net"
    net_dir.mkdir()
    (net_dir / "dev").write_text(NET_DEV_CONTENT)
    metric = make_metric(
        collector="network", key="host.net.rx",
        params={"interface": "eth0", "mode": "rx_bytes", "proc_root": str(tmp_path)},
    )
    result = await NetworkCollector().collect(metric)
    assert result.status == RESULT_OK
```

### Mocking the runner's collector instantiation

The runner calls `cls = get_collector(name)` then `instance = cls()` (synchronous),
then `await instance.collect(metric)`.  Use `MagicMock` for the class and
`AsyncMock` for the `collect` method:

```python
from unittest.mock import AsyncMock, MagicMock, patch

with patch("zabbig_client.runner.get_collector") as mock_get:
    mock_cls = MagicMock()                          # sync instantiation
    mock_cls.return_value.collect = AsyncMock(      # async collect()
        return_value=make_result("m1", "host.cpu", "42.0")
    )
    mock_get.return_value = mock_cls
    immediate, batch = await run_all_collectors([metric], cfg)
```

### Mocking HTTP (probe / ZabbixAPI)

```python
from unittest.mock import patch, MagicMock

def _make_http_response(status_code=200, body=b"OK"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.encoding = "utf-8"
    resp.raw.read.return_value = body
    return resp

with patch("requests.request", return_value=_make_http_response(200)):
    results = _run_http_probe(metric)
```

For `ZabbixAPI._call`, patch the session's `post` method on an API instance:

```python
api = ZabbixAPI("http://test/api_jsonrpc.php")
resp = MagicMock()
resp.status_code = 200
resp.raise_for_status = MagicMock()
resp.json.return_value = {"jsonrpc": "2.0", "result": "token123", "id": 1}
with patch.object(api._session, "post", return_value=resp):
    api.login("Admin", "zabbix")
assert api.auth == "token123"
```

### Testing zabbix_update builder functions

Builder functions in `create_trapper_items.py`, `create_template.py`,
`create_triggers.py`, and `create_dashboard.py` are pure functions — no
mocking required:

```python
import create_trapper_items as mod

metrics = [{"id": "cpu", "key": "host.cpu", "value_type": "float"}]
tpl_data = {
    "item_defaults": {"history": "7d", "trends": "365d"},
    "items": [{"key": "host.cpu", "name": "CPU Usage"}],
}
defs = mod._build_item_defs(metrics, tpl_data)
assert defs[0]["name"] == "CPU Usage"
assert defs[0]["value_type"] == 0   # VT_FLOAT
```

---

## Test File Reference

### `test_models.py`

Tests all constants and dataclasses from `zabbig_client/models.py`.

**Key imports:** `zabbig_client.models`  
**Notable coverage:**
- `VALID_COLLECTORS`, `VALID_DELIVERY`, `VALID_ERROR_POLICIES`, `VALID_VALUE_TYPES`
- `ZabbixConfig`, `RuntimeConfig`, `BatchingConfig`, `LoggingConfig`, `FeaturesConfig`, `ClientConfig`
- `MetricDef` construction and validation
- `MetricResult.is_sendable()`, `MetricResult.make_timeout()`, `MetricResult.make_error()`, `MetricResult.make_fallback()`
- `RunSummary` field counting

---

### `test_config_loader.py`

Tests `load_client_config` and `load_metrics_config` from `zabbig_client/config_loader.py`.

**Key imports:** `zabbig_client.config_loader`  
**Notable coverage:**
- Empty/minimal YAML → all defaults applied
- Each config section (`zabbix`, `runtime`, `batching`, `logging`, `features`)
- Invalid values raise `ValueError` (bad port, bad log level, unknown collector with `unknown_collector_strict: true`)
- Per-metric param validation: `disk` requires `mount`, `service` requires `service_name`, `network` requires `mode`, `log` requires `path` and `match`, `probe` requires `mode` + `url`/`host`/`port`
- `collector_defaults` inheritance (metric-level params override defaults)
- `enabled: false` metrics excluded from strict-unknown check

---

### `test_collector_registry.py`

Tests `collector_registry.py`.

**Key imports:** `zabbig_client.collector_registry`  
**Notable coverage:**
- All 7 collectors (`cpu`, `memory`, `disk`, `service`, `network`, `log`, `probe`) are registered
- `get_collector("unknown")` raises `KeyError` with message `"No collector registered for …"`
- Dynamic `register_collector` / `get_collector` round-trip
- All registered classes are `BaseCollector` subclasses with an async `collect` method

---

### `test_locking.py`

Tests `locking.py` (`RunLock`).

**Key imports:** `zabbig_client.locking`  
**Notable coverage:**
- `acquire()` writes PID to lock file
- Double acquire raises `LockError`
- Stale lock (dead PID) is cleared and re-acquired
- Context manager releases on normal exit and on exception
- Corrupt stale lock file is handled gracefully
- `release()` is idempotent

---

### `test_state_manager.py`

Tests `state_manager.py`.

**Key imports:** `zabbig_client.state_manager`  
**Notable coverage:**
- `save_state` creates file and persists all fields
- `STATE_ENABLED = False` makes both save and load no-ops
- `consecutive_failures` increments and resets correctly
- Missing / corrupt state file returns empty dict

---

### `test_logging_setup.py`

Tests `logging_setup.py`.

**Key imports:** `zabbig_client.logging_setup`  
**Notable coverage:**
- `format=text` produces a `StreamHandler`; `format=json` produces `_JsonFormatter`
- `log_file` adds a `FileHandler`
- `console=false` suppresses the stream handler
- Second call replaces handlers (no duplication)
- `_JsonFormatter` emits valid JSON with `level`, `message`, `time` fields

---

### `test_result_router.py`

Tests `result_router.route()`.

**Key imports:** `zabbig_client.result_router`  
**Notable coverage:**
- `delivery=batch` → placed in batch list
- `delivery=immediate` → placed in immediate list
- `status=failed`, `timeout`, `skipped` → dropped (not sent)
- `status=fallback` with a value → sendable, routed by delivery
- `value=None` → dropped regardless of status

---

### `test_runner.py`

Tests `run_all_collectors`, `_apply_error_policy`, and `update_summary` from `runner.py`.

**Key imports:** `zabbig_client.runner`  
**Notable coverage:**
- `_apply_error_policy`: `skip` → `RESULT_SKIPPED`, `mark_failed` → `RESULT_FAILED`, `fallback` with/without value
- `update_summary`: counts ok/failed/timeout/skipped correctly
- `run_all_collectors`: batch vs immediate placement, exception → skipped, timeout applied, probe list → flattened to individual results, concurrency limit respected
- Collector mock pattern: `MagicMock` for class, `AsyncMock` for `collect`

---

### `test_collector_cpu.py`

**Key imports:** `zabbig_client.collectors.cpu`  
**Mocking strategy:** Write fake `/proc/stat`, `/proc/uptime`, `/proc/loadavg` to `tmp_path`; pass path via `proc_root` param or direct helper call.  
**Modes covered:** `uptime`, `load1`, `load5`, `load15`, `percent` (default), unknown raises

---

### `test_collector_memory.py`

**Key imports:** `zabbig_client.collectors.memory`  
**Mocking strategy:** Write fake `/proc/meminfo` to `tmp_path`; pass path directly to helpers.  
**Modes covered:** `used_percent`, `available_bytes`, `swap_used_percent` (default=`used_percent`), no-swap returns 0, unknown raises

---

### `test_collector_disk.py`

**Key imports:** `zabbig_client.collectors.disk`  
**Mocking strategy:** `unittest.mock.patch("os.statvfs", return_value=mock_statvfs(...))`  
**Modes covered:** `used_percent`, `used_bytes`, `free_bytes`, `inodes_used_percent`, `inodes_used`, `inodes_free`, `inodes_total` (default=`used_percent`), zero-total edge cases, unknown raises

---

### `test_collector_service.py`

**Key imports:** `zabbig_client.collectors.service`  
**Mocking strategy:**
- `systemd` mode: `patch("subprocess.run", return_value=MagicMock(returncode=0))`
- `process` mode: write fake `/proc/<pid>/cmdline` files (NUL-separated) to `tmp_path`  

**Check modes covered:** `systemd` (active/inactive/timeout/not-found), `process` (match/no-match/permission-error), default=`systemd`, unknown raises

---

### `test_collector_network.py`

**Key imports:** `zabbig_client.collectors.network`  
**Mocking strategy:** Write fake `/proc/net/dev` and `/proc/net/sockstat` to `tmp_path`; pass `proc_root=str(tmp_path)` via params.  
**Modes covered:** All 8 counter modes, 2 rate modes (`rx_bytes_per_sec`, `tx_bytes_per_sec`), 4 sockstat modes, `interface=total` sums non-loopback, missing interface raises, unknown mode raises

---

### `test_collector_log.py`

**Key imports:** `zabbig_client.collectors.log`  
**Mocking strategy:** Write real log files to `tmp_path`; use `state_dir=str(tmp_path / "state")` to isolate state.  
**Coverage:**
- `_resolve_path`: exact, regex basename, most-recent, missing dir/file, invalid regex
- `_load_state` / `_save_state`: round-trip, missing file, corrupt JSON
- `_eval_one_condition`: `when` match/no-match, `extract` with `gt/lt/gte/lte/eq`, `$1` capture, catch-all
- `_resolve_result`: `first`, `last`, `max`, `min`, non-numeric fallback, unknown strategy raises
- `_log_count`: count all / filtered / empty file
- `_log_condition`: incremental offset, appended lines detected, rotation resets offset
- Modes: `condition` (default), `count`, unknown raises

---

### `test_collector_probe.py`

**Key imports:** `zabbig_client.collectors.probe`  
**Mocking strategy:**
- TCP: `patch("socket.create_connection", ...)`
- HTTP: `patch("requests.request", return_value=_make_fake_response(...))`
- SSL: `patch("ssl.create_default_context", return_value=mock_ctx)`  

**Coverage:**
- TCP: success=`on_success`, refused/timeout=`on_failure`, custom on_success/on_failure, `response_time_ms` sub-key, RT=0 on failure
- HTTP status: no conditions → raw code, conditions → evaluated, connect failure → default_value
- HTTP body: match pattern, condition evaluation, no-match → default_value
- SSL: valid cert → 1, `SSLCertVerificationError` → 0, `OSError` → 2
- `ProbeCollector.collect()` returns `list[MetricResult]`, unknown mode raises

---

### `test_zabbix_common.py`

**Key imports:** `_common` (from `zabbix_update/`)  
**Coverage:**
- `load_yaml`: valid YAML, empty YAML, missing file
- `server_host_from_config`: reads `zabbix.server_host`, missing file/key → `"127.0.0.1"`
- `load_metrics`: all vs `only_enabled=True`, skips metrics without `key`, empty section
- `YAML_VT_MAP` and `SEVERITY_MAP` constant values
- `ZabbixAPI._call`: returns `result`, raises on API error object
- `ZabbixAPI.login`: sets `auth` token; `logout`: clears `auth`, no-op when not logged in
- `auth` token included in every request payload
- `base_arg_parser`: `--api-url`, `--user`, `--password`, `--no-wait` flags with correct defaults
- `resolve_credentials`: CLI arg > env var; `ZABBIX_ADMIN_USER` / `ZABBIX_ADMIN_PASSWORD`
- `wait_for_api`: returns on HTTP < 500; raises `RuntimeError` after timeout

---

### `test_zabbix_item_builders.py`

**Key imports:** `create_trapper_items`, `create_template`  
**Parametrized over both modules** (ids: `trapper`, `template`) to ensure they stay in sync.  
**Coverage:**
- `_build_item_defs`: key/name/value_type/history/trends/tags for each metric; override vs default; empty list; unknown value_type defaults to VT_FLOAT
- `_build_self_mon_defs`: key, name (default = key), value_type
- `_build_additional_item_defs`: key, name, value_type, default history from `item_defaults`

---

### `test_zabbix_trigger_builder.py`

**Key imports:** `create_triggers._build_trigger_params`  
**Coverage:**
- `description` → `trigger["name"]`
- Expression preserved on template; template name substituted with host name when `on_template=False`
- All severity levels via `SEVERITY_MAP`
- `enabled: false` → `status=1`; default → `status=0`
- `recovery_expression` → `recovery_mode=1`; absent → `recovery_mode=0`
- `depends_on` resolved from `dependencies` dict; missing dependency skipped (no crash)
- `_host` marker set to `target_name`

---

### `test_zabbix_dashboard_builder.py`

**Key imports:** `create_dashboard`  
**Coverage:**
- `_random_ref`: length=5, valid chars (A-Z 0-9), statistically unique
- `_default_color`: cycles through `_PALETTE`, returns 6-char hex string
- `_wrap_widget`: `type`, `name`, `x`, `y`, `width`, `height`, `fields` all set correctly; default dimensions
- `_build_problems_widget`: type=`problems`, `show_lines` and `sort_triggers` fields
- `_build_clock_widget`: type=`clock`, `time_type` and `clock_type` fields
- `_build_item_widget`: type=`item`, `itemid` field added when key resolves; absent when not found
- `_build_graph_widget`: type=`svggraph`, `ds.*.hosts.*` / `ds.*.items.*` / `ds.*.color` fields, `reference` field

---

## Adding New Tests

### For a new collector

1. Add `pytest/test_collector_<name>.py`
2. Follow the two-class layout (`TestXxxHelpers`, `TestXxxCollector`)
3. Mock all I/O: use `tmp_path` for file system, `patch` for subprocess/socket/HTTP
4. Cover: every mode listed in `params.mode`, invalid mode raises `ValueError`, result has `status=RESULT_OK`, `collector=<name>` field, correct `value`

### For a new zabbix_update script

1. Add `pytest/test_zabbix_<script_name>.py`
2. Import builder functions directly (they are pure functions — no API calls needed)
3. For functions that call `ZabbixAPI`, mock `api._call` on a real `ZabbixAPI` instance

### Template for a new collector test

```python
"""test_collector_<name>.py — Tests for the <name> collector."""
from unittest.mock import patch

import pytest
from conftest import make_metric
from zabbig_client.collectors.<name> import <Name>Collector, _helper_fn
from zabbig_client.models import RESULT_OK


class Test<Name>Helpers:
    def test_helper_normal(self, tmp_path):
        # Write fake file, call helper, assert value
        ...

    def test_helper_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _helper_fn(str(tmp_path / "missing"))


class Test<Name>Collector:
    async def test_mode_x(self, tmp_path):
        metric = make_metric(
            collector="<name>", key="host.<name>.x",
            params={"mode": "x", "proc_root": str(tmp_path)},
        )
        result = await <Name>Collector().collect(metric)
        assert result.status == RESULT_OK
        assert float(result.value) >= 0

    async def test_unknown_mode_raises(self):
        metric = make_metric(
            collector="<name>", key="host.<name>",
            params={"mode": "invalid_mode"},
        )
        with pytest.raises(ValueError, match="Unknown"):
            await <Name>Collector().collect(metric)

    async def test_result_fields(self, tmp_path):
        metric = make_metric(
            collector="<name>", key="host.<name>",
            params={"mode": "x", "proc_root": str(tmp_path)},
        )
        result = await <Name>Collector().collect(metric)
        assert result.collector == "<name>"
        assert result.key == "host.<name>"
        assert result.status == RESULT_OK
```

---

## Known Limitations

- **No Docker integration tests** — all tests are fully unit-tested and offline; no running Zabbix instance is required.
- **Rate-mode tests (`rx_bytes_per_sec`, `tx_bytes_per_sec`)** patch `time.sleep` to avoid the 1-second real delay.
- **SSL tests** mock `ssl.create_default_context` — real TLS connections are not tested.
- **`_process_check` with missing `proc_root`** raises `FileNotFoundError` on macOS (os.scandir), not the `RuntimeError` wrapping that only fires on `PermissionError`. Tests handle both.
