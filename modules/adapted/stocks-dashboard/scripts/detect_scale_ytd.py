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
"""YTD-chain screen for filer power-of-ten errors in the XBRL cache (runbook §184). READ-ONLY.

detect_scale_errors.py flags only cells >= 50x LARGER than their neighbours, so a filing at 1/100 (a filer typing crore
figures into a lakh template: IRCON / UBL Mar-22) is invisible to it by construction. This screen uses the anchor the
scale_fix _README ranks strongest instead. For every single-basis filing F whose FourD is its year-to-date column:

    r = (YTD_F - quarter_F) / YTD_P        P = the same company + basis's filing for the previous quarter of that FY
      = s_F / s_P                          s = a filing's scale relative to the truth

An exact 10^k (k != 0) on revenue AND PAT proves that F and P disagree by 10^k -- NOT which one is wrong (a first pass
that assumed F blamed the neighbours of armed filings). The side is decided by, in order:
  (a) an ARMED filing that explains the pair (F armed with k, or P armed with -k) -> the pair is dropped;
  (b) the filing's own PaidUpValueOfEquityShareCapital against the company's median over ALL its filings (paid-up
      capital moves by real issuance, never by exactly x10 / x100 overnight);
  (c) the chain: the filing that disagrees with a neighbour which is itself consistent with ITS neighbour.
Each decided candidate is then compared with what the served stores hold (sf_revop / sf_fundamentals): SCALED (the store
carries the filing's raw value), right (the store already holds raw / 10^k from elsewhere) or other.

Candidates are SUSPECTS with an arithmetic anchor, not verdicts: adjudicate each by hand (§184 / §147 recipe) before
adding a scale_fix.json entry.

Run:  XBRL_CACHE=/Users/dhruvan/stocks-dashboard/scripts/_xbrl_cache python3 -X utf8 scripts/detect_scale_ytd.py [--out FILE]
"""
import datetime
import html
import json
import math
import os
import re
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import xbrl_symbol

CACHE = os.environ.get("XBRL_CACHE") or os.path.join(HERE, "_xbrl_cache")
NS = r"in-(?:bse-fin|capmkt)"
RE_SYM = re.compile(r'<xbrli:identifier scheme="http://www\.nseindia\.com/NSESymbol">([^<]+)</xbrli:identifier>')
RE_SYM2 = re.compile(r"<" + NS + r':Symbol contextRef="OneD"[^>]*>([^<]+)<')
RE_CTX = {
    c: re.compile(
        r'<xbrli:context id="' + c + r'">.*?<xbrli:startDate>(\d{4}-\d{2}-\d{2})</xbrli:startDate>'
        r"<xbrli:endDate>(\d{4}-\d{2}-\d{2})</xbrli:endDate>",
        re.DOTALL,
    )
    for c in ("OneD", "FourD")
}
RE_TS = re.compile(r"(\d{12,14})")
TAGS = (
    ("nat", "NatureOfReportStandaloneConsolidated"),
    ("round", "LevelOfRoundingUsedInFinancialStatements"),
    ("ds", "DateOfStartOfReportingPeriod"),
    ("de", "DateOfEndOfReportingPeriod"),
    ("fys", "DateOfStartOfFinancialYear"),
    ("rev", "RevenueFromOperations"),
    ("ie", "InterestEarned"),
    ("pat", "ProfitLossForPeriod"),
    ("pat2", "ProfitLossForThePeriod"),
    ("own", "ProfitOrLossAttributableToOwnersOfParent"),
    ("sc", "PaidUpValueOfEquityShareCapital"),
)
T = {
    k: {c: re.compile(r"<" + NS + ":" + t + r' contextRef="' + c + r'"[^>]*>([^<]+)<') for c in ("OneD", "FourD")}
    for k, t in TAGS
}


