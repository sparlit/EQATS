# -*- coding: utf-8 -*-
"""Switch the consolidated profit basis back to TOTAL PAT (ProfitLossForPeriod) from the
attributable-to-owners figure. This is the inverse of apply_reattr.py.

Why: Trendlyne's backtest screen ("Net Profit Qtr Growth YoY %") computes growth on TOTAL PAT,
not owners-attributable. Empirically (cmp test) switching to total PAT fixes the minority-interest
misses (ADANIENSOL, ZYDUSLIFE) with ZERO collateral changes to any other month/stock.

Sets npCon (index 3) = total PAT from _reattr_changes.json rows [sym, qe, total, owners, minority].
Standalone (npStd) and no-minority quarters are untouched. Atomic write.

NOTE: do NOT run apply_reattr.py after this — that would switch back to owners-attributable.
Run: python -X utf8 apply_total_pat.py
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
F = os.path.join(ROOT, "docs", "sf_fundamentals.json")

def main():
    live = json.load(open(F))
    changes = json.load(open(os.path.join(HERE, "_reattr_changes.json")))  # [sym, qe, total, owners, minority]
    total = {(c[0], c[1]): c[2] for c in changes}
    changed = 0; stocks = set()
    for sym, arr in live.items():
        for row in arr:                                   # [qe, npStd, annStd, npCon, annCon]
            t = total.get((sym, row[0]))
            if t is not None and row[3] is not None and abs(t - row[3]) > 0.5:
                row[3] = t; changed += 1; stocks.add(sym)
    tmp = F + ".tmp"; json.dump(live, open(tmp, "w"), separators=(",", ":")); os.replace(tmp, F)
    print("Switched npCon to TOTAL PAT for %d consolidated quarters across %d stocks." % (changed, len(stocks)))

if __name__ == "__main__":
    main()
