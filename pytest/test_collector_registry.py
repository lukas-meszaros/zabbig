"""
test_collector_registry.py — Tests for collector_registry.py.
"""
import pytest

from zabbig_client.collector_registry import (
    _ensure_collectors_imported,
    get_collector,
    load_collectors_for,
    register_collector,
    registered_names,
)

# Populate the full registry once for the whole test module.
_ensure_collectors_imported()


class TestRegistry:
    def test_all_collectors_registered(self):
        names = registered_names()
        for expected in ["cpu", "memory", "disk", "service", "network", "log", "probe"]:
            assert expected in names, f"'{expected}' not in registry"

    def test_get_known_collector(self):
        cls = get_collector("cpu")
        # Should be a class
        assert callable(cls)

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="No collector registered for"):
            get_collector("nonexistent_collector")

    def test_registered_names_sorted(self):
        names = registered_names()
        assert names == sorted(names)

    def test_register_and_retrieve(self):
        """Register a temporary dummy collector and remove it."""
        from zabbig_client.collector_registry import _REGISTRY

        @register_collector("_test_dummy_xyz")
        class DummyCollector:
            pass

        try:
            retrieved = get_collector("_test_dummy_xyz")
            assert retrieved is DummyCollector
        finally:
            _REGISTRY.pop("_test_dummy_xyz", None)

    def test_register_returns_class_unchanged(self):
        from zabbig_client.collector_registry import _REGISTRY

        @register_collector("_test_dummy_abc")
        class MyCollector:
            value = 99

        try:
            assert MyCollector.value == 99
            assert get_collector("_test_dummy_abc") is MyCollector
        finally:
            _REGISTRY.pop("_test_dummy_abc", None)

    def test_cpu_collector_is_base_subclass(self):
        from zabbig_client.collectors.base import BaseCollector
        cpu_cls = get_collector("cpu")
        assert issubclass(cpu_cls, BaseCollector)

    def test_probe_collector_is_base_subclass(self):
        from zabbig_client.collectors.base import BaseCollector
        probe_cls = get_collector("probe")
        assert issubclass(probe_cls, BaseCollector)

    @pytest.mark.parametrize("name", ["cpu", "memory", "disk", "service", "network", "log", "probe"])
    def test_each_collector_importable(self, name):
        cls = get_collector(name)
        assert cls is not None

    @pytest.mark.parametrize("name", ["cpu", "memory", "disk", "service", "network", "log", "probe"])
    def test_each_collector_has_collect_method(self, name):
        import inspect
        cls = get_collector(name)
        assert hasattr(cls, "collect")
        assert inspect.iscoroutinefunction(cls.collect)


class TestLoadCollectorsFor:
    def test_known_name_registers_collector(self):
        from zabbig_client.collector_registry import _REGISTRY
        # "cpu" must be in the registry after load_collectors_for
        load_collectors_for({"cpu"})
        assert "cpu" in _REGISTRY

    def test_multiple_names(self):
        from zabbig_client.collector_registry import _REGISTRY
        load_collectors_for({"memory", "disk"})
        assert "memory" in _REGISTRY
        assert "disk" in _REGISTRY

    def test_unknown_name_does_not_raise(self):
        # Should warn and continue, not raise
        load_collectors_for({"totally_unknown_collector_xyz"})

    def test_idempotent_double_call(self):
        # Calling twice for the same name should not raise or duplicate
        load_collectors_for({"cpu"})
        load_collectors_for({"cpu"})
        assert registered_names().count("cpu") == 1
