"""
test_scheduler.py — Tests for the per-metric scheduling logic (scheduler.py).
"""
import textwrap
from unittest.mock import patch

import pytest

from zabbig_client.models import MetricDef
from zabbig_client.scheduler import parse_hhmm, normalise_hhmm, should_execute, today_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metric(**kwargs) -> MetricDef:
    defaults = dict(
        id="m",
        name="m",
        enabled=True,
        collector="cpu",
        key="host.test",
        delivery="batch",
        timeout_seconds=10.0,
        error_policy="skip",
    )
    defaults.update(kwargs)
    return MetricDef(**defaults)


def _mins(h: int, m: int) -> int:
    return h * 60 + m


# ---------------------------------------------------------------------------
# parse_hhmm
# ---------------------------------------------------------------------------

class TestParseHhmm:
    def test_midnight(self):
        assert parse_hhmm("0000") == 0

    def test_eight_am(self):
        assert parse_hhmm("0800") == 8 * 60

    def test_end_of_day(self):
        assert parse_hhmm("2359") == 23 * 60 + 59

    def test_noon(self):
        assert parse_hhmm("1200") == 720

    def test_half_past_five(self):
        assert parse_hhmm("1730") == 17 * 60 + 30


# ---------------------------------------------------------------------------
# normalise_hhmm
# ---------------------------------------------------------------------------

class TestNormaliseHhmm:
    def test_string_already_padded(self):
        assert normalise_hhmm("0800") == "0800"

    def test_integer_pads_to_four(self):
        assert normalise_hhmm(800) == "0800"

    def test_integer_no_pad_needed(self):
        assert normalise_hhmm(1800) == "1800"


# ---------------------------------------------------------------------------
# today_str
# ---------------------------------------------------------------------------

class TestTodayStr:
    def test_returns_iso_date(self):
        s = today_str()
        assert len(s) == 10
        assert s[4] == "-" and s[7] == "-"


# ---------------------------------------------------------------------------
# dry_run bypass
# ---------------------------------------------------------------------------

class TestDryRunBypass:
    def test_bypasses_time_window(self):
        m = _metric(time_window_from="2300", time_window_till="2359")
        ok, reason = should_execute(m, run_counter=1, execution_count=0, dry_run=True)
        assert ok is True
        assert reason is None

    def test_bypasses_max_executions(self):
        m = _metric(max_executions_per_day=2)
        ok, _ = should_execute(m, run_counter=1, execution_count=999, dry_run=True)
        assert ok is True

    def test_bypasses_run_frequency(self):
        m = _metric(run_frequency=10)
        ok, _ = should_execute(m, run_counter=2, execution_count=0, dry_run=True)
        assert ok is True

    def test_bypasses_even_frequency(self):
        m = _metric(run_frequency="even")
        ok, _ = should_execute(m, run_counter=1, execution_count=0, dry_run=True)
        assert ok is True


# ---------------------------------------------------------------------------
# No constraints: always executes
# ---------------------------------------------------------------------------

class TestNoConstraints:
    def test_no_fields_always_runs(self):
        m = _metric()
        for counter in range(1, 20):
            ok, reason = should_execute(m, run_counter=counter, execution_count=0)
            assert ok is True, f"counter={counter}"
            assert reason is None


# ---------------------------------------------------------------------------
# time_window_from
# ---------------------------------------------------------------------------

class TestTimeWindowFrom:
    def _run(self, from_hhmm, current_h, current_m):
        m = _metric(time_window_from=from_hhmm)
        with patch("zabbig_client.scheduler.current_minutes", return_value=_mins(current_h, current_m)):
            return should_execute(m, run_counter=1, execution_count=0)

    def test_before_window_skipped(self):
        ok, reason = self._run("0800", 7, 59)
        assert ok is False
        assert "time_window_from" in reason

    def test_exactly_at_start_executes(self):
        ok, _ = self._run("0800", 8, 0)
        assert ok is True

    def test_after_start_executes(self):
        ok, _ = self._run("0800", 14, 30)
        assert ok is True

    def test_midnight_from_always_executes(self):
        ok, _ = self._run("0000", 0, 0)
        assert ok is True


