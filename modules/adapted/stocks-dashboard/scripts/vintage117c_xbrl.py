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
"""§117c — XBRL route for the comparative-column vision-fill audit.

For target rows BSE detres cannot serve (empty transpose — NBFC/financial and some 2019+
filers — plus every consolidated row, §42), fetch the ORIGINAL NSE filing of the target
quarter itself: list rows for (sym, qe, basis), earliest filingDate = as-filed (§109a),
download that row's XBRL and read rev/op/pat with the repo's own parsers
(build_revop.xbrl_revop + build_fundamentals.xbrl_profit — bank/NBFC/insurer formats included).

NB unlike §117b's provenance test, a single-filing period does NOT clear a row here: the
vision pass read a comparative column of the NEXT filing, so the only test is value-level
against the original. Detection buckets EXACT/NEAR/FLAG as in vintage117c_visioncomp.py;
FLAG rows go to hand adjudication (EPS + quarters-sum-to-annual) before any heal.

LEDGER: scripts/_vintage117c_xscan.json   XBRLs cached in scripts/_xbrl_cache/
RUN: python3 scripts/vintage117c_xbrl.py [--only SYM,SYM] [--limit N]
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import _nse_archive_revop as NA  # noqa: E402
import build_fundamentals as BF  # noqa: E402
import build_revop as BR  # noqa: E402

TARGETS = os.path.join(HERE, "_audit114_targets.json")
SCAN_D = os.path.join(HERE, "_vintage117c_scan.json")
OUT = os.path.join(HERE, "_vintage117c_xscan.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
XC = os.path.join(HERE, "_xbrl_cache")
os.makedirs(XC, exist_ok=True)

MON = {
    m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
}


def fdt(s):
    m = re.match(r"(\d{2})-([A-Za-z]{3})-(\d{4})", str(s or ""))
    return int(m.group(3)) * 10000 + MON[m.group(2)] * 100 + int(m.group(1)) if m else None


def near(a, b, abs_tol=0.06, rel_tol=0.001):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def flag(a, b):
    if a is None or b is None:
        return False
    return abs(a - b) > max(2.0, 0.03 * max(abs(a), abs(b)))


def bucket(stored, cands):
    cands = [c for c in cands if c is not None]
    if stored is None:
        return "no-stored"
    if not cands:
        return "no-xbrl-field"
    if any(near(stored, c) for c in cands):
        return "EXACT"
    if all(flag(stored, c) for c in cands):
        return "FLAG"
    return "NEAR"


def main():
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10**9

    targets = json.load(open(TARGETS, encoding="utf-8"))
    dscan = json.load(open(SCAN_D, encoding="utf-8")) if os.path.exists(SCAN_D) else {"cells": {}}
    fund = json.load(open(FUND, encoding="utf-8"))
    revop = json.load(open(REVOP, encoding="utf-8"))
    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    for k in [k for k, v in out.items() if v.get("verdict") in ("no-list", "xbrl-fetch-failed")]:
        del out[k]  # transport failure is not a result

    # jarless first: measured 2026-08-30, a fresh nse_jar was 403-blocked for every list fetch
    # while jarless calls served (43 spurious no-list rows); NA.list_rows retries with a fresh
    # jar internally on failure anyway.
    NA.JAR = None

    todo = []
    for t in targets:
        k = "%s|%d|%s" % (t["sym"], t["qe"], t["basis"])
        if only and t["sym"] not in only:
            continue
        if k in out:
            continue
        if t["basis"] == "std":
            dv = dscan["cells"].get(k, {}).get("verdict")
            if dv not in ("no-detres-row", "no-scrip", "fetch-failed", None):
                continue  # detres already served this row
        todo.append((k, t))
    todo = todo[:limit]
    print("xbrl route pending: %d (ledger holds %d)" % (len(todo), len(out)), flush=True)

    lists = {}
    for _n, (k, t) in enumerate(todo, 1):
        sym, qe, basis = t["sym"], t["qe"], t["basis"]
        if sym not in lists:
            try:
                lists[sym] = NA.list_rows(sym)
            except Exception:
                lists[sym] = None
        rec = {"sym": sym, "qe": qe, "basis": basis, "fill_rev": t.get("rev"), "fill_op": t.get("op")}
        rrow = (revop.get(sym) or {}).get(str(qe))
        frow = next((r for r in fund.get(sym, []) if r and r[0] == qe), None)
        ri, oi_, pi = (0, 2, 1) if basis == "std" else (1, 3, 3)
        rec["live_rev"] = rrow[ri] if rrow and len(rrow) > ri else None
        rec["live_op"] = rrow[oi_] if rrow and len(rrow) > oi_ else None
        rec["live_pat"] = frow[pi] if frow and len(frow) > pi else None
        if not lists[sym]:
            rec["verdict"] = "no-list"
            out[k] = rec
            continue
        want = "Consolidated" if basis == "con" else "Non-Consolidated"
        rows = [r for r in lists[sym] if (r.get("consolidated") or "") == want and fdt(r.get("toDate")) == qe]
        rows.sort(
            key=lambda r: (
                fdt((r.get("filingDate") or "").split()[0] if r.get("filingDate") else "") or 99999999,
                str(r.get("seqNumber") or ""),
            )
        )
        rec["n_rows"] = len(rows)
        rec["filings"] = [
            {
                "seq": r.get("seqNumber"),
                "filed": (r.get("filingDate") or "").split()[0],
                "reInd": r.get("reInd"),
                "indAs": r.get("indAs"),
            }
            for r in rows
        ]
        if not rows:
            rec["verdict"] = "no-nse-row"
            out[k] = rec
            json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
            continue
        first = rows[0]
        xurl = first.get("xbrl") or ""
        if not xurl or xurl.endswith("/-"):
            rec["verdict"] = "no-xbrl-on-earliest"
            out[k] = rec
            json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
            continue
        xp = os.path.join(XC, re.sub(r"[^A-Za-z0-9_.]", "_", xurl.rsplit("/", 1)[-1]))
        try:
            xml = NA.get(xurl, xp)
        except Exception as ex:
            rec["verdict"] = "xbrl-fetch-failed"
            rec["why"] = f"{type(ex).__name__}"
            out[k] = rec
            json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
            time.sleep(1.0)
            continue
        hint = first.get("consolidated")
        rs, os_, _es, rc, oc, _ec, fin = BR.xbrl_revop(xml, hint)
        nps, npc = BF.xbrl_profit(xml, hint)
        x = {"rev": rs, "op": os_, "pat": nps} if basis == "std" else {"rev": rc, "op": oc, "pat": npc}
        rec["xbrl"] = {"rev": x["rev"], "op": x["op"], "pat": x["pat"], "fin": fin, "seq": first.get("seqNumber")}
        verdicts = {}
        for slot in ("rev", "op", "pat"):
            stored = rec[f"live_{slot}"]
            if stored is None and slot in ("rev", "op"):
                stored = t.get(slot)
            verdicts[slot] = bucket(stored, [x[slot]])
        rec["verdicts"] = verdicts
        rec["verdict"] = (
            "FLAG"
            if "FLAG" in verdicts.values()
            else "NEAR"
            if "NEAR" in verdicts.values()
            else "clean"
            if "EXACT" in verdicts.values()
            else "no-values"
        )
        out[k] = rec
        print(
            "%-14s %d %s  n_rows=%d  rev:%-14s op:%-14s pat:%-14s -> %s"
            % (sym, qe, basis, len(rows), verdicts["rev"], verdicts["op"], verdicts["pat"], rec["verdict"]),
            flush=True,
        )
        json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
        time.sleep(0.4)

    from collections import Counter

    print("---")
    for v, c in Counter(v.get("verdict") for v in out.values()).most_common():
        print("  %-22s %d" % (v, c))


if __name__ == "__main__":
    main()
