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
"""CALIBRATE GATE E2b (the NEIGHBOUR-FY clause) by hold-out, in the era it would be used.

WHY. On the pre-2009 standalone-PAT residue (1,852 cells / 429 symbols, measured 2026-08-26)
GATE E as shipped passes **1 cell**. Its largest addressable refusal is E2: 328 cells, of which
**159 have a target FY whose own quarter-sum closes to the paisa** and are refused only because a
NEIGHBOUR FY does not close. E2's neighbour clause implements runbook §60d ("reject the years
adjacent to a restated one"), which is a real risk -- a restated vintage can bleed across a year
boundary -- but it is a conservatism, not a measurement, and a neighbour restatement is evidence
about the NEIGHBOUR.

So: measure it, exactly as era_calibrate.py measured E1's caps rather than arguing about them.
Every pre-2009 cell we ALREADY hold at a symbol in the residue's own universe is a hold-out test:
drop it from the anchor pool, run the gate as if it were a hole, compare what the gate would have
written against what we store.

  match     the gate reproduces our stored value
  mismatch  it would have written something else -- one of the two is wrong, and at fill time
            there is nothing to notice it

⚠️ Our stored value is not ground truth (§90c measured MC disagreeing with 13.1% of our 2002 cells,
and BHARTIARTL Mar-2005 shows which side can be wrong), so the mismatch rate is an UPPER BOUND on
the gate's error. That is still the right quantity for choosing between two settings of one clause,
because both settings are measured against the same imperfect yardstick.

  python3 -X utf8 scripts/agg_tools/era_calibrate_e2.py --reach <reach.json> --sample 1200
"""
import argparse
import collections
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agg_era_gate as EG  # noqa: E402
import agg_gate as G  # noqa: E402
import mc_era as E  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reach", required=True)
    ap.add_argument("--sample", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--to", type=int, default=20081231, help="hold-out era ceiling (quarter-end)")
    ap.add_argument("--out", default="/tmp/era_calib_e2.json")
    ap.add_argument(
        "--provenance",
        help="JSON [[SYM, QE, 'agg'|'indep'], ...]. Splits the reported mismatch by "
        "whether the TRUTH cell itself came from the aggregator route. ⚠️ A "
        "hold-out whose truth side was written by the route under test is that "
        "route agreeing with itself: it still proves identity and catches "
        "scale/entity errors, but it CANNOT arbitrate vintage. Report both.",
    )
    a = ap.parse_args()
    prov = {}
    if a.provenance:
        prov = {"%s|%d" % (s_, int(q_)): t_ for s_, q_, t_ in json.load(open(a.provenance))}

    reach = json.load(open(a.reach))
    idc = json.load(open(E._ISIN_CACHE))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))

    pop = []
    for sym, rec in reach.items():
        if not rec.get("resolved") or not idc.get(sym):
            continue
        for r in fund.get(sym, []):
            if r[0] <= a.to and r[1] is not None:
                pop.append((sym, r[0]))
    random.Random(a.seed).shuffle(pop)
    pop = pop[: a.sample]
    print("hold-out population: %d cells (<= %d) on %d companies\n" % (len(pop), a.to, len({s for s, _ in pop})))

    results = {}
    for label, neigh in (("E2 strict (target+prev+next)", True), ("E2b target FY only", False)):
        EG.NEIGHBOUR_FY_REQUIRED = neigh
        filled = match = 0
        split = collections.defaultdict(lambda: [0, 0])  # provenance -> [filled, match]
        misses, byyear = [], collections.Counter()
        t0 = time.time()
        for sym, qe in pop:
            ours = G.ours_series(sym, "patS")
            val, rep = EG.check(sym, qe, "patS", ident=idc[sym], excused={qe})
            if val is None:
                continue
            filled += 1
            byyear[qe // 10000] += 1
            tag = prov.get("%s|%d" % (sym, qe), "unknown")
            split[tag][0] += 1
            good = G._agree(ours[qe], val) != "no"
            split[tag][1] += good
            if good:
                match += 1
            else:
                misses.append(
                    {
                        "sym": sym,
                        "qe": qe,
                        "ours": ours[qe],
                        "gate": val,
                        "anchors": rep["chosen"]["anchors"],
                        "fy": rep["detail"].get("A5"),
                    }
                )
        results[label] = {
            "would_fill": filled,
            "reproduced_our_value": match,
            "mismatch": filled - match,
            "mismatch_rate": round(100.0 * (filled - match) / max(1, filled), 2),
            "coverage_of_holdout": round(100.0 * filled / max(1, len(pop)), 1),
            "by_year": dict(sorted(byyear.items())),
            "misses": misses[:60],
            "by_provenance": {
                k: {
                    "filled": v[0],
                    "match": v[1],
                    "mismatch": v[0] - v[1],
                    "mismatch_rate": round(100.0 * (v[0] - v[1]) / max(1, v[0]), 2),
                }
                for k, v in sorted(split.items())
            },
        }
        print(
            "%-30s fills %4d/%d (%4.1f%%)   reproduces ours %4d   MISMATCH %3d (%.2f%%)  [%.0fs]"
            % (
                label,
                filled,
                len(pop),
                100.0 * filled / max(1, len(pop)),
                match,
                filled - match,
                100.0 * (filled - match) / max(1, filled),
                time.time() - t0,
            )
        )
        for tag, v in sorted(split.items()):
            print(
                "      truth-provenance %-8s fills %4d  mismatch %3d (%.2f%%)"
                % (tag, v[0], v[0] - v[1], 100.0 * (v[0] - v[1]) / max(1, v[0]))
            )
        sys.stdout.flush()
    EG.NEIGHBOUR_FY_REQUIRED = True

    json.dump(
        {"population": len(pop), "era_ceiling": a.to, "settings": results}, open(a.out, "w"), indent=1, sort_keys=True
    )
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
