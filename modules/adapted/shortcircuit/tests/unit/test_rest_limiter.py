from __future__ import annotations

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
Tests for rest_limiter.py — the multi-window REST rate limiter.

Fyers enforces three simultaneous limits (10/s, 200/min, 100k/day). An earlier
revision enforced only the per-second bucket at 8 rps, which sustained is
480/min — 2.4x over the per-minute cap.

Time is patched rather than injected: the PRD is explicit that the module must
not be refactored to accept a clock.
"""


from shortcircuit.broker.rest_limiter import Priority, RateLimiter


def _fixed_clock(monkeypatch, start=1_000_000.0):
    """
    Freeze wall-clock time so window eviction is deterministic. Returns a setter
    so a test can advance time explicitly.
    """
    state = {"now": start}
    monkeypatch.setattr("shortcircuit.broker.rest_limiter.time.time", lambda: state["now"])
    monkeypatch.setattr("shortcircuit.broker.rest_limiter.time.monotonic", lambda: state["now"])
    return state


# window enforcement


def test_grants_up_to_the_per_second_ceiling(monkeypatch):
    clock = _fixed_clock(monkeypatch)
    rl = RateLimiter(per_second=5, per_minute=100, per_day=1000, reserve_second=0, reserve_minute=0)
    for _ in range(5):
        assert rl.acquire(timeout=0) is True
    assert rl.acquire(timeout=0) is False, "6th call within the same second must be refused"
    assert clock["now"] == 1_000_000.0


def test_capacity_returns_after_the_second_rolls(monkeypatch):
    clock = _fixed_clock(monkeypatch)
    rl = RateLimiter(per_second=2, per_minute=100, per_day=1000, reserve_second=0, reserve_minute=0)
    assert rl.acquire(timeout=0) and rl.acquire(timeout=0)
    assert rl.acquire(timeout=0) is False
    clock["now"] += 1.01
    assert rl.acquire(timeout=0) is True


def test_per_minute_ceiling_binds_even_when_the_second_is_clear(monkeypatch):
    """The bug the rewrite fixed: a generous per-second budget overrunning the minute."""
    clock = _fixed_clock(monkeypatch)
    rl = RateLimiter(per_second=10, per_minute=5, per_day=1000, reserve_second=0, reserve_minute=0)
    for i in range(5):
        clock["now"] += 1.01  # a fresh second each time
        assert rl.acquire(timeout=0) is True, f"call {i} should pass"
    clock["now"] += 1.01
    assert rl.acquire(timeout=0) is False, "per-minute cap must bind"


def test_minute_window_is_sliding_not_fixed(monkeypatch):
    """A burst at t=59s must not double-spend into the next wall-clock minute."""
    clock = _fixed_clock(monkeypatch)
    rl = RateLimiter(per_second=10, per_minute=3, per_day=1000, reserve_second=0, reserve_minute=0)
    for _ in range(3):
        clock["now"] += 0.2
        assert rl.acquire(timeout=0) is True
    clock["now"] += 30  # half a minute later, still inside the window
    assert rl.acquire(timeout=0) is False
    clock["now"] += 31  # now the first grants have aged out
    assert rl.acquire(timeout=0) is True


def test_daily_quota_refuses_beyond_the_cap(monkeypatch):
    _fixed_clock(monkeypatch)
    rl = RateLimiter(per_second=100, per_minute=100, per_day=2)
    assert rl.acquire(timeout=0) and rl.acquire(timeout=0)
    assert rl.acquire(timeout=0) is False
    assert rl.total_day_rejections == 1


# priority reservation


def test_high_priority_has_strictly_more_capacity():
    rl = RateLimiter(per_second=10, per_minute=100, reserve_second=3, reserve_minute=30)
    assert rl._capacity(Priority.HIGH) == (10, 100)
    assert rl._capacity(Priority.NORMAL) == (7, 70)


def test_normal_traffic_cannot_consume_the_reserved_headroom(monkeypatch):
    """A stop-loss must not be starved by scanner quote calls."""
    _fixed_clock(monkeypatch)
    rl = RateLimiter(per_second=5, per_minute=100, per_day=1000, reserve_second=2, reserve_minute=0)
    for _ in range(3):
        assert rl.acquire(priority=Priority.NORMAL, timeout=0) is True
    assert rl.acquire(priority=Priority.NORMAL, timeout=0) is False, "reserve exhausted for NORMAL"
    assert rl.acquire(priority=Priority.HIGH, timeout=0) is True, "HIGH may use the reserve"


def test_order_path_priority_is_higher_than_background():
    assert Priority.HIGH > Priority.NORMAL


# telemetry


def test_snapshot_reports_usage_against_caps(monkeypatch):
    _fixed_clock(monkeypatch)
    rl = RateLimiter(
        per_second=10, per_minute=100, per_day=1000, reserve_second=0, reserve_minute=0
    )
    for _ in range(3):
        rl.acquire(timeout=0)
    snap = rl.snapshot()
    assert snap["used_second"] == 3
    assert snap["used_minute"] == 3
    assert snap["cap_minute"] == 100
    assert snap["granted_total"] == 3


def test_timeout_zero_never_blocks(monkeypatch):
    _fixed_clock(monkeypatch)
    rl = RateLimiter(per_second=1, per_minute=10, per_day=100, reserve_second=0, reserve_minute=0)
    assert rl.acquire(timeout=0) is True
    assert rl.acquire(timeout=0) is False  # returns rather than sleeping


# configured singleton


def test_the_shipped_limiter_sits_under_the_documented_broker_limits():
    """Fyers: 10/s, 200/min, 100k/day. Ours must be strictly below each."""
    from shortcircuit.broker.rest_limiter import rest_limiter

    snap = rest_limiter.snapshot()
    assert snap["cap_second"] <= 10
    assert snap["cap_minute"] <= 200
    assert snap["cap_day"] <= 100_000
