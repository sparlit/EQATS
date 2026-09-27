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


# -*- coding: utf-8 -*-
"""Which session the market first traded a result in — for the results page's "result-day reaction" only.

A filing broadcast after the 15:30 IST close cannot move that day's close: the first session to price it is
the NEXT one. So the reaction of an after-close filer is close(next session) / close(filing day). User
decision 2026-09-27 (runbook §193).

⚠️ This is NOT the visibility date. The midnight rule (runbook §149) stays: a filing counts for the calendar
day it was broadcast, and `ann` keeps that day everywhere. Only the reaction/drift arithmetic in
build_quarterly_results.py / build_bse_results.py asks this module which bar to read.

Evidence, most specific first:
  1. scripts/result_times_cache.json.gz — BSE Result-category broadcasts per day, {YYYYMMDD: {scrip: [NEWS_DT…]}}
     (fetch_filing_times.py --result-dates), plus the month-end cache filing_times_cache.json.gz.
  2. docs/results_feed.json — the last 31 days of filings with their broadcast time, by symbol.
after_close() is True only when EVERY broadcast that company made that day was after 15:30 (a pre-close
filing that day means the market could trade it), False when any was at or before 15:30, and None when there
is no record — callers then keep the filing-day reaction (the old behaviour), never guess.
"""
import bisect
import gzip
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLOSE = "15:30"
_times = None


def _hhmm(ts):
    """'2020-10-30T17:08:23.81' / '2026-09-24 20:30:11' -> '17:08' ('' when unreadable)."""
    s = str(ts or "").replace("T", " ")
    return s[11:16] if len(s) >= 16 else ""


def _load():
    global _times
    if _times is not None:
        return _times
    t = {}  # (key, YYYYMMDD int) -> [HH:MM, ...]; key = scrip or 'SYM:<sym>'
    for name in ("filing_times_cache.json.gz", "result_times_cache.json.gz"):
        try:
            d = json.loads(gzip.decompress(open(os.path.join(HERE, name), "rb").read()))
        except (OSError, ValueError):
            continue
        for day, per in d.items():
            for scrip, stamps in (per or {}).items():
                hs = [h for h in (_hhmm(x) for x in stamps) if h]
                if hs:
                    t.setdefault((str(scrip), int(day)), set()).update(hs)
    try:
        rows = json.load(open(os.path.join(ROOT, "docs", "results_feed.json"), encoding="utf-8")).get("rows", [])
    except (OSError, ValueError):
        rows = []
    for r in rows:  # per row: one malformed row must not drop the rest
        try:
            h = _hhmm(r[2])
            if h:
                t.setdefault(("SYM:" + str(r[0]).upper(), int(str(r[2])[:10].replace("-", ""))), set()).add(h)
        except (ValueError, TypeError, IndexError):
            continue
    _times = t
    return t


def after_close(ann, scrip=None, sym=None):
    """True / False / None (unknown) — see module doc. `ann` is the YYYYMMDD filing day."""
    if not ann:
        return None
    t = _load()
    hs = set()
    if scrip:
        hs |= t.get((str(scrip), int(ann)), set())
    if sym:
        hs |= t.get(("SYM:" + str(sym).upper(), int(ann)), set())
    if not hs:
        return None
    return min(hs) > CLOSE


def reaction_index(dates, ann, after):
    """Index j of the reaction bar in an ascending YYYYMMDD `dates` list: the first session ON/AFTER the
    filing day, or — for an after-close filing made on a trading day — the session after it. None if none."""
    j = bisect.bisect_left(dates, ann)
    if j >= len(dates):
        return None
    if after and dates[j] == ann:
        j = j + 1 if j + 1 < len(dates) else None
    return j
