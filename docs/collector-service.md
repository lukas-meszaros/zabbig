# Service Collector

Checks whether a service or process is running. Returns `1` (running) or `0` (not running).

---

## Params

| Param | Required | Description |
|---|---|---|
| `check_mode` | yes | `systemd` or `process` |
| `service_name` | when `check_mode: systemd` | systemd unit name, without the `.service` suffix |
| `process_pattern` | when `check_mode: process` | Python regex matched against each process's full command line in `/proc/*/cmdline` |
| `proc_root` | no | Override `runtime.proc_root`. Used by `process` mode only. |

---

## Check Modes

### `check_mode: systemd`

Runs `systemctl is-active --quiet <service_name>`. Returns `1` if the exit code is 0 (active). Returns `0` for any non-zero exit code: inactive, failed, activating, etc.

Requires a systemd host. Use `process` mode on hosts with SysV init, OpenRC, or inside Docker containers.

### `check_mode: process`

Scans `/proc/*/cmdline` and matches the `process_pattern` regex against the full command line of every running process. Returns `1` if at least one process matches, `0` otherwise.

Each process's `cmdline` is read as NUL-separated arguments joined into a single space-separated string:
```
python3 /opt/myapp/server.py --port 8080
```

Works anywhere a Linux `/proc` filesystem is available — no systemd required.

---

## Delivery

Service metrics default to `delivery: immediate` so Zabbix receives the state change as quickly as possible rather than waiting for the full batch window.

---

## Scenarios

### Critical systemd service — failure visible in client health metrics

Using `error_policy: mark_failed` causes `zabbig.client.collectors.failed` to increment when the check itself fails (not to be confused with the service being down).

```yaml
- id: svc_postgresql
  name: PostgreSQL service state
  collector: service
  key: host.service.postgresql
  value_type: int
  delivery: immediate
  importance: critical
  error_policy: mark_failed
  params:
    check_mode: systemd
    service_name: postgresql
```

---

### Web server — treat "cannot check" as "service is down"

`error_policy: fallback` with `fallback_value: "0"` means a collection error (e.g. systemctl not available) is reported as "service down", which is the safest assumption.

```yaml
- id: svc_nginx
  name: Nginx service state
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
```

---

### Process check — no systemd required

Useful for custom applications started with a process supervisor or directly from cron.

```yaml
- id: svc_myapp_process
  name: myapp process running
  collector: service
  key: host.service.myapp.process
  value_type: int
  delivery: immediate
  importance: high
  params:
    check_mode: process
    process_pattern: "python.*myapp"
```

---

### Strict nginx master process check

The regex `nginx: master process` avoids matching worker processes.

```yaml
- id: svc_nginx_process
  collector: service
  key: host.service.nginx.process
  value_type: int
  params:
    check_mode: process
    process_pattern: "nginx: master process"
```

---

### cron or crond process check (inside Docker — no systemd)

```yaml
- id: svc_crond
  collector: service
  key: host.service.cron.process
  value_type: int
  params:
    check_mode: process
    process_pattern: "crond|cron"
    proc_root: "/host/proc"    # host /proc bind-mounted at this path
```

---

### Multiple services in one metrics.yaml

```yaml
- id: svc_ssh
  collector: service
  key: host.service.ssh
  value_type: int
  delivery: immediate
  params:
    check_mode: systemd
    service_name: sshd

- id: svc_redis
  collector: service
  key: host.service.redis
  value_type: int
  delivery: immediate
  importance: high
  params:
    check_mode: systemd
    service_name: redis
```

---

## Host Name Override

All metrics support the optional top-level `host_name` field. When set, the metric is sent to Zabbix under that host name instead of the global `zabbix.host_name` from `client.yaml`. Useful when a single client instance checks services on behalf of multiple Zabbix host objects.

```yaml
- id: svc_nginx
  collector: service
  key: host.service.nginx
  host_name: "web-server-01"    # override for this metric only
  params:
    check_mode: systemd
    service_name: nginx
```

See [configuration.md](configuration.md#metric-level-host_name) for the full priority chain.

---

## Metric Scheduling

Every service metric supports four optional scheduling fields that control when and how often the metric is collected. All four are inactive when absent.

```yaml
- id: nginx_running_biz
  collector: service
  key: host.service.nginx.running.biz
  value_type: int
  time_window_from: "0600"         # only during operational hours
  time_window_till: "2200"
  run_frequency: 5                 # every fifth invocation
  params:
    check_mode: systemd
    service_name: nginx
```

See [configuration.md](configuration.md#metric-scheduling-fields) for the full field reference, value rules, and evaluation order.
