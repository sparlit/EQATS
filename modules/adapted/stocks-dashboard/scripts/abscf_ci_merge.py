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
"""Merge THIS CI run's annual-BS/CF outputs onto the latest origin/main, without clobbering
whatever the nightly vision routine (or a concurrent run) landed in the meantime.

The 'Commit ledger' step used to `git reset --hard origin/main` and then blindly `cp` this run's
snapshot back over the reset files — which silently discarded any symbol-years the vision routine
had pushed since checkout (the 2026-09 clobber). This does a real union instead:

  * Ledger  (scripts/annual_bscf.json): union at (symbol -> "QE"). BASE (origin-now) wins any cell
    it already has — this run only ADDS the (sym,QE) cells origin lacks. Both writers only ever
    add gate-verified cells, so a real conflict is near-impossible; preferring BASE is the safe tie.
  * Gate    (scripts/annual_bscf_gate.json): per-symbol dict union. MINE (this run, freshest) wins
    per KEY, but BASE keys MINE doesn't carry are preserved — so a routine's vnil/na mark survives
    this run's verdict write, and vice-versa. With --gate-orig (the gate AT CHECKOUT) only the symbols
    this run CHANGED are merged — without it, a symbol the run never touched carried its stale checkout
    copy over a heal pushed mid-run (2026-09-25: 150 restored entries re-stamped 'filings-err 403').

Usage: abscf_ci_merge.py --ledger-mine A --ledger-base B --gate-mine C --gate-base D [--gate-orig E]
Writes the merged result into the --*-base paths. Missing MINE -> BASE kept as-is; missing BASE -> MINE.
"""
import json
import sys


def _load(p):
    try:
        return json.load(open(p))
    except Exception:
        return None


def _merge_ledger(mine, base):
    if not isinstance(base, dict):
        return mine if isinstance(mine, dict) else {}
    if not isinstance(mine, dict):
        return base
    for sym, years in mine.items():
        if not isinstance(years, dict):
            continue
        dst = base.setdefault(sym, {})
        for qe, cell in years.items():
            dst.setdefault(qe, cell)  # BASE cell wins; add only cells origin lacks
    return base


def _merge_gate(mine, base, orig=None):
    if not isinstance(base, dict):
        return mine if isinstance(mine, dict) else {}
    if not isinstance(mine, dict):
        return base
    for sym, mv in mine.items():
        if isinstance(orig, dict) and orig.get(sym) == mv:
            continue  # untouched by this run: origin's copy (maybe a heal) stands
        if not isinstance(mv, dict):
            base[sym] = mv
            continue
        bv = base.get(sym)
        if isinstance(bv, dict):
            bv.update(mv)  # union of keys; MINE (fresher) wins on overlap
        else:
            base[sym] = mv
    return base


def _arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def main():
    lm, lb = _arg("--ledger-mine"), _arg("--ledger-base")
    gm, gb = _arg("--gate-mine"), _arg("--gate-base")
    if lb:
        merged = _merge_ledger(_load(lm), _load(lb)) or {}
        json.dump(merged, open(lb, "w"), separators=(",", ":"), sort_keys=True)
        print(
            "ledger merged -> %s  (%d symbols, %d symbol-years)"
            % (lb, len(merged), sum(len(v) for v in merged.values() if isinstance(v, dict)))
        )
    if gb:
        go = _arg("--gate-orig")
        merged = _merge_gate(_load(gm), _load(gb), _load(go) if go else None) or {}
        json.dump(merged, open(gb, "w"), separators=(",", ":"), sort_keys=True)
        print("gate merged   -> %s  (%d entries)" % (gb, len(merged)))


if __name__ == "__main__":
    main()
