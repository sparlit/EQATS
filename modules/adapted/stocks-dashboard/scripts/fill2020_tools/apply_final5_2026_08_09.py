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
"""The last 5 unconfirmed cells, read by NEIGHBOUR-VALUE column anchoring. 2 settled, 3 still open.

They had abstained because `date_columns.quarter_columns` could not place the target quarter from
the page's printed header. That is only one way to find a column: §58's way needs no header at all
-- locate the column whose value reproduces a con PAT we ALREADY STORE for a DIFFERENT quarter.
Applying that here settled two of the five immediately.

  IRB 2020-09-30  CONFIRMED at -19.66, no change.
      Sep-2021 filing p20 (lakhs), "Profit after tax":
          Sep-21 42.31 | Jun-21 71.91 | SEP-20 -19.66 | H1FY22 114.21 | H1FY21 -49.80 | FY21 117.15
      Anchors: x240 == stored 42.31 (Sep-21) and x299 == stored 71.91 (Jun-21).
      Two identities close: H1FY22 42.31+71.91 = 114.22 (printed 114.21), and
      H1FY21 -19.66 + stored Jun-20 -30.14 = -49.80 EXACTLY as printed.
      So the mirror's -66.60 was the wrong one and sf_fundamentals was right.

  ARIHANTCAP 2026-03-31  1.28 -> 0.50  CORRECTED.
      Own Mar-2026 filing p5 (lakhs), "Profit/(Loss) for the Year":
          MAR-26 0.50 | Dec-25 5.18 | Mar-25 7.70 | FY26 31.46 | FY25 58.70
      Anchors: x351 == stored 5.18 (Dec-25) and x410 == stored 7.70 (Mar-25).
      FY26 closes EXACTLY: 12.70 + 13.08 + 5.18 + 0.50 = 31.46 as printed.
      Neither stored value was right -- fundamentals had 1.28, the mirror 10.96.

STILL OPEN (3), and none of them is a reader gap that more regex will fix:
  AXISCADES 2018-12  the only "anchor" found was a cash-flow Adjustments row matching on a 0.05
                     tolerance floor against a 0.08 stored value -- a false positive, not a lock.
                     Its OCR also absorbs figures into row captions.
  BANCOINDIA 2019-03 no row anywhere anchors on two stored neighbours.
  SUBCAPCITY 2021-03 no BSE listing at all (§71f); NSE serves only the self-contradictory XBRL.

  python -X utf8 scripts/fill2020_tools/apply_final5_2026_08_09.py [--apply]
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

SYM, QE, WAS, NOW = "ARIHANTCAP", 20260331, 1.28, 0.50
VERIFIED = [("IRB", 20200930, -19.66)]


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
    for s, q, v in VERIFIED:
        print("  %-20s CONFIRMED at %s against the filing -- no change" % ("%s|%d" % (s, q), v))
    print("\n%d slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(pass --apply)")
        return
    u = json.load(open(UNCONF, encoding="utf-8"))
    done = {(SYM, QE)} | {(s, q) for s, q, _v in VERIFIED}
    u["cells"] = [c for c in u["cells"] if (c["sym"], c["qe"]) not in done]
    u["_README"].append(
        "2026-08-09 neighbour-anchor pass (§71i): IRB 20200930 CONFIRMED at -19.66 (two identities "
        "close, incl. H1FY21 -19.66 + stored Jun-20 -30.14 = -49.80 exactly as printed); "
        "ARIHANTCAP 20260331 CORRECTED 1.28 -> 0.50 (FY26 12.70+13.08+5.18+0.50 = 31.46 exactly as "
        "printed -- neither stored value was right). 3 remain and none is a regex gap: AXISCADES "
        "(OCR absorbs figures into captions; its only 'anchor' was a false positive off the 0.05 "
        "tolerance floor), BANCOINDIA (nothing anchors on two stored neighbours), SUBCAPCITY "
        "(no BSE listing, §71f)."
    )
    json.dump(u, open(UNCONF, "w", encoding="utf-8"), indent=1)
    led = json.load(open(LEDGER, encoding="utf-8"))
    led["cells"]["%s|%d|patC" % (SYM, QE)] = {
        "owners": NOW,
        "stored_before": WAS,
        "note": "own Mar-2026 filing p5 (lakhs); column anchored on stored Dec-25 5.18 and Mar-25 "
        "7.70; FY26 identity 12.70+13.08+5.18+0.50 = 31.46 closes exactly",
    }
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), indent=1)
    print("unconfirmed ledger now %d open" % len(u["cells"]))


if __name__ == "__main__":
    main()
