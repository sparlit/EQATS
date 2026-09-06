# -*- coding: utf-8 -*-
"""REACH PROBE for the postDrift pre-2003 hole (runbook §91).

sf_fundamentals.json holds NO quarter before 2002-12-31 (measured 2026-08-12: 316 rows at
20021231, zero earlier, across all 3,946 symbols). postDrift therefore cannot exist before
~Feb-2004, because it needs the year-ago base quarter as well as the current one.

Filling it means creating quarters that sit ENTIRELY outside our frame -- 2001Q4..2002Q3.
§90's GATE E campaign never attempted these: its queue was defined against our own series, and
our series starts after them. So "can it be filled" is UNMEASURED, not known.

This script measures REACH ONLY. It writes no ledger and no value. For a sample of symbols
drawn from the actual postDrift blocking-cell list, it asks each aggregator: do you print the
quarters we need? Reports the hit rate per site and per quarter-end.

  python3 scripts/agg_tools/postdrift_reach_probe.py [N_SYMBOLS] [--sites mc,tl,tt]

Reads scripts/_postdrift_needed_cells.json (from postdrift_coverage.js).
Writes scripts/agg_tools/_postdrift_reach.json.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agg_sources as A  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
CELLS = os.path.join(ROOT, "scripts", "_postdrift_needed_cells.json")
OUT = os.path.join(HERE, "_postdrift_reach.json")

# the era that is entirely outside our frame
ERA = (20001231, 20010331, 20010630, 20010930, 20011231,
       20020331, 20020630, 20020930)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 20
    sites = ["mc"]
    for a in sys.argv[1:]:
        if a.startswith("--sites"):
            sites = a.split("=", 1)[1].split(",") if "=" in a else sites

    cells = json.load(open(CELLS))
    # symbols whose blocking cell is in the pre-frame era, ranked by rebalance-months unlocked
    per_sym = collections.OrderedDict()
    for c in cells:
        if c["qe"] in ERA:
            per_sym.setdefault(c["sym"], []).append(c)
    ranked = sorted(per_sym.items(), key=lambda kv: -sum(x["months"] for x in kv[1]))
    sample = ranked[:n]
    print("sampling %d of %d symbols blocked by a PRE-FRAME (2000Q4-2002Q3) quarter\n"
          % (len(sample), len(per_sym)), flush=True)

    res, hit_by_qe = [], collections.Counter()
    tot_need = tot_hit = 0
    for sym, want in sample:
        need = sorted({w["qe"] for w in want})
        row = {"sym": sym, "need": need, "months": sum(x["months"] for x in want), "sites": {}}
        for site in sites:
            try:
                q, note = A.read(site, sym, False)     # standalone -- the only basis that era has
            except Exception as e:                     # noqa: BLE001
                q, note = {}, "%s: EXC %s" % (site, e.__class__.__name__)
            got = [qe for qe in need if qe in q]
            row["sites"][site] = {"note": note, "have": got,
                                  "span": [min(q), max(q)] if q else None,
                                  "nQuarters": len(q)}
            if site == sites[0]:
                tot_need += len(need)
                tot_hit += len(got)
                for qe in got:
                    hit_by_qe[qe] += 1
        res.append(row)
        s0 = row["sites"][sites[0]]
        print("%-14s need %-2d  got %-2d  span %-19s %s"
              % (sym, len(need), len(s0["have"]),
                 ("%d..%d" % tuple(s0["span"])) if s0["span"] else "-", s0["note"][:64]),
              flush=True)

    print("\n=== REACH on the sample (%s) ===" % sites[0])
    print("cells needed: %d   cells the site prints: %d   HIT RATE: %.1f%%"
          % (tot_need, tot_hit, 100.0 * tot_hit / tot_need if tot_need else 0.0))
    print("\nby quarter-end:")
    for qe in ERA:
        need_q = sum(1 for r in res if qe in r["need"])
        if need_q:
            print("   %d  needed %-3d  reached %-3d  (%.0f%%)"
                  % (qe, need_q, hit_by_qe[qe], 100.0 * hit_by_qe[qe] / need_q))
    json.dump({"sample": res, "needed": tot_need, "hit": tot_hit}, open(OUT, "w"), indent=1)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
