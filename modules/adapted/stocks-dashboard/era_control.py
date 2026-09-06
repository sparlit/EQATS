# -*- coding: utf-8 -*-
"""THE ERA CONTROL -- how accurate is Moneycontrol in 2002-2014, measured on cells we already hold.

The gate proves identity from anchors, but for KSB (and most of this campaign) every anchor is 2008
or later while the targets are 2005-2007. "MC reproduces our 2008-2026 series" is evidence about MC
in THAT era. This measures MC in the era actually being filled: every pre-2015 quarter where our
stored npStd and MC's standalone PAT BOTH exist is a hold-out test we get for free.

It is a control, not a gate -- it cannot vet an individual cell. What it bounds is the error RATE
of the route in this era, which is the number a reader needs to judge the campaign. Reads only the
disk cache written by the sweep; no new fetches unless a symbol was never fetched.

  python3 -X utf8 scripts/agg_tools/era_control.py --syms-from /tmp/reach_0214.json --out /tmp/ctl.json
"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, HERE)
import agg_gate as G                                               # noqa: E402
import mc_era as E                                                 # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms-from", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hi", type=int, default=20141231)
    a = ap.parse_args()

    reach = json.load(open(a.syms_from))
    idcache = json.load(open(E._ISIN_CACHE)) if os.path.exists(E._ISIN_CACHE) else {}

    rows, by_year = [], collections.defaultdict(lambda: [0, 0])
    for sym in sorted(reach):
        ident = idcache.get(sym)
        if not ident:
            continue
        series, _ = E.quarters(ident, con=False)
        if not series:
            continue
        ours = G.ours_series(sym, "patS")
        for qe in sorted(series):
            if qe > a.hi or qe not in ours:
                continue
            v = series[qe].get("pat_total")
            if v is None:
                continue
            verdict = G._agree(ours[qe], v)
            y = qe // 10000
            by_year[y][0] += 1
            if verdict == "no":
                by_year[y][1] += 1
                rows.append({"sym": sym, "qe": qe, "ours": ours[qe], "mc": v,
                             "ratio": round(v / ours[qe], 3) if ours[qe] else None})

    tot = sum(v[0] for v in by_year.values())
    bad = sum(v[1] for v in by_year.values())
    print("PRE-2015 OVERLAP CONTROL -- our stored npStd vs Moneycontrol standalone PAT")
    print("year   overlap  disagree   rate")
    for y in sorted(by_year):
        n, b = by_year[y]
        print("%4d   %7d  %8d  %5.1f%%" % (y, n, b, 100.0 * b / n))
    print("TOTAL  %7d  %8d  %5.1f%%" % (tot, bad, 100.0 * bad / max(1, tot)))

    # a 10x / 0.1x ratio is the scale-step class and indicts OUR cell, not the route
    tens = [r for r in rows if r["ratio"] and (abs(r["ratio"] - 10) < 0.6 or
                                               abs(r["ratio"] - 0.1) < 0.006)]
    print("\nof the %d disagreements, %d are exactly ~10x or ~0.1x (the scale-step class)"
          % (len(rows), len(tens)))
    json.dump({"by_year": {str(k): v for k, v in by_year.items()}, "disagreements": rows,
               "scale_step_like": len(tens)}, open(a.out, "w"), indent=1, sort_keys=True)
    print("wrote %s" % a.out)


if __name__ == "__main__":
    main()
