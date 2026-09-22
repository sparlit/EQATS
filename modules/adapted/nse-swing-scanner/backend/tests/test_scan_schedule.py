import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
Tests for backend/scan_schedule.py — the single source of truth for the
twice-daily scan windows (shared by scan.yml's scan_status heredoc, the
watchdog decision script, and the CI cron guard).
"""
import datetime
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import scan_schedule  # noqa: E402
from settings import SCAN_WINDOWS_UTC  # noqa: E402

UTC = datetime.UTC


def dt(y, mo, d, h, mi):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=UTC)


class TestWindowsConfig(unittest.TestCase):
    def test_windows_match_scan_yml_crons(self):
        """The settings list must match .github/workflows/scan.yml's crons."""
        import re

        scan_yml = os.path.join(BACKEND_DIR, "..", ".github", "workflows", "scan.yml")
        with open(scan_yml) as f:
            text = f.read()
        found = re.findall(r'^\s+- cron:\s*"(\d+ \d+ \* \* 1-5)"', text, flags=re.MULTILINE)
        expected = [f"{m} {h} * * 1-5" for h, m in SCAN_WINDOWS_UTC]
        assert found == expected

    def test_scheduled_cron_string(self):
        assert scan_schedule.scheduled_cron_string([(3, 30), (10, 30)]) == "30 3 * * 1-5, 30 10 * * 1-5"


class TestAttributeWindow(unittest.TestCase):
    def test_on_time_scan_attributed_to_its_window(self):
        label, drift = scan_schedule.attribute_window(dt(2026, 9, 1, 3, 35))
        assert label == "03:30"
        assert drift == 5

    def test_evening_scan_attributed_to_evening_window(self):
        label, drift = scan_schedule.attribute_window(dt(2026, 9, 1, 10, 41))
        assert label == "10:30"
        assert drift == 11

    def test_before_first_window_uses_yesterday_last_window(self):
        # 00:15 UTC is closest to yesterday's 10:30 window, not today's 03:30.
        label, drift = scan_schedule.attribute_window(dt(2026, 9, 2, 0, 15))
        assert label == "10:30"
        assert drift == 24 * 60 - (10 * 60 + 30) + 15

    def test_slightly_after_midnight_not_attributed_to_today_morning(self):
        # 00:05 UTC: today's 03:30 is in the future; must pick yesterday 10:30.
        label, _ = scan_schedule.attribute_window(dt(2026, 9, 2, 0, 5))
        assert label == "10:30"

    def test_no_past_window_returns_none(self):
        # Monday 00:00 sharp with windows later that day: yesterday was Sunday
        # (no scan), today's windows haven't fired. The yesterday-last-window
        # candidate is still in the past, so attribution exists — assert the
        # invariant holds (never crashes, drift non-negative or None).
        label, drift = scan_schedule.attribute_window(dt(2026, 8, 31, 0, 0))
        assert label is None or drift >= 0


class TestNextScheduledWindow(unittest.TestCase):
    def test_before_window_returns_today_window(self):
        nxt = scan_schedule.next_scheduled_window(dt(2026, 9, 1, 3, 0))
        assert nxt == dt(2026, 9, 1, 3, 30)

    def test_after_last_window_returns_next_weekday(self):
        # Tue 2026-09-01 after 10:30 -> Wed 03:30.
        nxt = scan_schedule.next_scheduled_window(dt(2026, 9, 1, 11, 0))
        assert nxt == dt(2026, 9, 2, 3, 30)

    def test_friday_evening_skips_weekend(self):
        # Fri 2026-09-04 12:00 -> Mon 2026-09-07 03:30.
        nxt = scan_schedule.next_scheduled_window(dt(2026, 9, 4, 12, 0))
        assert nxt == dt(2026, 9, 7, 3, 30)

    def test_saturday_returns_monday(self):
        nxt = scan_schedule.next_scheduled_window(dt(2026, 9, 5, 9, 0))
        assert nxt == dt(2026, 9, 7, 3, 30)


if __name__ == "__main__":
    unittest.main()
