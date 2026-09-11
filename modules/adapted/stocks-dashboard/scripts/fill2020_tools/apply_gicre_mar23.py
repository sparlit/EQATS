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
"""GICRE 2023-03 consolidated revenue = 10655.87, read by hand from the audited filing pack.

WHY IT WAS "UNFILLABLE": insurer_con_rev.py refuses every GICRE quarter with "std control failed:
filing reads None". That is the READER, not the document. GICRE's text layer is glyph-corrupted in
the LABELS ("OPERA TING RES UL TS", "Premium Earned /Net\\", "/bl Income from investments",
"Profit for the vear") and tears Indian digit groups into separate tokens ("2 72 918"), so generic
label patterns and positional column indexing both miss. The FIGURES are intact.

DOCUMENT: BSE pack GICRE_20230331_123d1145-3066-495c-9929-622844c04090.pdf,
"Audited Statement of Consolidated Financial Results for the Quarter and Twelve Months ended
31/03/2023" (page 21); standalone twin at page 6. Rs in Lakhs -> /100.
Columns: (31/03/2023) (31/12/2022) (31/03/2022) FY(31/03/2023) FY(31/03/2022) — column 1 taken.

THE READ (GI convention, §55: Premium Earned (Net) + policyholders' Income from investments (net)
+ shareholders' Income from investments, row 18(b)):
    con  7,72,396 + 1,74,889 + 1,18,302 = 10,65,587 lakh = 10655.87
    std  7,65,911 + 1,74,909 + 1,14,812 = 10,55,632 lakh = 10556.32

FOUR INDEPENDENT GATES, all passed:
  A5 std control — the SAME filing's standalone page reproduces our stored revS 10556.32 EXACTLY.
     That tests the whole chain (page, column, scale, every revenue leg) against a known answer.
  ANCHOR — the con page's "Profit for the year" column 1 = 2,72,918 lakh = 2729.18 == our stored
     con PAT 2729.18 EXACTLY (this is the post-heal GENUINE anchor; §55c's blocker is gone).
  INTERNAL IDENTITY — the page's own arithmetic: 2,60,928 (profit after tax) + 11,990 (share of
     profit in associates) = 2,72,918. The anchor row is therefore not a coincidental match.
  RATIO FAMILY (§55b) — con/std = 1.0094, inside GICRE's own stored family 1.0000-1.0497 (n=8).

Fill-only, revenue slot (1) only.
Run: python -X utf8 scripts/fill2020_tools/apply_gicre_mar23.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LEDGER = os.path.join(SCRIPTS, "gicre_rev_fills.json")

SYM, QE, VAL = "GICRE", "20230331", 10655.87
EV = (
    "hand read of BSE pack 123d1145 p21 (audited con, Rs lakh/100), col (31/03/2023): "
    "772396+174889+118302=1065587; A5 std control p6 765911+174909+114812=1055632 == stored "
    "revS EXACTLY; anchor 2729.18 == stored con PAT EXACTLY; page identity 260928+11990=272918; "
    "ratio 1.0094 inside stored family 1.0000-1.0497"
)


def main():
    dry = "--apply" not in sys.argv
    for path in (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json")):
        d = json.load(open(path))
        row = d.get(SYM, {}).get(QE)
        if not row:
            print("%-28s no row" % os.path.basename(path))
            continue
        while len(row) < 9:
            row.append(None)
        if row[1] is not None:
            print("%-28s already filled: %s" % (os.path.basename(path), row[1]))
            continue
        row[1] = VAL
        d[SYM][QE] = row
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print("%-28s %s revC=%s" % (os.path.basename(path), "would fill" if dry else "filled", VAL))
    if not dry:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led[f"{SYM}|{QE}|revC"] = {
            "revC": VAL,
            "src": "BSE filing pack GICRE_20230331_123d1145 p21 (hand read)",
            "evidence": EV,
            "precision": "filing",
            "applied": "2026-08-11 GICRE hand read",
        }
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print(f"journalled -> {os.path.basename(LEDGER)}")
    else:
        print("DRY RUN -- nothing written.")


if __name__ == "__main__":
    main()
