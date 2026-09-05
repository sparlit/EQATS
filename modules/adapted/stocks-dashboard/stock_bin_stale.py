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

Usage: stock_bin_stale.py COMMITTED_FILE MAX_AGE_DAYS
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


def main():
    committed_path, max_age_days = sys.argv[1], float(sys.argv[2])
    try:
        latest_ts = latest_price_ts(committed_path)
    except Exception as e:
        print(f"stock_data.bin staleness check: treating as stale ({e})")
        return 1

    age_days = (time.time() - latest_ts) / 86400
    if age_days <= max_age_days:
        print(f"docs/stock_data.bin prices are {age_days:.1f}d old (<= {max_age_days}d) — skipping commit")
        return 0
    print(f"docs/stock_data.bin prices are {age_days:.1f}d old (> {max_age_days}d) — will commit fresh copy")
    return 1


if __name__ == "__main__":
    sys.exit(main())
