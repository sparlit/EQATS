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
"""PRE2015_CAMPAIGN STEP D batch-cycle guard (GROUND RULES 7 / LANDING RULES "poison
defences"): the year-shift detector, PAT(q) == PAT(q+10000) exactly (|v|>0.5), run
after every batch. Report-only -- this never writes/heals, it just flags for the
run to stop-and-report if something NEW (not already in yshift_genuine.json) shows
up on a CELL THIS CAMPAIGN ITSELF LANDED (std slot only, from pre2015_reads_d.json
-- STEP D never writes con). Deliberately narrower than "any pair on a touched
symbol": a symbol can carry pre-existing, already-scoped-elsewhere 2015+-era pairs
(e.g. a con-slot pair from the original XBRL pipeline) that have nothing to do with
this batch and would otherwise false-alarm every single run.

Run: python -X utf8 scripts/_yshift_scan_pre15.py [--reads FILE]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    argv = sys.argv
    readsf = argv[argv.index("--reads") + 1] if "--reads" in argv else os.path.join(HERE, "pre2015_reads_d.json")
    # A bare filename resolves against THIS script's dir, not the caller's cwd.
    # The STEP N driver invokes with cwd=ROOT and passes a plain filename, so
    # without this the file silently "doesn't exist", reads={} and the scan
    # reports "clean (0 landed cells checked)" -- which is what it did for all
    # 27 chunks of the 2026-08-04 run, disarming the poison guard completely.
    if not os.path.dirname(readsf):
        readsf = os.path.join(HERE, readsf)
    if not os.path.exists(readsf):
        # Never silently pass: a missing reads file means the guard cannot do
        # its job, which must be loud, not "clean".
        print(f"YSHIFT-SCAN: ERROR reads file not found: {readsf}")
        sys.exit(1)
    reads = json.load(open(readsf, encoding="utf8"))
    landed_qes = {sym: {int(qe) for qe in cells} for sym, cells in reads.items()}  # std only, by construction

    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf8"))
    genuine = json.load(open(os.path.join(HERE, "yshift_genuine.json"), encoding="utf8"))

    flagged = []
    for sym, qes in landed_qes.items():
        rows = fund.get(sym, [])
        m = {r[0]: r for r in rows}
        gsym = genuine.get(sym, {})
        idx, slot = 1, "std"  # STEP D only ever writes std (LANDING RULES 3)
        for qe in qes:
            r = m.get(qe)
            v = r[idx] if r and len(r) > idx else None
            if v is None or abs(v) <= 0.5:
                continue
            for partner_qe in (qe - 10000, qe + 10000):
                partner = m.get(partner_qe)
                pv = partner[idx] if partner and len(partner) > idx else None
                if pv is None or round(v, 2) != round(pv, 2):
                    continue
                key_a, key_b = "%d|%s" % (qe, slot), "%d|%s" % (partner_qe, slot)
                if key_a in gsym or key_b in gsym:
                    continue
                pair_key = (sym, min(qe, partner_qe), slot)
                if pair_key in {(f[0], f[1], f[2]) for f in flagged}:
                    continue
                flagged.append((sym, min(qe, partner_qe), slot, v))

    if flagged:
        print(
            "YSHIFT-SCAN: %d NEW unexplained PAT(q)==PAT(q+10000) pairs among landed cells (not in yshift_genuine.json):"
            % len(flagged)
        )
        for sym, qe, slot, v in sorted(flagged):
            print("  %-14s %d/%d  %-3s  v=%.2f" % (sym, qe, qe + 10000, slot, v))
    else:
        n_cells = sum(len(qes) for qes in landed_qes.values())
        print("YSHIFT-SCAN: clean (%d landed cells across %d symbols checked)" % (n_cells, len(landed_qes)))


if __name__ == "__main__":
    main()
