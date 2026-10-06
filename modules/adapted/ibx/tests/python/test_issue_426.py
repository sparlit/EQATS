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


"""ibx#426: server version and connection time after connect."""

import re

from ibx import EClient, EWrapper


def test_none_before_connect():
    c = EClient(EWrapper())
    assert c.server_version() is None
    assert c.tws_connection_time() is None


def test_after_connect_and_disconnect():
    c = EClient(EWrapper())
    c._test_connect("TEST123")
    assert c.server_version() == 214
    assert re.fullmatch(r"\d{8} \d{2}:\d{2}:\d{2} \S.*", c.tws_connection_time())
    c.disconnect()
    assert c.server_version() is None
    assert c.tws_connection_time() is None
