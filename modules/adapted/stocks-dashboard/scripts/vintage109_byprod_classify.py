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
"""§109e by-products — RE-DERIVE the sub-classification from the evidence, then measure.

The §109 report's `_subclass()` compared `row[3]` (npCon) against `v["stored"]`. For a
CONSOLIDATED-basis cell `v["stored"]` IS `row[3]`, so the "std slot holds the CON value (§59)"
test fires unconditionally on every con cell. This re-derives every label from scratch, per
basis, against the CURRENT origin/main store (never the sweep's snapshot).

OUT: _vintage109_byprod.json
"""
import datetime
import json
import os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
POWERS = (0.001, 0.01, 0.1, 10.0, 100.0, 1000.0)
FUND_SLOT = {"std": 1, "con": 3}
ANN_SLOT = {"std": 2, "con": 4}
ABS_TOL, REL_TOL = 2.0, 0.03
NEAR_ABS, NEAR_REL = 0.35, 0.005


def L(n):
    p = os.path.join(HERE, n)
    if not os.path.exists(p):
        print(f"  (ledger {n} ABSENT)")
        return {}
    return json.load(open(p, encoding="utf-8"))


def agree(a, b):
    return a is not None and b is not None and abs(a - b) <= max(ABS_TOL, abs(b) * REL_TOL)


def near(a, b):
    return a is not None and b is not None and abs(a - b) <= max(NEAR_ABS, abs(b) * NEAR_REL)


