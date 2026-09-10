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


from v2.entry_triggers import EntryTrigger, select_primary_trigger


def test_primary_trigger_prefers_qualified_pullback_over_breakout():
    triggers = (
        EntryTrigger("BREAKOUT", True, 95.0, ("breakout",), {}),
        EntryTrigger("QUALIFIED_PULLBACK", True, 72.0, ("pullback",), {}),
    )
    selected = select_primary_trigger(triggers)
    assert selected.name == "QUALIFIED_PULLBACK"


def test_primary_trigger_returns_no_trigger_when_none_actionable():
    triggers = (
        EntryTrigger("BREAKOUT", False, 100.0, ("not_actionable",), {}),
        EntryTrigger("NO_TRIGGER", False, 0.0, ("wait",), {}),
    )
    selected = select_primary_trigger(triggers)
    assert selected.name == "NO_TRIGGER"
    assert selected.actionable is False


def test_trigger_serialization_is_stable():
    trigger = EntryTrigger(
        name="TREND_CONTINUATION",
        actionable=True,
        score=78.0,
        reasons=("daily_and_weekly_trend_aligned",),
        metrics={"qualified_horizons": "3M,6M"},
    )
    payload = trigger.to_dict()
    assert payload["name"] == "TREND_CONTINUATION"
    assert payload["score"] == 78.0
    assert payload["metrics"]["qualified_horizons"] == "3M,6M"
