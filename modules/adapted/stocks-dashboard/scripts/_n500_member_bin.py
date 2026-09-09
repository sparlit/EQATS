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
"""Point-in-time N500 membership from docs/stock_data.bin indicesHistory (120 snapshots,
2002-10-02->date after STEP M1+M2). Same interface used across the rev-mission worktree:
membership(yyyymmdd) -> set of rename-normed symbols.
"""
import gzip
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

rmap = json.load(open(os.path.join(HERE, "_rename_map.json"), encoding="utf8"))


def norm(s):
    s = str(s).strip().upper()
    seen = set()
    while s in rmap and s not in seen and rmap[s] != s:
        seen.add(s)
        s = rmap[s]
    return s


def _load():
    D = json.loads(gzip.decompress(open(os.path.join(ROOT, "docs", "stock_data.bin"), "rb").read()))
    snaps = [
        (
            s["effectiveDate"].replace("-", ""),
            frozenset(norm(x) for x in s["symbols"] if not str(x).upper().startswith("DUMMY")),
        )
        for s in D["indicesHistory"]["Nifty 500"]
    ]
    snaps.sort()
    return snaps


_SNAPS = None


def membership(D):
    """Members as of yyyymmdd int: the nearest snapshot AT OR BEFORE the date."""
    global _SNAPS
    if _SNAPS is None:
        _SNAPS = _load()
    d = str(D)
    best = None
    for ed, syms in _SNAPS:
        if ed <= d:
            best = syms
        else:
            break
    return set(best) if best else set()
