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


"""Default "Collect max history" source - wraps scraper.get_daily_bars' existing yfinance path.
Was the only source before price_sources existed; kept as its own plugin (rather than a hardcoded
special case) so the registry in __init__.py doesn't need to treat it differently from any
alternate source added later."""
from app.core import scraper

from .errors import SourceError


def fetch_max(symbol):
    """Full available daily history (yfinance period='max'). Returns oldest-first list of
    {date, open, high, low, close, volume} dicts - date as an ISO string, matching
    price_history_max's schema directly."""
    try:
        return scraper.get_daily_bars(symbol, period="max")
    except Exception as e:
        raise SourceError(f"yfinance: {e}") from e
