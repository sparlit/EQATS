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
"""§117c follow-up — screen the remaining `screener-annual derivation` fill cells against MC.

The 2026-07-27 band3/4 pass derived some quarters as screener-FY-sales minus the OTHER THREE
stored quarters. §117c's addendum proved that residue wrong three ways on REC/SAMMAANCAP:
(a) a contaminated input quarter poisons the residue, (b) as-filed quarters need not be
additive (filers regroup FV lines between revenue and expense per filing), (c) the screener
annual itself can sit on a different definition/vintage. This screens the remaining family
against MC deep quarters (as-filed vintage; the §117c insurer method): stored rev vs MC
rev_ops / rev_total.

Buckets: EXACT (either line), MISMATCH (with both MC lines + deltas), mc-absent.
For MISMATCH Mar-quarters, also runs the MC-Q4-derived-residue check (MC FY annual − MC 9M ==
MC's Mar row ⇒ MC is itself a derivation there, not a reader —
feedback-aggregator-q4-is-a-derived-residue).

Report-only. LEDGER: scripts/_deriv136_scan.json
RUN: python3 scripts/deriv136_screen.py [--only SYM,SYM]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "agg_tools"))
from agg_tools import agg_sources as A  # noqa: E402

TARGETS = os.path.join(HERE, "_deriv136_targets.json")
OUT = os.path.join(HERE, "_deriv136_scan.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")


def near(a, b, abs_tol=0.06, rel_tol=0.001):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def main():
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    targets = json.load(open(TARGETS, encoding="utf-8"))
    revop = json.load(open(REVOP, encoding="utf-8"))
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}

    qcache = {}
    for t in sorted(targets, key=lambda t: (t["sym"], t["qe"])):
        sym, qe, basis = t["sym"], t["qe"], t["basis"]
        if only and sym not in only:
            continue
        k = "%s|%d|%s" % (sym, qe, basis)
        if k in out and out[k].get("verdict") != "mc-error":
            continue
        rrow = (revop.get(sym) or {}).get(str(qe))
        slot = 0 if basis == "std" else 1
        live = rrow[slot] if rrow and len(rrow) > slot else None
        rec = {"sym": sym, "qe": qe, "basis": basis, "fill_rev": t["rev"], "live_rev": live}
        ck = (sym, basis)
        if ck not in qcache:
            try:
                qcache[ck] = A.mc_quarters(sym, con=(basis == "con"))[0]
            except Exception as ex:
                qcache[ck] = None
                rec["why"] = type(ex).__name__
        qs = qcache[ck]
        stored = live if live is not None else t["rev"]
        if qs is None:
            rec["verdict"] = "mc-error"
        else:
            mc = qs.get(qe)
            if not mc:
                rec["verdict"] = "mc-absent"
            else:
                ro, rt = mc.get("rev_ops"), mc.get("rev_total")
                rec["mc_rev_ops"], rec["mc_rev_total"] = ro, rt
                if near(stored, rt) or near(stored, ro):
                    rec["verdict"] = "EXACT"
                else:
                    rec["verdict"] = "MISMATCH"
                    rec["d_ops"] = round(stored - ro, 2) if ro is not None else None
                    rec["d_total"] = round(stored - rt, 2) if rt is not None else None
                    if qe % 10000 == 331:
                        # is MC's Mar row its own annual-minus-9M residue?
                        try:
                            ann = A.mc_annuals(sym, con=(basis == "con"))[0]
                            fy = ann.get(qe) or ann.get(str(qe)) or {}
                        except Exception:
                            fy = {}
                        y = qe // 10000
                        nine = [(y - 1) * 10000 + 630, (y - 1) * 10000 + 930, (y - 1) * 10000 + 1231]
                        n9 = sum((qs.get(q) or {}).get("rev_ops") or 0 for q in nine)
                        fyv = fy.get("rev_ops") if isinstance(fy, dict) else None
                        if fyv and n9:
                            rec["mc_q4_residue"] = round(fyv - n9, 2)
        out[k] = rec
        if rec["verdict"] != "EXACT":
            print(
                "%-30s %-9s fill=%-10s live=%-10s mc_ops=%-10s mc_total=%-10s %s"
                % (
                    k,
                    rec["verdict"],
                    t["rev"],
                    live,
                    rec.get("mc_rev_ops"),
                    rec.get("mc_rev_total"),
                    rec.get("mc_q4_residue", ""),
                ),
                flush=True,
            )
        json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
    from collections import Counter

    print("---")
    for v, c in Counter(v.get("verdict") for v in out.values()).most_common():
        print("  %-12s %d" % (v, c))


if __name__ == "__main__":
    main()
