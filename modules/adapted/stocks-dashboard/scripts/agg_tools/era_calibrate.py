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
"""CALIBRATE GATE E by hold-out, instead of arguing about its constants.

GATE E's E1 cap (<=2 disagreeing anchors anywhere, <=3%) refuses 949 cells on 210 companies whose
series agree with ours 92-97% of the time -- KTKBANK 83 anchors / 3 disagreements, BASF 82/4,
UNITECH 80/4 -- and the disagreements are typically 12-17 years from the target, which is the exact
mistake runbook §81e recorded when agg_gate's GUARD_Q was 12: "those distant misses are usually OUR
defective cells, so the veto punished the wrong cell". agg_gate's own global cap is 15%, not 3%.

So: measure. Every pre-2015 cell we ALREADY hold is a hold-out test. Drop it from the anchor pool,
run GATE E as if it were a hole, and compare what the gate would have written against what we
store. Repeat per parameter setting.

  match     the gate reproduces our stored value    -> filling a hole at this setting is as safe
                                                      as the cells we already trust
  mismatch  it would have written something else    -> one of the two is wrong, and at fill time
                                                      there is nothing to notice it

⚠️ Our stored value is not ground truth -- 5.2% of it disagrees with MC in this era and BHARTIARTL
Mar-2005 (-13.96 against a filing-scale 1,209.56) shows which way that can go. So the mismatch rate
is an UPPER BOUND on the gate's error, not the error itself, and it is the right quantity for
choosing a cap: a setting whose hold-out mismatch is ~1% cannot be writing many wrong cells.

  python3 -X utf8 scripts/agg_tools/era_calibrate.py --reach /tmp/reach_0214.json --sample 1500
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

SETTINGS = [(2, 0.03), (3, 0.05), (4, 0.06), (6, 0.10), (10, 0.15), (99, 0.15)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reach", required=True)
    ap.add_argument("--sample", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="/tmp/era_calib.json")
    a = ap.parse_args()

    reach = json.load(open(a.reach))
    idc = json.load(open(E._ISIN_CACHE))
    fund = json.load(open(os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "sf_fundamentals.json")))

    # hold-out population: cells we hold, pre-2015, on companies MC resolved
    pop = []
    for sym, rec in reach.items():
        if not rec.get("resolved") or sym not in idc or not idc[sym]:
            continue
        for r in fund.get(sym, []):
            if r[0] <= 20141231 and r[1] is not None:
                pop.append((sym, r[0]))
    random.Random(a.seed).shuffle(pop)
    pop = pop[: a.sample]
    print("hold-out population: %d cells on %d companies\n" % (pop and len(pop), len({s for s, _ in pop})))

    results = {}
    for maxbad, rate in SETTINGS:
        EG.MAX_BAD, EG.MAX_BAD_RATE = maxbad, rate
        filled = match = 0
        misses = []
        t0 = time.time()
        for sym, qe in pop:
            ours = G.ours_series(sym, "patS")
            val, rep = EG.check(sym, qe, "patS", ident=idc[sym], excused={qe})
            if val is None:
                continue
            filled += 1
            if G._agree(ours[qe], val) != "no":
                match += 1
            else:
                misses.append(
                    {"sym": sym, "qe": qe, "ours": ours[qe], "gate": val, "anchors": rep["chosen"]["anchors"]}
                )
        key = "maxbad={} rate={:.0f}%".format("inf" if maxbad == 99 else maxbad, rate * 100)
        results[key] = {
            "would_fill": filled,
            "reproduced_our_value": match,
            "mismatch": filled - match,
            "mismatch_rate": round(100.0 * (filled - match) / max(1, filled), 2),
            "coverage_of_holdout": round(100.0 * filled / len(pop), 1),
            "misses": misses[:40],
        }
        print(
            "%-22s fills %4d/%d (%4.1f%% of hold-out)   reproduces ours %4d   MISMATCH %3d (%.2f%%)  [%.0fs]"
            % (
                key,
                filled,
                len(pop),
                100.0 * filled / len(pop),
                match,
                filled - match,
                100.0 * (filled - match) / max(1, filled),
                time.time() - t0,
            )
        )
        sys.stdout.flush()

    json.dump({"population": len(pop), "settings": results}, open(a.out, "w"), indent=1, sort_keys=True)
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
