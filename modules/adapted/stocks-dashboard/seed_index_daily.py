#!/usr/bin/env python3
"""One-time seeder for docs/index_monthly.json's `daily` window (1W column).

WHY THIS EXISTS
---------------
The Trailing-returns view's 1W column needs a daily close ~7 days back, but the
feed's history is month-end closes only and the nightly top-up
(fetch_index_monthly.py) can only append TODAY's close — so the rolling `daily`
window would take a week to become useful.

NSE does publish per-index daily history, at the same niftyindices.com endpoint
the whole monthly history was backfilled from — but that endpoint is bot-walled
for python (returns HTML/403), so it can only be read as a BROWSER page-context
XHR (see DATA_RUNBOOK §28). Hence the split: the browser dumps a compact
{key: {date: close}} JSON, this script merges it in.

USAGE
  1. Load https://www.niftyindices.com/reports/historical-data in the browser pane.
  2. Run the page-context XHR loop from DATA_RUNBOOK §28, save its output to a file.
  3. python scripts/seed_index_daily.py <that-file.json>

Idempotent: existing dates win only if the seed disagrees (it never does — both
are the same official closes), and the window is trimmed to the newest
DAILY_KEEP sessions exactly like the nightly top-up does.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED = os.path.join(ROOT, "docs", "index_monthly.json")
DAILY_KEEP = 45


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    seed = json.load(open(argv[1], encoding="utf-8"))
    feed = json.load(open(FEED, encoding="utf-8"))
    keys = {ix["key"] for ix in feed["indices"]}
    daily = feed.setdefault("daily", {})

    added, skipped = 0, []
    for key, rows in seed.items():
        if key not in keys:                       # never invent an index the page doesn't render
            skipped.append(key)
            continue
        for date, close in rows.items():
            try:
                v = round(float(close), 2)
            except (TypeError, ValueError):
                continue
            if v <= 0 or len(date) != 10:
                continue
            cell = daily.setdefault(date, {})
            if key not in cell:                   # the nightly top-up's own writes are authoritative
                cell[key] = v
                added += 1

    for d in sorted(daily)[:-DAILY_KEEP]:
        daily.pop(d)
    for d in [d for d, c in daily.items() if not c]:
        daily.pop(d)

    json.dump(feed, open(FEED, "w", encoding="utf-8"), separators=(",", ":"))
    print("seeded %d closes across %d sessions (%s → %s)"
          % (added, len(daily), min(daily) if daily else "-", max(daily) if daily else "-"))
    if skipped:
        print("WARN: ignored unknown index keys:", ", ".join(sorted(skipped)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
