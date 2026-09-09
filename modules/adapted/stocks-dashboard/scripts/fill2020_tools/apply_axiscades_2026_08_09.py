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
"""AXISCADES 2018-12-31 con PAT: -0.61 -> -0.73 (owners). And why BANCOINDIA still cannot be read.

AXISCADES abstained because its OCR absorbs figures into row captions. Dumping the WHOLE profit
block instead of the matched rows showed the page carries **two attribution blocks**, and we had
been comparing across them:

    IX. PROFIT/(LOSS) AFTER TAX          Dec-18  -0.61      <- total
        Owners of the Company                    -0.73      <- PROFIT attribution
        Non controlling interest                  0.11
    X.  Other Comprehensive Income       Dec-18   2.31
        (total comprehensive income)              1.70      = -0.61 + 2.31
        Owners of the Company                     1.59      <- TCI attribution
        Non controlling interest                  0.11

So sf_revop's **1.59 is total-comprehensive-income attributable to owners — not PAT at all**, and
sf_fundamentals' -0.61 is the TOTAL. The owners PAT is **-0.73**.

Checks: -0.61 - 0.11 = -0.72 against a printed -0.73 (0.01 of lakh->crore rounding), and the FY19
column closes exactly: -7.67 - 0.46 = **-8.13**, precisely the printed owners figure.

BANCOINDIA 2019-03-31 -- STILL UNREADABLE, with a sharper reason than before. All four windows were
swept: the own filing's consolidated pages are a BALANCE SHEET (p3) and auditors' reports (p7/p8),
the Q+1 and Q+4 filings carry only auditor narrative ("total revenues of Rs. ... total net profit of
Rs. ..."), and no consolidated P&L table exists as a text layer in any fetched PDF. Its XBRL has
total 4.87 and owners 14.00 but **no NCI tag**, so the split cannot be validated -- the implied
NCI of -9.13 is arithmetically possible and entirely unconfirmed. screener has no coverage. Not
written.

  python -X utf8 scripts/fill2020_tools/apply_axiscades_2026_08_09.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
FUND = (os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json"))
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
UNCONF = os.path.join(SCRIPTS, "_fund_unconfirmed_cells.json")
LEDGER = os.path.join(SCRIPTS, "owners_basis_heals.json")

SYM, QE, WAS, NOW = "AXISCADES", 20181231, -0.61, -0.73


def main():
    dry = "--apply" not in sys.argv
    n = 0
    for paths, idx, keyed in ((FUND, 3, False), (REVOP, 5, True)):
        for path in paths:
            d = json.load(open(path, encoding="utf-8"))
            row = (d.get(SYM) or {}).get(str(QE)) if keyed else next((r for r in d.get(SYM, []) if r[0] == QE), None)
            if not row or len(row) <= idx or row[idx] is None:
                continue
            if abs(row[idx] - NOW) < 0.005:
                continue
            if abs(row[idx] - WAS) > 0.005:
                sys.exit(f"GUARD {SYM} in {os.path.basename(path)}: {row[idx]} expected {WAS}")
            print("  %-20s %-26s %s -> %s" % ("%s|%d" % (SYM, QE), os.path.basename(path), row[idx], NOW))
            row[idx] = NOW
            n += 1
            if not dry:
                json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    print("\n%d slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return
    u = json.load(open(UNCONF, encoding="utf-8"))
    u["cells"] = [c for c in u["cells"] if not (c["sym"] == SYM and c["qe"] == QE)]
    for c in u["cells"]:
        if c["sym"] == "BANCOINDIA":
            c["why"] = (
                "no consolidated P&L table exists as a text layer in ANY fetched PDF across "
                "all four windows -- the own filing's con pages are a balance sheet and "
                "auditors' reports, Q+1/Q+4 carry only auditor narrative. The XBRL has "
                "total 4.87 and owners 14.00 but NO NCI tag, so the implied -9.13 split is "
                "possible and unconfirmed. screener has no coverage. Needs a different "
                "attachment or a vision read."
            )
    u["_README"].append(
        "2026-08-09 final pass: AXISCADES 20181231 settled at -0.73. Dumping the whole profit block "
        "(not just matched rows) showed TWO attribution blocks -- the mirror's 1.59 was TOTAL "
        "COMPREHENSIVE INCOME attributable to owners, not PAT. Owners PAT = -0.73, confirmed by the "
        "FY19 column closing exactly (-7.67 - 0.46 = -8.13 as printed). 2 remain: BANCOINDIA (no "
        "con P&L in any PDF) and SUBCAPCITY (no BSE listing, §71f)."
    )
    json.dump(u, open(UNCONF, "w", encoding="utf-8"), indent=1)
    led = json.load(open(LEDGER, encoding="utf-8"))
    led["cells"]["%s|%d|patC" % (SYM, QE)] = {
        "owners": NOW,
        "period": WAS,
        "nci": 0.11,
        "stored_before": WAS,
        "note": "Mar-2019 filing p4: two attribution blocks; PROFIT attribution gives owners -0.73 "
        "(total -0.61, NCI 0.11) while the 1.59 in the mirror is the TCI attribution. FY19 "
        "control: -7.67 - 0.46 = -8.13 exactly as printed.",
    }
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), indent=1)
    print("unconfirmed ledger now %d open" % len(u["cells"]))


if __name__ == "__main__":
    main()
