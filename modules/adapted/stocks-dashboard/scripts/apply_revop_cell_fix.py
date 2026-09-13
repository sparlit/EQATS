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
"""Apply scripts/revop_cell_fix.json — REVIEWED revenue value corrections — to the revop JSONs.

The revop analogue of apply_fund_cell_fix.py. Writes docs/sf_revop.json AND the build ledger
scripts/revop_fundamentals.json, so the next incremental build_revop keeps the corrected value.
Basis names map to row slots: std/con = revenue 0/1 (the original pair), op_std/op_con = 2/3,
pat_std/pat_con = 4/5 (the §70 PAT MIRROR — authority for net profit stays sf_fundamentals;
a pat_* entry here only syncs the mirror to a fund_cell_fix heal, added 2026-08-24 SYNGENE).

Guarded on `was`: idempotent, and refuses to overwrite a cell someone else has since moved (that
case is reported and left alone, never forced). Dry run by default.

Usage:  apply_revop_cell_fix.py            # report only
        apply_revop_cell_fix.py --apply    # write
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(HERE, "revop_cell_fix.json")
TARGETS = [os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(HERE, "revop_fundamentals.json")]
SLOT = {
    "std": 0,
    "con": 1,
    "op_std": 2,
    "op_con": 3,
    "pat_std": 4,
    "pat_con": 5,
    "ebit_std": 7,
    "ebit_con": 8,
}  # 7/8 added 2026-08-30 (LODHA 20220331 scale row)
TOL = 0.01


def main():
    apply = "--apply" in sys.argv
    fixes = json.load(open(LEDGER))["fixes"]
    print("ledger: %d reviewed revenue corrections" % len(fixes))
    for path in TARGETS:
        if not os.path.exists(path):
            print(f"  (skip, absent) {os.path.relpath(path, ROOT)}")
            continue
        d = json.load(open(path))
        rel = os.path.relpath(path, ROOT)
        towrite = already = absent = moved = 0
        for f in fixes:
            sym, qe, slot = f["sym"], str(f["qe"]), SLOT[f["basis"]]
            row = (d.get(sym) or {}).get(qe)
            if row is None or len(row) <= slot:
                absent += 1
                continue
            cur = row[slot]
            if cur is not None and abs(cur - f["fixed"]) <= TOL:
                already += 1
                continue
            if cur is None or abs(cur - f["was"]) > TOL:
                moved += 1
                print(
                    "  MOVED-ON {} {} {}: stored {} != was {} — left alone".format(sym, qe, f["basis"], cur, f["was"])
                )
                continue
            print("  {} {} {}: {} -> {}".format(sym, qe, f["basis"], cur, f["fixed"]))
            if apply:
                row[slot] = f["fixed"]
                d[sym][qe] = row
            towrite += 1
        print(
            "  [%s] to-write %d | already-correct %d | cell-absent %d | moved-on %d"
            % (rel, towrite, already, absent, moved)
        )
        if apply and towrite:
            json.dump(d, open(path, "w"), separators=(",", ":"))
            print(f"  wrote {rel}")
    if not apply:
        print("\n(dry run — pass --apply to write)")


if __name__ == "__main__":
    main()
