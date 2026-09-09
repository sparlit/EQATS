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
"""Per-session bar-count guard for the dashboard price payload.

DATA_RUNBOOK.md section 1b + section 18. Run after build_compressed.py, BEFORE the commit
step, alongside guard_feed.py.

guard_feed.py checks file SIZE (>=90% of the committed copy). That cannot see a half-loaded
trading day: the 2026-08-05 13:28 IST build lost 3,856 of 2026-07-31's 4,454 bars and still
weighed 99.45% of the good build it replaced, so it sailed through and went live. This guard
counts bars PER SESSION instead.

  CHECK A  regression — a session already published may not lose bars wholesale.
           Fails at <90% of the committed copy. Benign build-to-build churn (Yahoo dropping
           whole symbols from the universe) measured at 96.2% p1 / 97.3% p5 over 40 real
           builds; every observed decrease below 95% was this defect. Cannot wedge the
           pipeline: heal_price_series.py's floor pass makes such a drop structurally
           impossible, so a failure here means something upstream really broke.

  CHECK B  trailing median — no session may sit far below its neighbours.
           Fails at <80% of the median of the previous 20 sessions. The newest session is
           exempt (it is still filling when refresh.yml runs 3x through the evening: measured
           91.9%-96.0% of trailing median across 40 builds). A session that is ALSO below the
           floor in the committed copy is reported as pre-existing and only WARNS — the guard
           refuses new damage, it does not block on damage it inherited.

Exit 0 = safe to commit. Exit 1 = fails the workflow loudly (feed-monitor / auto-rerun pick
it up) and the previous good data stays live.
"""
import datetime as dt
import gzip
import json
import os
import statistics
import subprocess
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW = os.path.join(ROOT, "docs", "dash_slim.bin")

REGRESSION_FLOOR = 0.90  # check A
MEDIAN_FLOOR = 0.80  # check B
MEDIAN_WINDOW = 20
DAY = 86400


def sessions(blob):
    """gzip dash_slim payload -> {iso date: bars}."""
    d = json.loads(gzip.decompress(blob))
    start_ts = d["startTs"]
    cnt = Counter()
    for cs in d["series"].values():
        for o in cs["d"]:
            cnt[o] += 1
    return {dt.datetime.fromtimestamp(start_ts + o * DAY, dt.UTC).date().isoformat(): n for o, n in cnt.items()}


def committed(path):
    """The copy currently in git, or None when there is nothing to compare against."""
    rel = os.path.relpath(path, ROOT)
    res = subprocess.run(["git", "show", f"HEAD:{rel}"], capture_output=True, cwd=ROOT)
    return res.stdout if res.returncode == 0 and res.stdout else None


def main():
    new_path = sys.argv[1] if len(sys.argv) > 1 else NEW
    with open(new_path, "rb") as fh:
        new = sessions(fh.read())
    if len(sys.argv) > 2:
        with open(sys.argv[2], "rb") as fh:
            old_blob = fh.read()
    else:
        old_blob = committed(new_path)
    old = sessions(old_blob) if old_blob else None

    rows = sorted(new.items())
    newest = rows[-1][0] if rows else None
    problems, warnings = [], []

    # ---- check A: no published session may collapse --------------------------------------
    if old is None:
        print("guard_sessions: no committed copy to compare against — CHECK A skipped")
    else:
        old_newest = max(old)
        for date, n in sorted(old.items()):
            if date == old_newest:
                continue  # was still filling when it was committed
            now = new.get(date)
            if now is None:
                continue  # rolled out of the 250-day window
            if now < REGRESSION_FLOOR * n:
                problems.append(
                    f"{date}: {n} -> {now} bars ({now / n:.0%} of the committed copy, "
                    f"floor {REGRESSION_FLOOR:.0%}) — a published session collapsed"
                )

    # ---- check B: no session may sit far below its neighbours -----------------------------
    for i, (date, n) in enumerate(rows):
        if date == newest or i < 5:
            continue
        med = statistics.median(v for _, v in rows[max(0, i - MEDIAN_WINDOW) : i])
        if not med or n >= MEDIAN_FLOOR * med:
            continue
        msg = (
            f"{date}: {n} bars vs trailing-{MEDIAN_WINDOW} median {int(med)} ({n / med:.0%}, floor {MEDIAN_FLOOR:.0%})"
        )
        was = old.get(date) if old else None
        if was is not None and was < MEDIAN_FLOOR * med:
            warnings.append(f"{msg} — pre-existing (committed copy has {was}), not new damage")
        else:
            problems.append(f"{msg} — half-loaded session")

    print(f"guard_sessions: {len(rows)} sessions checked, newest={newest} (exempt, still filling)")
    for w in warnings:
        print(f"  WARN  {w}")
    if problems:
        print("SESSION GUARD FAILED — nothing was committed; the previous good data stays live.")
        for p in problems:
            print(f"  FAIL  {p}")
        print("Diagnosis + fix: DATA_RUNBOOK.md section 1b.")
        return 1
    print("  session bar counts sane")
    return 0


if __name__ == "__main__":
    sys.exit(main())
