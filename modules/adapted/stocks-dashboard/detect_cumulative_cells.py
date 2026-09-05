# -*- coding: utf-8 -*-
"""Find quarters that actually hold a CUMULATIVE (year-to-date) figure instead of the quarter.

Found by the screener audit: KIRLFER 2024-09-30 revS stores 3220.82, which is EXACTLY its Jun-2024
value (1553.71) plus the real Sep quarter (1667.11). Many Indian filings print a year-to-date column
next to the quarter column, and a reader that grabs the wrong column lands a cumulative figure that
looks entirely plausible on its own — it only betrays itself against its siblings.

THE TEST IS SELF-CONTAINED — no screener, no network, no external truth. For Q2/Q3/Q4 of a financial
year, a cumulative value satisfies

    stored[q]  ==  sum(stored[earlier quarters of the same FY])  +  a plausible quarter

so we require BOTH:
  * stored[q] minus the sum of the earlier stored quarters lands within [0.5x, 1.6x] of the median
    of the OTHER quarters in that year (i.e. the residual is itself a believable quarter), and
  * stored[q] is at least 1.6x that median (a real quarter rarely doubles its siblings).

Both conditions together are what separate a cumulative cell from a genuinely big quarter. Reported,
never auto-corrected: the fix must be journalled per cell like any other heal (CLAUDE.md rule 5).

  python -X utf8 scripts/fill2020_tools/detect_cumulative_cells.py [--min-year 2015]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def fy_of(qe):
    y, m = qe // 10000, (qe // 100) % 100
    return y + 1 if m > 3 else y


def fy_quarters(fy):
    return [(fy - 1) * 10000 + 630, (fy - 1) * 10000 + 930,
            (fy - 1) * 10000 + 1231, fy * 10000 + 331]


def main():
    miny = int(sys.argv[sys.argv.index("--min-year") + 1]) if "--min-year" in sys.argv else 2015
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    hits = []
    for sym, qmap in revop.items():
        for field, slot in (("revS", 0), ("revC", 1)):
            vals = {}
            for q, row in qmap.items():
                if row and len(row) > slot and row[slot] is not None and row[slot] > 0:
                    vals[int(q)] = row[slot]
            if len(vals) < 4:
                continue
            for qe in sorted(vals):
                fy = fy_of(qe)
                if fy < miny:
                    continue
                qs = fy_quarters(fy)
                if qe not in qs or qs.index(qe) == 0:
                    continue
                idx = qs.index(qe)
                earlier = [qs[i] for i in range(idx)]
                others = [q for q in qs if q != qe and q in vals]
                if not all(q in vals for q in earlier) or len(others) < 2:
                    continue
                sib = sorted(vals[q] for q in others)
                med = sib[len(sib) // 2] if len(sib) % 2 else (sib[len(sib) // 2 - 1] + sib[len(sib) // 2]) / 2.0
                if med <= 0:
                    continue
                v = vals[qe]
                resid = v - sum(vals[q] for q in earlier)
                if v >= 1.6 * med and 0.5 * med <= resid <= 1.6 * med:
                    hits.append({"sym": sym, "qe": qe, "field": field, "stored": round(v, 2),
                                 "implied_quarter": round(resid, 2),
                                 "earlier_sum": round(sum(vals[q] for q in earlier), 2),
                                 "sibling_median": round(med, 2), "fy": fy,
                                 "ratio": round(v / med, 2)})
    hits.sort(key=lambda h: -h["ratio"])
    print("cumulative-looking cells: %d\n" % len(hits))
    print("%-12s %-9s %-5s %12s %12s %12s %6s" % ("sym", "quarter", "field", "stored",
                                                  "implied Q", "sib median", "ratio"))
    for h in hits[:45]:
        print("%-12s %-9d %-5s %12.2f %12.2f %12.2f %6.2f"
              % (h["sym"], h["qe"], h["field"], h["stored"], h["implied_quarter"],
                 h["sibling_median"], h["ratio"]))
    json.dump(hits, open("/tmp/cumulative_cells.json", "w"), indent=1)
    print("\n-> /tmp/cumulative_cells.json")


if __name__ == "__main__":
    main()
