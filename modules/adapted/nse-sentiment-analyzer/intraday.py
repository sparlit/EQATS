import datetime
from typing import Any, Optional

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


"""Intraday trading tools — VWAP, pivot levels, India VIX.

All functions are pure-data: they take inputs, return dicts, and have zero
Streamlit dependencies. Designed to be testable with mocked yfinance calls.
"""

import logging

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    import yfinance as yf

    HAS_DEPS = True
except ImportError:
    pd = None
    yf = None
    HAS_DEPS = False


def compute_vwap(ticker: str) -> dict[str, Any]:
    """Compute VWAP + deviation from intraday 5-min data.

    Fetches today's 5-min OHLCV via yfinance. Returns current price relative
    to VWAP as a % deviation. Positive = price above VWAP (bullish bias),
    negative = below VWAP (bearish bias).

    Args:
        ticker: NSE ticker symbol (e.g. 'RELIANCE', '^INDIAVIX')

    Returns:
        dict with keys: vwap (float|None), price (float|None), deviation_pct (float|None)
    """
    if not HAS_DEPS:
        return {"vwap": None, "price": None, "deviation_pct": None}

    # Indices (^ prefix) don't get .NS suffix; stocks do
    symbol = f"{ticker}.NS" if not ticker.startswith("^") else ticker
    data = yf.download(symbol, period="1d", interval="5m", progress=False, auto_adjust=True)

    if data is None or data.empty or len(data) < 2:
        return {"vwap": None, "price": None, "deviation_pct": None}

    try:
        # VWAP = Sigma(typical_price * volume) / Sigma(volume)
        typ_price = (data["High"] + data["Low"] + data["Close"]) / 3
        vol = data["Volume"]
        vol_sum = vol.sum()
    except (KeyError, TypeError, AttributeError):
        return {"vwap": None, "price": None, "deviation_pct": None}

    # vol_sum can be a Series from MultiIndex columns — check scalar-safe
    try:
        if float(vol_sum) == 0:
            return {"vwap": None, "price": None, "deviation_pct": None}
    except (TypeError, ValueError, AttributeError):
        return {"vwap": None, "price": None, "deviation_pct": None}

    try:
        vwap_val = float((typ_price * vol).sum() / vol_sum)
        current_price = float(data["Close"].iloc[-1])
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        return {"vwap": None, "price": None, "deviation_pct": None}

    deviation = ((current_price - vwap_val) / vwap_val) * 100 if vwap_val else 0.0

    return {
        "vwap": round_to_ist_tick(vwap_val),
        "price": round_to_ist_tick(current_price),
        "deviation_pct": round(deviation, 2),
    }
