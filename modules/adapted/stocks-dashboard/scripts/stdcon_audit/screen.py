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
"""Screen for std-slot-holds-con suspects.

Rule (as specified by the user, reproduced verbatim):
  * consider quarters where BOTH std and con PAT are stored
  * divergent = abs(con-std) > max(0.05, 0.001*abs(std))
  * a company with >=3 divergent quarters, and EXACT-equality quarters SANDWICHED between
    divergent ones (a divergent quarter both before AND after), is suspect.
This is a SCREEN, not a defect count.
"""
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")


def divergent(std, con):
    return abs(con - std) > max(0.05, 0.001 * abs(std))


def screen(fund):
    out = {}
    for sym, rows in fund.items():
        pairs = [(r[0], r[1], r[3]) for r in rows if len(r) >= 4 and r[1] is not None and r[3] is not None]
        pairs.sort()
        if len(pairs) < 4:
            continue
        flags = [divergent(s, c) for _, s, c in pairs]
        ndiv = sum(flags)
        if ndiv < 3:
            continue
        first_div = flags.index(True)
        last_div = len(flags) - 1 - flags[::-1].index(True)
        # "equality" here = NON-DIVERGENT under the stated tolerance (this is what reproduces
        # the user's 775-co / 3,073-cell screen; a bit-exact test gives only 414/1,339).
        sand = [pairs[i][0] for i in range(first_div + 1, last_div) if not flags[i]]
        if sand:
            out[sym] = {"n_div": ndiv, "n_pairs": len(pairs), "cells": sand}
    return out


if __name__ == "__main__":
    fund = json.load(open(FUND))
    res = screen(fund)
    tot = sum(len(v["cells"]) for v in res.values())
    print("suspect companies: %d | suspect cells: %d" % (len(res), tot))
    top = sorted(res.items(), key=lambda kv: -len(kv[1]["cells"]))[:15]
    for s, v in top:
        print("  %-12s %3d cells (div %d/%d)" % (s, len(v["cells"]), v["n_div"], v["n_pairs"]))
    json.dump(
        res,
        open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_screen.json"), "w"),
        indent=0,
        sort_keys=True,
    )
