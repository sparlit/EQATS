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
"""Resync sf_revop's con-PAT MIRROR to the authoritative sf_fundamentals. Writes only the mirror.

WHY A RESYNC AND NOT AN ADJUDICATION. 766 cells disagreed. The obvious move was to adjudicate each
against the filer's XBRL -- and that was tried first and ABANDONED, because the XBRL owners tag is
itself the corrupted thing in this population:

    MARUTI 2022-09-30   sf_fundamentals 2112.50   XBRL owners tag  212.50   (true: 2112.5)
    LUPIN  2021-09-30   sf_fundamentals -2094.87  XBRL owners tag -209.84   (true: -2094.87)
    KAYNES 2023-03-31   sf_fundamentals   63.51   XBRL owners tag 5814249.6
    SELMCL 2018-03-31   sf_fundamentals -1541.55  XBRL owners tag +1541.34  (sign flipped)

`build_fundamentals.xbrl_profit` -- the EPS-guarded parser -- returns the SAME bad tag, so
sf_fundamentals' correct values did not come from these cached filings at all. Trusting the cache
would have overwritten 693 correct values with garbage, at scale. sf_revop's patC is built from the
unguarded tag, which is exactly why it is the file that diverges.

SO: sf_fundamentals is authoritative (`stock.html`: "never swap in sf_revop's PAT mirror slots";
`build_quarterly_results` the same), it is what the site displays, and after §70 it is what
Discovery reads. Making the mirror match it introduces NO new error anywhere -- worst case the
mirror carries an error the site was already showing -- and it removes the whole divergence class.

HELD BACK: 23 cells where sf_fundamentals is itself the suspect, screened against each company's
OWN median |npCon| (fund out-of-family by >8x or <0.125x while revop is in-family). Resyncing from
a value that looks wrong would launder it into a second file. Those are journalled instead, in
`_fund_suspect_cells.json`, as a fresh audit list.

  python -X utf8 scripts/fill2020_tools/resync_revop_patc_2026_08_09.py [--apply]
"""
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
FUNDP = os.path.join(ROOT, "docs", "sf_fundamentals.json")
REVOP = (os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(SCRIPTS, "revop_fundamentals.json"))
SUSPECTS = os.path.join(SCRIPTS, "_fund_suspect_cells.json")
FUND_IDX, REVOP_IDX = 3, 5


def main():
    dry = "--apply" not in sys.argv
    fu = json.load(open(FUNDP, encoding="utf-8"))
    auth, fam = {}, {}
    for sym, rows in fu.items():
        for r in rows:
            if len(r) > FUND_IDX and r[FUND_IDX] is not None:
                auth[(sym, r[0])] = r[FUND_IDX]
        vals = [
            abs(r[FUND_IDX]) for r in rows if len(r) > FUND_IDX and r[FUND_IDX] is not None and abs(r[FUND_IDX]) > 0.01
        ]
        if len(vals) >= 6:
            fam[sym] = statistics.median(vals)

    def oof(v, m):
        if m is None or v is None or abs(v) < 0.01:
            return False
        r = abs(v) / m
        return r > 8 or r < 0.125

    rv = json.load(open(REVOP[0], encoding="utf-8"))
    div, suspect = [], []
    for sym, qmap in rv.items():
        for q, row in qmap.items():
            if not row or len(row) <= REVOP_IDX or row[REVOP_IDX] is None:
                continue
            a = auth.get((sym, int(q)))
            if a is None or abs(a - row[REVOP_IDX]) <= max(0.02, abs(a) * 0.002):
                continue
            m = fam.get(sym)
            if oof(a, m) and not oof(row[REVOP_IDX], m):
                suspect.append(
                    {"sym": sym, "qe": int(q), "fund": a, "revop": row[REVOP_IDX], "family_median": round(m, 2)}
                )
            else:
                div.append((sym, int(q), a))

    print("divergent con-PAT cells      : %d" % (len(div) + len(suspect)))
    print("  resync mirror <- authoritative : %d" % len(div))
    print("  HELD BACK, fundamentals suspect: %d" % len(suspect))
    for s in sorted(suspect, key=lambda z: -abs(z["fund"]))[:8]:
        print(
            "     %-12s %d fund=%-12s revop=%-11s family_median=%s"
            % (s["sym"], s["qe"], s["fund"], s["revop"], s["family_median"])
        )

    n = 0
    for path in REVOP:
        d = json.load(open(path, encoding="utf-8"))
        for sym, qe, a in div:
            row = (d.get(sym) or {}).get(str(qe))
            if (
                row
                and len(row) > REVOP_IDX
                and row[REVOP_IDX] is not None
                and abs(row[REVOP_IDX] - a) > max(0.02, abs(a) * 0.002)
            ):
                row[REVOP_IDX] = a
                n += 1
        if not dry:
            json.dump(d, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    print("\n%d mirror slot(s) %s" % (n, "would change (dry run)" if dry else "changed"))
    if dry:
        print("(sf_fundamentals is NOT touched by this script at all)")
        print("(pass --apply)")
        return
    json.dump(
        {
            "_README": [
                "Cells where sf_fundamentals' npCon is ITSELF out of family against that company's own",
                "median |npCon| (>8x or <0.125x) while sf_revop's mirror is in family. NOT resynced --",
                "copying a value that looks wrong would launder it into a second file. Each needs a filing",
                "read. Found 2026-08-09 while resyncing the mirror; runbook §71.",
            ],
            "generated": "2026-08-09",
            "cells": suspect,
        },
        open(SUSPECTS, "w", encoding="utf-8"),
        indent=1,
    )
    print(f"suspect list -> {SUSPECTS}")


if __name__ == "__main__":
    main()
