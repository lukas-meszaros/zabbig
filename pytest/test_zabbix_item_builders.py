"""
test_zabbix_item_builders.py — Tests for item builder functions in
create_trapper_items.py and create_template.py.

Both files have identical _build_item_defs, _build_self_mon_defs, and
_build_additional_item_defs functions — we test both to ensure they stay in sync.
"""
import pytest

import create_trapper_items as trapper_mod
import create_template as template_mod
from _common import YAML_VT_MAP


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_SAMPLE_METRICS = [
    {"id": "cpu_percent", "key": "host.cpu.percent",   "value_type": "float"},
    {"id": "mem_used",    "key": "host.mem.used",       "value_type": "int"},
    {"id": "disk_used",   "key": "host.disk.used",      "value_type": "string"},
]

_SAMPLE_TPL_DATA = {
    "item_defaults": {
        "history": "30d",
        "trends":  "730d",
        "tags": [{"tag": "component", "value": "system"}],
    },
    "items": [
        {
            "key":         "host.cpu.percent",
            "name":        "CPU Usage %",
            "description": "CPU utilisation as a percentage",
            "history":     "7d",
        }
    ],
    "self_monitoring_items": [
        {
            "key":        "zabbig.client.heartbeat",
            "name":       "Client Heartbeat",
            "value_type": "int",
            "description": "1 = alive",
        },
        {
            "key":        "zabbig.client.last_run",
            "name":       "Client Last Run",
            "value_type": "int",
        },
    ],
    "additional_items": [
        {
            "key":        "host.probe.tcp.response_time_ms",
            "name":       "TCP Response Time",
            "value_type": "int",
        }
    ],
}


# ---------------------------------------------------------------------------
# Parametrize over both modules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mod", [trapper_mod, template_mod], ids=["trapper", "template"])
class TestBuildItemDefs:
    def test_returns_one_def_per_metric(self, mod):
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        assert len(defs) == len(_SAMPLE_METRICS)

    def test_key_field_set(self, mod):
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        keys = [d["key_"] for d in defs]
        assert "host.cpu.percent" in keys
        assert "host.mem.used" in keys

    def test_name_from_override(self, mod):
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        cpu_def = next(d for d in defs if d["key_"] == "host.cpu.percent")
        assert cpu_def["name"] == "CPU Usage %"

    def test_name_defaults_to_key(self, mod):
        """Items without an override in tpl_data should use the key as the name."""
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        mem_def = next(d for d in defs if d["key_"] == "host.mem.used")
        assert mem_def["name"] == "host.mem.used"

    def test_value_type_float_maps_to_0(self, mod):
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        cpu_def = next(d for d in defs if d["key_"] == "host.cpu.percent")
        assert cpu_def["value_type"] == 0

    def test_value_type_int_maps_to_3(self, mod):
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        mem_def = next(d for d in defs if d["key_"] == "host.mem.used")
        assert mem_def["value_type"] == 3

    def test_value_type_string_maps_to_4(self, mod):
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        disk_def = next(d for d in defs if d["key_"] == "host.disk.used")
        assert disk_def["value_type"] == 4

    def test_history_from_override(self, mod):
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        cpu_def = next(d for d in defs if d["key_"] == "host.cpu.percent")
        assert cpu_def["history"] == "7d"

    def test_history_from_defaults(self, mod):
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        mem_def = next(d for d in defs if d["key_"] == "host.mem.used")
        assert mem_def["history"] == "30d"

    def test_trends_from_defaults(self, mod):
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        mem_def = next(d for d in defs if d["key_"] == "host.mem.used")
        assert mem_def["trends"] == "730d"

    def test_tags_from_defaults(self, mod):
        defs = mod._build_item_defs(_SAMPLE_METRICS, _SAMPLE_TPL_DATA)
        mem_def = next(d for d in defs if d["key_"] == "host.mem.used")
        assert mem_def.get("tags") == [{"tag": "component", "value": "system"}]

    def test_empty_metrics_returns_empty_list(self, mod):
        assert mod._build_item_defs([], _SAMPLE_TPL_DATA) == []

    def test_unknown_value_type_defaults_to_float(self, mod):
        metrics = [{"id": "x", "key": "host.x", "value_type": "unknown_type"}]
        defs = mod._build_item_defs(metrics, {})
        assert defs[0]["value_type"] == 0  # VT_FLOAT fallback


@pytest.mark.parametrize("mod", [trapper_mod, template_mod], ids=["trapper", "template"])
class TestBuildSelfMonDefs:
    def test_returns_self_mon_items(self, mod):
        defs = mod._build_self_mon_defs(_SAMPLE_TPL_DATA)
        assert len(defs) == 2

    def test_key_field_set(self, mod):
        defs = mod._build_self_mon_defs(_SAMPLE_TPL_DATA)
        keys = [d["key_"] for d in defs]
        assert "zabbig.client.heartbeat" in keys
        assert "zabbig.client.last_run" in keys

    def test_name_field_set(self, mod):
        defs = mod._build_self_mon_defs(_SAMPLE_TPL_DATA)
        hb = next(d for d in defs if d["key_"] == "zabbig.client.heartbeat")
        assert hb["name"] == "Client Heartbeat"

    def test_name_defaults_to_key(self, mod):
        defs = mod._build_self_mon_defs(_SAMPLE_TPL_DATA)
        lr = next(d for d in defs if d["key_"] == "zabbig.client.last_run")
        assert lr["name"] == "Client Last Run"

    def test_value_type_int(self, mod):
        defs = mod._build_self_mon_defs(_SAMPLE_TPL_DATA)
        hb = next(d for d in defs if d["key_"] == "zabbig.client.heartbeat")
        assert hb["value_type"] == 3  # VT_INT

    def test_empty_self_monitoring_items(self, mod):
        defs = mod._build_self_mon_defs({})
        assert defs == []


@pytest.mark.parametrize("mod", [trapper_mod, template_mod], ids=["trapper", "template"])
class TestBuildAdditionalItemDefs:
    def test_returns_additional_items(self, mod):
        defs = mod._build_additional_item_defs(_SAMPLE_TPL_DATA)
        assert len(defs) == 1

    def test_key_set(self, mod):
        defs = mod._build_additional_item_defs(_SAMPLE_TPL_DATA)
        assert defs[0]["key_"] == "host.probe.tcp.response_time_ms"

    def test_name_set(self, mod):
        defs = mod._build_additional_item_defs(_SAMPLE_TPL_DATA)
        assert defs[0]["name"] == "TCP Response Time"

    def test_value_type_int(self, mod):
        defs = mod._build_additional_item_defs(_SAMPLE_TPL_DATA)
        assert defs[0]["value_type"] == 3

    def test_uses_default_history(self, mod):
        defs = mod._build_additional_item_defs(_SAMPLE_TPL_DATA)
        assert defs[0]["history"] == "30d"

    def test_empty_additional_items(self, mod):
        defs = mod._build_additional_item_defs({"item_defaults": {}})
        assert defs == []
