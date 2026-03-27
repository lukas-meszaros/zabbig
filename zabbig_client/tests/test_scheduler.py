"""
test_scheduler.py — Unit tests for the per-metric scheduling logic.
"""
import os
import sys
import unittest
from unittest.mock import patch

_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from zabbig_client.models import MetricDef
from zabbig_client.scheduler import parse_hhmm, should_execute, normalise_hhmm, today_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metric(**kwargs) -> MetricDef:
    defaults = dict(
        id="test_metric",
        name="Test",
        enabled=True,
        collector="cpu",
        key="host.test",
        delivery="batch",
        timeout_seconds=10.0,
        error_policy="skip",
    )
    defaults.update(kwargs)
    return MetricDef(**defaults)


def _patch_time(hour: int, minute: int):
    """Context manager: freeze current_minutes() to the given time."""
    import datetime as _dt

    fake_now = _dt.datetime(2026, 3, 27, hour, minute, 0)
    return patch("zabbig_client.scheduler.datetime.datetime") 


def _minutes(h: int, m: int) -> int:
    return h * 60 + m


# ---------------------------------------------------------------------------
# parse_hhmm
# ---------------------------------------------------------------------------

class TestParseHhmm(unittest.TestCase):

    def test_midnight(self):
        self.assertEqual(parse_hhmm("0000"), 0)

    def test_eight_am(self):
        self.assertEqual(parse_hhmm("0800"), 8 * 60)

    def test_end_of_day(self):
        self.assertEqual(parse_hhmm("2359"), 23 * 60 + 59)

    def test_noon(self):
        self.assertEqual(parse_hhmm("1200"), 720)


# ---------------------------------------------------------------------------
# normalise_hhmm
# ---------------------------------------------------------------------------

class TestNormaliseHhmm(unittest.TestCase):

    def test_string_already_padded(self):
        self.assertEqual(normalise_hhmm("0800"), "0800")

    def test_integer_pads(self):
        self.assertEqual(normalise_hhmm(800), "0800")

    def test_integer_no_pad_needed(self):
        self.assertEqual(normalise_hhmm(1800), "1800")


# ---------------------------------------------------------------------------
# should_execute — dry_run bypass
# ---------------------------------------------------------------------------

class TestDryRunBypass(unittest.TestCase):

    def test_dry_run_bypasses_time_window(self):
        m = _make_metric(time_window_from="2300", time_window_till="2359")
        ok, reason = should_execute(m, run_counter=1, execution_count=0, dry_run=True)
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_dry_run_bypasses_max_executions(self):
        m = _make_metric(max_executions_per_day=2)
        ok, reason = should_execute(m, run_counter=1, execution_count=5, dry_run=True)
        self.assertTrue(ok)

    def test_dry_run_bypasses_frequency(self):
        m = _make_metric(run_frequency=10)
        ok, reason = should_execute(m, run_counter=2, execution_count=0, dry_run=True)
        self.assertTrue(ok)

    def test_dry_run_bypasses_even_frequency(self):
        m = _make_metric(run_frequency="even")
        ok, reason = should_execute(m, run_counter=1, execution_count=0, dry_run=True)
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# should_execute — no constraints → always executes
# ---------------------------------------------------------------------------

class TestNoConstraints(unittest.TestCase):

    def test_no_constraints_always_runs(self):
        m = _make_metric()
        for counter in range(1, 20):
            ok, reason = should_execute(m, run_counter=counter, execution_count=0)
            self.assertTrue(ok, f"counter={counter}")
            self.assertIsNone(reason)


# ---------------------------------------------------------------------------
# should_execute — time_window_from
# ---------------------------------------------------------------------------

class TestTimeWindowFrom(unittest.TestCase):

    def _run(self, from_hhmm: str, current_h: int, current_m: int):
        m = _make_metric(time_window_from=from_hhmm)
        with patch("zabbig_client.scheduler.current_minutes",
                   return_value=_minutes(current_h, current_m)):
            return should_execute(m, run_counter=1, execution_count=0)

    def test_before_window_is_skipped(self):
        ok, reason = self._run("0800", 7, 59)
        self.assertFalse(ok)
        self.assertIn("time_window_from", reason)

    def test_exactly_at_window_start_executes(self):
        ok, _ = self._run("0800", 8, 0)
        self.assertTrue(ok)

    def test_after_window_start_executes(self):
        ok, _ = self._run("0800", 14, 30)
        self.assertTrue(ok)

    def test_midnight_from_executes_always(self):
        ok, _ = self._run("0000", 0, 0)
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# should_execute — time_window_till
# ---------------------------------------------------------------------------

