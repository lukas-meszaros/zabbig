# Disk Collector

Reports filesystem space and inode usage via `os.statvfs()`.

---

## Params

| Param | Required | Description |
|---|---|---|
| `mount` | yes | Absolute path to the mount point to inspect (e.g. `/`, `/data`, `/var`) |
| `mode` | yes | Which disk metric to return (see modes table below) |

---

## Modes

| Mode | Returns |
|---|---|
| `used_percent` | Percentage of filesystem blocks in use (non-root perspective) |
| `used_bytes` | Bytes currently in use (total minus bytes available to non-root users) |
| `free_bytes` | Bytes available to non-root users (`f_bavail × f_frsize`) |
| `inodes_used_percent` | Inode slots in use as a percentage of total. Returns `0.0` on filesystems that report 0 total inodes (btrfs, tmpfs). |
| `inodes_used` | Number of inode slots currently in use |
| `inodes_free` | Number of free inode slots |
| `inodes_total` | Total inode slots on the filesystem |

> **Inode exhaustion** is a common production incident: a filesystem runs out of inodes while still showing available space. This typically affects mail queues, session stores, or directories with millions of small files. Monitor both `used_percent` and `inodes_used_percent` on critical partitions.

---

## Scenarios

### Root partition space — most common alert

```yaml
- id: disk_root_used_percent
  name: Root partition used percent
  collector: disk
  key: host.disk.root.used_percent
  value_type: float
  unit: "%"
  importance: high
  params:
    mount: "/"
    mode: used_percent
```

---

### Free bytes alongside used-percent

Percentage alone can be misleading on very large disks. Tracking absolute free bytes helps catch "only 50 GB left on a 5 TB disk" situations.

```yaml
- id: disk_root_free_bytes
  collector: disk
  key: host.disk.root.free_bytes
  value_type: int
  unit: "B"
  params:
    mount: "/"
    mode: free_bytes
```

---

### Separate data partition

```yaml
- id: disk_data_used_percent
  collector: disk
  key: host.disk.data.used_percent
  value_type: float
  unit: "%"
  params:
    mount: "/data"
    mode: used_percent
```

---

### Inode monitoring — catch exhaustion before space runs out

```yaml
- id: disk_root_inodes_used_percent
  name: Root inode used percent
  collector: disk
  key: host.disk.root.inodes_used_percent
  value_type: float
  unit: "%"
  importance: high
  params:
    mount: "/"
    mode: inodes_used_percent
```

---

### /var inode monitoring (log/dpkg directories)

`/var` is a common inode exhaustion target due to log rotation fragments and dpkg metadata. Enable this when `/var` is on its own partition.

```yaml
- id: disk_var_inodes_used_percent
  enabled: false    # enable if /var is on its own partition
  collector: disk
  key: host.disk.var.inodes_used_percent
  value_type: float
  unit: "%"
  importance: high
  params:
    mount: "/var"
    mode: inodes_used_percent
```

---

### Absolute inode counts for trend graphs

```yaml
- id: disk_root_inodes_free
  collector: disk
  key: host.disk.root.inodes_free
  value_type: int
  params:
    mount: "/"
    mode: inodes_free

- id: disk_root_inodes_total
  collector: disk
  key: host.disk.root.inodes_total
  value_type: int
  params:
    mount: "/"
    mode: inodes_total
```

---

For `host_name` override, scheduling fields (`time_window_from`, `time_window_till`, `max_executions_per_day`, `run_frequency`), and all other common metric fields see [configuration-metrics.yaml.md](configuration-metrics.yaml.md).
