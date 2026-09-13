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
"""Record Moneycontrol browser-driven reads into scripts/_mc_reads.json.

Same merge-only contract as _vis_add.py (an existing (sym,qe) entry is never overwritten, so
batches are re-runnable). Input on stdin: {SYM: {QE: entry-or-list}}. Each entry carries its own
basis/fin; _apply_reads.py re-anchors every cell against stored sf_fundamentals PAT at apply
time, which is what actually gates the data — a wrong basis assignment here fails the anchor
there instead of writing.

  python -X utf8 scripts/_mc_add.py < batch.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "_mc_reads.json")


def main():
    blob = json.load(sys.stdin)
    d = json.load(open(P, encoding="utf8")) if os.path.exists(P) else {}
    added = dup = 0
    for sym, cells in blob.items():
        t = d.setdefault(sym, {})
        for qe, c in cells.items():
            if qe in t:
                dup += 1
                continue
            t[qe] = c
            added += 1
    json.dump(d, open(P, "w", encoding="utf8"), indent=1, sort_keys=True)
    total = sum(len(v) for v in d.values())
    print("added %d (%d already present); total %d cells across %d syms" % (added, dup, total, len(d)))


if __name__ == "__main__":
    main()