class TestTimeWindowTill(unittest.TestCase):

    def _run(self, till_hhmm: str, current_h: int, current_m: int):
        m = _make_metric(time_window_till=till_hhmm)
        with patch("zabbig_client.scheduler.current_minutes",
                   return_value=_minutes(current_h, current_m)):
            return should_execute(m, run_counter=1, execution_count=0)

    def test_before_till_executes(self):
        ok, _ = self._run("1800", 17, 59)
        self.assertTrue(ok)

    def test_exactly_at_till_is_skipped(self):
        ok, reason = self._run("1800", 18, 0)
        self.assertFalse(ok)
        self.assertIn("time_window_till", reason)

    def test_after_till_is_skipped(self):
        ok, reason = self._run("1800", 20, 0)
        self.assertFalse(ok)

    def test_midnight_till_always_skips(self):
        # time_window_till="0000" means "until midnight" i.e. current>=0 always
        ok, reason = self._run("0000", 0, 0)
        self.assertFalse(ok)


# ---------------------------------------------------------------------------
# should_execute — both time_window_from and time_window_till
# ---------------------------------------------------------------------------

class TestTimeWindowBoth(unittest.TestCase):

    def _run(self, current_h: int, current_m: int):
        m = _make_metric(time_window_from="0800", time_window_till="1800")
        with patch("zabbig_client.scheduler.current_minutes",
                   return_value=_minutes(current_h, current_m)):
            return should_execute(m, run_counter=1, execution_count=0)

    def test_inside_window(self):
        ok, _ = self._run(12, 0)
        self.assertTrue(ok)

    def test_before_from(self):
        ok, reason = self._run(7, 59)
        self.assertFalse(ok)
        self.assertIn("time_window_from", reason)

    def test_at_till(self):
        ok, reason = self._run(18, 0)
        self.assertFalse(ok)
        self.assertIn("time_window_till", reason)

    def test_after_till(self):
        ok, _ = self._run(22, 0)
        self.assertFalse(ok)


# ---------------------------------------------------------------------------
# should_execute — max_executions_per_day
# ---------------------------------------------------------------------------

class TestMaxExecutionsPerDay(unittest.TestCase):

    def test_under_limit_executes(self):
        m = _make_metric(max_executions_per_day=5)
        ok, _ = should_execute(m, run_counter=1, execution_count=4)
        self.assertTrue(ok)

    def test_at_limit_skips(self):
        m = _make_metric(max_executions_per_day=5)
        ok, reason = should_execute(m, run_counter=1, execution_count=5)
        self.assertFalse(ok)
        self.assertIn("max_executions_per_day", reason)

    def test_over_limit_skips(self):
        m = _make_metric(max_executions_per_day=3)
        ok, _ = should_execute(m, run_counter=1, execution_count=100)
        self.assertFalse(ok)

    def test_zero_means_no_limit(self):
        m = _make_metric(max_executions_per_day=0)
        ok, _ = should_execute(m, run_counter=1, execution_count=9999)
        self.assertTrue(ok)

    def test_none_means_no_limit(self):
        m = _make_metric(max_executions_per_day=None)
        ok, _ = should_execute(m, run_counter=1, execution_count=9999)
        self.assertTrue(ok)

    def test_limit_of_one(self):
        m = _make_metric(max_executions_per_day=1)
        ok, _ = should_execute(m, run_counter=1, execution_count=0)
        self.assertTrue(ok)
        ok2, reason = should_execute(m, run_counter=2, execution_count=1)
        self.assertFalse(ok2)


# ---------------------------------------------------------------------------
# should_execute — run_frequency (integer)
# ---------------------------------------------------------------------------

