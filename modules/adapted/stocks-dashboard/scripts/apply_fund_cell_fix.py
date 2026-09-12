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
"""Apply scripts/fund_cell_fix.json — REVIEWED value corrections — to the fundamentals JSONs.

Row shape: [qe, npStd, annStd, npCon, annCon]; this writes slot 1 (std) or slot 3 (con).

Guarded on `was`, so it is idempotent and refuses to overwrite a cell someone else has since
moved (that case is reported and left alone, never forced — same discipline as
fetch_shareholding's apply_cell_fix, whose lesson we learned the hard way today).

Dry run by default, like every other applier in this repo.

Usage:  apply_fund_cell_fix.py            # report only
        apply_fund_cell_fix.py --apply    # write docs/sf_fundamentals.json (+ scripts mirror)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(HERE, "fund_cell_fix.json")
TARGETS = [os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(HERE, "fundamentals.json")]
SLOT = {"std": 1, "con": 3}
TOL = 0.005


def main():
    apply = "--apply" in sys.argv
    fixes = json.load(open(LEDGER))["fixes"]
    print(f"ledger: {len(fixes)} reviewed corrections")

    for path in TARGETS:
        if not os.path.exists(path):
            continue
        fund = json.load(open(path))
        rel = os.path.relpath(path, ROOT)
        applied = already = absent = moved = 0
        for f in fixes:
            sym, qe, slot = f["sym"], int(f["qe"]), SLOT[f["basis"]]
            row = next((r for r in fund.get(sym, []) if r[0] == qe), None)
            if row is None or len(row) <= slot:
                absent += 1
                continue
            cur = row[slot]
            if cur is not None and abs(cur - f["fixed"]) < TOL:
                already += 1
                continue
            if cur is None or abs(cur - f["was"]) > TOL:
                moved += 1
                print(
                    f"  SKIP {sym} {qe} {f['basis']}: holds {cur}, ledger expected was={f['was']}"
                    f" — re-adjudicate, not forcing"
                )
                continue
            print(f"  {sym} {qe} {f['basis']}: {cur} -> {f['fixed']}")
            if apply:
                row[slot] = f["fixed"]
            applied += 1
        print(f"  [{rel}] to-write {applied} | already-correct {already} | cell-absent {absent} | moved-on {moved}")
        if apply and applied:
            json.dump(fund, open(path, "w"), separators=(",", ":"))
            print(f"  wrote {rel}")
    if not apply:
        print("\n(dry run — pass --apply to write)")


if __name__ == "__main__":
    main()
