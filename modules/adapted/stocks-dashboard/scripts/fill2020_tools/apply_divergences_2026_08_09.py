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
"""The last named fund-vs-revop divergences, plus the resync that removes the whole class.

THREE THINGS, because measuring the three named cells turned up something much larger.

1. THE NAMED CELLS (+1 the FY identity then required), read from the filings:
     ATUL    2025-09-30  182.37 -> 179.24   period 182.37 - NCI 3.13; H1 FY26 owners
                                            307.01 = 179.24 + 127.77 EXACT
     SADBHAV 2020-12-31  -41.36 -> -24.32   period -41.36 - NCI (-17.04). BOTH files were wrong:
                                            fundamentals held the TOTAL, revop held +24.32 --
                                            the right magnitude with a FLIPPED SIGN
     RENUKA  2020-12-31  -141.1 -> -141.2   period -141.1 - NCI 0.1
     RENUKA  2021-03-31   -44.9 ->  -44.0   period -44.9 - NCI (-0.9); FY21 owners
                                            -34.9 + 105.4 + -141.2 + -44.0 = -114.7 EXACT
   (RENUKA Sep-2020 105.4 was already owners -- it is what makes FY21 close.)

2. THE REAL SCALE. sf_fundamentals npCon and sf_revop patC disagree on **1,372 of 43,731**
   populated cells (3.14%), spread evenly over 2018-2026. 603 are revop == 0.0 against a real
   fundamentals value -- the XBRL owners=0 mis-tag that `apply_owners_full` guards against in
   fundamentals and NOTHING guards in revop. Those are resynced here. 716 are genuinely different
   numbers and 15 have fundamentals == 0.0; both are left alone and reported, because guessing a
   winner is what produced the defects being cleaned up.

3. WHY IT MATTERED. `stock.html` is explicit -- "Net profit comes from sf_fundamentals ... never
   swap in sf_revop's PAT mirror slots" -- and `build_quarterly_results` says the same. But
   `build_discovery.ttm_pat` reads `pick(cell, 5, 4)`, i.e. exactly those mirror slots, so the
   Discovery / Order-Wins TTM P/E was computed off the divergent copy: 298 divergent cells sit in
   the 2025-26 window it uses, across 203 symbols. That is fixed separately in build_discovery.py.

  python -X utf8 scripts/fill2020_tools/apply_divergences_2026_08_09.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
FUND = (os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json"))
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
LEDGER = os.path.join(SCRIPTS, "owners_basis_heals.json")
FUND_IDX, REVOP_IDX = 3, 5

# (sym, qe) -> (period, nci, owners, stored_fund_before, note)
FIX = {
    ("ATUL", 20250930): (182.37, 3.13, 179.24, 182.37, "fundamentals held the TOTAL"),
    ("SADBHAV", 20201231): (
        -41.36,
        -17.04,
        -24.32,
        -41.36,
        "fundamentals held the TOTAL; revop held +24.32, sign-flipped",
    ),
    ("RENUKA", 20201231): (-141.1, 0.1, -141.2, -141.1, "fundamentals held the period"),
    ("RENUKA", 20210331): (-44.9, -0.9, -44.0, -44.9, "fundamentals held the period; needed to close FY21"),
}
IDENTITIES = [
    ("ATUL H1FY26 owners", [179.24, 127.77], 307.01, 0.02),
    ("RENUKA FY21 owners", [-34.9, 105.4, -141.2, -44.0], -114.7, 0.05),
]


def main():
    dry = "--apply" not in sys.argv
    print("%-9s %-10s %9s %8s %9s %9s  %s" % ("sym", "quarter", "period", "nci", "owners", "stored", "note"))
    for (sym, qe), (p, nc, o, was, note) in sorted(FIX.items()):
        print("%-9s %-10d %9.2f %8.2f %9.2f %9.2f  %s" % (sym, qe, p, nc, o, was, note))
        if abs((p - nc) - o) > 0.06:
            sys.exit("SPLIT BROKEN %s %d" % (sym, qe))
    print()
    for name, parts, total, tol in IDENTITIES:
        s = sum(parts)
        ok = abs(s - total) <= tol
        print("  %-22s %9.2f vs printed %9.2f  %s" % (name, s, total, "OK" if ok else "*** BROKEN"))
        if not ok:
            sys.exit("identity broken -- refusing to write")

    # ---- 1. the named cells, into BOTH files ------------------------------------------------
    prior, n = {}, 0
    for paths, idx, keyed in ((FUND, FUND_IDX, False), (REVOP, REVOP_IDX, True)):
        for path in paths:
            d = json.load(open(path, encoding="utf-8"))
            for (sym, qe), (p, nc, o, was, note) in FIX.items():
                row = (
                    (d.get(sym) or {}).get(str(qe)) if keyed else next((r for r in d.get(sym, []) if r[0] == qe), None)
                )
                if not row or len(row) <= idx:
                    continue
                cur = row[idx]
                if cur is not None and abs(cur - o) < 0.005:
                    continue
                if not keyed and cur is not None and abs(cur - was) > 0.005:
                    sys.exit("GUARD %s %d in %s: %s expected %s" % (sym, qe, os.path.basename(path), cur, was))
                prior.setdefault("%s|%d" % (sym, qe), {})[os.path.basename(path)] = cur
                row[idx] = o
                n += 1
            if not dry:
                json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    print("\nnamed cells: %d slot(s)" % n)

    # ---- 2. resync the provably-broken revop==0 cells ----------------------------------------
    fu = json.load(open(FUND[0], encoding="utf-8"))
    authoritative = {}
    for sym, rows in fu.items():
        for r in rows:
            if len(r) > 3 and r[3] is not None:
                authoritative[(sym, r[0])] = r[3]
    resync = 0
    for path in REVOP:
        d = json.load(open(path, encoding="utf-8"))
        for sym, qmap in d.items():
            for q, row in qmap.items():
                if not row or len(row) <= REVOP_IDX:
                    continue
                a = authoritative.get((sym, int(q)))
                # ONLY the unambiguous case: revop says exactly 0.0 while the authoritative file
                # has a real non-zero value. Anything else is a genuine disagreement, not a
                # mis-tag, and is left for adjudication.
                if row[REVOP_IDX] == 0 and a is not None and abs(a) > 0.005:
                    row[REVOP_IDX] = a
                    resync += 1
        if not dry:
            json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    print("revop==0 resynced from sf_fundamentals: %d slot(s)" % resync)

    if dry:
        print("\n(dry run; pass --apply)")
        return
    led = json.load(open(LEDGER, encoding="utf-8"))
    for (sym, qe), (p, nc, o, was, note) in FIX.items():
        led["cells"]["%s|%d|patC" % (sym, qe)] = {
            "period": p,
            "nci": nc,
            "owners": o,
            "stored_before": was,
            "note": note,
            "prior_per_file": prior.get("%s|%d" % (sym, qe), {}),
        }
    led["_README"].append(
        "2026-08-09 third pass: the named fund-vs-revop cells (ATUL Sep-25, SADBHAV Dec-20, RENUKA "
        "Dec-20 +Mar-21). Measuring them found sf_fundamentals and sf_revop disagree on 1,372 of "
        "43,731 populated con-PAT cells (3.14%); the 603 where revop is exactly 0.0 against a real "
        "fundamentals value were resynced, the 716 genuine disagreements and 15 fundamentals==0 "
        "cells are NOT touched. build_discovery's TTM P/E was reading the divergent mirror. §70."
    )
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), indent=1)
    print("ledger updated")


if __name__ == "__main__":
    main()
