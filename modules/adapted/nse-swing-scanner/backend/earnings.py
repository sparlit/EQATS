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
earnings.py
Upcoming-earnings-date lookup for gate-passed names.

The intent is NOT a hard gate — yfinance NSE earnings dates are frequently
missing or stale. This module surfaces the data so the UI can render a
warning chip ("Earnings in N days") and the user can decide.

Resolution chain:
  1. yfinance Ticker.calendar (next earnings date)
  2. yfinance Ticker.get_earnings_dates() — wider net, may surface older
     reported dates plus the next one. We pick the closest strictly-future
     date.

Missing / source-failed status is returned honestly; the UI must fail-open
(no chip rendered) rather than auto-blocking a PASS.
"""

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Optional

from cache import cached_call
from source_status import make_status

# Earnings within this many days of the scan are surfaced as a warning.
# Outside the window, the chip is hidden (data still fetched for caching).
EARNINGS_WARN_DAYS = 14
# TTL for the earnings cache — yfinance earnings dates change rarely,
# but caching too long means we miss a fresh announcement.
EARNINGS_CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 hours


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v]


def _to_date(d) -> date | None:
    """Normalise yfinance date-ish values (datetime.date, datetime.datetime,
    pandas Timestamp, ISO string) to a plain date, or None."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    try:
        return datetime.fromisoformat(str(d)[:10]).date()
    except Exception:
        return None


def _extract_next_earnings_date(yf_ticker: str) -> str | None:
    """
    Try yfinance and return the next future earnings date as an ISO string
    (YYYY-MM-DD), or None when not available.

    Handles both yfinance calendar shapes:
      - modern (>= ~0.2.40): `Ticker.calendar` is a dict,
        {'Earnings Date': [datetime.date(...)], ...}
      - legacy: `Ticker.calendar` is a DataFrame with an 'Earnings Date'
        row label.
    """
    try:
        import yfinance as yf

        t = yf.Ticker(yf_ticker)
    except Exception:
        return None

    today = datetime.now(UTC).date()

    # Primary: Ticker.calendar
    try:
        cal = t.calendar
        candidates = []
        if isinstance(cal, dict):
            candidates = _as_list(cal.get("Earnings Date"))
        elif cal is not None and getattr(cal, "empty", True) is False:
            try:
                candidates = [d for d in _as_list(cal.loc["Earnings Date"]) if d is not None]
            except Exception:
                candidates = []
        future = [d for d in (_to_date(c) for c in candidates) if d and d >= today]
        if future:
            return min(future).isoformat()
    except Exception:
        pass

    # Fallback: get_earnings_dates() returns a DatetimeIndex of past + future dates.
    try:
        dates = t.get_earnings_dates(limit=8)
        if dates is not None and len(dates) > 0:
            future = [d for d in (_to_date(x) for x in dates) if d and d >= today]
            if future:
                return min(future).isoformat()
    except Exception:
        pass

    return None


def fetch_earnings(symbol: str, yf_ticker: str) -> dict:
    """
    Returns a source_status envelope for one symbol.

    Data shape on status='ok':
        { "earnings_date": "2026-08-04", "within_days": 3 }
    On status='missing' / 'source_failed', `data` is None — the UI must
    not render a chip in that case.
    """
    # v2 key: invalidates 12h-TTL "missing" entries written before the
    # dict-calendar fix (1.2.1) so they don't suppress fresh fetches.
    cache_key = f"earnings:v2:{symbol.upper()}"
    result = cached_call(
        cache_key,
        EARNINGS_CACHE_TTL_SECONDS,
        _fetch_earnings_uncached,
        yf_ticker,
    )
    # Always set symbol in the envelope for traceability.
    result["symbol"] = symbol
    return result


def _fetch_earnings_uncached(yf_ticker: str) -> dict:
    iso = _extract_next_earnings_date(yf_ticker)
    if iso is None:
        return make_status(
            source="yfinance:earnings",
            status="missing",
            data=None,
            error="No upcoming earnings date from yfinance",
        )

    try:
        ed = datetime.fromisoformat(iso[:10]).date()
    except Exception:
        return make_status(
            source="yfinance:earnings",
            status="source_failed",
            data=None,
            error=f"Unparseable earnings date from yfinance: {iso!r}",
        )

    within = (ed - datetime.now(UTC).date()).days
    return make_status(
        source="yfinance:earnings",
        status="ok",
        as_of=datetime.now(UTC).isoformat()[:10],
        data={"earnings_date": iso, "within_days": within},
    )
