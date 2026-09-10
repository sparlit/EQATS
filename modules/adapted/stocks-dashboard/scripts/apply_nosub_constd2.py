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
"""Fill consolidated = standalone for 11 more N500 companies verified to have no consolidatable
subsidiary (explicit no-sub notes for IRFC/BDL/NETWEB/ATHERENERG; no consolidated filed at Q4/annual
-> regulatory proof of no subsidiary for the rest). Fill-only. Run: python -X utf8 apply_nosub_constd2.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")
MIRROR = os.path.join(HERE, "fundamentals.json")

COMPANIES = [
    "ATHERENERG",
    "BAJAJHFL",
    "BDL",
    "BHARTIHEXA",
    "CASTROLIND",
    "ENRIN",
    "GODIGIT",
    "IRFC",
    "LGEINDIA",
    "NETWEB",
    "TTML",
]
QES = [20250331, 20250630, 20250930, 20251231]


def apply(path):
    d = json.load(open(path))
    filled = 0
    skipped = []
    for sym in COMPANIES:
        rows = d.get(sym)
        if not rows:
            skipped.append((sym, "nosym"))
            continue
        byqe = {r[0]: r for r in rows}
        for qe in QES:
            r = byqe.get(qe)
            if not r:
                skipped.append((sym, qe, "norow"))
                continue
            while len(r) < 5:
                r.append(None)
            if r[1] is None:
                skipped.append((sym, qe, "nostd"))
                continue
            if r[3] is not None:
                skipped.append((sym, qe, "hascon"))
                continue
            r[3] = r[1]
            if r[4] is None:
                r[4] = r[2]
            filled += 1
    json.dump(d, open(path, "w"), separators=(",", ":"))
    return filled, skipped


if __name__ == "__main__":
    f1, s1 = apply(DOCS)
    f2, s2 = apply(MIRROR)
    print("docs filled", f1, "mirror filled", f2)
    if s1:
        print("skipped:", s1)
