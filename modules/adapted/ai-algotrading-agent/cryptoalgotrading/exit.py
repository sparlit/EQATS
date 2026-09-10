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
exit.py

Example exit functions.
"""


def cross_smas(data, smas=None, emas=None):
    """
    Checks if it's an exit point based on crossed smas.
    """
    if emas is None:
        emas = [10]
    if smas is None:
        smas = [10, 20]
    if (
        data.Last.rolling(smas[0]).mean().iloc[-1] < data.Last.rolling(smas[1]).mean().iloc[-1]
        and data.Last.rolling(smas[0]).mean().iloc[-2] > data.Last.rolling(smas[1]).mean().iloc[-2]
    ):
        return True

    return False
