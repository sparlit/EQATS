# -*- coding: utf-8 -*-
"""Fill NULL announcement dates in docs/sf_fundamentals.json with the SEBI filing DEADLINE
(45 days after quarter-end; 60 for the Q4/annual). The deadline is the LATEST a result can be
published, so a quarter only becomes point-in-time-usable on/after that date -> conservative,
never look-ahead. Without this, a quarter with a missing date is skipped and the screen falls
back to a stale quarter (which wrongly excluded AIIL, and others, from month-end screens).

Also DEMOTES impossible dates (ann <= quarter-end) to the same deadline: a result can't be
declared before its quarter ends, so such a date is a backfill placeholder or typo — and it is
LOOK-AHEAD BIAS in the backtests (the quarter turns point-in-time-visible before it existed).
The 2026-07-21 audit found 20 of these (mostly ann=qe stamps from the 2018 Nifty-500 backfill,
plus ENRIN pre-IPO and a FEDERALBNK year typo); this run in the nightly keeps the count at 0.

Run: python -X utf8 fill_ann_dates.py
"""
import os, json, datetime

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
F = os.path.join(ROOT, "docs", "sf_fundamentals.json")

def deadline(qe):
    y, mmdd = qe // 10000, qe % 10000
    d = datetime.date(y, mmdd // 100, mmdd % 100)
    lag = 60 if mmdd == 331 else 45                  # Q4 (annual) 60d, Q1-Q3 45d
    return int((d + datetime.timedelta(days=lag)).strftime("%Y%m%d"))

def heal(data, label="sf_fundamentals"):
    """Fill nulls + demote impossible anns, in place. Returns (n_filled, n_demoted)."""
    fixed = demoted = 0
    for sym, arr in data.items():
        for q in arr:                                # q = [qe, npStd, annStd, npCon, annCon]
            if not (isinstance(q, list) and len(q) >= 5 and isinstance(q[0], int)): continue
            est = None
            if q[1] is not None and q[2] is None: q[2] = est = deadline(q[0]); fixed += 1
            if q[3] is not None and q[4] is None: q[4] = est or deadline(q[0]); fixed += 1
            for ai in (2, 4):                        # impossible: declared on/before the quarter-end
                # ⚠️ ann=0 is the established "date unknown" sentinel (falsy -> consumers skip it, page
                # shows no date) — it is NOT an impossible date and MUST stay untouched; only a real
                # pre-quarter-end date (backfill placeholder / typo) gets demoted to the deadline.
                if q[ai] and q[ai] <= q[0]:
                    print("  %s: %s %d ann %d IMPOSSIBLE -> deadline %d" % (label, sym, q[0], q[ai], deadline(q[0])))
                    q[ai] = deadline(q[0]); demoted += 1
    return fixed, demoted

def main():
    data = json.load(open(F))
    fixed, demoted = heal(data)
    tmp = F + ".tmp"; json.dump(data, open(tmp, "w"), separators=(",", ":")); os.replace(tmp, F)
    print("Filled %d null + demoted %d impossible announcement dates in %s" % (fixed, demoted, F))

if __name__ == "__main__":
    main()
