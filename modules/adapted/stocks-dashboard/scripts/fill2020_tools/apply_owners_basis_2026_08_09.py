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
"""ATUL / SADBHAV / RENUKA: put the consolidated PAT series onto the OWNERS convention.

Started as three named suspect cells. Each turned out to be a series that mixes owners with TOTAL,
so each is repaired across its affected window -- the KIRLFER rule (§68): a single-cell fix inside
an inconsistent series is locally right and globally no better.

Every value is `profit for the period - non-controlling interest` at the target column, read off
the quarter's OWN filing (as-reported, never a restated comparative -- §67a), and every window is
closed by a printed full-year or half-year OWNERS subtotal:

  ATUL     FY23 owners 164.52 + 150.91 + 105.10 + 93.56 = 514.09   (printed) EXACT
           FY24 owners 103.35 +  90.32 +  70.94 + 58.41 = 323.02   (printed) EXACT
  SADBHAV  H1FY20 owners      -15.94 + -8.07           = -24.01    (printed) EXACT
  RENUKA   FY20 owners -364.2 + 2817.9 + -208.6 + -146.0 = 2099.1  vs printed 2099.2 (0.1 rounding)

Per-cell the split also reconciles on the page: ATUL Mar-24 58.79 - 0.38 = 58.41; SADBHAV Sep-19
-39.89 - (-23.95) = -15.94; RENUKA Sep-19 2739.6 - (-78.3) = 2817.9.

RENUKA Sep-2019's magnitude is real, not a scale error: the quarter carries a very large one-off,
and the H1 FY20 column prints 2327.9 = 2739.6 + (-411.7) on the same row.

  python -X utf8 scripts/fill2020_tools/apply_owners_basis_2026_08_09.py [--apply]
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

# sym -> qe -> (period, nci, owners, stored_before, note)
FIX = {
    "ATUL": {
        20220331: (136.56, 0.30, 136.26, 136.58, "held the TOTAL"),
        20221231: (102.88, -2.22, 105.10, 136.87, "held 136.87, which is neither basis for this quarter"),
        20230331: (92.21, -1.35, 93.56, 92.21, "held the TOTAL"),
        20240331: (58.79, 0.38, 58.41, 74.90, "held 74.90, which is neither basis for this quarter"),
    },
    "SADBHAV": {
        20190630: (-30.05, -21.98, -8.07, -30.05, "held the TOTAL"),
        20190930: (-39.89, -23.95, -15.94, -39.89, "held the TOTAL"),
    },
    "RENUKA": {
        20190930: (2739.6, -78.3, 2817.9, 2739.6, "held the TOTAL"),
        20200331: (-145.2, 0.8, -146.0, -145.2, "held the TOTAL"),
        20200630: (-35.3, -0.4, -34.9, -35.3, "held the TOTAL"),
    },
}

# printed subtotals the corrected quarters must reproduce
IDENTITIES = [
    ("ATUL FY23 owners", [164.52, 150.91, 105.10, 93.56], 514.09, 0.02),
    ("ATUL FY24 owners", [103.35, 90.32, 70.94, 58.41], 323.02, 0.02),
    ("SADBHAV H1FY20 owners", [-15.94, -8.07], -24.01, 0.02),
    ("RENUKA FY20 owners", [-364.2, 2817.9, -208.6, -146.0], 2099.2, 0.2),
]


def main():
    dry = "--apply" not in sys.argv
    print("%-9s %-10s %9s %8s %9s %9s  %s" % ("sym", "quarter", "period", "nci", "owners", "stored", "note"))
    for sym in FIX:
        for qe in sorted(FIX[sym]):
            p, n, o, was, note = FIX[sym][qe]
            print("%-9s %-10d %9.2f %8.2f %9.2f %9.2f  %s" % (sym, qe, p, n, o, was, note))
            if abs((p - n) - o) > 0.06:
                sys.exit("SPLIT BROKEN %s %d: %.2f - %.2f != %.2f" % (sym, qe, p, n, o))
    print()
    for name, parts, total, tol in IDENTITIES:
        s = sum(parts)
        ok = abs(s - total) <= tol
        print("  %-24s %10.2f vs printed %10.2f  %s" % (name, s, total, "OK" if ok else "*** BROKEN"))
        if not ok:
            sys.exit("identity broken -- refusing to write")

    PRIOR = {}
    n = 0
    for paths, idx, keyed in ((FUND, FUND_IDX, False), (REVOP, REVOP_IDX, True)):
        for path in paths:
            d = json.load(open(path, encoding="utf-8"))
            for sym in FIX:
                for qe, (p, _nc, o, was, note) in FIX[sym].items():
                    if keyed:
                        row = (d.get(sym) or {}).get(str(qe))
                    else:
                        row = next((r for r in d.get(sym, []) if r[0] == qe), None)
                    if not row or len(row) <= idx:
                        continue
                    cur = row[idx]
                    if cur is not None and abs(cur - o) < 0.005:
                        continue
                    # sf_fundamentals is the file `was` was measured against, so a surprise there
                    # aborts. sf_revop is NOT the same number: ATUL's two files disagree at six
                    # quarters (Mar-23 revop holds -105.24, an equity-attribution figure; Mar-24
                    # revop already holds the correct 58.41 while fundamentals has 74.90). The
                    # owners value is document-anchored either way, so revop is overwritten and its
                    # prior value recorded rather than trusted.
                    if not keyed and cur is not None and abs(cur - was) > 0.005:
                        sys.exit("GUARD %s %d in %s: %s, expected %s" % (sym, qe, os.path.basename(path), cur, was))
                    PRIOR.setdefault("%s|%d" % (sym, qe), {})[os.path.basename(path)] = cur
                    row[idx] = o
                    n += 1
            if not dry:
                json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))

    print("\n%d slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return
    json.dump(
        {
            "_README": [
                "ATUL / SADBHAV / RENUKA consolidated PAT put onto the OWNERS convention, 2026-08-09.",
                "owners = profit for the period - non-controlling interest, from each quarter's OWN filing.",
                "Each window is closed by a printed full-year or half-year OWNERS subtotal; see the applier",
                "docstring and runbook §69. Cells NOT changed but suspect: ATUL 20210630 (stored 165.15, the",
                "FY22 owners subtotal 604.26 implies 165.94) and SADBHAV 20200331 (stored 886.63 against a",
                "standalone of 8.18, wildly out of family -- no P&L page located in that filing).",
            ],
            "generated": "2026-08-09",
            "cells": {
                "%s|%d|patC" % (s, q): {
                    "period": v[0],
                    "nci": v[1],
                    "owners": v[2],
                    "stored_before": v[3],
                    "note": v[4],
                    "prior_per_file": PRIOR.get("%s|%d" % (s, q), {}),
                }
                for s in FIX
                for q, v in FIX[s].items()
            },
        },
        open(LEDGER, "w", encoding="utf-8"),
        indent=1,
    )
    print(f"ledger -> {LEDGER}")


if __name__ == "__main__":
    main()
