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
"""Check whether the COMMITTED docs/stock_data.bin's price series is stale enough
to warrant committing a freshly-rebuilt copy.

Exit 0  -> committed copy's prices are recent enough: safe to SKIP committing.
Exit 1  -> committed copy's prices are stale (or the file is missing/corrupt):
           COMMIT the fresh copy this run already built.

docs/stock_data.bin (17 MB) is committed on a capped cadence, not every run, to
limit repo growth. That cadence used to be "whichever runs happen to touch the
file" (refresh-membership.yml patching only fnoHistory in place) — which
silently drifted into a ~10-week price freeze while the commit log still looked
like healthy weekly activity, because nothing ever re-checked actual price
recency (DATA_RUNBOOK.md section 103, found 2026-08-20). This checks the ACTUAL
last price date instead of trusting a schedule, so a missed or broken run can
never cause a silent multi-week freeze again — the very next run self-corrects.

Usage: stock_bin_stale.py COMMITTED_FILE MAX_AGE_DAYS [NEW_FILE]   (NEW_FILE: also commit when the symbol set changed)
"""
import gzip
import json
import sys
import time


def latest_price_ts(path):
    d = json.loads(gzip.decompress(open(path, "rb").read()))
    start_ts = d["startTs"]
    mx = 0
    for series in d["series"].values():
        days = series.get("d")
        if days and days[-1] > mx:
            mx = days[-1]
    return start_ts + mx * 86400


def universe_changed(committed_path, new_path):
    """True when the freshly built file lists a different symbol set than the committed one.
    Prices can be days-fresh while the UNIVERSE is stale: on 2026-09-22 the NSE SME platform
    (571 names) joined dash_slim.bin at 17:23 IST, but the committed stock_data.bin (15:31 IST,
    4,929 names) passed the age check for the rest of the day, so every dashboard range that
    pulls the full history dropped every SME name (DATA_RUNBOOK §145). A symbol-set diff is
    the cheapest honest test; the file is committed whenever it moves."""
    old = set(json.loads(gzip.decompress(open(committed_path, "rb").read())).get("meta") or {})
    new = set(json.loads(gzip.decompress(open(new_path, "rb").read())).get("meta") or {})
    added, gone = new - old, old - new
    if added or gone:
        print(
            f"docs/stock_data.bin universe changed: +{len(added)} symbols, -{len(gone)} "
            f"(e.g. +{sorted(added)[:3]} -{sorted(gone)[:3]}) — will commit fresh copy"
        )
        return True
    return False


def main():
    committed_path, max_age_days = sys.argv[1], float(sys.argv[2])
    new_path = sys.argv[3] if len(sys.argv) > 3 else None
    try:
        latest_ts = latest_price_ts(committed_path)
    except Exception as e:
        print(f"stock_data.bin staleness check: treating as stale ({e})")
        return 1
    if new_path:
        try:
            if universe_changed(committed_path, new_path):
                return 1
        except Exception as e:
            print(f"stock_data.bin universe check: treating as stale ({e})")
            return 1

    age_days = (time.time() - latest_ts) / 86400
    if age_days <= max_age_days:
        print(f"docs/stock_data.bin prices are {age_days:.1f}d old (<= {max_age_days}d) — skipping commit")
        return 0
    print(f"docs/stock_data.bin prices are {age_days:.1f}d old (> {max_age_days}d) — will commit fresh copy")
    return 1


if __name__ == "__main__":
    sys.exit(main())
