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
"""Apply scripts/ann_cell_fix.json — REVIEWED announce-date corrections — to the fundamentals JSONs.

Row shape: [qe, npStd, annStd, npCon, annCon]; this writes slot 2 (std) or slot 4 (con).

The ann-date sibling of apply_fund_cell_fix.py, for the class the two existing mechanisms cannot
reach: a POPULATED ann that must move LATER. ann_date_fills.json overrides are earlier-only by
design (the NSE-broadcast-lag class, runbook §104), and its normal entries fill only ann==0 —
neither can retire a FABRICATED-EARLY date (a qe+45d default stamped on a pre-listing quarter
whose value measurably was not public then; runbook §99/§108, SYNGENE 2026-08-24).

Entries carry the GATED date (§12 next-trading-day form for post-15:30 disclosures), because this
applier writes the twins directly with no downstream gate pass. Guarded on `was`: idempotent, and
a cell someone else has since moved is reported and left alone. An EMPTY slot (null, or the ann==0
unknown sentinel) is always writable — the scripts/ master mirror holds null anns for rows docs
has dated, and filling an empty slot with a reviewed date clobbers nobody.
`fixed` must be a real post-qe date. Dry run by default.

Usage:  apply_ann_cell_fix.py            # report only
        apply_ann_cell_fix.py --apply    # write docs/sf_fundamentals.json (+ scripts mirror)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(HERE, "ann_cell_fix.json")
TARGETS = [os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(HERE, "fundamentals.json")]
SLOT = {"std": 2, "con": 4}


def main():
    apply = "--apply" in sys.argv
    fixes = json.load(open(LEDGER))["fixes"]
    print(f"ledger: {len(fixes)} reviewed ann-date corrections")

    for path in TARGETS:
        if not os.path.exists(path):
            continue
        fund = json.load(open(path))
        rel = os.path.relpath(path, ROOT)
        applied = already = absent = moved = 0
        for f in fixes:
            sym, qe, slot, fixed = f["sym"], int(f["qe"]), SLOT[f["basis"]], int(f["fixed"])
            if fixed <= qe:
                print(f"  BAD-ENTRY {sym} {qe}: fixed {fixed} <= qe — refused")
                continue
            row = next((r for r in fund.get(sym, []) if r[0] == qe), None)
            if row is None or len(row) <= slot:
                absent += 1
                continue
            cur = row[slot]
            if cur == fixed:
                already += 1
                continue
            # accept: cur equals the recorded `was`, or the slot is empty (None / ann==0 sentinel)
            if not (cur == f["was"] or cur in (None, 0)):
                moved += 1
                print(
                    f"  SKIP {sym} {qe} {f['basis']}: holds {cur}, ledger expected was={f['was']}"
                    f" — re-adjudicate, not forcing"
                )
                continue
            print(f"  {sym} {qe} {f['basis']}: {cur} -> {fixed}")
            if apply:
                row[slot] = fixed
            applied += 1
        print(f"  [{rel}] to-write {applied} | already-correct {already} | cell-absent {absent} | moved-on {moved}")
        if apply and applied:
            json.dump(fund, open(path, "w"), separators=(",", ":"))
            print(f"  wrote {rel}")
    if not apply:
        print("\n(dry run — pass --apply to write)")


if __name__ == "__main__":
    main()
