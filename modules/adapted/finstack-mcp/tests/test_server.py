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


import json

from finstack.server import TOOL_CATALOG, TOTAL_TOOLS, finstack_info, health_check


def test_tool_catalog_matches_expected_total():
    assert len(TOOL_CATALOG) == 94
    assert TOTAL_TOOLS == 95


def test_finstack_info_reports_catalog_count():
    info = json.loads(finstack_info())

    assert info["tools_available"] == len(TOOL_CATALOG)
    assert len(info["tools"]) == len(TOOL_CATALOG)


def test_health_check_uses_total_tool_count():
    status = health_check()

    assert status["tools"] == TOTAL_TOOLS
