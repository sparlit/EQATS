"""
Economic & corporate-events calendar — free sources.

Two streams:
  1. Corporate events (results / board meetings) — NSE /api/event-calendar (free).
  2. Macro events (RBI MPC, CPI, GDP, F&O expiry) — curated, since no clean free
     India macro-calendar API exists. F&O expiry is computed (last Thursday).

Both degrade gracefully.
"""
from __future__ import annotations

import calendar as _cal
from datetime import date, datetime, timedelta

import requests
from loguru import logger

NSE_BASE = "https://www.nseindia.com"
NSE_EVENT_API = "https://www.nseindia.com/api/event-calendar"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar",
}


def _parse_date(raw: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def fetch_corporate_events(days_ahead: int = 14, limit: int = 12) -> list[dict]:
    """Upcoming NSE results / board meetings within the next `days_ahead` days."""
    try:
        s = requests.Session()
        s.headers.update(_HEADERS)
        s.get(NSE_BASE, timeout=10)
        r = s.get(NSE_EVENT_API, timeout=12)
        r.raise_for_status()
        rows = r.json()
        today = date.today()
        horizon = today + timedelta(days=days_ahead)
        out = []
        for row in rows:
            d = _parse_date(row.get("date", ""))
            if not d or d < today or d > horizon:
                continue
            out.append({
                "date": d,
                "date_str": d.strftime("%d %b"),
                "symbol": row.get("symbol", ""),
                "company": (row.get("company", "") or "")[:38],
                "purpose": (row.get("purpose", "") or "")[:30],
            })
        out.sort(key=lambda x: x["date"])
        if out:
            return out[:limit]
    except Exception as exc:
        logger.warning("Corporate events direct fetch failed ({}); trying cache", type(exc).__name__)

    # Fallback to the GitHub-Actions-populated cache (NSE blocks datacenter IPs)
    try:
        from data.nse_cache import read_cache
        cached = read_cache().get("corporate") or []
        return [{k: v for k, v in e.items() if k != "date"} for e in cached][:limit]
    except Exception:
        return []


def _last_thursday(year: int, month: int) -> date:
    last_day = _cal.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != 3:   # Thursday = 3
        d -= timedelta(days=1)
    return d


def macro_events(days_ahead: int = 21) -> list[dict]:
    """
    Curated upcoming macro/market events. F&O monthly expiry is computed;
    recurring macro events are flagged 'approx — confirm'.
    """
    today = date.today()
    horizon = today + timedelta(days=days_ahead)
    events: list[dict] = []

    # F&O monthly expiry (last Thursday) for this & next month
    for m_off in (0, 1):
        y = today.year + (today.month - 1 + m_off) // 12
        m = (today.month - 1 + m_off) % 12 + 1
        exp = _last_thursday(y, m)
        if today <= exp <= horizon:
            events.append({"date": exp, "date_str": exp.strftime("%d %b"),
                           "event": "F&O Monthly Expiry", "impact": "HIGH", "note": "NSE derivatives settlement"})

    # Recurring macro placeholders (no free API — flagged approximate)
    macro = [
        ("CPI Inflation (India)", "HIGH", "Released ~12th monthly — confirm"),
        ("RBI MPC Decision",      "HIGH", "Bi-monthly — confirm exact date"),
        ("US Fed / FOMC",         "MED",  "Impacts FII flows — confirm"),
    ]
    for name, impact, note in macro:
        events.append({"date": None, "date_str": "Upcoming", "event": name, "impact": impact, "note": note})

    dated = sorted([e for e in events if e["date"]], key=lambda x: x["date"])
    undated = [e for e in events if not e["date"]]
    return dated + undated


def fetch_calendar(days_ahead: int = 14) -> dict:
    """Combined calendar: corporate events + macro events."""
    return {
        "corporate": fetch_corporate_events(days_ahead=days_ahead),
        "macro": macro_events(),
    }