# ---------------------------------------------------------------------------
# time_window_till
# ---------------------------------------------------------------------------

class TestTimeWindowTill:
    def _run(self, till_hhmm, current_h, current_m):
        m = _metric(time_window_till=till_hhmm)
        with patch("zabbig_client.scheduler.current_minutes", return_value=_mins(current_h, current_m)):
            return should_execute(m, run_counter=1, execution_count=0)

    def test_before_till_executes(self):
        ok, _ = self._run("1800", 17, 59)
        assert ok is True

    def test_exactly_at_till_skipped(self):
        ok, reason = self._run("1800", 18, 0)
        assert ok is False
        assert "time_window_till" in reason

    def test_after_till_skipped(self):
        ok, _ = self._run("1800", 20, 0)
        assert ok is False

    def test_midnight_till_always_skips(self):
        ok, _ = self._run("0000", 0, 0)
        assert ok is False


# ---------------------------------------------------------------------------
# Both time_window_from and time_window_till
# ---------------------------------------------------------------------------

class TestTimeWindowBoth:
    def _run(self, current_h, current_m):
        m = _metric(time_window_from="0800", time_window_till="1800")
        with patch("zabbig_client.scheduler.current_minutes", return_value=_mins(current_h, current_m)):
            return should_execute(m, run_counter=1, execution_count=0)

    def test_inside_window(self):
        ok, _ = self._run(12, 0)
        assert ok is True

    def test_before_from(self):
        ok, reason = self._run(7, 59)
        assert ok is False
        assert "time_window_from" in reason

    def test_at_till_boundary(self):
        ok, reason = self._run(18, 0)
        assert ok is False
        assert "time_window_till" in reason

    def test_after_till(self):
        ok, _ = self._run(22, 0)
        assert ok is False


# ---------------------------------------------------------------------------
# max_executions_per_day
# ---------------------------------------------------------------------------

class TestMaxExecutionsPerDay:
    def test_under_limit_executes(self):
        m = _metric(max_executions_per_day=5)
        ok, _ = should_execute(m, run_counter=1, execution_count=4)
        assert ok is True

    def test_at_limit_skips(self):
        m = _metric(max_executions_per_day=5)
        ok, reason = should_execute(m, run_counter=1, execution_count=5)
        assert ok is False
        assert "max_executions_per_day" in reason

    def test_over_limit_skips(self):
        m = _metric(max_executions_per_day=3)
        ok, _ = should_execute(m, run_counter=1, execution_count=100)
        assert ok is False

    def test_zero_means_no_limit(self):
        m = _metric(max_executions_per_day=0)
        ok, _ = should_execute(m, run_counter=1, execution_count=9999)
        assert ok is True

    def test_none_means_no_limit(self):
        m = _metric(max_executions_per_day=None)
        ok, _ = should_execute(m, run_counter=1, execution_count=9999)
        assert ok is True

    def test_limit_one(self):
        m = _metric(max_executions_per_day=1)
        ok, _ = should_execute(m, run_counter=1, execution_count=0)
        assert ok is True
        ok2, _ = should_execute(m, run_counter=2, execution_count=1)
        assert ok2 is False


# ---------------------------------------------------------------------------
# run_frequency — integer
# ---------------------------------------------------------------------------

