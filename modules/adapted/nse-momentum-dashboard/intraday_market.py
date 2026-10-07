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
NIFTY 50 constituents + breadth for the intraday strategy.

Two distinct kinds of "advance/decline" here, deliberately not conflated:

1. `compute_first15_breadth()` -- the number that actually DRIVES the
   day's trade decision (Spec.md §2.2): reconstructed from each NIFTY50
   constituent's own first-15-minute return (09:25-candle close vs
   previous day's close), NOT from NSE's live snapshot endpoint. This
   is locked in once, at 09:30, and never changes for the rest of the
   day -- it's what intraday_strategy.day_bias()/select_candidates()
   consume.
2. `fetch_advance_decline()` -- NSE's own LIVE, continuously-updating
   market-breadth snapshot (whole-day LTP vs previous close, not a
   first-15-min figure). Informational only -- a "how is the market
   doing right now" pulse for the Dashboard, never fed into the
   strategy's own decision. The intraday-pullback-trading project's own
   README notes exactly this distinction: the live endpoint has no
   history, so backtesting (and this port) reconstructs breadth from
   candle data instead.

Reuses nse_api.session() (this dashboard's own cookie-warmed NSE
session, already proven for the corporate-data endpoints) and
sector_universe.py's INDEX_TRACKER_URL host/endpoint convention.
"""


import json
import os
import time

import intraday_strategy as strat
import nse_api
import sector_universe

INDEX_TRACKER_URL = sector_universe.INDEX_TRACKER_URL
NIFTY50_CACHE_PATH = os.path.join("cache", "nifty50_constituents.json")
NIFTY50_CACHE_MAX_AGE_DAYS = 7


def fetch_nifty50_constituents(force_refresh: bool = False) -> list[str]:
    """NIFTY 50 index constituent symbols, via the same getConstituents
    endpoint sector_universe.py already uses for sector indices. Cached
    like every other NSE reference-data fetch in this app -- constituent
    changes happen a few times a year, not intraday."""
    age_days = (
        (time.time() - os.path.getmtime(NIFTY50_CACHE_PATH)) / 86400
        if os.path.exists(NIFTY50_CACHE_PATH)
        else 1e9
    )
    if not force_refresh and age_days < NIFTY50_CACHE_MAX_AGE_DAYS:
        with open(NIFTY50_CACHE_PATH) as f:
            return json.load(f)

    s = nse_api.session()
    r = s.get(
        INDEX_TRACKER_URL,
        params={"functionName": "getConstituents", "index": "NIFTY 50", "noofrecords": 0},
        timeout=15,
    )
    r.raise_for_status()
    symbols = sorted({row["cmSymbol"] for row in r.json().get("data", []) if row.get("cmSymbol")})
    os.makedirs(os.path.dirname(NIFTY50_CACHE_PATH), exist_ok=True)
    with open(NIFTY50_CACHE_PATH, "w") as f:
        json.dump(symbols, f, indent=1)
    return symbols


AD_CACHE_TTL_SECONDS = 15  # breadth doesn't move meaningfully sub-15s; the
# Dashboard's Intraday page calls this from a 1s-refresh st.fragment for
# NIFTY 50 + up to 2 candidate sectors -- without this, that's up to 3
# live NSE requests every single second, which is both pointless (this
# is a "how's the market doing" pulse, not a tick feed) and the likely
# cause of the sector card's periodic multi-second stalls (NSE's own
# host intermittently slow-responds/throttles under that hammering).
_ad_cache: dict[str, tuple[float, dict]] = {}


def fetch_advance_decline(index: str = "NIFTY 50") -> dict:
    """LIVE, informational-only market-breadth snapshot -- NOT what the
    strategy's own day_bias is computed from (see module docstring).
    Returns {"advances", "declines", "unchanged", "total"}. Cached in
    memory for AD_CACHE_TTL_SECONDS per index."""
    cached = _ad_cache.get(index)
    if cached is not None and time.time() - cached[0] < AD_CACHE_TTL_SECONDS:
        return cached[1]
    s = nse_api.session()
    r = s.get(
        INDEX_TRACKER_URL, params={"functionName": "getAdvanceDecline", "index": index}, timeout=15
    )
    r.raise_for_status()
    row = r.json()["data"][0]
    result = {
        "advances": int(row["advance_symbol"]),
        "declines": int(row["decline_symbol"]),
        "unchanged": int(row["unchanged_symbol"]),
        "total": int(row["total_symbol"]),
    }
    _ad_cache[index] = (time.time(), result)
    return result


def compute_first15_breadth(
    nifty50_symbols: list[str], close_0925: dict[str, float], prev_day_close: dict[str, float]
) -> tuple[float, dict[str, float]]:
    """Spec.md §2.2 -- the reconstructed breadth ratio that actually
    drives the day's bias, plus each symbol's own first15_return (also
    reused for candidate ranking within the F&O subset, §2.3).

    close_0925 / prev_day_close: {symbol: price}, both required for a
    symbol for it to count -- a symbol missing from either dict (no
    09:25 candle yet, or no prior close available) is silently excluded
    from the ratio, matching the validated scratch script's own
    dropna(subset=["prev_close", "c930"]) behavior.

    Returns (nifty_ratio, {symbol: ret_first15_pct}) -- nifty_ratio is
    advancers/decliners among NIFTY50 constituents (float("inf") if
    decliners == 0), ready for intraday_strategy.day_bias()."""
    ret_first15: dict[str, float] = {}
    for sym in nifty50_symbols:
        c0925 = close_0925.get(sym)
        prev_close = prev_day_close.get(sym)
        if c0925 is None or prev_close is None or prev_close == 0:
            continue
        ret_first15[sym] = strat.first15_return(c0925, prev_close)

    advancers = sum(1 for v in ret_first15.values() if v > 0)
    decliners = sum(1 for v in ret_first15.values() if v < 0)
    nifty_ratio = advancers / decliners if decliners else float("inf")
    return nifty_ratio, ret_first15
