"""
test_result_router.py — Tests for result_router.py.
"""
import pytest
from conftest import make_result
from zabbig_client.models import (
    DELIVERY_BATCH,
    DELIVERY_IMMEDIATE,
    RESULT_FAILED,
    RESULT_FALLBACK,
    RESULT_OK,
    RESULT_SKIPPED,
    RESULT_TIMEOUT,
)
from zabbig_client.result_router import route


class TestRoute:
    def test_empty_list(self):
        batch, immediate = route([])
        assert batch == []
        assert immediate == []

    def test_ok_batch_result(self):
        r = make_result(status=RESULT_OK, delivery=DELIVERY_BATCH, value="10")
        batch, immediate = route([r])
        assert len(batch) == 1
        assert immediate == []

    def test_ok_immediate_result(self):
        r = make_result(status=RESULT_OK, delivery=DELIVERY_IMMEDIATE, value="10")
        batch, immediate = route([r])
        assert batch == []
        assert len(immediate) == 1

    def test_fallback_is_sendable(self):
        r = make_result(status=RESULT_FALLBACK, delivery=DELIVERY_BATCH, value="0")
        batch, immediate = route([r])
        assert len(batch) == 1

    def test_failed_dropped(self):
        r = make_result(status=RESULT_FAILED, delivery=DELIVERY_BATCH, value=None)
        batch, immediate = route([r])
        assert batch == []
        assert immediate == []

    def test_timeout_dropped(self):
        r = make_result(status=RESULT_TIMEOUT, delivery=DELIVERY_BATCH, value=None)
        batch, immediate = route([r])
        assert batch == []
        assert immediate == []

    def test_skipped_dropped(self):
        r = make_result(status=RESULT_SKIPPED, delivery=DELIVERY_BATCH, value=None)
        batch, immediate = route([r])
        assert batch == []
        assert immediate == []

    def test_none_value_dropped(self):
        r = make_result(status=RESULT_OK, delivery=DELIVERY_BATCH, value=None)
        batch, immediate = route([r])
        assert batch == []

    def test_mixed_results(self):
        results = [
            make_result(key="k1", status=RESULT_OK, delivery=DELIVERY_BATCH, value="1"),
            make_result(key="k2", status=RESULT_OK, delivery=DELIVERY_IMMEDIATE, value="2"),
            make_result(key="k3", status=RESULT_FAILED, delivery=DELIVERY_BATCH, value=None),
            make_result(key="k4", status=RESULT_SKIPPED, delivery=DELIVERY_IMMEDIATE, value=None),
            make_result(key="k5", status=RESULT_FALLBACK, delivery=DELIVERY_IMMEDIATE, value="0"),
        ]
        batch, immediate = route(results)
        assert len(batch) == 1
        assert batch[0].key == "k1"
        assert len(immediate) == 2
        assert {r.key for r in immediate} == {"k2", "k5"}

    def test_routing_preserves_result_object(self):
        r = make_result(key="mykey", status=RESULT_OK, delivery=DELIVERY_BATCH, value="99")
        batch, _ = route([r])
        assert batch[0] is r

    def test_multiple_batch(self):
        results = [
            make_result(key=f"k{i}", status=RESULT_OK, delivery=DELIVERY_BATCH, value=str(i))
            for i in range(5)
        ]
        batch, _ = route(results)
        assert len(batch) == 5

    def test_multiple_immediate(self):
        results = [
            make_result(key=f"k{i}", status=RESULT_OK, delivery=DELIVERY_IMMEDIATE, value=str(i))
            for i in range(3)
        ]
        _, immediate = route(results)
        assert len(immediate) == 3
