# -*- coding: utf-8 -*-
"""§111i — the CON-SIDE invariant, per cell, before -> after, over the §109e by-product population.

WHAT IT MEASURES. Agreement between our consolidated PAT slot and Moneycontrol's OWNERS-attributable
figure (`pat_own`), for every con by-product cell where MC has a reading — the same population and
the same quantity as §111g's third row, so the numbers are comparable across campaigns.

WHY PER CELL. "How many disagree now" cannot see a cell that was fine and got worse. Three states
are reconstructed, each from committed data so this re-runs at any time:

  pre-both   the value before EITHER 2026-08-24/25 campaign touched it — every fund_cell_fix entry
             rolled back to its own `was`; for a RETRACTED entry (§112) the heal is the "before"
             and its `was` is what ships
  now        whatever docs/sf_fundamentals.json holds when this runs
  after      what the ledger says the cell should hold — `fixed` — i.e. what CI will re-assert
             (§109j), which is the state that actually ships

★ MC IS NOT AN ORACLE, and this is not a vote. §111e measured MC at 42% restated on a known-answer
set, so MC agreeing never CLOSES a cell. It is used here for exactly one thing, which it is good
for: a DIRECTION-OF-TRAVEL check on a population. 52 of the 59 disputed heals moved the cell away
from MC's owners figure; if a correction is right, that number goes back down and NO cell that
agreed before disagrees after.

RUN: python3 -X utf8 vintage111_invariant.py
"""
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADJ = "/Users/dhruvan/stocks-wt/vintage109-evidence/_vintage109_adjud.json"
BYPROD_CAMPS = ("vintage108 by-product sweep 2026-08-24",
                "vintage109 by-product campaign 2026-08-25",
                "vintage108 §109h residue adjudication 2026-08-25")


def agree(a, b, ab=2.0, rl=0.03):
    return a is not None and b is not None and abs(a - b) <= max(ab, abs(b) * rl)


def main():
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf-8"))
    adj = json.load(open(ADJ, encoding="utf-8"))["cells"]
    lg = json.load(open(os.path.join(HERE, "fund_cell_fix.json"), encoding="utf-8"))
    # §112 moved withdrawn heals from `fixes` to a `retracted` list rather than deleting them, so
    # the pre-campaign value still has to be reconstructed from BOTH lists — reading `fixes` alone
    # silently drops every reverted cell out of the population and the invariant flatters itself.
    led = {}
    for lst, live in (("retracted", False), ("fixes", True)):
        for f in lg.get(lst, []):
            if isinstance(f, dict) and "sym" in f:
                f = dict(f, _live=live)
                led["%s|%s|%s" % (f["sym"], f["qe"], f["basis"])] = f

    rows = []
    for k, a in sorted(adj.items()):
        if a["basis"] != "con":
            continue
        mc = (a.get("mc") or {}).get("pat_own")
        if mc is None:
            continue
        sym, qe = a["sym"], int(a["qe"])
        r = next((x for x in fund.get(sym, []) if x[0] == qe), None)
        now = r[3] if r and len(r) > 3 else None
        f = led.get(k)
        if f is None:
            pre = after = now
        elif not f.get("_live"):
            # a RETRACTED entry: the heal was withdrawn, so what ships is the value it replaced
            pre, after = f["fixed"], f["was"]
        else:
            pre = f.get("original", f["was"])
            after = f["fixed"]
        rows.append((k, pre, now, after, mc, f))

    print("population: %d con by-product cells with an MC owners reading" % len(rows))
    for tag, ix in (("pre-both", 1), ("now (payload)", 2), ("after (ledger)", 3)):
        n = sum(1 for x in rows if agree(x[ix], x[4]))
        print("   agreement with MC owners, %-15s %4d/%d = %5.1f%%"
              % (tag, n, len(rows), 100.0 * n / len(rows)))

    for name, bi, ai in (("pre-both -> after", 1, 3), ("now -> after", 2, 3)):
        c, worse = Counter(), []
        for k, pre, now, after, mc, f in rows:
            b, a2 = (pre, now, after)[bi - 1], (pre, now, after)[ai - 1]
            ab, aa = agree(b, mc), agree(a2, mc)
            if ab and not aa:
                c["WORSENED"] += 1
                worse.append((k, b, a2, mc))
            elif aa and not ab:
                c["improved"] += 1
            elif b != a2:
                c["moved, both %s" % ("agree" if aa else "disagree")] += 1
            else:
                c["untouched"] += 1
        print("\n%-20s %s" % (name, dict(c)))
        for w in worse:
            print("   REGRESSION %-26s %s -> %s   MC owners %s" % w)
    print("\n(any WORSENED above zero blocks the correction — §109d's hole, con side)")


if __name__ == "__main__":
    main()
