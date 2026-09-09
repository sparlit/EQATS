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
"""Build the target list for the staleness campaign (DATA_RUNBOOK §102/§103):
cells whose ann-date is EXACTLY quarter-end + 45 days (the apply_agg_pat_fills.py
CONVENTION signature, confirmed 96.8% of ALL dated pre-2015 cells per that
script's own docstring — an organic filing-date distribution cannot produce
that concentration, so an exact-match is treated as "placeholder, not real").

Output: scripts/_staleness_fix/target_list.json
  { SYMBOL: [ [qe, basis('std'|'con'), current_ann], ... ] }
"""
import datetime
import json


def qe45(qe):
    y, m, d = qe // 10000, (qe // 100) % 100, qe % 100
    return int((datetime.date(y, m, d) + datetime.timedelta(days=45)).strftime("%Y%m%d"))


def main():
    fund = json.load(open("docs/sf_fundamentals.json"))
    targets = {}
    n = 0
    for sym, arr in fund.items():
        rows = []
        for row in arr:
            qe = row[0]
            exp = qe45(qe)
            if row[2] and row[2] == exp:
                rows.append([qe, "std", row[2]])
                n += 1
            if row[4] and row[4] == exp:
                rows.append([qe, "con", row[4]])
                n += 1
        if rows:
            targets[sym] = rows
    json.dump(targets, open("scripts/_staleness_fix/target_list.json", "w"))
    print(f"{n} target cells across {len(targets)} symbols -> scripts/_staleness_fix/target_list.json")


if __name__ == "__main__":
    main()
