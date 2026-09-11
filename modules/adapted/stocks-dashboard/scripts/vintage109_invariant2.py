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
"""PER-CELL before -> after agreement with BSE detres. The only shape that shows a REGRESSION.

Counting "how many disagree now" cannot see a cell that was fine and got worse; this compares the
same cell to itself. A single WORSENED row is the §109d hole and blocks the campaign.
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SLOT = {"std": 1, "con": 3}
REVOP_SLOT = {"std": 0, "con": 1, "op_std": 2, "op_con": 3, "pat_std": 4, "pat_con": 5}


def agree(a, b, ab=2.0, rl=0.03):
    return a is not None and b is not None and abs(a - b) <= max(ab, abs(b) * rl)


def fnum(f, *names):
    for n in names:
        v = f.get(n)
        if v not in (None, "", "-"):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def main():
    scan = json.load(open(os.path.join(HERE, "_vintage108_scan.json")))["cells"]
    raw = json.load(open(os.path.join(HERE, "_vintage108_raw.json")))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    # Reconstruct BEFORE from the LEDGERS' own `was` values, not from a scratch proposals file:
    # `was` is committed, exact, and still correct after the heal has been applied, so this check
    # can be re-run at any time (a scratch file is rewritten and the comparison silently empties).
    CAMP = ("vintage109 by-product campaign", "vintage109 re-read of the §108 sweep")

    def _mine(lg):
        return [
            f
            for f in json.load(open(os.path.join(HERE, lg)))["fixes"]
            if any(t in str(f.get("found", "")) for t in CAMP)
        ]

    heals = {"proposals": _mine("fund_cell_fix.json"), "revop": _mine("revop_cell_fix.json")}

    before_pat, before_rev = {}, {}
    for k, v in scan.items():
        if v.get("state") != "done":
            continue
        sym, qe = v["sym"], v["qe"]
        row = next((r for r in fund.get(sym, []) if r[0] == qe), None)
        before_pat[k] = row[1] if row and len(row) > 1 else None
        rr = (revop.get(sym) or {}).get(str(qe)) or []
        before_rev[k] = rr[0] if rr else None

    # the files on disk ARE the "after"; roll each healed cell BACK to its ledgered `was`
    after_pat, after_rev = dict(before_pat), dict(before_rev)
    for p in heals["proposals"]:
        if p["basis"] == "std":
            k = "{}|{}".format(p["sym"], p["qe"])
            if k in before_pat:
                before_pat[k] = p["was"]
    for p in heals["revop"]:
        if p["basis"] == "std":
            k = "{}|{}".format(p["sym"], p["qe"])
            if k in before_rev:
                before_rev[k] = p["was"]

    for tag, bef, aft, det_get in (
        ("std PAT", before_pat, after_pat, lambda k: scan.get(k, {}).get("detres")),
        (
            "std revenue",
            before_rev,
            after_rev,
            lambda k: (lambda v: None if v is None else v / 10.0)(
                fnum(
                    raw.get(k, {}),
                    "Net Sales/Revenue From Operations",
                    "Total Income From Operations",
                    "Net Sales",
                    "Interest Earned",
                )
            ),
        ),
    ):
        c, worse = Counter(), []
        nb = na = n = 0
        for k in bef:
            d = det_get(k)
            if d is None:
                continue
            b, a = bef[k], aft[k]
            if b is None and a is None:
                continue
            n += 1
            ab, aa = agree(b, d), agree(a, d)
            nb += ab
            na += aa
            if ab and not aa:
                c["WORSENED"] += 1
                worse.append((k, b, a, d))
            elif aa and not ab:
                c["improved"] += 1
            elif b != a:
                c["moved, both %s" % ("agree" if aa else "disagree")] += 1
            else:
                c["untouched"] += 1
        print("\n%-12s  %d cells with a detres reading" % (tag, n))
        print(f"   agreement  BEFORE {100.0 * nb / n:5.1f}%  ->  AFTER {100.0 * na / n:5.1f}%")
        print(f"   {dict(c)}")
        for w in worse:
            print("     REGRESSION %-24s %s -> %s   detres %s" % w)
    print("\n(a WORSENED count above zero is the §109d hole and blocks the campaign)")


if __name__ == "__main__":
    main()
