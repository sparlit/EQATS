# -*- coding: utf-8 -*-
"""TRIPWIRE for power-of-ten scale errors in the source XBRL (DATA_RUNBOOK §11).

Surfaces SUSPECTS for a human to adjudicate. It deliberately does NOT fix anything: the disease
is not auto-detectable, and every naive rule I tried deletes real data.

Why no threshold works on its own — the flagged population is mostly LEGITIMATE:
  * a real collapse: JETAIRWAYS/HDIL/ANDHRACEMT decline to ~0, which drags the symbol's median
    down until its healthy years look like outliers (the "50x the median" test flags 268 cells,
    of which ~198 are real);
  * a holding-co shell: BINANIIND/ROLTA/DCM standalone is ~0 while consolidated is real;
  * a merger step-change: ABCAPITAL's standalone jumps ~100 -> ~4,000 on the Apr-2025 ABFL merger;
  * a one-off: SIL Mar-22 rev 429.97 -> op 212.44 is a textbook ~49% land-sale margin; SPARC
    Mar-26 rev 1853.22 - op 1772.94 = 80.28 of cost == its normal quarterly cost base;
  * recurring seasonality: MAHSCOOTER spikes every SEPTEMBER (the annual Bajaj dividend), and
    RTNINDIA/WESTLIFE every JUNE (subsidiary dividends).
Cross-slot agreement does not save you either: for an investment company rev == op == pat by
nature, so all slots move together whether the cause is a scale error or a real dividend.

ADJUDICATE a suspect with a hard anchor, strongest first:
  (a) YTD — a Q2/Q3/Q4 filing carries its own year-to-date figure, so
        (YTD_parsed - quarter_parsed) / sum(earlier quarters of that FY, from OTHER filings)
      is the factor, by arithmetic. IRCTC/GAEL/GRAPHITE/TTML land on EXACTLY 100.000 this way.
  (b) CROSS-BASIS — the same company's other-basis filing for the same quarter, minutes apart
      (BATAINDIA's FinanceCosts is byte-identical to its con filing after /1000).
  (c) NEIGHBOURS — only where exactly one power of ten lands every slot in range.
Then add it to scale_fix.json with the evidence in `why`.

Run: python -X utf8 detect_scale_errors.py [--factor 50]
"""
import os, sys, json, math, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
if not os.path.exists(REVOP):
    REVOP = os.path.join(HERE, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
if not os.path.exists(FUND):
    FUND = os.path.join(HERE, "fundamentals.json")

SLOTS = {"std": {"rev": 0, "op": 2, "pat": 4, "ebit": 7},
         "con": {"rev": 1, "op": 3, "pat": 5, "ebit": 8}}

# Compare against the ADJACENT quarters, never the symbol's whole-series median, and never
# require a minimum number of quarters. Both of those hide real cases:
#   * the median is dragged to ~0 by a company's dead years, so its healthy quarters read as
#     outliers and its ONE scaled quarter reads no worse than they do;
#   * a ">= 6 quarters" floor hid GICL 20250930 (x1e5 on both bases) outright — it only has 4.
# sf_fundamentals is swept too: QUINT is absent from sf_revop entirely, so its scaled net-profit
# cells are invisible to a revop-only sweep.


def nbr_level(rows, qs, i, slot):
    got = []
    for rng in (range(i - 1, -1, -1), range(i + 1, len(qs))):
        for j in rng:
            r = rows[qs[j]] + [None] * (9 - len(rows[qs[j]]))
            if r[slot] is not None and r[slot] != 0:
                got.append(abs(r[slot])); break
    return statistics.median(got) if got else None


def main():
    factor = 50.0
    if "--factor" in sys.argv:
        factor = float(sys.argv[sys.argv.index("--factor") + 1])
    data = json.load(open(REVOP, encoding="utf-8"))
    try:
        import scale_fix
        known = {(e["sym"], e["qe"], e["basis"]) for e in scale_fix.load()}
    except Exception:
        known = set()

    hits = []
    for sym, rows in data.items():
        qs = sorted(rows)
        for i, qe in enumerate(qs):
            row = rows[qe] + [None] * (9 - len(rows[qe]))
            for basis, slots in SLOTS.items():
                if (sym, qe, basis) in known:
                    continue
                ev = []
                for name, slot in slots.items():
                    v = row[slot]
                    if v is None or v == 0:
                        continue
                    lvl = nbr_level(rows, qs, i, slot)
                    if lvl and abs(v) >= factor * lvl:
                        ev.append((name, v, lvl, math.log10(abs(v) / lvl)))
                if ev:
                    hits.append((sym, qe, basis, ev))

    print("=== sf_revop: %d suspect filing(s) >= %.0fx their adjacent quarters, not already in\n"
          "    scale_fix.json. SUSPECTS ONLY — most are real (see the module docstring).\n"
          "    Adjudicate against a YTD / cross-basis / neighbour anchor before touching anything.\n"
          % (len(hits), factor))
    for sym, qe, basis, ev in sorted(hits):
        print("  %-12s %s %-3s" % (sym, qe, basis))
        for name, v, lvl, lg in ev:
            print("       %-5s %16.2f  vs adjacent %10.2f   x%-9.0f log10=%.2f"
                  % (name, v, lvl, abs(v) / lvl, lg))

    # --- net profit (sf_fundamentals): a separate parser and a separate file, same disease ---
    fund = json.load(open(FUND, encoding="utf-8"))
    fhits = []
    for sym, rows in fund.items():
        rows = [r for r in rows if isinstance(r, list) and len(r) >= 4]
        for bi, i in (("std", 1), ("con", 3)):
            vals = [(str(r[0]), r[i]) for r in rows if r[i] is not None and r[i] != 0]
            for j, (qe, v) in enumerate(vals):
                nb = [abs(vals[k][1]) for k in (j - 1, j + 1) if 0 <= k < len(vals)]
                nb = [x for x in nb if x > 0]
                if not nb:
                    continue
                lvl = statistics.median(nb)
                if abs(v) >= factor * lvl and (sym, qe, bi) not in known:
                    fhits.append((sym, qe, bi, v, lvl))
    print("\n=== sf_fundamentals (net profit): %d suspect cell(s)\n" % len(fhits))
    for sym, qe, bi, v, lvl in sorted(fhits):
        print("  %-12s %s %-3s np=%14.2f  vs adjacent %10.2f  x%.0f" % (sym, qe, bi, v, lvl, abs(v) / lvl))


if __name__ == "__main__":
    main()
