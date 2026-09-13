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
"""Per-cell continuity gate for the Dec-2015 / Mar-2016 seam cells.

WHY THIS EXISTS. The seam derivation reconstructs FII as the un-itemised remainder of the
institutions block (inst_sub minus the itemised domestic rows). Measured against our own Jun-2016
XBRL cells that is excellent AT THE MEDIAN (0.87pp) and has a fat tail: p90 8.78pp, max 45.61pp,
16% of cells >5pp. The TOTAL institutions figure is sound throughout (median 0.41pp, p90 2.67) —
it is the FII/DII SPLIT that fails, because for some companies the remainder is domestic, not
foreign (JUSTDIAL derived 58.49 against a 12.88 anchor; LICHSGFIN 27.53 against 0.00).

A median gate cannot see this. That is the same mistake recorded in memory as
"MEDIAN is the wrong scale ref" — committed again while building the gate meant to prevent it.
So: gate EVERY cell individually against a value we did not derive.

ANCHOR LADDER, best first:
  1. our own parsed cell (from XBRL, not from a seam ledger) at the nearest quarter — Jun-2016
     forward or Sep-2015 back; tolerance widens with distance;
  2. no such anchor -> the OTHER route's value for the same cell (wayback-derived vs Trendlyne-rows,
     genuinely independent: different site, different method), on a tighter tolerance since there
     is no time gap to excuse;
  3. neither -> UNVERIFIABLE. Kept only if --keep-unanchored, and always tagged in provenance so a
     later audit can find them.

  python3 -X utf8 scripts/_shp_seam_continuity_gate.py --dry
  python3 -X utf8 scripts/_shp_seam_continuity_gate.py            # rewrites both ledgers
"""
import argparse
import collections
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WB = os.path.join(HERE, "shp_fill_hist_2010_2016.json.gz")
TP = os.path.join(HERE, "shp_fill_thirdparty.json.gz")
HIST = os.path.join(HERE, "shp_history.json")
SEAM = ("2015-12-31", "2016-03-31")
# tolerance in pp on |fii - anchor_fii|, by quarters of separation. One quarter of genuine drift is
# small (the anchored median is 0.87pp); 5pp is generous to a real move and still amputates the tail.
TOL = {1: 5.0, 2: 7.0}
TOL_CROSS = 2.0  # route-vs-route, no time gap, so demand more


def load_gz(p):
    return json.load(gzip.open(p, "rt", encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--keep-unanchored", action="store_true")
    a = ap.parse_args()

    hist = json.load(open(HIST, encoding="utf-8"))
    wb, tp = load_gz(WB), load_gz(TP)

    seam_src = collections.defaultdict(dict)  # (sym,qe) -> {route: cell}
    for route, led in (("wayback", wb), ("trendlyne", tp)):
        for s, qs in led["fills"].items():
            for q, c in qs.items():
                if q in SEAM:
                    seam_src[(s, q)][route] = c

    # anchors = cells in shp_history that are NOT seam cells, i.e. parsed by us from XBRL
    def anchor_for(sym, qe):
        h = hist.get(sym) or {}
        cands = []
        for aq, dist in (
            ("2016-06-30", 1 if qe == "2016-03-31" else 2),
            ("2015-09-30", 1 if qe == "2015-12-31" else 2),
        ):
            if aq in h and (sym, aq) not in seam_src:
                cands.append((dist, aq, h[aq]))
        cands.sort()
        return cands[0] if cands else None

    verdict = collections.Counter()
    drops = collections.defaultdict(list)
    keep = {}
    for (sym, qe), routes in sorted(seam_src.items()):
        anc = anchor_for(sym, qe)
        for route, cell in routes.items():
            fii = cell[1]
            if anc:
                dist, _aq, ac = anc
                # ⚠ CHECK BOTH LEGS. The first version gated on fii alone and let HDFCBANK
                # Dec-2015 through with dii 53.51 against a 13.79 anchor — it passed because its
                # fii was fine. A split error can sit in EITHER leg; gating one is gating neither.
                d = max(abs(fii - ac[1]), abs(cell[2] - ac[2]))
                ok = d <= TOL.get(dist, 7.0)
                verdict["{}:{}".format(route, "PASS-anchor" if ok else "DROP-anchor")] += 1
                if not ok:
                    drops[route].append((round(d, 2), sym, qe, fii, ac[1]))
                    continue
                keep[(sym, qe, route)] = cell
                continue
            other = [r for r in routes if r != route]
            if other:
                o = routes[other[0]]
                d = max(abs(fii - o[1]), abs(cell[2] - o[2]))
                ok = d <= TOL_CROSS
                verdict["{}:{}".format(route, "PASS-cross" if ok else "DROP-cross")] += 1
                if not ok:
                    drops[route].append((round(d, 2), sym, qe, fii, routes[other[0]][1]))
                    continue
                keep[(sym, qe, route)] = cell
                continue
            verdict[f"{route}:UNANCHORED"] += 1
            if a.keep_unanchored:
                c = list(cell)
                if len(c) > 7:
                    c[7] = str(c[7]) + ";UNVERIFIED-split"
                keep[(sym, qe, route)] = c

    print("VERDICTS")
    for k in sorted(verdict):
        print("   %-24s %4d" % (k, verdict[k]))
    for route in sorted(drops):
        drops[route].sort(reverse=True)
        print(f"\n   worst {route} drops (|fii-anchor|, sym, qe, cell, anchor):")
        for d in drops[route][:6]:
            print("      %6.2fpp  %-11s %s   fii %6.2f vs %6.2f" % d)

    # rebuild both ledgers keeping only survivors
    sum(1 for _ in seam_src for _ in _ if False) or 0
    for route, led, path in (("wayback", wb, WB), ("trendlyne", tp, TP)):
        f = led["fills"]
        before = sum(1 for s, qs in f.items() for q in qs if q in SEAM)
        for s in list(f):
            for q in list(f[s]):
                if q in SEAM and (s, q, route) not in keep:
                    del f[s][q]
                elif q in SEAM:
                    f[s][q] = keep[(s, q, route)]
            if not f[s]:
                del f[s]
        after = sum(1 for s, qs in f.items() for q in qs if q in SEAM)
        led["_meta"]["cells"] = sum(len(v) for v in f.values())
        led["_meta"]["seam_continuity_gate"] = {
            "kept": after,
            "dropped": before - after,
            "tol_pp_by_quarter_gap": TOL,
            "tol_cross_route_pp": TOL_CROSS,
            "why": "median-only validation hid a fat tail (p90 8.78pp); every seam cell is now "
            "gated individually against a value we did not derive",
        }
        print("\n%-10s seam cells %d -> %d  (dropped %d)" % (route, before, after, before - after))
        if not a.dry:
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                json.dump(led, fh, separators=(",", ":"))
    print("\n(dry run — nothing written)" if a.dry else "\nledgers rewritten")


if __name__ == "__main__":
    main()
