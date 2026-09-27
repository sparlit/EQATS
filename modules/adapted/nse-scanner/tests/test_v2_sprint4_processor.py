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


from dataclasses import replace

from v2.lifecycle import TradeState, new_position, transition
from v2.lifecycle_processor import horizon_trailing_stop, process_daily_bar
from v2.portfolio_message import render_portfolio_message


def ready_position():
    position = new_position("TEST", "SWING_1_3M", "2026-01-01", 100, 95, 110, 120, 10)
    return transition(position, "QUALIFY", "2026-01-01", price=99)


def open_position():
    return transition(ready_position(), "ENTER", "2026-01-02", price=100)


def test_ready_position_enters_and_carries_forward():
    events = process_daily_bar(ready_position(), "2026-01-02", {"low": 98, "high": 102, "close": 101})
    assert [event.event_type for event in events] == ["ENTER", "MARK"]
    assert events[-1].position.state == TradeState.OPEN


def test_same_bar_entry_stop_collision_is_conservative():
    events = process_daily_bar(ready_position(), "2026-01-02", {"low": 94, "high": 102, "close": 99})
    assert [event.event_type for event in events] == ["ENTER", "STOP_HIT"]
    assert events[-1].position.state == TradeState.CLOSED
    assert events[-1].position.exit_price == 95


def test_stop_wins_when_stop_and_targets_are_inside_same_bar():
    events = process_daily_bar(open_position(), "2026-01-03", {"low": 94, "high": 125, "close": 115})
    assert [event.event_type for event in events] == ["STOP_HIT"]
    assert events[-1].position.exit_price == 95


def test_t1_then_t2_can_close_on_same_bar_without_stop_touch():
    events = process_daily_bar(open_position(), "2026-01-03", {"low": 99, "high": 121, "close": 118})
    assert [event.event_type for event in events] == ["T1_HIT", "T2_HIT"]
    assert events[-1].position.state == TradeState.CLOSED
    assert events[-1].position.exit_price == 120


def test_partial_position_trails_by_horizon_atr():
    partial = transition(open_position(), "T1_HIT", "2026-01-03", price=110)
    events = process_daily_bar(
        partial,
        "2026-01-04",
        {"low": 104, "high": 115, "close": 114, "atr14": 4},
    )
    assert [event.event_type for event in events] == ["TRAIL"]
    assert events[-1].position.stop == 106
    assert events[-1].position.state == TradeState.TRAILING


def test_message_two_contains_position_state_and_levels():
    position = replace(open_position(), last_price=105)
    message = render_portfolio_message([position], "2026-01-03")
    assert "NSE V3 — PORTFOLIO LIFECYCLE" in message
    assert "TEST" in message
    assert "State: OPEN" in message
    assert "Initial Stop: ₹95.00" in message
    assert "Target 2: ₹120.00" in message
    assert position.trade_id in message
