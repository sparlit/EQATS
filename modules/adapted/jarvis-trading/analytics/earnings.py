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


"""
Earnings Intelligence — a stock's historical post-earnings behavior, computed
from cached earnings dates (fundamentals cache) + the OHLCV cache.

Answers: "TCS reports in 3 days — how does it usually move on results?"
  avg |move| on results day, % of positive reactions, avg 5-day drift after.

Note: results-day move is approximated as the close-to-close change of the
first trading day ON/AFTER the announcement date (announcement time-of-day
isn't in the free data), which captures the reaction bar for NSE names.
"""

import contextlib
from datetime import date, datetime

import numpy as np
from loguru import logger


def earnings_stats(symbol: str, lookback_quarters: int = 8) -> dict | None:
    from data.fundamentals_cache import get_cached_fundamentals
    from data.ohlcv_cache import get_cached_ohlcv

    sym = symbol.upper().replace(".NS", "")
    fund = get_cached_fundamentals(sym) or {}
    dates = fund.get("earnings_dates") or []
    if not dates:
        return None
    today = date.today().isoformat()
    past = [d for d in dates if d < today][-lookback_quarters:]
    future = [d for d in dates if d >= today]

    df = get_cached_ohlcv(f"{sym}.NS")
    if df is None or df.empty:
        return None
    idx = np.array([d.strftime("%Y-%m-%d") for d in df.index])
    closes = df["close"].to_numpy()

    moves, drifts = [], []
    for d in past:
        i = int(np.searchsorted(idx, d))
        if i <= 0 or i >= len(closes):
            continue
        moves.append((closes[i] / closes[i - 1] - 1) * 100)
        j = i + 5
        if j < len(closes):
            drifts.append((closes[j] / closes[i] - 1) * 100)
    if not moves:
        return None

    out = {
        "n": len(moves),
        "avg_abs_move": round(float(np.mean(np.abs(moves))), 2),
        "max_abs_move": round(float(np.max(np.abs(moves))), 2),
        "pct_up": round(float(np.mean([m > 0 for m in moves]) * 100), 0),
        "avg_drift5": round(float(np.mean(drifts)), 2) if drifts else None,
        "last_move": round(float(moves[-1]), 2),
    }
    if future:
        out["next_date"] = future[0]
        with contextlib.suppress(ValueError):
            out["days_to"] = (datetime.strptime(future[0], "%Y-%m-%d").date() - date.today()).days
    return out
