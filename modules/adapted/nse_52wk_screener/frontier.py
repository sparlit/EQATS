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
High-water "frontier" for multi-year / all-time high screening.

For one stock, the frontier is its sequence of TRAILING RECORD highs — the points
where the (adjusted) high was greater than everything after it. It is short (tens
of points, not thousands) yet answers *any* N-year high plus the all-time high:

  * Sorted oldest→newest, prices are non-increasing; the oldest point is the ATH.
  * The N-year high = the OLDEST frontier point whose date is within the last N
    years (its price is the window max; its date is when that high was set).

Daily maintenance is O(1): push today's high, pop any points it dominates.
Nothing here fetches data — callers pass an adjusted-high series.
"""

from datetime import date

import pandas as pd

SEP = "|"  # between points in the encoded string
KV = ":"  # between date and price


def compute_frontier(high_series: pd.Series) -> list[tuple[str, float]]:
    """Return trailing-record highs as [(YYYY-MM-DD, price)], oldest (ATH) first.

    A point qualifies if its high is strictly greater than every later high, so
    for a repeated high level the MOST RECENT occurrence is kept (matches the
    screener's "most recent date the high was touched" convention).
    """
    s = high_series.dropna()
    s = s[s > 0]
    if s.empty:
        return []
    cands: list[tuple[str, float]] = []
    cur_max = float("-inf")
    for dt, price in zip(reversed(s.index), reversed(s.values), strict=False):  # newest → oldest
        p = float(price)
        if p > cur_max:
            cands.append((pd.Timestamp(dt).date().isoformat(), round(p, 2)))
            cur_max = p
    cands.reverse()  # oldest (ATH) → newest
    return cands


def encode_frontier(frontier: list[tuple[str, float]]) -> str:
    """'2015-03-04:1234.5|2020-01-06:1611.8|…' (oldest→newest)."""
    return SEP.join(f"{d}{KV}{p:g}" for d, p in frontier)


def decode_frontier(s) -> list[tuple[str, float]]:
    if not isinstance(s, str) or not s:
        return []
    out: list[tuple[str, float]] = []
    for part in s.split(SEP):
        d, _, p = part.partition(KV)
        if d and p:
            out.append((d, float(p)))
    return out


def ath(frontier: list[tuple[str, float]]) -> tuple[float | None, str | None]:
    """All-time high (price, date) — the oldest frontier point."""
    if not frontier:
        return None, None
    d, p = frontier[0]
    return p, d


def nyear_high(frontier: list[tuple[str, float]], cutoff: str) -> tuple[float | None, str | None]:
    """N-year high (price, date): the oldest frontier point with date >= cutoff.

    `cutoff` = ISO date (today - N years). Frontier is oldest→newest with prices
    non-increasing, so the first point in-window is the window's max.
    """
    if not frontier:
        return None, None
    for d, p in frontier:
        if d >= cutoff:
            return p, d
    # cutoff is after the most recent point (shouldn't happen); use the newest
    d, p = frontier[-1]
    return p, d


def years_cutoff(years: float, today: date | None = None) -> str:
    """ISO date `years` before today (used as the N-year window start)."""
    t = today or pd.Timestamp.now().date()
    return (pd.Timestamp(t) - pd.DateOffset(years=years)).date().isoformat()
