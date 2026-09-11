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
"""Merge a staged SHP backfill (scripts/shp_history_stage.json) into the main
scripts/shp_history.json. Run ONLY when no other fetch_shareholding process is writing.

Rules: per (sym, quarter) — add if missing; if both have it, keep the cell with the newer
submission date (tie -> main wins, it may carry the nsh enrichment). _names fill-only.
ABORTs if the merged file would have fewer cells than main currently does.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "shp_history.json")
STAGE = os.path.join(HERE, "shp_history_stage.json")


def load(path):
    for i in range(8):
        try:
            return json.load(open(path, encoding="utf-8"))
        except (json.JSONDecodeError, PermissionError):
            time.sleep(1 + i)
    return json.load(open(path, encoding="utf-8"))


main, stage = load(MAIN), load(STAGE)
before = sum(len(v) for k, v in main.items() if not k.startswith("_"))

added = updated = kept = 0
per_q = {}
for sym, qs in stage.items():
    if sym.startswith("_") or not isinstance(qs, dict):
        continue
    tgt = main.setdefault(sym, {})
    for qe, cell in qs.items():
        cur = tgt.get(qe)
        if cur is None:
            tgt[qe] = cell
            added += 1
            per_q[qe] = per_q.get(qe, 0) + 1
        elif str(cell[5]) > str(cur[5]):
            tgt[qe] = cell
            updated += 1
        else:
            kept += 1
names = main.setdefault("_names", {})
for s, n in (stage.get("_names") or {}).items():
    names.setdefault(s, n)

after = sum(len(v) for k, v in main.items() if not k.startswith("_"))
if after < before:
    print("ABORT: merge would shrink %d -> %d" % (before, after))
    sys.exit(1)

tmp = MAIN + ".tmp.%d" % os.getpid()
json.dump(main, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
for i in range(10):
    try:
        os.replace(tmp, MAIN)
        break
    except PermissionError:
        time.sleep(1 + i)
print("merged: +%d added, %d updated-newer, %d kept; cells %d -> %d" % (added, updated, kept, before, after))
for qe in sorted(per_q):
    print("  %s +%d" % (qe, per_q[qe]))
