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
"""Apply the attributable-to-owners switch to docs/sf_fundamentals.json using the owners' figures
computed from the local XBRL cache (_reattr_owners.json: "SYMBOL|qe" -> owners cr). Sets npCon
(consolidated profit) to the parent owners' share wherever it differs from the stored total PAT;
leaves everything else (standalone, no-minority, backfilled quarters) untouched. Atomic write.

Run: python -X utf8 apply_reattr.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
F = os.path.join(ROOT, "docs", "sf_fundamentals.json")


def main():
    live = json.load(open(F))
    owners = json.load(open(os.path.join(HERE, "_reattr_owners.json")))
    changed = 0
    stocks = set()
    for sym, arr in live.items():
        for row in arr:  # [qe, npStd, annStd, npCon, annCon]
            a = owners.get("%s|%d" % (sym, row[0]))
            if a is not None and row[3] is not None and abs(a - row[3]) > 0.5:
                row[3] = a
                changed += 1
                stocks.add(sym)
    tmp = F + ".tmp"
    json.dump(live, open(tmp, "w"), separators=(",", ":"))
    os.replace(tmp, F)
    print("Applied attributable-to-owners to %d consolidated quarters across %d stocks." % (changed, len(stocks)))


if __name__ == "__main__":
    main()