def days(a, b):
    try:
        return (
            datetime.date(b // 10000, (b // 100) % 100, b % 100) - datetime.date(a // 10000, (a // 100) % 100, a % 100)
        ).days
    except Exception:
        return None


def fnum(f, *names):
    for n in names:
        v = f.get(n)
        if v not in (None, "", "-"):
            try:
                return float(v), n
            except ValueError:
                pass
    return None, None


def main():
    props = L("_vintage109_proposals.json")
    bp = props.get("byproduct", {})
    nse = {"std": L("_vintage109_nse_fixed.json"), "con": L("_vintage109_nse_con_fixed.json")}
    scan = L("_vintage108_scan.json").get("cells", {})
    raw = L("_vintage108_raw.json")
    prov = L("_vintage108_prov.json")
    vrf = L("vision_rev_fills.json")
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf-8"))
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json"), encoding="utf-8"))

    # provenance index (sym,qe,basis) -> record
    pidx = {}
    for k, v in prov.items():
        pidx[(v["sym"], v["qe"], v["basis"])] = v

    keys = sorted({k for lst in bp.values() for k in lst})
    print("by-product population: %d cells (%s)" % (len(keys), dict(Counter(k.split("|")[2] for k in keys))))

    out, drift = {}, []
    for k in keys:
        sym, qes, basis = k.split("|")
        qe = int(qes)
        nk = f"{sym}|{qes}"
        v = nse[basis].get(nk) or {}
        frow = next((r for r in fund.get(sym, []) if r[0] == qe), None)
        cur = frow[FUND_SLOT[basis]] if frow and len(frow) > FUND_SLOT[basis] else None
        ann = frow[ANN_SLOT[basis]] if frow and len(frow) > ANN_SLOT[basis] else None
        std_now = frow[1] if frow and len(frow) > 1 else None
        con_now = frow[3] if frow and len(frow) > 3 else None
        if v.get("stored") is not None and cur is not None and abs(v["stored"] - cur) > 0.005:
            drift.append((k, v["stored"], cur))
        vints = [x for x in v.get("vintages", []) if x.get("pat") is not None and x.get("cumulative") != "Cumulative"]
        asf = vints[0] if vints else None
        det = scan.get(nk, {}).get("detres") if basis == "std" else None
        fdet = raw.get(nk, {}) if basis == "std" else {}
        drev, _ = fnum(
            fdet, "Net Sales/Revenue From Operations", "Total Income From Operations", "Net Sales", "Interest Earned"
        )
        dop, _ = fnum(
            fdet,
            "Profit from Operations before Other Income, Interest and Exceptional Items",
            "Operating Profit before Provisions and Contingencies",
        )
        rrow = (revop.get(sym) or {}).get(qes) or []
        pr = pidx.get((sym, qe, basis))

        rec = {
            "sym": sym,
            "qe": qe,
            "basis": basis,
            "stored": cur,
            "ann": ann,
            "std_now": std_now,
            "con_now": con_now,
            "nse_verdict": v.get("verdict"),
            "n_rows": v.get("n_rows"),
            "nse_pat": (asf or {}).get("pat"),
            "nse_op": (asf or {}).get("op"),
            "nse_rev": (asf or {}).get("rev"),
            "nse_filed": (asf or {}).get("filed"),
            "nse_indas": (asf or {}).get("indAs"),
            "nse_seq": (asf or {}).get("seq"),
            "nse_unit": (asf or {}).get("unit"),
            "nse_basis": (asf or {}).get("basis"),
            "nse_audited": (asf or {}).get("audited"),
            "detres_pat": det,
            "detres_rev": None if drev is None else round(drev / 10.0, 4),
            "detres_op": None if dop is None else round(dop / 10.0, 4),
            "revop": rrow,
            "prov_verdict": (pr or {}).get("verdict"),
            "prov_src_seq": (pr or {}).get("src_seq"),
            "vrf": (vrf.get("%s|%d" % (sym, qe)) or {}).get(basis),
            "gap_ann_to_nsefiled": days(ann, (asf or {}).get("filed")) if ann and asf else None,
            "gap_qe_to_nsefiled": days(qe, (asf or {}).get("filed")) if asf else None,
        }
        rec["cls"] = classify(rec)
        out[k] = rec

    print("\nDRIFT vs sweep snapshot: %d cells" % len(drift))
    for d in drift[:15]:
        print("   ", d)

    print("\nRE-DERIVED CLASSES")
    for c, n in Counter(r["cls"] for r in out.values()).most_common():
        sub = Counter(r["basis"] for r in out.values() if r["cls"] == c)
        print("  %-46s %4d   %s" % (c, n, dict(sub)))

    print("\nOLD LABEL x NEW LABEL")
    oldlab = {}
    for lab, lst in bp.items():
        for k in lst:
            oldlab[k] = lab
    cross = Counter((oldlab[k], out[k]["cls"]) for k in keys)
    for (o, n), c in sorted(cross.items(), key=lambda x: -x[1]):
        print("  %4d  %-42s -> %s" % (c, o[:42], n))

    json.dump(
        {"_doc": "§109e by-products re-classified against current origin/main", "cells": out},
        open(os.path.join(HERE, "_vintage109_byprod.json"), "w"),
        indent=1,
    )
    print("\nwrote _vintage109_byprod.json")


def classify(r):
    """Per-basis, evidence-first. Order matters: the cheapest DISQUALIFIER first."""
    st, nse_pat, basis = r["stored"], r["nse_pat"], r["basis"]
    if st is None:
        return "no-stored-value"
    if nse_pat is None:
        return "no-readable-vintage"
    if near(st, nse_pat):
        return "store-now-matches-nse"  # healed since the sweep, or drift
    ratio = st / nse_pat if nse_pat else 0
    if any(abs(ratio - p) <= 0.02 * p for p in POWERS):
        return "scale-step (§74)"
    # §59 direction: the STD slot parroting the CON slot (only meaningful on std)
    if basis == "std" and r["con_now"] is not None and abs(r["con_now"] - st) <= 0.011:
        return "std slot == con slot (§59)"
    # the mirror image on the con side
    if basis == "con" and r["std_now"] is not None and abs(r["std_now"] - st) <= 0.011:
        return "con slot == std slot (§59 mirror)"
    if basis == "std":
        det = r["detres_pat"]
        if det is None:
            return "std, no detres — NSE alone"
        if agree(det, nse_pat):
            return "two as-filed readers vs the store"
        if near(det, st):
            return "detres BACKS the store, NSE differs"
        return "the two readers disagree with each other"
    return "con, no independent reader"


if __name__ == "__main__":
    main()
