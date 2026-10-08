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


# database/tv_search.py

from database.symbol import SymToken


def search_symbols(symbol, exchange):
    """Look up symbols by exact symbol-exchange match.

    Performs an exact-match query against the ``SymToken`` table
    and returns all rows where both ``symbol`` and ``exchange``
    match the provided values.

    Args:
        symbol: The symbol string to match exactly.
        exchange: The exchange code to match exactly (e.g. ``'NSE'``, ``'NFO'``).

    Returns:
        A list of ``SymToken`` ORM instances matching the query.
    """
    return SymToken.query.filter(SymToken.symbol == symbol, SymToken.exchange == exchange).all()