class TestRunFrequencyInt:
    def test_frequency_1_always_runs(self):
        m = _metric(run_frequency=1)
        for i in range(1, 15):
            ok, _ = should_execute(m, run_counter=i, execution_count=0)
            assert ok is True, f"freq=1 run={i}"

    def test_frequency_0_always_runs(self):
        m = _metric(run_frequency=0)
        for i in range(1, 15):
            ok, _ = should_execute(m, run_counter=i, execution_count=0)
            assert ok is True, f"freq=0 run={i}"

    @pytest.mark.parametrize("counter,expected", [
        (1, True), (2, False), (3, True), (4, False), (5, True), (6, False),
    ])
    def test_frequency_2_alternates(self, counter, expected):
        m = _metric(run_frequency=2)
        ok, _ = should_execute(m, run_counter=counter, execution_count=0)
        assert ok is expected, f"freq=2 run={counter}"

    @pytest.mark.parametrize("counter,expected", [
        (1, True), (2, False), (3, False), (4, False), (5, False),
        (6, True), (7, False), (11, True),
    ])
    def test_frequency_5(self, counter, expected):
        m = _metric(run_frequency=5)
        ok, _ = should_execute(m, run_counter=counter, execution_count=0)
        assert ok is expected, f"freq=5 run={counter}"

    def test_skip_reason_contains_key_info(self):
        m = _metric(run_frequency=3)
        ok, reason = should_execute(m, run_counter=2, execution_count=0)
        assert ok is False
        assert "run_frequency" in reason
        assert "run=2" in reason


# ---------------------------------------------------------------------------
# run_frequency — "even" / "odd"
# ---------------------------------------------------------------------------

class TestRunFrequencyString:
    @pytest.mark.parametrize("counter", [2, 4, 6, 8, 100])
    def test_even_runs_on_even_counters(self, counter):
        m = _metric(run_frequency="even")
        ok, _ = should_execute(m, run_counter=counter, execution_count=0)
        assert ok is True, f"even counter={counter}"

    @pytest.mark.parametrize("counter", [1, 3, 5, 7, 99])
    def test_even_skips_odd_counters(self, counter):
        m = _metric(run_frequency="even")
        ok, _ = should_execute(m, run_counter=counter, execution_count=0)
        assert ok is False, f"even counter={counter}"

    @pytest.mark.parametrize("counter", [1, 3, 5, 7, 99])
    def test_odd_runs_on_odd_counters(self, counter):
        m = _metric(run_frequency="odd")
        ok, _ = should_execute(m, run_counter=counter, execution_count=0)
        assert ok is True, f"odd counter={counter}"

    @pytest.mark.parametrize("counter", [2, 4, 6, 8, 100])
    def test_odd_skips_even_counters(self, counter):
        m = _metric(run_frequency="odd")
        ok, _ = should_execute(m, run_counter=counter, execution_count=0)
        assert ok is False, f"odd counter={counter}"


# ---------------------------------------------------------------------------
# Compound constraints
# ---------------------------------------------------------------------------

class TestCompound:
    def test_time_and_max_both_pass(self):
        m = _metric(time_window_from="0800", max_executions_per_day=5)
        with patch("zabbig_client.scheduler.current_minutes", return_value=_mins(10, 0)):
            ok, _ = should_execute(m, run_counter=1, execution_count=3)
        assert ok is True

    def test_time_fails_first(self):
        """A time window failure returns before checking quota."""
        m = _metric(time_window_from="2000", max_executions_per_day=5)
        with patch("zabbig_client.scheduler.current_minutes", return_value=_mins(10, 0)):
            ok, reason = should_execute(m, run_counter=1, execution_count=0)
        assert ok is False
        assert "time_window_from" in reason

    def test_quota_exceeded_before_frequency_check(self):
        """Quota exhausted — frequency check is not reached."""
        m = _metric(max_executions_per_day=5, run_frequency=2)
        ok, reason = should_execute(m, run_counter=1, execution_count=5)
        assert ok is False
        assert "max_executions_per_day" in reason

    def test_quota_ok_frequency_fails(self):
        m = _metric(max_executions_per_day=5, run_frequency=2)
        ok, reason = should_execute(m, run_counter=2, execution_count=0)
        assert ok is False
        assert "run_frequency" in reason

    def test_all_four_constraints_passing(self):
        m = _metric(
            time_window_from="0800",
            time_window_till="2000",
            max_executions_per_day=10,
            run_frequency=2,
        )
        with patch("zabbig_client.scheduler.current_minutes", return_value=_mins(12, 0)):
            ok, _ = should_execute(m, run_counter=1, execution_count=3)
        assert ok is True
