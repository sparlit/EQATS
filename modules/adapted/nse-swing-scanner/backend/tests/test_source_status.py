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


"""Tests for the source_status envelope."""
import pytest
from source_status import SOURCE_STATUSES, make_status, worst_status


def test_make_status_basic():
    s = make_status("nse:bhavcopy", "ok", as_of="2026-07-01", data={"X": 1})
    assert s["source"] == "nse:bhavcopy"
    assert s["status"] == "ok"
    assert s["as_of"] == "2026-07-01"
    assert s["data"] == {"X": 1}
    assert "error" not in s


def test_make_status_unknown_status_rejected():
    with pytest.raises(ValueError):
        make_status("x", "potato")


def test_make_status_with_error():
    s = make_status("nse", "source_failed", error="HTTP 503")
    assert s["status"] == "source_failed"
    assert s["error"] == "HTTP 503"
    assert "as_of" not in s


def test_worst_status_ordering():
    assert worst_status("ok", "ok") == "ok"
    assert worst_status("ok", "fallback_used") == "fallback_used"
    assert worst_status("ok", "source_failed") == "source_failed"
    assert worst_status("flag_only", "source_failed") == "source_failed"
    assert worst_status("ok", "missing") == "missing"
    assert worst_status() == "ok"
