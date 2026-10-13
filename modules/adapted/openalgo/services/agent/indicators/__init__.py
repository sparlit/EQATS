from __future__ import annotations

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


"""The agent's indicator catalogue over the Rust-backed ``openalgo.ta`` library.

Three modules, and the split is deliberate:

* :mod:`registry` is the table of facts about the 127 callables on the ``ta``
  singleton: which OHLCV series each one takes, what it returns and in what
  order, and how many bars of warm-up it needs. It is asserted against
  ``dir(ta)`` at import, so an SDK upgrade that adds or removes an indicator
  fails loudly here instead of silently shipping a stale list.
* :mod:`descriptions` is one sentence per indicator, so the catalogue is
  searchable by intent rather than only by method name.
* :mod:`compute` is the single dispatcher every caller goes through. It owns
  the argument coercion, the warm-up padding and the refusals.

Nothing here touches the network, the database or the clock. Candles arrive as
a DataFrame the caller fetched; every decision leaves as a return value. That is
what lets the tool layer, and a test, drive it identically.
"""


__all__ = ["compute", "descriptions", "registry"]