def ts_key(f):
    m = RE_TS.search(f)
    if not m:
        return f
    d = m.group(1)
    return d[4:8] + d[2:4] + d[0:2] + d[8:] if len(d) == 14 else d


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def index_one(fn):
    """One cached filing -> its identity, scale hints and the raw OneD/FourD money we need (None if unusable)."""
    try:
        x = open(os.path.join(CACHE, fn), encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    if "OneD" not in x:
        return None
    m = RE_SYM.search(x) or RE_SYM2.search(x)
    if not m:
        return None
    try:
        sym = (xbrl_symbol.resolve(html.unescape(m.group(1)).strip().upper(), x) or "").upper()
    except Exception:
        return None
    if not sym:
        return None

    def g(k, c):
        mm = T[k][c].search(x)
        return mm.group(1).strip() if mm else None

    n1, n4 = (g("nat", "OneD") or "").lower(), (g("nat", "FourD") or "").lower()
    if not n1:
        return None
    mm = RE_CTX["OneD"].search(x)
    per = (mm.group(1), mm.group(2)) if mm else (g("ds", "OneD"), g("de", "OneD"))
    if not (per[0] and per[1]):
        return None
    try:
        days = (datetime.date.fromisoformat(per[1]) - datetime.date.fromisoformat(per[0])).days
    except ValueError:
        return None
    if not 0 < days <= 100:
        return None
    rec = {
        "f": fn,
        "ts": ts_key(fn),
        "sym": sym,
        "b": "c" if "consol" in n1 else "s",
        "qe": per[1].replace("-", ""),
        "round": g("round", "OneD"),
        "fys": g("fys", "OneD"),
        "nat4": bool(n4),
        "same4": bool(n4) and (("consol" in n4) == ("consol" in n1)),
    }
    for k, alts in (("rev", ("rev", "ie")), ("pat", ("pat", "pat2")), ("own", ("own",)), ("sc", ("sc",))):
        for c, suf in (("OneD", "1"), ("FourD", "4")):
            v = None
            for a in alts:
                v = _num(g(a, c))
                if v is not None:
                    break
            rec[k + suf] = v
    return rec


def pow10(x, tol):
    if x is None or x <= 0:
        return None
    k = round(math.log10(x))
    return k if abs(x / 10**k - 1) < tol else None


def prev_qe(qe):
    y, m = int(qe[:4]), int(qe[4:6]) - 3
    if m <= 0:
        m, y = m + 12, y - 1
    return "%04d%02d%02d" % (y, m, {3: 31, 6: 30, 9: 30, 12: 31}[m])


def qpos(r):
    """1..4 = the quarter's position in its financial year (from DateOfStartOfFinancialYear), else None."""
    if not r.get("fys"):
        return None
    fy = r["fys"].replace("-", "")
    months = (int(r["qe"][:4]) - int(fy[:4])) * 12 + int(r["qe"][4:6]) - int(fy[4:6]) + 1
    return months // 3 if months % 3 == 0 and 1 <= months // 3 <= 4 else None


def ytd(r, k):
    q = qpos(r)
    if q == 1:
        return r.get(k + "1")
    if q and q > 1 and (r["same4"] or not r["nat4"]):
        return r.get(k + "4")
    return None


def main():
    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    if not os.path.isdir(CACHE):
        sys.exit(f"XBRL cache not found at {CACHE} -- set XBRL_CACHE (it lives in the MAIN checkout)")
    fns = sorted(os.listdir(CACHE))
    recs = []
    with ProcessPoolExecutor(8) as ex:
        for r in ex.map(index_one, fns, chunksize=400):
            if r:
                recs.append(r)
    print("filings indexed: %d of %d cache files" % (len(recs), len(fns)))
    R = {r["f"]: r for r in recs}
    by = defaultdict(list)
    for r in recs:
        by[(r["sym"], r["b"], r["qe"])].append(r)

    # ---- every (F, P) pair with a YTD relation --------------------------------------------------------------------------
    pairs = []
    for (sym, b, qe), fs in by.items():
        for F in fs:
            q = qpos(F)
            if not q or q == 1 or not (F["same4"] or not F["nat4"]):
                continue
            for P in by.get((sym, b, prev_qe(qe)), []):
                if qpos(P) != q - 1:
                    continue
                p = {"sym": sym, "b": b, "qe": qe, "F": F["f"], "P": P["f"]}
                for k in ("rev", "pat"):
                    y, qv, py = F.get(k + "4"), F.get(k + "1"), ytd(P, k)
                    p["r_" + k] = ((y - qv) / py) if None not in (y, qv, py) and py else None
                pairs.append(p)
    out_of, into = defaultdict(list), defaultdict(list)
    for p in pairs:
        out_of[p["F"]].append(p)
        into[p["P"]].append(p)

    ledger = json.load(open(os.path.join(HERE, "scale_fix.json"), encoding="utf-8"))["fixes"]
    armed = {e["file"]: e["k"] for e in ledger}
    sc_by = defaultdict(list)
    for r in recs:
        if r.get("sc1"):
            sc_by[r["sym"]].append(r["sc1"])

    def sc_scale(f):
        r = R[f]
        v, vals = r.get("sc1"), sc_by.get(r["sym"], [])
        return pow10(v / statistics.median(vals), 0.002) if v and len(vals) >= 3 else None

    # ---- anomalies: revenue AND PAT an exact 10^k; decide the side ----------------------------------------------------------
    n_anom = n_expl = 0
    refound, cands = set(), {}
    for p in pairs:
        k = pow10(p["r_rev"], 0.002)
        if not k or k != pow10(p["r_pat"], 0.01):
            continue
        n_anom += 1
        F, P = p["F"], p["P"]
        if armed.get(F) == k or armed.get(P) == -k:
            n_expl += 1
            refound.add(F if armed.get(F) == k else P)
            continue
        sF, sP = sc_scale(F), sc_scale(P)
        ev = {"sc_scale_F": sF, "sc_scale_P": sP}
        if sF == k and sP in (0, None):
            odd, kk = F, k
        elif sP == -k and sF in (0, None):
            odd, kk = P, -k
        else:
            p_ok = any(pow10(q["r_rev"], 0.02) == 0 for q in out_of.get(P, []))
            n_ok = any(pow10(q["r_rev"], 0.02) == 0 for q in into.get(F, []))
            n_back = any(pow10(q["r_rev"], 0.002) == -k for q in into.get(F, []))
            ev.update(P_consistent_with_prev=p_ok, next_consistent_with_F=n_ok, next_reverts=n_back)
            if (p_ok or n_back) and not n_ok:
                odd, kk = F, k
            elif n_ok and not (p_ok or n_back):
                odd, kk = P, -k
            else:
                odd, kk = None, None
        c = cands.setdefault(odd or (F + "|" + P), {"file": odd, "k": kk, "ev": ev, "pairs": []})
        c["pairs"].append({"F": F, "P": P, "r_rev": p["r_rev"], "r_pat": p["r_pat"]})

    cached_armed = [f for f in armed if f in R]
    print(
        "pairs: %d | anomalous (rev AND pat exact 10^k): %d | explained by an armed filing: %d"
        % (len(pairs), n_anom, n_expl)
    )
    print("recall on the ledger: %d of %d cached armed filings re-found" % (len(refound), len(cached_armed)))

    # ---- triage against the served stores ---------------------------------------------------------------------------------------
    rev = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    latest = {}
    for f, r in R.items():
        key = (r["sym"], r["b"], r["qe"])
        if key not in latest or r["ts"] > R[latest[key]]["ts"]:
            latest[key] = f

    def cls(stored, raw, fix):
        if stored is None:
            return "none"
        if raw is not None and abs(stored - raw) <= max(0.011, abs(raw) * 0.005):
            return "SCALED"
        if fix is not None and abs(stored - fix) <= max(0.05, abs(fix) * 0.005):
            return "right"
        return "other"

    rows, undecided = [], []
    for c in cands.values():
        if not c["file"]:
            undecided.append(c)
            continue
        r, k = R[c["file"]], c["k"]
        sym, qe, b = r["sym"], r["qe"], r["b"]
        raw_rev = r["rev1"] / 1e7 if r["rev1"] is not None else None
        rp = r["own1"] if (b == "c" and r.get("own1") not in (None, 0)) else r["pat1"]
        raw_pat = rp / 1e7 if rp is not None else None

        def fix(v):
            return None if v is None else round(v / 10**k, 2)

        row = rev.get(sym, {}).get(qe)
        srev = row[0 if b == "s" else 1] if row else None
        fr = [x for x in fund.get(sym, []) if str(x[0]) == qe]
        spat = fr[0][1 if b == "s" else 3] if fr else None
        rows.append(
            {
                "sym": sym,
                "qe": qe,
                "basis": "con" if b == "c" else "std",
                "k": k,
                "file": c["file"],
                "latest": latest[(sym, b, qe)] == c["file"],
                "rounding": r["round"],
                "rev_store": srev,
                "rev_raw": raw_rev and round(raw_rev, 4),
                "rev_fixed": fix(raw_rev),
                "rev_store_is": cls(srev, raw_rev, fix(raw_rev)),
                "pat_store": spat,
                "pat_raw": raw_pat and round(raw_pat, 4),
                "pat_fixed": fix(raw_pat),
                "pat_store_is": cls(spat, raw_pat, fix(raw_pat)),
                "evidence": c["ev"],
                "pairs": c["pairs"],
            }
        )
    cells = defaultdict(list)
    for x in rows:
        cells[(x["sym"], x["qe"], x["basis"])].append(x)
    live = sorted(c for c, xs in cells.items() if any("SCALED" in (x["rev_store_is"], x["pat_store_is"]) for x in xs))
    xtra_only = sorted(c for c, xs in cells.items() if c not in live and any(x["latest"] for x in xs))
    superseded = sorted(c for c, xs in cells.items() if c not in live and not any(x["latest"] for x in xs))
    print(
        "candidates NOT in the ledger: %d filings / %d cells | undecided pairs: %d"
        % (len(rows), len(cells), sum(len(c["pairs"]) for c in undecided))
    )
    print(
        "  store holds the scaled value: %d cells (revenue %d, PAT %d)"
        % (
            len(live),
            sum(1 for c in live if any(x["rev_store_is"] == "SCALED" for x in cells[c])),
            sum(1 for c in live if any(x["pat_store_is"] == "SCALED" for x in cells[c])),
        )
    )
    print("  stores right, scaled filing is the latest (xbrl_extra exposure): %d %s" % (len(xtra_only), xtra_only))
    print("  stores right, scaled filing superseded by a later one: %d" % len(superseded))
    for x in sorted(rows, key=lambda x: (x["sym"], x["qe"], x["basis"])):
        print(
            "  %-11s %s %s k=%-2d latest=%-5s rev %-6s %s -> %s | pat %-6s %s -> %s"
            % (
                x["sym"],
                x["qe"],
                x["basis"],
                x["k"],
                x["latest"],
                x["rev_store_is"],
                x["rev_store"],
                x["rev_fixed"],
                x["pat_store_is"],
                x["pat_store"],
                x["pat_fixed"],
            )
        )
    if out_path:
        json.dump(
            {
                "_README": [
                    "Output of scripts/detect_scale_ytd.py (runbook §184). SUSPECTS with a YTD-chain anchor, NOT verdicts:",
                    "adjudicate each by hand before adding a scale_fix.json entry. k = the filing's power of ten vs the",
                    "truth (fixed = raw / 10^k); *_store_is: SCALED = the served store carries the raw value.",
                ],
                "generated": datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
                "summary": {
                    "filings_indexed": len(recs),
                    "pairs": len(pairs),
                    "anomalous": n_anom,
                    "explained_by_armed": n_expl,
                    "recall": [len(refound), len(cached_armed)],
                    "candidate_filings": len(rows),
                    "cells": len(cells),
                    "store_scaled_cells": len(live),
                    "xbrl_extra_only": xtra_only,
                    "superseded": superseded,
                },
                "candidates": sorted(rows, key=lambda x: (x["sym"], x["qe"], x["basis"])),
                "undecided": undecided,
            },
            open(out_path, "w", encoding="utf-8"),
            indent=1,
            ensure_ascii=False,
        )
        print("wrote", out_path)


if __name__ == "__main__":
    main()
