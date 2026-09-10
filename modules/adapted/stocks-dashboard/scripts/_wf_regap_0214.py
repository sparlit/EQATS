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
"""2002-2014 gap INVENTORY (sizing the next fetch) for the full 2002-date union.
Counts every missing std/con net-profit cell 20020331..20141231 for _full_union_2002.json,
resolved to current symbols. Reports how much data already exists vs must be fetched.
Writes _wf_gaps_0214.json + _wf_bins_0214.json (NOT the live loop's files)."""
import json
import os

data = json.load(open("../docs/sf_fundamentals.json"))
rmap = json.load(open("_rename_map.json"))


def norm(s):
    s = str(s).strip().upper()
    seen = set()
    while s in rmap and s not in seen and rmap[s] != s:
        seen.add(s)
        s = rmap[s]
    return s


union = sorted({norm(s) for s in json.load(open("_full_union_2002.json"))})
QES = [y * 10000 + md for y in range(2002, 2015) for md in (331, 630, 930, 1231)]  # 2002Q4..2014Q4
gaps = {}
have_any = 0
have_cells = 0
miss_cells = 0
for sym in union:
    rec = data.get(sym) or []
    byq = {r[0]: r for r in rec}
    if rec:
        have_any += 1
    g = []
    for q in QES:
        r = byq.get(q)
        miss = []
        if r is None or r[1] is None:
            miss.append("std")
        else:
            have_cells += 1
        if r is None or (r[3] if len(r) > 3 else None) is None:
            miss.append("con")
        else:
            have_cells += 1
        if miss:
            g.append({"qe": q, "miss": miss})
            miss_cells += len(miss)
    if g:
        gaps[sym] = {"gaps": g}
json.dump(gaps, open("_wf_gaps_0214.json", "w"))
json.dump([[s] for s in sorted(gaps)], open("_wf_bins_0214.json", "w"))
print("2002-2014 UNION:", len(union), "companies")
print("  have >=1 stored quarter (any era):", have_any)
print("  cells already present in 2002-2014:", have_cells)
print("  MISSING cells 2002-2014 (std+con):", miss_cells, "across", len(gaps), "companies")
print("  full matrix would be:", len(union) * len(QES) * 2, "cells")
