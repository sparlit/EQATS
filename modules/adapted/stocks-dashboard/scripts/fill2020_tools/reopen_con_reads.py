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
"""Re-open refusals in scripts/con_pat_nse_reads.json so an improved reader can retry them.

Scoped STRICTLY to the (sym, qe) keys present in the given inventory's con_qtr map -- another
campaign's refusals are never touched. Only refusals whose reason matches one of the given
prefixes are removed; landed reads are never removed.

  python3 scripts/fill2020_tools/reopen_con_reads.py --inv <inventory.json> --reasons fetch:,E-recon,connet-differs
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
READS = os.path.join(os.path.dirname(HERE), "con_pat_nse_reads.json")


def main():
    a = sys.argv[1:]
    inv = json.load(open(a[a.index("--inv") + 1]))
    reasons = a[a.index("--reasons") + 1].split(",")
    scope = set()
    for sym, rec in inv.items():
        for qe_s in rec.get("con_qtr") or {}:
            scope.add(f"{sym}|{qe_s}")
    reads = json.load(open(READS))
    gone = []
    for k in list(reads):
        v = reads[k]
        if k in scope and v.get("skip") and any(v["skip"].startswith(r) for r in reasons):
            gone.append((k, v["skip"][:60]))
            del reads[k]
    json.dump(reads, open(READS, "w"), indent=0, sort_keys=True)
    print(
        "re-opened %d refusal(s) in scope (%d keys in scope, %d ledger entries left)"
        % (len(gone), len(scope), len(reads))
    )
    for k, r in gone[:40]:
        print("  ", k, r)


if __name__ == "__main__":
    main()
