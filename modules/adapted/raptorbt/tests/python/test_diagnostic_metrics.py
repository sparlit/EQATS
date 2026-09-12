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
Diagnostics a reader can act on, and the conventions they promise.

These metrics exist to answer questions a bare Sharpe cannot: is the edge real
or is it a short-vol illusion, do costs eat it, is the exit giving the move
back, where can a stop sit. That only works if the numbers mean exactly what
they say, so the conventions are pinned here rather than left to the reader:

* skew and excess kurtosis must equal ``scipy.stats`` with ``bias=False``,
  because a caller comparing against a remembered threshold of 3.0 rather than
  0.0 is off by exactly 3.0 and nothing in the number says so;
* ``None`` always means *not measured*, never a measured zero;
* ``mfe_capture_ratio`` is a ratio of sums over winners, gross of costs -- the
  naive form (mean of per-trade ratios, all trades) returns negative nonsense.
"""
