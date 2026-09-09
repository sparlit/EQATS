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
"""§54a SAME-BASIS NEIGHBOUR BAND — the screen that catches a power-of-ten read.

WHY THIS EXISTS, and what it caught. The 2018 §58 sweep landed HINDALCO 2018-12 revC = **332,131.0**
against a standalone 11,937.74. Its own CONSOLIDATED neighbours run 31,077 / 33,745 / 29,972 /
29,657 / 29,197 — so the value is 10x its true magnitude, a plain scale error, and it passed every
guard the sweep has:

  * the PAT column anchor passed — the COLUMN was identified correctly; only the SCALE was wrong,
    and PAT and revenue were both scaled by the same wrong factor on that page;
  * `con-rev-far-below-std` only fires BELOW standalone, and this is 27.8x ABOVE it;
  * §54a explicitly forbids banding against the OTHER basis' stored twin — con/std ratios are
    legitimately huge (BBTC runs 41-61x because it holds Britannia; TMPV 4.6x for JLR) — so the
    obvious check is the wrong one and would reject real data.

§54a's prescription is the one that works: **band against the company's OWN SAME-BASIS neighbouring
quarters.** A consolidated revenue that is 10x every other consolidated quarter is wrong regardless
of what the standalone side does.

Run over every cell a campaign writes, not just the suspicious-looking ones.

  python -X utf8 scripts/fill2020_tools/screen_neighbour_band.py [--qe 20180331,...] [--band 3.0]
"""
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TARGETS = os.path.join(HERE, "_rev2018_targets.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
Q2018 = [20180331, 20180630, 20180930, 20181231]


def main():
    qes = {int(q) for q in sys.argv[sys.argv.index("--qe") + 1].split(",")} if "--qe" in sys.argv else set(Q2018)
    band = float(sys.argv[sys.argv.index("--band") + 1]) if "--band" in sys.argv else 3.0
    targets = json.load(open(TARGETS))
    revop = json.load(open(REVOP))

    checked, flagged, nonb = 0, [], []
    for sym, v in sorted(targets.items()):
        for basis, slot in (("std", 0), ("con", 1)):
            want = v.get("revS" if basis == "std" else "revC", [])
            for qe in want:
                if qe not in qes:
                    continue
                row = (revop.get(sym) or {}).get(str(qe))
                if not row or len(row) <= slot or row[slot] is None:
                    continue
                val = row[slot]
                checked += 1
                # SAME-BASIS neighbours only, and never the cell itself.
                nb = [
                    r[slot]
                    for q, r in (revop.get(sym) or {}).items()
                    if int(q) != qe and len(r) > slot and r[slot] not in (None, 0)
                ]
                if len(nb) < 3:
                    nonb.append((sym, qe, basis, val, len(nb)))
                    continue
                # ADJACENT quarters, not the whole-series median. A global median is the wrong
                # scale reference for a trending series (it produced 99.3% false positives in the
                # §74 scale campaign) AND it is too blunt the other way: Hindalco's own consolidated
                # revenue nearly doubles across the stored window, so its global median (53,151)
                # made a 10x error look like 6.25x. The six nearest same-basis quarters track the
                # trend, so the ratio means what it looks like.
                near = sorted(
                    (
                        (abs(int(q) - qe), r[slot])
                        for q, r in (revop.get(sym) or {}).items()
                        if int(q) != qe and len(r) > slot and r[slot] not in (None, 0)
                    )
                )[:6]
                ref = statistics.median([v for _, v in near])
                if ref <= 0:
                    nonb.append((sym, qe, basis, val, len(nb)))
                    continue
                ratio = val / ref
                if ratio > band or ratio < 1.0 / band:
                    flagged.append((sym, qe, basis, val, ref, ratio, len(near)))

    print("cells checked: %d   band: %.1fx the nearest-6 same-basis median\n" % (checked, band))
    print("FLAGGED (%d):" % len(flagged))
    for sym, qe, basis, val, med, ratio, n in sorted(flagged, key=lambda x: -abs(x[5])):
        print(
            "  %-12s %d %s  value %14.2f   nearest-6 median %12.2f over %2d qtrs   ratio %7.2fx"
            % (sym, qe, basis, val, med, n, ratio)
        )
    if not flagged:
        print("  (none)")
    print("\nNO BAND POSSIBLE (fewer than 3 same-basis neighbours) — %d:" % len(nonb))
    for sym, qe, basis, val, n in sorted(nonb):
        print("  %-12s %d %s  value %14.2f   neighbours %d" % (sym, qe, basis, val, n))


if __name__ == "__main__":
    main()
