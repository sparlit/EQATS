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
"""Verify the 7 §71g cells against filings. One CONFIRMED, one REGRESSION I caused, five still open.

§71g resynced these mirror<-authoritative with no independent source reaching them, and recorded
that "no longer divergent is not verified". Going to the documents proves the caveat was worth
writing:

  3IINFOLTD 2025-12-31  -> 2.14   ** I WROTE THE WRONG VALUE **
      Own Dec-2025 filing p7 (lakhs), Dec-25 column: period 208, non-controlling -5, so owners 213.
      The XBRL agrees and its identity CLOSES: owners 2.14 + NCI -0.05 = total 2.09. We store
      OWNERS, so 2.14 is right -- and the §71g resync overwrote it with the TOTAL 2.09 because the
      blanket "fundamentals is authoritative" rule does not know the difference. Corrected.

  DELTAMAGNT 2022-03-31 -> -0.12  CONFIRMED, no change
      Own Mar-2022 filing p15 row XI "Profit/(loss) for the period/year" = -12.21 lakh = -0.12 cr,
      and the Q+1 filing's Mar-22 column prints -0.12 again. NCI is nil, so owners == total.

STILL UNCONFIRMED (5): AXISCADES 2018-12 (values absorbed into OCR labels -- "(2,290.o4)" and
"(1.263.51)" appear inside row captions, so the columns are incomplete and owners 1.59 + NCI 0.11
does not reconcile to the -0.61 after-tax line); ARIHANTCAP 2026-03 and IRB 2020-09 (no header row
places the target quarter, and IRB's profit caption is glyph-wrecked); BANCOINDIA 2019-03 (no
consolidated page with a profit block in any fetched PDF); SUBCAPCITY 2021-03 (no BSE listing at
all, §71f, and NSE offers only the self-contradictory XBRL).

  python -X utf8 scripts/fill2020_tools/apply_verify7_2026_08_09.py [--apply]
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

SYM, QE, WAS, NOW = "3IINFOLTD", 20251231, 2.09, 2.14
VERIFIED_NO_CHANGE = [("DELTAMAGNT", 20220331, -0.12)]


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
            print("  %-18s %-26s %s -> %s" % ("%s|%d" % (SYM, QE), os.path.basename(path), row[idx], NOW))
            row[idx] = NOW
            n += 1
            if not dry:
                json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    for s, q, v in VERIFIED_NO_CHANGE:
        print("  %-18s verified against the filing at %s -- no change" % ("%s|%d" % (s, q), v))
    print("\n%d slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return
    u = json.load(open(UNCONF, encoding="utf-8"))
    done = {(SYM, QE)} | {(s, q) for s, q, _v in VERIFIED_NO_CHANGE}
    u["cells"] = [c for c in u["cells"] if (c["sym"], c["qe"]) not in done]
    u["_README"].append(
        "2026-08-09 verification pass: 2 of 7 settled from filings. 3IINFOLTD 20251231 was a "
        "REGRESSION introduced by the §71g blanket resync -- the filing and the XBRL both give "
        "owners 2.14 (period 2.09, NCI -0.05) and the resync wrote the TOTAL; corrected to 2.14. "
        "DELTAMAGNT 20220331 confirmed at -0.12 in two filings. The remaining 5 are unreadable for "
        "per-cell reasons recorded in each entry -- they are NOT verified."
    )
    json.dump(u, open(UNCONF, "w", encoding="utf-8"), indent=1)
    led = json.load(open(LEDGER, encoding="utf-8"))
    led["cells"]["%s|%d|patC" % (SYM, QE)] = {
        "owners": NOW,
        "period": 2.09,
        "nci": -0.05,
        "stored_before": WAS,
        "note": "own Dec-2025 filing p7 (lakhs): period 208, NCI -5 => owners 213; XBRL identity "
        "closes at owners 2.14 + NCI -0.05 = total 2.09. The §71g resync had written the total.",
    }
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), indent=1)
    print("unconfirmed ledger now %d open" % len(u["cells"]))


if __name__ == "__main__":
    main()
