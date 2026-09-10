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
"""Merge shard ledgers written by read_con_pat_nse.py --reads <shard.json> into the shared
scripts/con_pat_nse_reads.json. Never overwrites an existing shared entry (a shard only ever holds
keys the shared ledger lacked when the shard started), and reports any collision instead.

  python3 scripts/fill2020_tools/merge_con_reads.py shard1.json shard2.json ...
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
READS = os.path.join(os.path.dirname(HERE), "con_pat_nse_reads.json")


def main():
    shared = json.load(open(READS))
    added = coll = 0
    for p in sys.argv[1:]:
        if not os.path.exists(p):
            print("missing shard", p)
            continue
        for k, v in json.load(open(p)).items():
            if k in shared:
                coll += 1
                if shared[k] != v:
                    print("  COLLISION (kept shared):", k)
                continue
            shared[k] = v
            added += 1
    json.dump(shared, open(READS, "w"), indent=0, sort_keys=True)
    print("merged: %d added, %d already present -> %d entries" % (added, coll, len(shared)))


if __name__ == "__main__":
    main()