class TestRunFrequencyInt(unittest.TestCase):

    def test_frequency_1_always_runs(self):
        m = _make_metric(run_frequency=1)
        for i in range(1, 15):
            ok, _ = should_execute(m, run_counter=i, execution_count=0)
            self.assertTrue(ok, f"freq=1 run={i}")

    def test_frequency_0_always_runs(self):
        m = _make_metric(run_frequency=0)
        for i in range(1, 15):
            ok, _ = should_execute(m, run_counter=i, execution_count=0)
            self.assertTrue(ok, f"freq=0 run={i}")

    def test_frequency_2_alternates(self):
        m = _make_metric(run_frequency=2)
        expected = {1: True, 2: False, 3: True, 4: False, 5: True, 6: False}
        for counter, should in expected.items():
            ok, _ = should_execute(m, run_counter=counter, execution_count=0)
            self.assertEqual(ok, should, f"freq=2 run={counter}")

    def test_frequency_5(self):
        m = _make_metric(run_frequency=5)
        expected = {1: True, 2: False, 3: False, 4: False, 5: False,
                    6: True, 7: False, 11: True}
        for counter, should in expected.items():
            ok, _ = should_execute(m, run_counter=counter, execution_count=0)
            self.assertEqual(ok, should, f"freq=5 run={counter}")

    def test_frequency_skip_reason_included(self):
        m = _make_metric(run_frequency=3)
        ok, reason = should_execute(m, run_counter=2, execution_count=0)
        self.assertFalse(ok)
        self.assertIn("run_frequency", reason)
        self.assertIn("run=2", reason)


# ---------------------------------------------------------------------------
# should_execute — run_frequency (string "even" / "odd")
# ---------------------------------------------------------------------------

class TestRunFrequencyString(unittest.TestCase):

    def test_even_runs_on_even_counters(self):
        m = _make_metric(run_frequency="even")
        for counter in [2, 4, 6, 8, 100]:
            ok, _ = should_execute(m, run_counter=counter, execution_count=0)
            self.assertTrue(ok, f"even counter={counter}")

    def test_even_skips_odd_counters(self):
        m = _make_metric(run_frequency="even")
        for counter in [1, 3, 5, 7, 99]:
            ok, _ = should_execute(m, run_counter=counter, execution_count=0)
            self.assertFalse(ok, f"even counter={counter}")

    def test_odd_runs_on_odd_counters(self):
        m = _make_metric(run_frequency="odd")
        for counter in [1, 3, 5, 7, 99]:
            ok, _ = should_execute(m, run_counter=counter, execution_count=0)
            self.assertTrue(ok, f"odd counter={counter}")

    def test_odd_skips_even_counters(self):
        m = _make_metric(run_frequency="odd")
        for counter in [2, 4, 6, 8, 100]:
            ok, _ = should_execute(m, run_counter=counter, execution_count=0)
            self.assertFalse(ok, f"odd counter={counter}")


# ---------------------------------------------------------------------------
# should_execute — compound constraints
# ---------------------------------------------------------------------------

class TestCompound(unittest.TestCase):

    def test_time_and_max_both_pass(self):
        m = _make_metric(time_window_from="0800", max_executions_per_day=5)
        with patch("zabbig_client.scheduler.current_minutes", return_value=_minutes(10, 0)):
            ok, _ = should_execute(m, run_counter=1, execution_count=3)
        self.assertTrue(ok)

    def test_time_fails_stops_evaluation(self):
        """Even if max quota is fine, a time window failure still skips."""
        m = _make_metric(time_window_from="2000", max_executions_per_day=5)
        with patch("zabbig_client.scheduler.current_minutes", return_value=_minutes(10, 0)):
            ok, reason = should_execute(m, run_counter=1, execution_count=0)
        self.assertFalse(ok)
        self.assertIn("time_window_from", reason)

    def test_max_and_frequency_both_checked(self):
        """Quota exceeded — frequency check is not reached."""
        m = _make_metric(max_executions_per_day=5, run_frequency=2)
        ok, reason = should_execute(m, run_counter=1, execution_count=5)
        self.assertFalse(ok)
        self.assertIn("max_executions_per_day", reason)

    def test_frequency_check_after_quota_passes(self):
        m = _make_metric(max_executions_per_day=5, run_frequency=2)
        # Quota not exceeded but wrong run number
        ok, reason = should_execute(m, run_counter=2, execution_count=0)
        self.assertFalse(ok)
        self.assertIn("run_frequency", reason)


if __name__ == "__main__":
    unittest.main()
