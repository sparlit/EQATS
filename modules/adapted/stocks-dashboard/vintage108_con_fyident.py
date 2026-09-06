# -*- coding: utf-8 -*-
"""FY-IDENTITY adjudication for the consolidated cells no owners reader can settle.

WHY THIS AND NOT THE FILINGS. The route ladder (§57) was walked and MEASURED before spending the
vision rung:
  * XBRL owners (_reattr_owners.json, DEFINITIONAL) — the FY16-FY17 era is thin: ~30 cells per
    quarter against 245 for Mar-2018 and 812 for Mar-2023. Reaches 8 of my 143 con cells.
  * Reconstructing owners from the NSE archive page's own components — FAILED CALIBRATION. Against
    the 8 XBRL-known cells, `P - MI - associates` reproduces only 3; TATACONSUM Mar-2017 prints
    P 84.36 / associates 33.24 / minority 0 and no combination yields the XBRL owners 31.41,
    because the filer never populated the minority row. The page cannot give the owners figure.
  * The Mar-2017 filing PDFs — 0 of 4 reachable ones carry a usable text layer (1-14 pages, 0-13
    characters). Scanned, as §75/§84 predict for the era. That is the VISION rung, which is last
    and needs explicit permission.

WHAT IS LEFT, and it is a real constraint rather than another opinion: the four consolidated
quarters of a fiscal year must sum to that year's audited consolidated annual. A quarterly series on
the WRONG BASIS (total instead of owners) will not reconcile to an OWNERS annual, and a series on the
wrong VINTAGE will not reconcile to the as-filed one. It is the gate §52a calls "the stronger of the
two", and it settled ASSAMCO and GAYAPROJ when three readers deadlocked 2-2.

    stored Q1 + Q2 + Q3 + candidate Q4  ==  MC annual (owners) within max(3 cr, 3%)

Both candidates are tested — the store's own value and the heal that was retracted — so the identity
either CONFIRMS the store, REINSTATES the heal, or reconciles to NEITHER and says so.

⚠️ It is still Moneycontrol, so it is not an independent VENDOR (the three aggregators are one —
memory: feedback-aggregators-are-one-vendor). It is an independent ROW: an annual total cannot be
reproduced by a quarterly series that is on a different basis, whatever the vendor.

OUT: scripts/_vintage108_con_fyident.json
RUN: python3 scripts/vintage108_con_fyident.py [--limit N] [--only SYM,SYM]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "agg_tools"))
import agg_sources as AG  # noqa: E402

NEED = os.path.join(HERE, "_vintage108_con_needs_filing.json")
READJ = os.path.join(HERE, "_vintage108_con_readjud.json")
OUT = os.path.join(HERE, "_vintage108_con_fyident.json")
FY_ABS, FY_REL = 3.0, 0.03


def fy_of(qe):
    y, m = qe // 10000, (qe // 100) % 100
    fy = y + 1 if m > 3 else y
    return [(fy - 1) * 10000 + 630, (fy - 1) * 10000 + 930, (fy - 1) * 10000 + 1231,
            fy * 10000 + 331], fy * 10000 + 331


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10 ** 9
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    need = json.load(open(NEED, encoding="utf-8"))
    readj = json.load(open(READJ, encoding="utf-8"))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf-8"))
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}

    todo = [k for k in need if k not in out and (not only or k.split("|")[0] in only)][:limit]
    print("consolidated cells to test by FY identity: %d" % len(todo))
    ann_cache, q_cache = {}, {}
    for k in todo:
        sym, qe = k.split("|")
        qe = int(qe)
        qs, end = fy_of(qe)
        if sym not in ann_cache:
            try:
                ann_cache[sym] = AG.mc_annuals(sym, True)[0]
            except Exception:
                ann_cache[sym] = {}
            try:
                q_cache[sym] = AG.mc_quarters(sym, True)[0]
            except Exception:
                q_cache[sym] = {}
        arow = ann_cache[sym].get(end) or {}
        ann = arow.get("pat_own")
        ann_src = "MC annual owners"
        if ann is None:
            ann = arow.get("pat_total")
            ann_src = "MC annual TOTAL (owners row absent)"
        rec = {"sym": sym, "qe": qe, "fy_end": end, "annual": ann, "annual_src": ann_src,
               "was": readj[k][3], "fixed": readj[k][4], "owners_reader": readj[k][1],
               "owners_value": readj[k][2]}
        if ann is None:
            rec["verdict"] = "no-annual"
            out[k] = rec
            continue
        sib, missing = 0.0, []
        for q in qs:
            if q == qe:
                continue
            row = next((r for r in fund.get(sym, []) if r[0] == q), None)
            v = row[3] if row and len(row) > 3 else None
            if v is None:                        # fall back to MC's own quarter, like §42's fy_gate
                v = (q_cache[sym].get(q) or {}).get("pat_own")
            if v is None:
                missing.append(q)
            else:
                sib += v
        if missing:
            rec["verdict"] = "siblings-missing"
            rec["missing"] = missing
            out[k] = rec
            continue
        tol = max(FY_ABS, abs(ann) * FY_REL)
        d_was, d_fixed = abs(sib + rec["was"] - ann), abs(sib + rec["fixed"] - ann)
        rec.update(sibling_sum=round(sib, 3), implied_q4=round(ann - sib, 3),
                   err_was=round(d_was, 3), err_fixed=round(d_fixed, 3), tol=round(tol, 3))
        if d_was <= tol and d_fixed > tol:
            rec["verdict"] = "identity CONFIRMS the store"
        elif d_fixed <= tol and d_was > tol:
            rec["verdict"] = "identity REINSTATES the heal"
        elif d_was <= tol and d_fixed <= tol:
            rec["verdict"] = "identity cannot separate"
        else:
            rec["verdict"] = "identity reconciles to NEITHER"
        out[k] = rec
        json.dump(out, open(OUT, "w"), indent=1)
    from collections import Counter
    print("done: %d cells" % len(out))
    for v, n in Counter(x.get("verdict") for x in out.values()).most_common():
        print("   %-34s %d" % (v, n))


if __name__ == "__main__":
    main()
