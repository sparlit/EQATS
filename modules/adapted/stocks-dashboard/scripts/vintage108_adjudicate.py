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
"""§108 PASS 2 — separate the RESTATED-VINTAGE class from the other things a detres flag can be.

Pass 1 (vintage108_sweep.py) flags |detres - stored| > max(2cr, 3%) on FY16-FY17 std PAT. A flag is
NOT a finding: runbook §108 says it is either the restated-comparative vintage class or §74's scale
class, and experience adds three more (exceptional-item definition splits, mis-slotted/cumulative
values, and a wrong scrip mapping). This pass gathers the evidence that separates them, per SYMBOL,
and proposes a class. It never writes a data file — adjudication ledgers only.

EVIDENCE COLLECTED per flagged symbol
  * the audited AS-FILED annual (detres QID NN.50 on the fiscal-year-END quarter, §42) for each FY
    holding a flag — tried Apr-Mar first, then Jan-Dec (calendar filers, §52c);
  * stored FY sum vs detres FY sum vs that annual — the §108 fingerprint is a stored row that does
    NOT reconcile to the as-filed annual while the detres row DOES;
  * MC's deep standalone quarterly feed as an INDEPENDENT second reader (§108 signature 2 is
    "detres + MC agreeing against the store");
  * the quarter's own Exceptional Item row, and every other quarter's detres value, so a
    definition split or a mis-slotted/cumulative value is visible rather than guessed at.

CLASS PROPOSALS (a proposal, never a verdict — every heal is adjudicated per name against the
original filing, §108/§58)
  identity-suspect  every compared quarter mismatches -> the scrip may not be this company (§76)
  scale             stored/detres is a clean power of ten (§74)
  vintage-candidate detres row reconciles to the as-filed annual, the stored row does not, and MC
                    sides with detres
  definition        the gap is the quarter's exceptional item (or matches another period exactly)
  store-right       MC sides with the STORE against detres
  unresolved        needs the documents

RUN:  python3 scripts/vintage108_adjudicate.py [--only SYM,SYM] [--limit N] [--sleep 2.0]
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "agg_tools"))
import vintage108_sweep as sweep  # noqa: E402

FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
SCAN = os.path.join(HERE, "_vintage108_scan.json")
RAW = os.path.join(HERE, "_vintage108_raw.json")
OUT = os.path.join(HERE, "_vintage108_adjud.json")

FY_ABS, FY_REL = 3.0, 0.03  # §42 FY-consistency tolerance
CELL_ABS, CELL_REL = 2.0, 0.03  # same tolerance pass 1 flags on
POWERS = (0.001, 0.01, 0.1, 10.0, 100.0, 1000.0)


def close(a, b, abs_tol=CELL_ABS, rel=CELL_REL):
    return abs(a - b) <= max(abs_tol, abs(b) * rel)


def annual_qid(qe_end):
    y, m = qe_end // 10000, (qe_end // 100) % 100
    return "%d.50" % (85 + (y - 2015) * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m])


def fy_quarters(qe, calendar=False):
    """The four quarter-ends of the fiscal year containing `qe`, plus the FY-end quarter."""
    y, m = qe // 10000, (qe // 100) % 100
    if calendar:
        return [y * 10000 + 331, y * 10000 + 630, y * 10000 + 930, y * 10000 + 1231], y * 10000 + 1231
    fy = y + 1 if m > 3 else y
    return (
        [(fy - 1) * 10000 + 630, (fy - 1) * 10000 + 930, (fy - 1) * 10000 + 1231, fy * 10000 + 331],
        fy * 10000 + 331,
    )


def main():
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10**9
    sleep = float(args[args.index("--sleep") + 1]) if "--sleep" in args else 2.0

    fund = json.load(open(FUND, encoding="utf-8"))
    scan = json.load(open(SCAN, encoding="utf-8"))
    raw = json.load(open(RAW, encoding="utf-8"))
    cells = scan["cells"]

    out = {}
    if os.path.exists(OUT):
        out = json.load(open(OUT, encoding="utf-8"))
    out.setdefault(
        "_doc",
        "runbook 108 pass 2: evidence + proposed class per flagged symbol. "
        "A proposal is not a verdict; every heal is adjudicated per name.",
    )
    out.setdefault("syms", {})

    bysym = {}
    for v in cells.values():
        if v.get("state") != "done":
            continue
        bysym.setdefault(v["sym"], []).append(v)
    flagged = sorted(
        s for s, vs in bysym.items() if any(v.get("verdict") == "FLAG" for v in vs) and (not only or s in only)
    )
    todo = [s for s in flagged if s not in out["syms"]][:limit]
    print("flagged symbols: %d  (already adjudicated %d)  this batch %d" % (len(flagged), len(out["syms"]), len(todo)))

    try:
        import agg_sources
    except Exception as ex:
        agg_sources = None
        print(f"  ! MC second reader unavailable ({ex}) — evidence will say so, not assume")

    last = 0.0
    for n, sym in enumerate(todo, 1):
        vs = {v["qe"]: v for v in bysym[sym]}
        cmpable = [v for v in vs.values() if v.get("verdict") in ("FLAG", "match")]
        flags = [v for v in cmpable if v["verdict"] == "FLAG"]
        rec = {
            "scrip": flags[0]["scrip"],
            "n_compared": len(cmpable),
            "n_flag": len(flags),
            "cells": {},
            "fy": {},
            "notes": [],
        }
        stored_all = {r[0]: r[1] for r in fund.get(sym, []) if len(r) > 1 and r[1] is not None}

        for v in sorted(flags, key=lambda x: x["qe"]):
            qe = v["qe"]
            f = raw.get("%s|%d" % (sym, qe), {})
            exc, _ = sweep.fnum(f, "Exceptional Item", "Exceptional Items")
            e = {
                "stored": v["stored"],
                "detres": v["detres"],
                "diff": v["diff"],
                "ratio": round(v["stored"] / v["detres"], 5) if v["detres"] else None,
                "exceptional_mn": exc,
            }
            # a stored value that IS another period's detres value -> mis-slot / cumulative
            # DETECT != CONFIRM: "the stored value is another period's" needs a TIGHT absolute
            # tolerance. At the 3% flag tolerance two unrelated quarters of a steady filer collide
            # constantly, and the class gets proposed on a coincidence.
            for oq, ov in vs.items():
                if (
                    oq != qe
                    and ov.get("detres") is not None
                    and abs(v["stored"] - ov["detres"]) <= max(0.05, abs(ov["detres"]) * 0.002)
                ):
                    e.setdefault("equals_other_period", []).append(oq)
            rec["cells"][str(qe)] = e

        # ---- FY reconciliation against the AS-FILED audited annual -------------------------
        fys = {}
        for v in flags:
            for cal in (False, True):
                qs, end = fy_quarters(v["qe"], cal)
                fys.setdefault(end, (qs, cal))
        for end, (qs, cal) in sorted(fys.items()):
            wait = sleep - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.time()
            try:
                a = sweep.fetch(rec["scrip"], annual_qid(end))[0]
            except RuntimeError as ex:
                rec["fy"][str(end)] = {"annual": None, "err": str(ex)}
                continue
            a_np, _ = sweep.fnum(a, *sweep.NP_NAMES)
            b, ee = sweep.parse_dt(a.get("Date Begin")), sweep.parse_dt(a.get("Date End"))
            span = None
            if b and ee:
                span = (ee // 10000 * 12 + (ee // 100) % 100) - (b // 10000 * 12 + (b // 100) % 100) + 1
            fy = {
                "convention": "Jan-Dec" if cal else "Apr-Mar",
                "dbeg": b,
                "dend": ee,
                "span_months": span,
                "annual_cr": round(a_np / 10.0, 4) if a_np is not None else None,
            }
            if fy["annual_cr"] is None or span != 12 or ee != end:
                fy["usable"] = False
            else:
                fy["usable"] = True
                s_sum = d_sum = 0.0
                s_have = d_have = 0
                for q in qs:
                    if q in stored_all:
                        s_sum += stored_all[q]
                        s_have += 1
                    dv = vs.get(q, {}).get("detres")
                    if dv is not None:
                        d_sum += dv
                        d_have += 1
                fy.update(
                    stored_sum=round(s_sum, 4), stored_have=s_have, detres_sum=round(d_sum, 4), detres_have=d_have
                )
                # Keep the ERROR, not just the §42 boolean: a row that reproduces the audited
                # annual to the paisa and one that misses it by 5 cr both "reconcile" at 3% on a
                # 200 cr filer, and the difference between them is the whole finding.
                if s_have == 4:
                    fy["stored_err"] = round(s_sum - fy["annual_cr"], 4)
                    fy["stored_reconciles"] = close(s_sum, fy["annual_cr"], FY_ABS, FY_REL)
                if d_have == 4:
                    fy["detres_err"] = round(d_sum - fy["annual_cr"], 4)
                    fy["detres_reconciles"] = close(d_sum, fy["annual_cr"], FY_ABS, FY_REL)
            rec["fy"][str(end)] = fy

        # ---- MC: the independent second reader ---------------------------------------------
        rec["mc"] = {}
        if agg_sources is not None:
            try:
                q, note = agg_sources.mc_quarters(sym, False)
            except Exception as ex:
                q, note = {}, f"mc: exception {type(ex).__name__}"
            rec["mc"]["note"] = note
            for v in flags:
                mv = (q.get(v["qe"]) or {}).get("pat_total")
                if mv is None:
                    continue
                rec["mc"][str(v["qe"])] = {
                    "pat": mv,
                    "sides_with": (
                        "detres"
                        if close(mv, v["detres"]) and not close(mv, v["stored"])
                        else "store"
                        if close(mv, v["stored"]) and not close(mv, v["detres"])
                        else "both"
                        if close(mv, v["detres"]) and close(mv, v["stored"])
                        else "neither"
                    ),
                }

        if agg_sources is not None:
            try:
                ya, ynote = agg_sources.mc_annuals(sym, False)
            except Exception as ex:
                ya, ynote = {}, f"mc-annual: exception {type(ex).__name__}"
            rec["mc_annual"] = {"note": ynote}
            for end in rec["fy"]:
                row = ya.get(int(end)) or {}
                v = row.get("pat_total") if isinstance(row, dict) else None
                if v is not None:
                    rec["mc_annual"][end] = v

        rec["proposed"] = classify(rec)
        out["syms"][sym] = rec
        print("  %-14s flags %d/%d  -> %s" % (sym, rec["n_flag"], rec["n_compared"], rec["proposed"]))
        if n % 5 == 0 or n == len(todo):
            sweep.save(OUT, out)
    sweep.save(OUT, out)


def classify(rec):
    """Proposed class, strongest signal first. Never a verdict — see the module docstring."""
    cells = rec["cells"]
    if rec["n_compared"] >= 3 and rec["n_flag"] == rec["n_compared"]:
        return "identity-suspect"
    ratios = [c["ratio"] for c in cells.values() if c.get("ratio")]
    if ratios and all(any(abs(r - p) <= 0.02 * p for p in POWERS) for r in ratios):
        return "scale"
    if any(c.get("equals_other_period") for c in cells.values()):
        return "period-mismatch"
    exc_ok = all(
        c.get("exceptional_mn") and close(c["stored"], c["detres"] - c["exceptional_mn"] / 10.0) for c in cells.values()
    )
    if cells and exc_ok:
        return "definition-exceptional"

    sides = [rec["mc"].get(q, {}).get("sides_with") for q in cells]
    sides = [s for s in sides if s]
    fy_ok = [f for f in rec["fy"].values() if f.get("usable")]

    # THE §108 FINGERPRINT: the as-filed quarters reproduce the audited annual (to the paisa, not
    # merely inside 3%), the stored ones do not. `close`'s FY tolerance is too loose to separate
    # them, so measure both errors.
    def repro(f, key):
        e = f.get(key)
        return e is not None and abs(e) <= max(0.5, abs(f["annual_cr"]) * 0.002)

    fp = [
        f
        for f in fy_ok
        if repro(f, "detres_err")
        and f.get("stored_err") is not None
        and abs(f["stored_err"]) > max(1.0, abs(f["annual_cr"]) * 0.01)
    ]
    if fp:
        if sides and all(s == "detres" for s in sides):
            return "vintage-candidate"
        if sides and any(s == "store" for s in sides):
            return "vintage-candidate(mc-split)"
        return "vintage-candidate(no-mc)"
    if sides and all(s == "store" for s in sides):
        return "store-right"
    if sides and all(s == "detres" for s in sides):
        return "detres+mc-vs-store"
    return "unresolved"


if __name__ == "__main__":
    main()
