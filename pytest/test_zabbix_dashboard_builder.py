"""
test_zabbix_dashboard_builder.py — Tests for dashboard widget builder functions
in create_dashboard.py.
"""
import string
from unittest.mock import MagicMock, patch

import pytest

from create_dashboard import (
    _random_ref,
    _default_color,
    _wrap_widget,
    _build_problems_widget,
    _build_clock_widget,
    _build_item_widget,
    _build_graph_widget,
    _build_page,
    _PALETTE,
)


# ---------------------------------------------------------------------------
# _random_ref
# ---------------------------------------------------------------------------

class TestRandomRef:
    def test_returns_5_chars(self):
        ref = _random_ref()
        assert len(ref) == 5

    def test_only_uppercase_and_digits(self):
        valid = set(string.ascii_uppercase + string.digits)
        for _ in range(20):
            ref = _random_ref()
            assert all(c in valid for c in ref)

    def test_returns_unique_values(self):
        refs = {_random_ref() for _ in range(50)}
        # At least 40/50 unique (statistically almost certain)
        assert len(refs) >= 40


# ---------------------------------------------------------------------------
# _default_color
# ---------------------------------------------------------------------------

class TestDefaultColor:
    def test_returns_first_palette_color(self):
        assert _default_color(0) == _PALETTE[0]

    def test_cycles_through_palette(self):
        assert _default_color(len(_PALETTE)) == _PALETTE[0]

    def test_second_color(self):
        assert _default_color(1) == _PALETTE[1]

    def test_returns_hex_string(self):
        color = _default_color(0)
        assert len(color) == 6
        int(color, 16)  # Should not raise — must be valid hex


# ---------------------------------------------------------------------------
# _wrap_widget
# ---------------------------------------------------------------------------

class TestWrapWidget:
    def _widget(self, **kwargs):
        w = {"title": "Test Widget", "width": 8, "height": 4}
        w.update(kwargs)
        return w

    def test_type_set(self):
        result = _wrap_widget(self._widget(), 0, 0, "svggraph", [])
        assert result["type"] == "svggraph"

    def test_name_from_title(self):
        result = _wrap_widget(self._widget(title="My Title"), 0, 0, "item", [])
        assert result["name"] == "My Title"

    def test_coordinates_set(self):
        result = _wrap_widget(self._widget(), 3, 7, "clock", [])
        assert result["x"] == 3
        assert result["y"] == 7

    def test_dimensions(self):
        result = _wrap_widget(self._widget(width=12, height=6), 0, 0, "problems", [])
        assert result["width"] == 12
        assert result["height"] == 6

    def test_default_dimensions(self):
        result = _wrap_widget({}, 0, 0, "clock", [])
        assert result["width"] == 6
        assert result["height"] == 5

    def test_fields_included(self):
        fields = [{"type": 0, "name": "show_lines", "value": 25}]
        result = _wrap_widget(self._widget(), 0, 0, "problems", fields)
        assert result["fields"] == fields


# ---------------------------------------------------------------------------
# _build_problems_widget
# ---------------------------------------------------------------------------

class TestBuildProblemsWidget:
    def test_type_is_problems(self):
        result = _build_problems_widget({}, 0, 0)
        assert result["type"] == "problems"

    def test_has_show_lines_field(self):
        result = _build_problems_widget({}, 0, 0)
        names = [f["name"] for f in result["fields"]]
        assert "show_lines" in names

    def test_has_sort_triggers_field(self):
        result = _build_problems_widget({}, 0, 0)
        names = [f["name"] for f in result["fields"]]
        assert "sort_triggers" in names

    def test_coordinates(self):
        result = _build_problems_widget({}, 2, 4)
        assert result["x"] == 2
        assert result["y"] == 4


# ---------------------------------------------------------------------------
# _build_clock_widget
# ---------------------------------------------------------------------------

