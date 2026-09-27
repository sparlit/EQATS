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


"""Shared request-layer helpers: SSE framing and the cache-aside wrapper every live
scraper call goes through. Imported by routers and services alike - it depends on nothing in
either, which is what keeps it cycle-free."""
import json

from app.core import db


def _sse(obj):
    return f"data: {json.dumps(obj)}\n\n"


def _cached(symbol, kind, ttl_minutes, fetch):
    """Cache-aside for live scraper calls (price/quote/chart/financials) - fetches once, reused
    for ttl_minutes, busted wholesale by POST /api/cache/clear."""
    data = db.get_cached(symbol, kind, ttl_minutes)
    if not _blank(data):
        return data
    data = fetch()
    if not _blank(data):
        db.set_cached(symbol, kind, data)
    return data


def _blank(data):
    """A failed fetch comes back as {"price": None, "changePercent": None}, not an exception.
    Caching it served that blank to every reader for the whole TTL - a watchlist workflow priced
    eight stocks from cache in 5ms, all null. Checked on read too, so a blank already stored is a
    miss rather than another 15 minutes of nulls."""
    return data is None or (isinstance(data, dict) and bool(data) and all(v is None for v in data.values()))
