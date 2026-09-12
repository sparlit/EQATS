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
"""ATUL con PAT, FY21-FY22: finish putting the series onto the OWNERS convention.

§69 corrected ATUL from Mar-2022 forward. Reading Jun-2021 to settle the one cell flagged there
showed the same defect running back through FY21 and FY22, so both years are closed out here.
Values are `profit for the period - non-controlling interest` at the target column of each
quarter's OWN filing, and both years reconcile EXACTLY against the printed OWNERS subtotal:

    FY21 owners  117.78 + 174.35 + 188.58 + 175.05 = 655.76   (printed) EXACT
    FY22 owners  165.94 + 146.63 + 155.43 + 136.26 = 604.26   (printed) EXACT

Per-cell the split reconciles on the page too: Jun-21 165.15 - (-0.79) = 165.94;
Mar-21 176.67 - 1.62 = 175.05; Jun-20 117.94 - 0.16 = 117.78.

Sep-2020 (174.35) and Dec-2020 (188.58) were ALREADY the owners figures and are left alone --
Dec-2020 is confirmed by subtraction against the FY21 subtotal.

Sep-2021 is the odd one: stored 148.82 matches NEITHER the period (146.12) nor the owners (146.63)
figure, the same stray-number shape as ATUL Dec-22/Mar-24 and KIRLFER Sep-24 (§69a).

sf_revop's patC for these quarters holds OCI/comprehensive-income attribution figures
(4.16 / -36.92 / 130.90 / 114.90), not PAT at all, so both files are written (§69b).

  python -X utf8 scripts/fill2020_tools/apply_atul_fy21_fy22_2026_08_09.py [--apply]
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

# qe -> (period, nci, owners, stored_before_in_fundamentals, note)
FIX = {
    20200630: (117.94, 0.16, 117.78, 117.94, "held the TOTAL"),
    20210331: (176.67, 1.62, 175.05, 176.67, "held the TOTAL"),
    20210630: (165.15, -0.79, 165.94, 165.15, "held the TOTAL"),
    20210930: (146.12, -0.51, 146.63, 148.82, "held 148.82 -- neither the period nor the owners figure"),
    20211231: (156.91, 1.48, 155.43, 156.91, "held the TOTAL"),
}
IDENTITIES = [
    ("ATUL FY21 owners", [117.78, 174.35, 188.58, 175.05], 655.76),
    ("ATUL FY22 owners", [165.94, 146.63, 155.43, 136.26], 604.26),
]


def main():
    dry = "--apply" not in sys.argv
    print("%-10s %9s %8s %9s %9s  %s" % ("quarter", "period", "nci", "owners", "stored", "note"))
    for qe in sorted(FIX):
        p, nc, o, was, note = FIX[qe]
        print("%-10d %9.2f %8.2f %9.2f %9.2f  %s" % (qe, p, nc, o, was, note))
        if abs((p - nc) - o) > 0.02:
            sys.exit("SPLIT BROKEN %d" % qe)
    print()
    for name, parts, total in IDENTITIES:
        s = sum(parts)
        ok = abs(s - total) < 0.02
        print("  %-20s %9.2f vs printed %9.2f  %s" % (name, s, total, "OK" if ok else "*** BROKEN"))
        if not ok:
            sys.exit("identity broken -- refusing to write")

    prior, n = {}, 0
    for paths, idx, keyed in ((FUND, FUND_IDX, False), (REVOP, REVOP_IDX, True)):
        for path in paths:
            d = json.load(open(path, encoding="utf-8"))
            for qe, (p, nc, o, was, note) in FIX.items():
                row = (
                    (d.get("ATUL") or {}).get(str(qe))
                    if keyed
                    else next((r for r in d.get("ATUL", []) if r[0] == qe), None)
                )
                if not row or len(row) <= idx:
                    continue
                cur = row[idx]
                if cur is not None and abs(cur - o) < 0.005:
                    continue
                if not keyed and cur is not None and abs(cur - was) > 0.005:
                    sys.exit("GUARD %d in %s: %s, expected %s" % (qe, os.path.basename(path), cur, was))
                prior.setdefault(str(qe), {})[os.path.basename(path)] = cur
                row[idx] = o
                n += 1
            if not dry:
                json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))

    print("\n%d slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return
    led = json.load(open(LEDGER, encoding="utf-8"))
    for qe, (p, nc, o, was, note) in FIX.items():
        led["cells"]["ATUL|%d|patC" % qe] = {
            "period": p,
            "nci": nc,
            "owners": o,
            "stored_before": was,
            "note": note,
            "prior_per_file": prior.get(str(qe), {}),
        }
    led["_README"].append(
        "2026-08-09 second pass: ATUL FY21+FY22 closed out (Jun-20, Mar-21, Jun-21, Sep-21, Dec-21). "
        "SADBHAV 2020-03-31 was RE-CHECKED and is CORRECT as stored: the Jun-2020 filing prints "
        "Mar-20 period 1280.78 and NCI 394.14 -> owners 886.64, and FY20 owners "
        "-8.07 + -15.94 + -69.79 + 886.63 = 792.83 exactly as printed. The value only looked wrong "
        "because it is a very large genuine one-off -- the RENUKA lesson (runbook §69c)."
    )
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), indent=1)
    print(f"ledger updated -> {LEDGER}")


if __name__ == "__main__":
    main()