class TestBuildClockWidget:
    def test_type_is_clock(self):
        result = _build_clock_widget({}, 0, 0)
        assert result["type"] == "clock"

    def test_has_time_type_field(self):
        result = _build_clock_widget({}, 0, 0)
        names = [f["name"] for f in result["fields"]]
        assert "time_type" in names

    def test_has_clock_type_field(self):
        result = _build_clock_widget({}, 0, 0)
        names = [f["name"] for f in result["fields"]]
        assert "clock_type" in names

    def test_coordinates(self):
        result = _build_clock_widget({}, 5, 3)
        assert result["x"] == 5
        assert result["y"] == 3


# ---------------------------------------------------------------------------
# _build_item_widget
# ---------------------------------------------------------------------------

class TestBuildItemWidget:
    def _make_api(self, item_ids=None):
        api = MagicMock()
        if item_ids is not None:
            api._call.return_value = [{"key_": k, "itemid": v} for k, v in item_ids.items()]
        else:
            api._call.return_value = []
        return api

    def test_type_is_item(self):
        api = self._make_api({"host.cpu": "111"})
        result = _build_item_widget({"keys": ["host.cpu"]}, "42", api, 0, 0)
        assert result["type"] == "item"

    def test_itemid_field_added_when_resolved(self):
        api = self._make_api({"host.cpu": "111"})
        result = _build_item_widget({"keys": ["host.cpu"]}, "42", api, 0, 0)
        field_names = [f["name"] for f in result["fields"]]
        assert "itemid" in field_names

    def test_no_itemid_when_key_not_found(self):
        api = self._make_api({})
        result = _build_item_widget({"keys": ["nonexistent.key"]}, "42", api, 0, 0)
        field_names = [f["name"] for f in result["fields"]]
        assert "itemid" not in field_names

    def test_empty_keys_no_itemid(self):
        api = self._make_api({})
        result = _build_item_widget({"keys": []}, "42", api, 0, 0)
        field_names = [f["name"] for f in result["fields"]]
        assert "itemid" not in field_names


# ---------------------------------------------------------------------------
# _build_graph_widget
# ---------------------------------------------------------------------------

class TestBuildGraphWidget:
    def _make_api(self, items_map=None):
        api = MagicMock()
        api._call.return_value = [
            {"key_": k, "name": v} for k, v in (items_map or {}).items()
        ]
        return api

    def test_type_is_svggraph(self):
        api = self._make_api({"host.cpu.percent": "CPU Usage %"})
        result = _build_graph_widget(
            {"keys": ["host.cpu.percent"]}, "myhost", "42", 0, 0, api
        )
        assert result["type"] == "svggraph"

    def test_ds_hosts_field_present(self):
        api = self._make_api({"host.cpu": "CPU"})
        result = _build_graph_widget(
            {"keys": ["host.cpu"]}, "myhost", "42", 0, 0, api
        )
        field_names = [f["name"] for f in result["fields"]]
        assert any("hosts" in n for n in field_names)

    def test_ds_items_field_uses_item_name(self):
        api = self._make_api({"host.cpu": "CPU Usage %"})
        result = _build_graph_widget(
            {"keys": ["host.cpu"]}, "myhost", "42", 0, 0, api
        )
        item_field = next(
            f for f in result["fields"] if "items" in f.get("name", "")
        )
        assert item_field["value"] == "CPU Usage %"

    def test_reference_field_present(self):
        api = self._make_api({})
        result = _build_graph_widget({"keys": []}, "myhost", "42", 0, 0, api)
        field_names = [f["name"] for f in result["fields"]]
        assert "reference" in field_names

    def test_color_field_set(self):
        api = self._make_api({"host.cpu": "CPU"})
        result = _build_graph_widget(
            {"keys": ["host.cpu"]}, "myhost", "42", 0, 0, api
        )
        color_field = next(f for f in result["fields"] if "color" in f.get("name", ""))
        assert len(color_field["value"]) == 6  # hex color string
