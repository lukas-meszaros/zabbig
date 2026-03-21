"""
test_zabbix_trigger_builder.py — Tests for _build_trigger_params in create_triggers.py.
"""
import pytest

from create_triggers import _build_trigger_params
from _common import SEVERITY_MAP


_TEMPLATE_NAME = "zabbig Linux Host"

_MINIMAL_TRIGGER = {
    "name": "CPU high",
    "expression": "{zabbig Linux Host:host.cpu.percent.last()}>90",
    "severity": "high",
}

_FULL_TRIGGER = {
    "name": "Memory critical",
    "expression": "{zabbig Linux Host:host.mem.used_percent.last()}>95",
    "severity": "disaster",
    "description": "Memory is nearly full",
    "enabled": True,
    "recovery_expression": "{zabbig Linux Host:host.mem.used_percent.last()}<80",
    "depends_on": [],
}

_DISABLED_TRIGGER = {
    "name": "Disk warning",
    "expression": "{zabbig Linux Host:host.disk.used_percent.last()}>80",
    "severity": "warning",
    "enabled": False,
}


def _build(trigger, target_name=_TEMPLATE_NAME, template_name=_TEMPLATE_NAME,
           on_template=True, dependencies=None):
    return _build_trigger_params(
        trigger,
        target_name=target_name,
        template_name=template_name,
        on_template=on_template,
        dependencies=dependencies or {},
    )


class TestBuildTriggerParams:
    def test_description_set(self):
        p = _build(_MINIMAL_TRIGGER)
        assert p["description"] == "CPU high"

    def test_expression_preserved_on_template(self):
        p = _build(_MINIMAL_TRIGGER, on_template=True)
        assert "{zabbig Linux Host:" in p["expression"]

    def test_expression_substituted_on_host(self):
        p = _build(
            _MINIMAL_TRIGGER,
            target_name="prod-server-01",
            template_name=_TEMPLATE_NAME,
            on_template=False,
        )
        assert "{prod-server-01:" in p["expression"]
        assert "{zabbig Linux Host:" not in p["expression"]

    def test_severity_high(self):
        p = _build(_MINIMAL_TRIGGER)
        assert p["priority"] == SEVERITY_MAP["high"] == 4

    def test_severity_disaster(self):
        p = _build(_FULL_TRIGGER)
        assert p["priority"] == SEVERITY_MAP["disaster"] == 5

    def test_severity_defaults_to_warning(self):
        trigger = {"name": "x", "expression": "{T:k.last()}>1"}
        p = _build(trigger)
        assert p["priority"] == SEVERITY_MAP["warning"] == 2

    def test_enabled_trigger_status_0(self):
        p = _build(_FULL_TRIGGER)
        assert p["status"] == 0

    def test_disabled_trigger_status_1(self):
        p = _build(_DISABLED_TRIGGER)
        assert p["status"] == 1

    def test_enabled_defaults_to_true(self):
        trigger = {"name": "x", "expression": "{T:k.last()}>1"}
        p = _build(trigger)
        assert p["status"] == 0

    def test_recovery_expression_sets_mode_1(self):
        p = _build(_FULL_TRIGGER)
        assert p["recovery_mode"] == 1
        assert p["recovery_expression"] == _FULL_TRIGGER["recovery_expression"]

    def test_no_recovery_expression_sets_mode_0(self):
        p = _build(_MINIMAL_TRIGGER)
        assert p["recovery_mode"] == 0
        assert "recovery_expression" not in p

    def test_comments_from_description_field(self):
        p = _build(_FULL_TRIGGER)
        assert p["comments"] == "Memory is nearly full"

    def test_comments_empty_when_missing(self):
        p = _build(_MINIMAL_TRIGGER)
        assert p["comments"] == ""

    def test_host_marker_set(self):
        # When on_template=True, _build is called with target_name = template_name
        # (the run() function sets target_name=template_name when on_template)
        p = _build(_MINIMAL_TRIGGER, target_name=_TEMPLATE_NAME, on_template=True)
        assert p["_host"] == _TEMPLATE_NAME

    def test_host_marker_set_for_host_target(self):
        p = _build(_MINIMAL_TRIGGER, target_name="prod-server-01", on_template=False)
        assert p["_host"] == "prod-server-01"

    def test_depends_on_resolved(self):
        deps = {"CPU high": "trigger_id_123"}
        trigger = {
            "name": "Memory warning",
            "expression": "{zabbig Linux Host:host.mem.last()}>90",
            "depends_on": ["CPU high"],
        }
        p = _build(trigger, dependencies=deps)
        assert p["dependencies"] == [{"triggerid": "trigger_id_123"}]

    def test_depends_on_missing_skipped(self):
        trigger = {
            "name": "Memory warning",
            "expression": "{zabbig Linux Host:host.mem.last()}>90",
            "depends_on": ["NonexistentTrigger"],
        }
        p = _build(trigger, dependencies={})
        assert "dependencies" not in p

    def test_empty_depends_on_no_dependencies_key(self):
        p = _build(_MINIMAL_TRIGGER)
        assert "dependencies" not in p
