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
"""FILL-2020: three standalone-revenue cells read by hand from the filings (user-requested).

Each was invisible to every automated route: BSE detailed-results returns an empty row for these
quarters and the NSE archive list does not reach them, so only the announcement PDF has the numbers.
That is the ANGELONE lesson -- "the source I tried has no row" is not "the value does not exist".

  ANGELONE   2025-03  revS 1031.35   (filing 17-Apr-2025, Rs in millions -> /10)
      Total revenue from operations 10,313.46. Anchored FIVE ways: the same page's PAT column
      1,802.58 -> 180.26 == stored std PAT exactly; the two prior PAT columns 3,010.28 -> 301.03 and
      3,460.16 -> 346.02 == stored Dec-24/Mar-24; and the two prior REVENUE columns 12,459.94 ->
      1,245.99 and 13,469.94 -> 1,346.99 == stored revS for those quarters. Sanity: con 1,056.01
      sits just above it, matching ANGELONE's usual ~2% gap.

  ADANIGREEN 2025-03  revS 6461.00   (filing 28-Apr-2025, Rs in crores)
      Revenue From Operations = Power Supply 2 + Sale of Goods/Equipment 6,461 + Others (2).
      Anchored: the same row's PAT columns 113 / 557 / (195) == stored std PAT for Mar-25 / Dec-24 /
      Mar-24 exactly; the internal identity 6,461 + 314 other income - 7 FX == the printed Total
      Income 6,768; and the Mar-24 column reproduces stored revS 7,304 exactly.
      NOTE revS (6,461) EXCEEDS revC (3,073) here. That is real for this company, not an error:
      standalone includes large equipment/EPC sales to its own SPVs which are eliminated on
      consolidation. The stored neighbours show the same shape (Mar-24 revS 7,304 vs revC 2,527).

  LICI       2023-06  revS 188749.16 (filing 10-Aug-2023, Rs in lakhs -> /100)
      Standalone policyholders' Total = 1,88,74,915.73 lakh. Our stored "revenue" for LICI is TOTAL
      INCOME (premium + investment income), not premium -- confirmed because net premium alone is
      only ~98,363 cr against a stored con of 190,163.
      Anchored on the MAR-2023 comparative column, not on this quarter: that column's PAT
      13,427.81 == our stored 2023-03 std PAT exactly, and its total income 200,185.38 == our stored
      2023-03 revS 200,178.83 (0.003%). Document, columns and scale are therefore certain.
      ⚠️ THE JUN-2023 PAT ANCHOR DELIBERATELY FAILS AND IS NOT USED: the filing states standalone
      PAT 9,543.71 while we store 9,634.98 -- which is also exactly our stored CONSOLIDATED value,
      i.e. the std slot appears to hold the consolidated figure for that quarter. That is a
      correctness defect (runbook §2b territory), NOT something a fill pass may quietly rewrite.
      Recorded in the ledger and reported; the revenue cell is landed on the Mar-2023 anchor alone.

NOT INCLUDED -- GICRE 2024-12: its filing PDF is severely OCR-corrupted (rows extract as
"!,-=--·49" and "J!2v\x12If!!!''!I"), so no row can be read safely. It needs the §43 IRDAI
public-disclosures route or a vision read, not a text-layer guess.

Fill-only, revenue slot (0) only. Run: python -X utf8 .../apply_named_rev_cells.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
REVOP_DOCS = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "named_rev_cell_fills.json")

CELLS = {
    ("ANGELONE", "20250331"): (
        1031.35,
        (
            "filing 2025-04-17, Rs mn/10: total rev from ops 10,313.46; anchors = same-page PAT "
            "180.26==stored std, prior PAT cols 301.03/346.02==stored, prior REV cols "
            "1245.99/1346.99==stored revS"
        ),
    ),
    ("ADANIGREEN", "20250331"): (
        6461.00,
        (
            "filing 2025-04-28, Rs cr: rev from ops 2+6461+(2); anchors = PAT cols 113/557/(195)"
            "==stored std Mar25/Dec24/Mar24, total-income identity 6461+314-7==6768, Mar-24 rev col"
            "==stored revS 7304"
        ),
    ),
    ("LICI", "20230630"): (
        188749.16,
        (
            "filing 2023-08-10, Rs lakh/100: standalone policyholders' Total 1,88,74,915.73; anchored "
            "on the MAR-2023 column (PAT 13427.81==stored, total income 200185.38 vs stored revS "
            "200178.83, 0.003%). Jun-23 PAT anchor NOT used: filing says std PAT 9543.71 vs our stored "
            "9634.98 (== our stored CON) -- suspected std/con mix-up in stored data, flagged not fixed"
        ),
    ),
}


def main():
    dry = "--apply" not in sys.argv
    journal = {}
    for path in (REVOP_DOCS, REVOP_SCR):
        d = json.load(open(path))
        filled, skipped = 0, []
        for (sym, qe), (val, why) in sorted(CELLS.items()):
            row = d.get(sym, {}).get(qe)
            if not row:
                skipped.append((sym, qe, "no-row"))
                continue
            while len(row) < 9:
                row.append(None)
            if row[0] is not None:
                skipped.append((sym, qe, f"already={row[0]}"))
                continue
            row[0] = val
            filled += 1
            d[sym][qe] = row
            if path == REVOP_DOCS:
                journal[f"{sym}|{qe}"] = {
                    "revS": val,
                    "src": "bse-filing-pdf-manual-read",
                    "evidence": why,
                    "applied": "2026-08-06 FILL-2020 named cells",
                }
        if not dry:
            json.dump(d, open(path, "w"), separators=(",", ":"))
        print(
            "%-32s %s %d cells%s"
            % (
                os.path.basename(path),
                "would fill" if dry else "filled",
                filled,
                (f"  skipped: {skipped}") if skipped else "",
            )
        )
    if not dry and journal:
        led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
        led.update(journal)
        json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
        print("journalled %d -> %s" % (len(journal), os.path.basename(LEDGER)))
    if dry:
        print("DRY RUN -- nothing written.")


if __name__ == "__main__":
    main()
