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


"""Corporate action handling notes and utilities.

yfinance provides an ``Adj Close`` column that applies:
    * Forward split/reverse split adjustments
    * Dividend adjustments (using the proportional method)

What this handles
-----------------
* Stock splits (e.g. 10:1 or 1:5)
* Regular and special cash dividends
* Bonus issues (treated as splits by NSE)

What this does NOT handle reliably
------------------------------------
* Rights issues: yfinance may or may not adjust correctly for rights-issue
  prices at different subscription prices.
* Demergers / spin-offs: the parent company adjustment is often incorrect.
* Scheme of arrangements / mergers: symbol changes are not tracked.
* Stock dividends (non-cash): may not be captured.

These limitations are documented in the README Limitations section.

For a production system, one would use a dedicated corporate action vendor
(e.g. Refinitiv, Bloomberg, or an NSE-certified data feed).  For this POC,
yfinance adjusted prices are accepted with the limitations above noted.

Public API
----------
compute_returns(panel) is in nse_alpha/data/panel.py.
This module provides only documentation and the ``ADJUSTMENT_WARNINGS`` constant.
"""


ADJUSTMENT_WARNINGS: list[str] = [
    "Rights issues: adjustment may be incomplete or incorrect in yfinance.",
    "Demergers / spin-offs: parent company adjustment often wrong.",
    "Scheme of arrangements / mergers: symbol discontinuities not tracked.",
    "Stock dividends (non-cash): may not be captured.",
]


def get_adjustment_caveats() -> list[str]:
    """Return known caveats about yfinance corporate action adjustments."""
    return ADJUSTMENT_WARNINGS.copy()
