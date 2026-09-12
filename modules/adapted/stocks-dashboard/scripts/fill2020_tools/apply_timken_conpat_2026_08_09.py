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
"""TIMKEN consolidated PAT: Dec-2024 and Jun-2025, from the Dec-2025 filing's own columns.

Both cells currently hold TIMKEN's STANDALONE figure in the con slot -- the copy defect
(detect_con_copy). TIMKEN filed standalone only through Sep-2025 and began consolidating with
Dec-2025; that filing is the first to carry restated consolidated COMPARATIVES for the earlier
quarters, which is where these two values come from.

WHY THE READER COULD NOT DO THIS AUTOMATICALLY, and why the read is still trustworthy.
On the consolidated page the PAT row's Dec-2024 token is glyph-corrupted -- it extracts as
"782.0J" -- so no value-matching reader can pick it up. The column is nonetheless pinned, four
independent ways:

  1. THE SAME ROW reproduces two values we already store, exactly: 545.56/10 = 54.56 == stored
     con PAT 2025-12-31, and 935.99/10 = 93.60 == stored con PAT 2025-09-30. That is the §58
     column anchor, twice over, on the row being read.
  2. PBT - tax == PAT holds on every clean column of the same two rows (2565.82, 2718.89,
     4621.94 all reproduce the printed PAT to the paisa). At the Dec-2024 column both inputs are
     clean: 1029.79 - 247.71 = 782.08.
  3. The corrupted token itself begins "782.0", agreeing with 782.08 to four characters.
  4. screener reports 78 for that quarter, independently. 782.08 / 10 = 78.21.

  Jun-2025 comes from the same page's nine-month identity (§45): 9M FY26 2565.82 - Q3 545.56 -
  Q2 935.99 = 1084.27 -> 108.43, against screener's independent 108.

Scale: the statement declares "in Million", so /10 gives crore.
Owners basis: the consolidated statement carries no NCI split, so PAT == owners' PAT.

This is a §2b correction of a wrong NON-NULL value, not a fill. Guard-asserted on the old value
and journalled to con_copy_heals.json, so it is reversible.

  python -X utf8 scripts/fill2020_tools/apply_timken_conpat_2026_08_09.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
JOURNAL = os.path.join(SCRIPTS, "con_copy_heals.json")
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
FUND = (os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json"))
PATC_REVOP, PATC_FUND = 5, 3

CELLS = {
    "TIMKEN|20241231|patC": {
        "was": 74.31,
        "now": 78.21,
        "row": "Net Profit after tax (3-4)",
        "page": 5,
        "scale": 10.0,
        "src": "Dec-2025 filing, consolidated page",
        "confirm": "same row reproduces stored con PAT 54.56 (2025-12-31) and 93.60 (2025-09-30) "
        "exactly; PBT-tax 1029.79-247.71=782.08 and that identity holds on all 3 clean "
        "columns; corrupt token reads '782.0J'; screener 78",
        "reason": "con slot held a copy of standalone (74.31); true consolidated read from the "
        "first filing that carried restated consolidated comparatives",
    },
    "TIMKEN|20250630|patC": {
        "was": 104.22,
        "now": 108.43,
        "row": "Net Profit after tax (3-4)",
        "page": 5,
        "scale": 10.0,
        "src": "Dec-2025 filing, consolidated page (9M identity)",
        "confirm": "9M FY26 2565.82 - Q3 545.56 - Q2 935.99 = 1084.27 -> 108.43; the two "
        "subtrahends are themselves confirmed against stored con PAT; screener 108",
        "reason": "con slot held a copy of standalone (104.22); quarter never filed on a "
        "consolidated basis, recovered by the nine-month identity (runbook §45)",
    },
}


def load(paths):
    return [(p, json.load(open(p, encoding="utf-8"))) for p in paths if os.path.exists(p)]


def main():
    dry = "--apply" not in sys.argv
    jr = json.load(open(JOURNAL, encoding="utf-8")) if os.path.exists(JOURNAL) else {}
    touched = []

    for path, data in load(FUND):
        for key, c in CELLS.items():
            sym, qe, _f = key.split("|")
            row = next((r for r in (data.get(sym) or []) if r[0] == int(qe)), None)
            if row is None or len(row) <= PATC_FUND:
                print("  %-26s %-42s NO ROW" % (key, os.path.basename(path)))
                continue
            cur = row[PATC_FUND]
            if cur is not None and abs(cur - c["now"]) < 0.005:
                print("  %-26s %-42s already %s" % (key, os.path.basename(path), c["now"]))
                continue
            if cur is None or abs(cur - c["was"]) > 0.005:
                sys.exit("GUARD: {} in {} is {}, expected the old value {} -- ABORT".format(key, path, cur, c["was"]))
            row[PATC_FUND] = c["now"]
            touched.append((path, key, cur, c["now"]))
            print("  %-26s %-42s %s -> %s" % (key, os.path.basename(path), cur, c["now"]))
        if not dry:
            json.dump(data, open(path, "w", encoding="utf-8"), separators=(",", ":"))

    for path, data in load(REVOP):
        for key, c in CELLS.items():
            sym, qe, _f = key.split("|")
            row = (data.get(sym) or {}).get(qe)
            if not row or len(row) <= PATC_REVOP:
                continue
            cur = row[PATC_REVOP]
            if cur is not None and abs(cur - c["now"]) < 0.005:
                continue
            # fill-only where the slot is empty; guarded overwrite where it holds the copy
            if cur is not None and abs(cur - c["was"]) > 0.005:
                sys.exit("GUARD: {} revop is {}, expected {} -- ABORT".format(key, cur, c["was"]))
            row[PATC_REVOP] = c["now"]
            touched.append((path, key, cur, c["now"]))
            print("  %-26s %-42s %s -> %s" % (key, os.path.basename(path), cur, c["now"]))
        if not dry:
            json.dump(data, open(path, "w", encoding="utf-8"), separators=(",", ":"))

    print("\n%d slot(s) %s" % (len(touched), "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return
    for key, c in CELLS.items():
        jr[key] = dict(c, applied="2026-08-09")
    json.dump(jr, open(JOURNAL, "w", encoding="utf-8"), indent=1)
    print(f"journalled -> {JOURNAL}")


if __name__ == "__main__":
    main()
