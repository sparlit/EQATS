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


from tradingview_mcp.core.utils.validators import sanitize_timeframe


def test_sanitize_timeframe_accepts_lowercase_day_week_month():
    assert sanitize_timeframe("1d") == "1D"
    assert sanitize_timeframe("1w") == "1W"
    assert sanitize_timeframe("1m") == "1M"


def test_sanitize_timeframe_accepts_uppercase_with_whitespace():
    assert sanitize_timeframe(" 1D ") == "1D"
    assert sanitize_timeframe(" 1W ") == "1W"
    assert sanitize_timeframe(" 1M ") == "1M"


def test_sanitize_timeframe_preserves_intraday_timeframes():
    assert sanitize_timeframe("5m") == "5m"
    assert sanitize_timeframe("15m") == "15m"
    assert sanitize_timeframe("1h") == "1h"
    assert sanitize_timeframe("4h") == "4h"


def test_sanitize_timeframe_falls_back_to_default():
    assert sanitize_timeframe("invalid", "15m") == "15m"
