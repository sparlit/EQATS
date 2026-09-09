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
"""REACH PROBE for the 2002-2014 standalone-PAT gap (memory: feedback-measure-source-reach-first).

Answers ONE question before any sweep runs: for the companies that actually have pre-2015 patS
holes, does Moneycontrol's standalone quarterly table reach that far back, and does it carry the
PAT row there? Nothing is written to any dataset.

  python3 -X utf8 scripts/agg_tools/probe_reach_0214.py --cells /tmp/open_cells_0214.json --n 12
"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agg_sources as A  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", required=True)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--syms")
    ap.add_argument("--out")
    a = ap.parse_args()

    cells = json.load(open(a.cells))
    by = collections.defaultdict(list)
    for sym, qe, _field in cells:
        by[sym].append(qe)

    syms = list(a.syms.split(",")) if a.syms else [s for s, _ in sorted(by.items(), key=lambda kv: -len(kv[1]))[: a.n]]

    print("%-12s %-8s %5s  %-9s  %6s  %6s  %s" % ("SYM", "sc_id", "qtrs", "oldest", "gap", "hasPAT", "note"))
    tot_gap = tot_hit = 0
    out = {}
    for sym in syms:
        gaps = sorted(by.get(sym, []))
        ident = A.mc_id(sym)
        if not ident:
            print(
                "%-12s %-8s %5s  %-9s  %6d  %6s  %s"
                % (sym, "-", "-", "-", len(gaps), "-", "no exact symbol match in autosuggest")
            )
            out[sym] = {"sc_id": None, "gaps": len(gaps), "have": 0}
            tot_gap += len(gaps)
            continue
        series, note = A.mc_quarters(sym, con=False)
        have = [q for q in gaps if q in series and series[q].get("pat_total") is not None]
        tot_gap += len(gaps)
        tot_hit += len(have)
        out[sym] = {
            "sc_id": ident["sc_id"],
            "isin": ident.get("isin"),
            "quarters": len(series),
            "oldest": min(series) if series else None,
            "gaps": len(gaps),
            "have": len(have),
            "sample": {str(q): series[q].get("pat_total") for q in have[:3]},
        }
        print(
            "%-12s %-8s %5d  %-9s  %6d  %6d  %s"
            % (sym, ident["sc_id"], len(series), min(series, default="-"), len(gaps), len(have), note[:60])
        )
        sys.stdout.flush()

    print(
        "\nTOTAL over probe: %d of %d gap quarters present with a PAT value (%.1f%%)"
        % (tot_hit, tot_gap, 100.0 * tot_hit / max(1, tot_gap))
    )
    if a.out:
        json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
