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


#!/usr/bin/env python3
"""Re-run match_targets over the CACHED raw rows (v3_raw*.jsonl) — no BSE traffic.
This is what PLAN F4 bought: a classifier tweak re-matches 2,399 symbols in seconds instead of
a 90-minute crawl. Preserves each symbol's scripcode/error metadata from fetch_results.json and
replaces only its matches. Run after ANY change to classify.py, then re-run apply_redating.py."""
import importlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import classify

importlib.reload(classify)
import fetch_and_match as fm

importlib.reload(fm)  # rebind fm.classify_row/row_dates to the reloaded classify

results = json.load(open(os.path.join(HERE, "fetch_results.json")))
targets = json.load(open(os.path.join(HERE, "target_list.json")))

seen = set()
rematched = 0
for shard in ("v3_raw0.jsonl", "v3_raw1.jsonl"):
    p = os.path.join(HERE, shard)
    if not os.path.exists(p):
        continue
    for line in open(p):
        rec = json.loads(line)
        sym = rec["sym"]
        if sym in seen or sym not in targets:
            continue
        seen.add(sym)
        entry = results.get(sym)
        if entry is None or entry.get("error"):
            continue
        entry["matches"] = fm.match_targets(rec["rows"], targets[sym])
        rematched += 1

json.dump(results, open(os.path.join(HERE, "fetch_results.json"), "w"))
print(f"rematched {rematched} symbols from raw cache ({len(seen)} raw records seen, {len(results)} total in results)")
