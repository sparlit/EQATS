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


"""Real-network check — every FUTURES_WATCHLIST ticker must resolve.

TradingView's screener API silently returns 0 rows for a ticker whose
exchange prefix doesn't match how that contract is actually indexed — no
error, just an empty DataFrame. ``CME:ES1!``, ``CME:NQ1!``, ``CME:RTY1!``,
``CME:YM1!`` and ``CME:EMD1!`` looked plausible (they trade on CME/CBOT
under those product codes) but the screener indexes the E-mini contracts
under ``CME_MINI``/``CBOT_MINI``, and CBOT-grouped livestock (``LE1!``,
``HE1!``) is actually indexed under plain ``CME``. Both mistakes made
get_futures_overview/get_futures_category_snapshot return an empty result
for the most commonly requested contracts (NQ, ES, RTY, YM) with no
indication anything was wrong.

Mocks can't catch this — the bug IS the mapping to a real upstream
exchange code. Run explicitly (skipped by default, like the rest of
``tests/stress``):

    pytest -m stress -v
"""

import pytest
from tradingview_mcp.core.services.futures_service import (
    FUTURES_WATCHLIST,
    _tickers_query,
)

pytestmark = pytest.mark.stress

_ALL_TICKERS = [
    (category, symbol) for category, symbols in FUTURES_WATCHLIST.items() for symbol in symbols
]


@pytest.mark.parametrize("category,symbol", _ALL_TICKERS)
def test_watchlist_ticker_resolves_to_real_data(category, symbol):
    count, df = _tickers_query([symbol]).get_scanner_data(timeout=20)
    assert len(df) > 0, (
        f"{symbol!r} in FUTURES_WATCHLIST[{category!r}] returned 0 rows from "
        f"the live screener — wrong exchange prefix for this contract."
    )
    assert df.iloc[0]["name"] == symbol.split(":", 1)[1]
