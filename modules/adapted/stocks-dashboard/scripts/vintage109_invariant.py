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
"""THE POST-HEAL INVARIANT — agreement with BSE detres, before vs after, over the WHOLE window.

§109d's gate was first written as "at least one line of evidence" and that let a PROV-only cell be
healed towards a value detres rejects. Nothing in the per-cell logic caught it; this did — agreement
with an independent as-filed reader rose but not to 100%, and every cell left disagreeing was the
hole. So the campaign does not ship on the strength of its own gate; it ships on this number.

Run BEFORE `--apply` (simulated) and AFTER (against the written files) — both must read 100%.
RUN: python3 scripts/vintage109_invariant.py [--after]
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
    after = "--after" in sys.argv
    scan = json.load(open(os.path.join(HERE, "_vintage108_scan.json")))["cells"]
    raw = json.load(open(os.path.join(HERE, "_vintage108_raw.json")))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    heals = json.load(open(os.path.join(HERE, "_vintage109_heals.json")))

    # simulate the heal on an in-memory copy unless we are reading the written files
    if not after:
        for p in heals["proposals"]:
            row = next((r for r in fund.get(p["sym"], []) if r[0] == int(p["qe"])), None)
            if row and len(row) > SLOT[p["basis"]]:
                row[SLOT[p["basis"]]] = p["fixed"]
        for p in heals["revop"]:
            row = (revop.get(p["sym"]) or {}).get(str(p["qe"]))
            s = REVOP_SLOT[p["basis"]]
            if row and len(row) > s:
                row[s] = p["fixed"]

    healed = {(p["sym"], p["qe"], p["basis"]) for p in heals["proposals"]}
    for tag, getter, det_get in (
        (
            "std PAT",
            lambda sym, qe: next((r[1] for r in fund.get(sym, []) if r[0] == qe), None),
            lambda k: scan.get(k, {}).get("detres"),
        ),
        (
            "std revenue",
            lambda sym, qe: ((revop.get(sym) or {}).get(str(qe)) or [None])[0],
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
        n = ok = 0
        bad = []
        for k, v in scan.items():
            if v.get("state") != "done":
                continue
            sym, qe = v["sym"], v["qe"]
            cur, det = getter(sym, qe), det_get(k)
            if cur is None or det is None:
                continue
            n += 1
            if agree(cur, det):
                ok += 1
            else:
                bad.append((sym, qe, cur, det, (sym, str(qe), "std") in healed))
        print(
            "%-12s  %4d cells with a detres reading   agreement %5.1f%%   (%d disagree)"
            % (tag, n, 100.0 * ok / max(n, 1), len(bad))
        )
        touched = [b for b in bad if b[4]]
        print("               of the disagreements, %d are cells THIS CAMPAIGN moved" % len(touched))
        for b in touched[:15]:
            print("                  %-13s %-9s store=%-11s detres=%s" % (b[0], b[1], b[2], b[3]))


if __name__ == "__main__":
    main()
