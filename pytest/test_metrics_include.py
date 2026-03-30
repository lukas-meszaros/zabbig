"""
test_metrics_include.py — Tests for the `include:` directive in metrics.yaml.
"""
import os
import textwrap

import pytest

from zabbig_client.config_loader import ConfigError, load_metrics_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(tmp_path, filename, content):
    p = tmp_path / filename
    p.write_text(textwrap.dedent(content))
    return str(p)


def write_yaml_in_dir(directory, filename, content):
    path = directory / filename
    path.write_text(textwrap.dedent(content))
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIncludeDirective:
    def test_no_include_loads_normally(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: cpu_util
                collector: cpu
                key: host.cpu.util
                params:
                  mode: percent
        """)
        cfg = load_metrics_config(path)
        assert len(cfg.metrics) == 1
        assert cfg.include == []

    def test_include_loads_additional_metrics(self, tmp_path):
        extra_dir = tmp_path / "metrics.d"
        extra_dir.mkdir()
        write_yaml_in_dir(extra_dir, "extra.yaml", """
            metrics:
              - id: mem_used
                collector: memory
                key: host.memory.used_percent
                params:
                  mode: used_percent
        """)
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            include:
              - metrics.d/*.yaml
            metrics:
              - id: cpu_util
                collector: cpu
                key: host.cpu.util
                params:
                  mode: percent
        """)
        cfg = load_metrics_config(path)
        assert len(cfg.metrics) == 2
        ids = {m.id for m in cfg.metrics}
        assert "cpu_util" in ids
        assert "mem_used" in ids

    def test_include_respects_scoped_defaults(self, tmp_path):
        extra_dir = tmp_path / "metrics.d"
        extra_dir.mkdir()
        write_yaml_in_dir(extra_dir, "extra.yaml", """
            defaults:
              delivery: immediate
            metrics:
              - id: mem_used
                collector: memory
                key: host.memory.used_percent
                params:
                  mode: used_percent
        """)
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            include:
              - metrics.d/*.yaml
            defaults:
              delivery: batch
            metrics: []
        """)
        cfg = load_metrics_config(path)
        assert len(cfg.metrics) == 1
        # The included file's scoped defaults override the main file's defaults
        assert cfg.metrics[0].delivery == "immediate"

    def test_include_uses_global_collector_defaults(self, tmp_path):
        extra_dir = tmp_path / "metrics.d"
        extra_dir.mkdir()
        write_yaml_in_dir(extra_dir, "extra.yaml", """
            metrics:
              - id: cpu_load
                collector: cpu
                key: host.cpu.load1
                params:
                  mode: load1
        """)
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            collector_defaults:
              cpu:
                timeout_seconds: 77.0
            include:
              - metrics.d/*.yaml
            metrics: []
        """)
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].timeout_seconds == 77.0

    def test_duplicate_id_across_files_raises(self, tmp_path):
        extra_dir = tmp_path / "metrics.d"
        extra_dir.mkdir()
        write_yaml_in_dir(extra_dir, "extra.yaml", """
            metrics:
              - id: cpu_util
                collector: cpu
                key: host.cpu.util2
                params:
                  mode: load1
        """)
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            include:
              - metrics.d/*.yaml
            metrics:
              - id: cpu_util
                collector: cpu
                key: host.cpu.util
                params:
                  mode: percent
        """)
        with pytest.raises(ConfigError, match="Duplicate metric id"):
            load_metrics_config(path, strict=True)

    def test_duplicate_key_across_files_raises(self, tmp_path):
        extra_dir = tmp_path / "metrics.d"
        extra_dir.mkdir()
        write_yaml_in_dir(extra_dir, "extra.yaml", """
            metrics:
              - id: cpu_util2
                collector: cpu
                key: host.cpu.util
                params:
                  mode: load1
        """)
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            include:
              - metrics.d/*.yaml
            metrics:
              - id: cpu_util
                collector: cpu
                key: host.cpu.util
                params:
                  mode: percent
        """)
        with pytest.raises(ConfigError, match="Duplicate Zabbix key"):
            load_metrics_config(path, strict=True)

    def test_nonmatching_glob_warns_not_errors(self, tmp_path, caplog):
        import logging
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            include:
              - metrics.d/*.yaml
            metrics: []
        """)
        with caplog.at_level(logging.WARNING):
            cfg = load_metrics_config(path, strict=True)
        assert cfg.metrics == []
        assert any("no files matched" in r.message for r in caplog.records)

    def test_include_multiple_patterns_merged(self, tmp_path):
        extra_dir = tmp_path / "metrics.d"
        extra_dir.mkdir()
        write_yaml_in_dir(extra_dir, "a.yaml", """
            metrics:
              - id: metric_a
                collector: cpu
                key: host.cpu.a
                params:
                  mode: load1
        """)
        write_yaml_in_dir(extra_dir, "b.yaml", """
            metrics:
              - id: metric_b
                collector: cpu
                key: host.cpu.b
                params:
                  mode: load5
        """)
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            include:
              - metrics.d/a.yaml
              - metrics.d/b.yaml
            metrics: []
        """)
        cfg = load_metrics_config(path)
        assert {m.id for m in cfg.metrics} == {"metric_a", "metric_b"}

    def test_include_stored_in_metricsconfig(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            include:
              - metrics.d/*.yaml
            metrics: []
        """)
        cfg = load_metrics_config(path, strict=False)
        assert cfg.include == ["metrics.d/*.yaml"]

    def test_absolute_include_path(self, tmp_path):
        extra = tmp_path / "elsewhere" / "extra.yaml"
        extra.parent.mkdir()
        extra.write_text(textwrap.dedent("""
            metrics:
              - id: cpu_a
                collector: cpu
                key: host.cpu.x
                params:
                  mode: load1
        """))
        path = write_yaml(tmp_path, "metrics.yaml", f"""
            version: 1
            include:
              - {str(extra)}
            metrics: []
        """)
        cfg = load_metrics_config(path)
        assert len(cfg.metrics) == 1
        assert cfg.metrics[0].id == "cpu_a"


class TestCacheSecondsField:
    def test_cache_seconds_parsed(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: disk_inodes
                collector: disk
                key: host.disk.inodes_total
                cache_seconds: 300
                params:
                  mount: "/"
                  mode: inodes_total
        """)
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].cache_seconds == 300

    def test_cache_seconds_absent_is_none(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: cpu_util
                collector: cpu
                key: host.cpu.util
                params:
                  mode: percent
        """)
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].cache_seconds is None

    def test_cache_seconds_zero_valid(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: cpu_util
                collector: cpu
                key: host.cpu.util
                cache_seconds: 0
                params:
                  mode: percent
        """)
        cfg = load_metrics_config(path)
        assert cfg.metrics[0].cache_seconds == 0

    def test_cache_seconds_negative_raises(self, tmp_path):
        path = write_yaml(tmp_path, "metrics.yaml", """
            version: 1
            metrics:
              - id: cpu_util
                collector: cpu
                key: host.cpu.util
                cache_seconds: -1
                params:
                  mode: percent
        """)
        with pytest.raises(ConfigError, match="cache_seconds"):
            load_metrics_config(path, strict=True)
