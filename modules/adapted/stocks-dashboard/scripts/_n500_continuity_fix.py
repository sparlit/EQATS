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
"""Repair the Nifty-500 backward walk between pinned checkpoints.

build_membership_v2.py reconstructs membership by walking BACKWARD from today's
official list:  m = (m - included) | excluded.  That is only self-correcting when
the changelog is complete.  Every EXCLUSION the press-release parser missed is a
member the walk never restores, so the reconstructed count shrinks monotonically
into the past -- 501 at 2018-10-04 down to 485 at 2015-03-27, a ~15-name hole that
sits over the whole 2015-2018 stretch (there is no archived full list between
2015-03-25 and 2018-10-04 to pin it back).

The invariant used here: a symbol present in BOTH surrounding checkpoints, and
never named in an exclusion between them, was a member for the entire interval.
A genuine leave-and-rejoin is recorded as an exclusion, so requiring "never
excluded" keeps those real gaps intact -- the repair only closes holes the
changelog itself cannot account for.

Checkpoint snapshots are pinned exact by the builder, so they are read straight
out of the reconstructed file and share its symbol vocabulary; no re-mapping.

Run: python -X utf8 scripts/_n500_continuity_fix.py [--write] [--idx "Nifty 500"]
"""
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "_indices_history_NEW.json")
WB = os.path.join(HERE, "_wb_n500_snaps.json")
CL = os.path.join(HERE, "_changelog.json")
OUT = os.path.join(HERE, "_indices_history_FIXED.json")


def main():
    write = "--write" in sys.argv
    idx = sys.argv[sys.argv.index("--idx") + 1] if "--idx" in sys.argv else "Nifty 500"

    hist = json.load(open(HIST))
    segs = sorted(hist[idx], key=lambda s: s["effectiveDate"])
    bydate = {s["effectiveDate"]: {x.strip().upper() for x in s["symbols"]} for s in segs}
    dates = [s["effectiveDate"] for s in segs]

    cps = [d for d in sorted(json.load(open(WB))) if d in bydate]
    events = json.load(open(CL)).get(idx, [])

    def excluded_between(lo, hi):
        """every symbol named in an exclusion with lo < eff <= hi"""
        out = set()
        for e in events:
            if lo < e["eff"] <= hi:
                out |= {x.strip().upper() for x in e.get("excluded", [])}
        return out

    added = {}
    for a, b in itertools.pairwise(cps):
        A, B = bydate[a], bydate[b]
        both = A & B
        never_out = both - excluded_between(a, b)
        for d in dates:
            if not (a < d < b):
                continue
            missing = never_out - bydate[d]
            if missing:
                bydate[d] |= missing
                for s in missing:
                    added.setdefault(s, []).append(d)

    print("%-12s %s" % ("date", "before -> after"))
    for s in segs:
        d = s["effectiveDate"]
        if "2015" <= d[:4] <= "2019":
            print("%-12s %4d -> %4d" % (d, len({x.strip().upper() for x in s["symbols"]}), len(bydate[d])))
    print("\nsymbols restored: %d (over %d snapshot-slots)" % (len(added), sum(len(v) for v in added.values())))
    top = sorted(added.items(), key=lambda kv: -len(kv[1]))[:15]
    for s, ds in top:
        print("   %-12s %2d snaps  %s .. %s" % (s, len(ds), ds[0], ds[-1]))

    if write:
        for s in segs:
            s["symbols"] = sorted(bydate[s["effectiveDate"]])
        hist[idx] = segs
        json.dump(hist, open(OUT, "w"), separators=(",", ":"))
        print("\nwritten:", OUT)


if __name__ == "__main__":
    main()
