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
"""JHS 2018-09-30 consolidated PAT: -27.82 / 0.93  ->  -0.98 (owners). NO VISION NEEDED.

The cell was queued for a vision read because three automated passes reported "no consolidated page
at all in any fetched PDF". Both halves of that were wrong:

  * the OWN-quarter PDFs did not fail to parse, they FAILED TO FETCH (3 of 4 returned no bytes) --
    transport, not a scan (§57c);
  * the Q+4 filing (Sep-2019, which carries Sep-2018 as its year-ago column) IS scanned, but it
    carries an OCR TEXT LAYER, and that was enough.

So this was rung 6 of the ladder -- the comparative column of the next-year filing -- not rung 10.

THE READ. Page 4, "STATEMENT OF UNAUDITED CONSOLIDATED FINANCIAL RESULTS", Rs in lakhs, columns
[Q Sep-19, Q Jun-19, Q SEP-18, H1 Sep-19, H1 Sep-18, FY Mar-19]. JHS has non-controlling interests,
so the owners figure is what we store. OCR corrupts digits in this document, so no printed number is
trusted on its own -- every value is pinned by an identity the page itself asserts:

    period Sep-18   = PBT -106.56 - tax (13.90 + -18.81 = -4.91)      = -101.65  (printed, exact)
    owners Sep-18   = period -101.65 - NCI (-3.71)                    =  -97.94  (OCR shows "[92 94)")
    control 1       Sep-19 owners -54.48 + Jun-19 owners -28.73       =  -83.21  = printed H1 owners
    control 2       Sep-19: PBT -98.09 - tax 96.18 = -194.27          = printed period, exact
    control 3       owners -97.94 + OCI owners 0.39                   =  -97.55  = printed TCI owners

-97.94 lakh = -0.98 crore, which sits inside JHS's ~1.68 family median -- the out-of-family -27.82
that raised the flag was simply wrong, and the mirror's 0.93 is wrong too. Both files are written.

  python -X utf8 scripts/fill2020_tools/apply_jhs_2026_08_09.py [--apply]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
FUND = (os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(SCRIPTS, "fundamentals.json"))
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
SUSPECTS = os.path.join(SCRIPTS, "_fund_suspect_cells.json")
LEDGER = os.path.join(SCRIPTS, "owners_basis_heals.json")

SYM, QE, WAS_FUND, WAS_REVOP, NOW = "JHS", 20180930, -27.82, 0.93, -0.98


def main():
    dry = "--apply" not in sys.argv
    n = 0
    for paths, idx, keyed in ((FUND, 3, False), (REVOP, 5, True)):
        for path in paths:
            d = json.load(open(path, encoding="utf-8"))
            row = (d.get(SYM) or {}).get(str(QE)) if keyed else next((r for r in d.get(SYM, []) if r[0] == QE), None)
            if not row or len(row) <= idx:
                continue
            cur = row[idx]
            if cur is not None and abs(cur - NOW) < 0.005:
                continue
            exp = WAS_REVOP if keyed else WAS_FUND
            if cur is not None and abs(cur - exp) > 0.005:
                sys.exit(f"GUARD {SYM} in {os.path.basename(path)}: {cur} expected {exp}")
            print("  %-16s %-26s %s -> %s" % ("%s|%d" % (SYM, QE), os.path.basename(path), cur, NOW))
            row[idx] = NOW
            n += 1
            if not dry:
                json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    print("\n%d slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return
    sus = json.load(open(SUSPECTS, encoding="utf-8"))
    sus["cells"] = [c for c in sus["cells"] if not (c["sym"] == SYM and c["qe"] == QE)]
    sus["_README"].append(
        "2026-08-09 pass 4: JHS 20180930 settled at -0.98 (owners) from the Sep-2019 filing's "
        "year-ago column -- and WITHOUT a vision read, though one had been approved. The 'no "
        "consolidated page' diagnosis was wrong twice over: the own-quarter PDFs FAILED TO FETCH "
        "(transport, not a scan) and the Q+4 scan carries a usable OCR text layer. Check the "
        "next-year filing before escalating anything else here to vision."
    )
    json.dump(sus, open(SUSPECTS, "w", encoding="utf-8"), indent=1)
    led = json.load(open(LEDGER, encoding="utf-8"))
    led["cells"]["%s|%d|patC" % (SYM, QE)] = {
        "owners": NOW,
        "stored_before": WAS_FUND,
        "period": -1.02,
        "nci": -0.04,
        "note": "Sep-2019 filing p4 (lakhs), year-ago column; OCR digits pinned by four on-page "
        "identities -- see apply_jhs_2026_08_09.py",
    }
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), indent=1)
    print("suspect ledger now %d open" % len(sus["cells"]))


if __name__ == "__main__":
    main()
