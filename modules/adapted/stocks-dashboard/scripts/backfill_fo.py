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
"""
One-time (resumable) backfill of NSE participant-wise derivatives OPEN INTEREST
from 02-Jan-2012 (the earliest NSE publishes this report) to today, into
docs/fii_fo.json. Net positions for FII / DII / Pro / Client in index & stock
futures. The FII buy/sell VALUE report (.xls) only exists for recent dates, so
this bulk pass fetches OI only (include_bs=False); the daily fetcher adds buy/sell
for current days.

Safe to re-run: it skips dates already in fii_fo.json and checkpoints every 50
new dates, so an interrupted run resumes where it left off.

Usage:
  python -X utf8 backfill_fo.py [START_YYYY-MM-DD]
"""
import datetime
import json
import os
import sys
import time

import fetch_fii_dii as F

OUT_FO = F.OUT_FO
START = datetime.date(2012, 1, 2)
if len(sys.argv) > 1:
    START = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()


def load():
    try:
        return {r["date"]: r for r in json.load(open(OUT_FO, encoding="utf-8")).get("rows", [])}
    except Exception:
        return {}


def save(fo):
    rows = [fo[d] for d in sorted(fo)]
    json.dump(
        {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows},
        open(OUT_FO, "w", encoding="utf-8"),
        separators=(",", ":"),
    )


def main():
    fo = load()
    print("starting with %d existing rows" % len(fo))
    today = datetime.date.today()
    jar = F._nse_jar()
    d = START
    tried = got = new = 0
    while d <= today:
        key = d.strftime("%Y-%m-%d")
        if d.weekday() < 5 and key not in fo:  # Mon-Fri, not already have it
            tried += 1
            try:
                rec = F.fetch_fo_for_date(d, jar, include_bs=False)
                if rec:
                    rec["date"] = key
                    fo[key] = rec
                    got += 1
                    new += 1
            except Exception:
                pass
            if new and new % 50 == 0:
                save(fo)
                print("  ...checkpoint: %s, %d new this run (%d tried)" % (key, new, tried))
            if tried % 200 == 0:
                jar = F._nse_jar()  # refresh cookie periodically
            time.sleep(0.45)
        d += datetime.timedelta(days=1)
    save(fo)
    rows = sorted(fo)
    print(
        "DONE: %d total rows (%s -> %s); fetched %d/%d this run"
        % (len(fo), rows[0] if rows else "-", rows[-1] if rows else "-", got, tried)
    )


if __name__ == "__main__":
    main()
