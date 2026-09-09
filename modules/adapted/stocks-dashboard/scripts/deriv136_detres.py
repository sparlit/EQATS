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
"""§117c deriv-family phase 2 — detres (as-filed PRINT) over the MC-screen MISMATCH cells.

MC alone cannot adjudicate the 81 mismatches: it is blind on bank-format rows, its Mar-quarter
can be its own annual-minus-9M residue, and the 2015-17 era mixes excise/IGAAP conventions.
BSE detres is the as-filed print (§42). For every MISMATCH std cell, fetch the transpose,
persist the raw field dict, and bucket stored against the print's revenue candidates
(net-sales, net-sales+OOI, total-income, bank interest-earned) + NP anchor vs sf_fundamentals.

LEDGERS: scripts/_deriv136_draw.json (raw), scripts/_deriv136_dscan.json
RUN: python3 scripts/deriv136_detres.py [--limit N] [--only SYM,SYM] [--sleep 1.5]
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import vintage117c_visioncomp as V  # noqa: E402  (scrip_map, fetch, qid, parse_dt)

SCAN_MC = os.path.join(HERE, "_deriv136_scan.json")
OUT = os.path.join(HERE, "_deriv136_dscan.json")
RAW = os.path.join(HERE, "_deriv136_draw.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")


def f(d, *names):
    for n in names:
        v = d.get(n)
        if v in (None, "", "-"):
            continue
        try:
            return float(v) / 10.0
        except (TypeError, ValueError):
            continue
    return None


def near(a, b, abs_tol=0.06, rel_tol=0.001):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10**9
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    sleep = float(args[args.index("--sleep") + 1]) if "--sleep" in args else 1.5

    mc = json.load(open(SCAN_MC, encoding="utf-8"))
    fund = json.load(open(FUND, encoding="utf-8"))
    codes = V.scrip_map()
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    raw = json.load(open(RAW, encoding="utf-8")) if os.path.exists(RAW) else {}

    todo = [
        (k, v)
        for k, v in sorted(mc.items())
        if v.get("verdict") in ("MISMATCH", "mc-absent")
        and v["basis"] == "std"
        and k not in out
        and (not only or v["sym"] in only)
    ][:limit]
    print("detres pass pending: %d (ledger holds %d)" % (len(todo), len(out)), flush=True)

    for k, t in todo:
        sym, qe = t["sym"], t["qe"]
        stored = t["live_rev"] if t.get("live_rev") is not None else t.get("fill_rev")
        frow = next((r for r in fund.get(sym, []) if r and r[0] == qe), None)
        rec = {"sym": sym, "qe": qe, "stored_rev": stored, "np_stored": frow[1] if frow and len(frow) > 1 else None}
        code = codes.get(sym)
        if not code:
            rec["verdict"] = "no-scrip"
            out[k] = rec
            continue
        try:
            fdict, _ = V.fetch(code, V.qid(qe))
        except RuntimeError as ex:
            rec["verdict"] = "fetch-failed"
            rec["why"] = str(ex)
            out[k] = rec
            json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
            continue
        d1 = V.parse_dt(fdict.get("Date End"))
        if d1 != qe:
            rec["verdict"] = "no-detres-row"
            out[k] = rec
            json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
            time.sleep(sleep)
            continue
        raw[k] = fdict
        ns = f(
            fdict,
            "Net Sales/Revenue From Operations",
            "Revenue from Operations",
            "Net Sales",
            "Revenue From Operations",
        )
        ooi = f(
            fdict,
            "Other Operating Income",
            "Other operating income",
            "Other Operating Revenues",
            "Other operating revenue",
        )
        ti = f(fdict, "Total Income", "Total Income from Operations")
        ie = f(fdict, "Interest Earned", "Interest Earned/Net Income from sales/services")
        np_ = f(fdict, "Net Profit")
        cands = {
            "net-sales": ns,
            "net-sales+ooi": (ns + ooi) if (ns is not None and ooi is not None) else None,
            "total-income": ti,
            "interest-earned": ie,
        }
        rec["detres"] = {kk: vv for kk, vv in cands.items() if vv is not None}
        rec["detres_np"] = np_
        rec["np_anchor"] = (
            "OK"
            if near(np_, rec["np_stored"], 0.06, 0.002)
            else ("none" if np_ is None or rec["np_stored"] is None else "FAIL")
        )
        hit = next((n for n, v2 in cands.items() if near(stored, v2)), None)
        if hit:
            rec["verdict"] = "asfiled"
            rec["via"] = hit
        elif not rec["detres"]:
            rec["verdict"] = "no-rev-fields"
        else:
            rec["verdict"] = "PRINT-MISMATCH"
        out[k] = rec
        print(
            "%-28s %-15s stored=%-10s detres=%s np:%s"
            % (k, rec["verdict"], stored, {n: round(v2, 2) for n, v2 in rec["detres"].items()}, rec["np_anchor"]),
            flush=True,
        )
        json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
        json.dump(raw, open(RAW, "w", encoding="utf-8"), indent=0)
        time.sleep(sleep)

    from collections import Counter

    print("---")
    for v, c in Counter(v.get("verdict") for v in out.values()).most_common():
        print("  %-16s %d" % (v, c))


if __name__ == "__main__":
    main()
