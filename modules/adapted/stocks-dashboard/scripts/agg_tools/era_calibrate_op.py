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
"""CALIBRATE GATE E for STANDALONE OPERATING PROFIT (opS) by hold-out -- the op twin of
era_calibrate.py, which is hard-wired to patS / sf_fundamentals.

Why a separate calibration and not a reuse of the patS numbers: the anchor GEOMETRY differs. For
patS our pre-2015 series is dense (§90i: 62-99% per year), so a hold-out cell usually has stored
neighbours a few quarters away. For opS the store is 0-27% before 2015, 84-93% in 2015-16 and
90%+ from 2018 (measured 2026-09-05), so a real fill target in 2005 sits 40 quarters from its
nearest anchor and every anchor comes from a DIFFERENT extraction (XBRL 2018+, BSE-PDF reads
2015-16) than the one that produced the few pre-2015 op cells we hold (detres/STEP-N, 2026-08-04).
A gate calibrated on patS says nothing about that. Measure it.

Two hold-out variants per cell, both run by dropping the cell from the anchor pool
(`excused` -- agg_era_gate.check never counts an excused quarter as agreement or disagreement):

  self      drop only the target       -> what era_calibrate.py measures
  strict    drop EVERY stored opS of that symbol dated <= 2017 -> the true fill geometry: the
            gate may anchor only on 2018+ (and nothing else), exactly as it will for the
            16,000-cell queue where the symbol holds NO pre-2017 op at all

  match     the gate reproduces our stored value (agg_gate._agree != "no")
  mismatch  it would have written something else -- an UPPER bound on gate error (our stored
            cell can be the wrong one; §90c measured 5.2% of stored pre-2015 PAT disagreeing)

  python3 -X utf8 scripts/agg_tools/era_calibrate_op.py --reach /tmp/reach_op.json --sample 800
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reach", required=True)
    ap.add_argument("--sample", type=int, default=800)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--lo", type=int, default=20050331)
    ap.add_argument("--hi", type=int, default=20171231)
    ap.add_argument("--exclude", help="json list of symbols to leave out (lenders)")
    ap.add_argument(
        "--excuse",
        help="json {SYM: [qe,...]}: stored cells adjudicated as NOT this "
        "field's definition (the EBIT-in-op-slot class). They are "
        "removed from the hold-out population AND from every anchor "
        "pool, exactly as the sweep will run.",
    )
    ap.add_argument("--out", default="/tmp/era_calib_op.json")
    ap.add_argument("--e2-pat", action="store_true", help="E2 vintage test on PAT (see agg_era_gate)")
    a = ap.parse_args()
    if a.e2_pat:
        EG.E2_VINTAGE_FOR_OP = "pat_total"

    reach = json.load(open(a.reach))
    idc = json.load(open(E._ISIN_CACHE)) if os.path.exists(E._ISIN_CACHE) else {}
    excl = set(json.load(open(a.exclude))) if a.exclude else set()
    excuse = {k: set(v) for k, v in json.load(open(a.excuse)).items()} if a.excuse else {}

    pop = []
    for sym, rec in reach.items():
        if not rec.get("resolved") or sym in excl:
            continue
        ours = G.ours_series(sym, "opS")
        for qe, v in ours.items():
            if a.lo <= qe <= a.hi and v is not None and v != 0.0 and qe not in excuse.get(sym, ()):
                pop.append((sym, qe))
    random.Random(a.seed).shuffle(pop)
    pop = pop[: a.sample]
    print(
        "hold-out population: %d cells on %d companies (opS, %d..%d)\n"
        % (len(pop), len({s for s, _ in pop}), a.lo, a.hi)
    )

    results = {}
    for variant in ("self", "strict"):
        filled = match = 0
        by_year = collections.defaultdict(lambda: [0, 0])
        misses, states = [], collections.Counter()
        t0 = time.time()
        for sym, qe in pop:
            ours = G.ours_series(sym, "opS")
            if variant == "self":
                excused = {qe} | excuse.get(sym, set())
            else:
                excused = {q for q in ours if q <= 20171231} | excuse.get(sym, set())
            val, rep = EG.check(sym, qe, "opS", ident=idc.get(sym), excused=excused)
            states[rep.get("state", "?")] += 1
            if val is None:
                continue
            filled += 1
            y = qe // 10000
            by_year[y][1] += 1
            if G._agree(ours[qe], val) != "no":
                match += 1
                by_year[y][0] += 1
            else:
                misses.append(
                    {
                        "sym": sym,
                        "qe": qe,
                        "ours": ours[qe],
                        "gate": val,
                        "row": (rep.get("chosen") or {}).get("row"),
                        "anchors": (rep.get("chosen") or {}).get("anchors"),
                    }
                )
        results[variant] = {
            "population": len(pop),
            "filled": filled,
            "match": match,
            "mismatch": filled - match,
            "mismatch_rate": round(100.0 * (filled - match) / max(1, filled), 2),
            "by_year": {y: {"match": m, "filled": f} for y, (m, f) in sorted(by_year.items())},
            "states": dict(states),
            "misses": misses,
        }
        print(
            "variant %-6s  filled %4d/%4d  match %4d  mismatch %3d (%.2f%%)  %.0fs"
            % (
                variant,
                filled,
                len(pop),
                match,
                filled - match,
                100.0 * (filled - match) / max(1, filled),
                time.time() - t0,
            )
        )
        for y, (m, f) in sorted(by_year.items()):
            print("      %d  filled %4d  mismatch %3d" % (y, f, f - m))
        print("      states:", dict(states))
        for m in misses[:25]:
            print("      MISS", m)
        sys.stdout.flush()
    json.dump(results, open(a.out, "w"), indent=1, sort_keys=True)
    print("\n->", a.out)


if __name__ == "__main__":
    main()
