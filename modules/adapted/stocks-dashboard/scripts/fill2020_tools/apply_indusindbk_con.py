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
"""Residue batch: INDUSINDBK consolidated revenue (Interest Earned) ×4, from the bank's own
consolidated statement pages in the NSE outcome PDFs (scanned, OCR text layer — every landed digit
is anchored against an independently-stored XBRL value or an internal identity).

Why the XBRL routes are dead: the classic index lists con BANKING XBRLs for Mar-23/Jun-23 that 404
(never published); banking + integrated XBRLs are single-period so no comparatives exist (§54).

DOCUMENTS (both scanned; con statement pages have a usable OCR text layer, std pages do not):
  * IIB Jun-23 outcome PDF (INDUSINDBK_18072023153702_FinancialResultsIbl18072023.pdf), page 5:
    "Unaudited Consolidated Financial Results ... June 30, 2023", Rs in lakhs -> /100.
    cols [30.06.2023 | 31.03.2023 | 30.06.2022 | FY 31.03.2023]
    Interest Earned  10,729.65 | 10,020.71 | 8,181.77 | 36,367.92
    Net Profit (12)   2,124.44 |  2,043.36 | 1,631.02 |  7,443.13
  * IIB Mar-23 outcome PDF (INDUSINDBK_24042023142255_Results24042023f.pdf), page 7:
    "Audited Consolidated Financial Results ... March 31, 2023", Rs in lakhs -> /100.
    cols [31.03.2023 | 31.12.2022 | 31.03.2022 | FY23 | FY22]
    Interest Earned  10,020.71 | 9,457.41 | 7,859.89 | FY23 (OCR-mangled) | 34,822.44
    Net Profit (12)   2,043.36 | 1,963.54 | 1,400.52 | 7,443.13 | 4,804.63

ANCHORS (all exact vs stored, which came from the std/con XBRLs independently):
  con PAT 2124.44 == stored 20230630 patC | 2043.36 == 20230331 (BOTH docs) | 1963.54 == 20221231
  | 1631.02 ~ stored 20220630 patC 1631.14 (0.12 < 2cr tol).
  Interest Earned equals the stored STANDALONE value in every already-stored column — Jun-22 col
  8181.77 == stored revS AND revC (elimination parity: BFIL's income is intra-group and nets out;
  stored Sep-23 con==std shows the same), Mar-23 col 10020.71 == stored revS, Dec-22 col 9457.41 ==
  stored revS.
  FY-IDENTITY: 8181.77 + 8708.03 + 9457.41 + 10020.71 = 36367.92 == the Jun-23 doc's printed FY23
  con Interest Earned EXACTLY — this both certifies the whole column set and documents the Sep-22
  con value (8708.03, = stored std) that no surviving con statement prints directly.

Fill-only, revC (slot 1) only:
  20230331 <- 10020.71  (printed, two documents)
  20230630 <- 10729.65  (printed)
  20221231 <-  9457.41  (printed)
  20220930 <-  8708.03  (FY-identity §45, all four components filed)
Run: python -X utf8 scripts/fill2020_tools/apply_indusindbk_con.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
LEDGER = os.path.join(SCRIPTS, "named_rev_cell_fills.json")

SYM = "INDUSINDBK"
CELLS = {
    "20230331": (
        10020.71,
        ("printed in BOTH the Mar-23 audited and Jun-23 con statements; con PAT 2043.36 == stored exactly in both"),
    ),
    "20230630": (10729.65, "Jun-23 con statement current col; con PAT 2124.44 == stored exactly"),
    "20221231": (
        9457.41,
        (
            "Mar-23 con statement preceding-quarter col; con PAT 1963.54 == stored "
            "exactly; == stored revS (elimination parity)"
        ),
    ),
    "20220930": (
        8708.03,
        (
            "FY-identity: printed FY23 con 36367.92 minus printed Jun-22 8181.77, "
            "Dec-22 9457.41, Mar-23 10020.71 (§45); == stored revS"
        ),
    ),
}


def main():
    dry = "--apply" not in sys.argv
    for path in (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json")):
        d = json.load(open(path))
        for qe, (val, _) in sorted(CELLS.items()):
            row = d.get(SYM, {}).get(qe)
            if not row:
                print("%-26s %s no row" % (os.path.basename(path), qe))
                continue
            while len(row) < 9:
                row.append(None)
            if row[1] is not None:
                print("%-26s %s already filled: %s" % (os.path.basename(path), qe, row[1]))
                continue
            row[1] = val
            d[SYM][qe] = row
            print("%-26s %s %s revC=%s" % (os.path.basename(path), qe, "would fill" if dry else "filled", val))
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
    if not dry:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        for qe, (val, ev) in CELLS.items():
            led[f"{SYM}|{qe}"] = {
                "revC": val,
                "src": "nse-outcome-pdf-con-statement",
                "evidence": ev,
                "applied": "2026-08-10 residue batch",
            }
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print(f"journalled -> {os.path.basename(LEDGER)}")
    else:
        print("DRY RUN -- nothing written.")


if __name__ == "__main__":
    main()
