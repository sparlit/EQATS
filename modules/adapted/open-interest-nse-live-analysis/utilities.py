import datetime
from typing import Any, Dict, List, Optional, Union

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


# The following functions require external dependencies (lxml, requests, matplotlib)
# They are kept as stubs with proper type hints to avoid syntax errors


def nse_data(url: str) -> dict[str, Any]:
    """Fetch and parse NSE option chain data. Requires lxml and requests."""
    msg = "This function requires lxml and requests dependencies"
    raise NotImplementedError(msg)


def bar_graph(url: str, c_p_or_both: str = "both", values_from_mid: int = 7, quantity: str = "OI") -> None:
    """Generate bar graph from NSE data. Requires matplotlib, lxml, requests."""
    msg = "This function requires matplotlib, lxml, and requests dependencies"
    raise NotImplementedError(msg)
