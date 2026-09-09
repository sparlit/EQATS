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
"""NSE results-archive STANDALONE PAT reader for the pre-2015 residue (WP-P3, runbook §57 rung 2).

The list row (scripts/_nsearch_cache/list_<SYM>.json, cached by the CON-GAP campaign) DECLARES
basis / cumulative / audited / bank / toDate; the detail page (financial_res_<SYM>_<id>.html) prints
Net Profit, Face Value, Paid-up Equity and Basic EPS with the unit declared. Gates, all on the
document itself (nothing anchors on us, because the cell IS the gap):
  G1 page Symbol in {sym}+era aliases     G2 Period Ended == qe      G3 basis Non-Consolidated
  G4 list row + page say Non-cumulative   G5 a Net Profit row exists and is not the all-zero template
  G6 EPS identity: Basic EPS x Paid-up / Face Value == Net Profit within max(3%, EPS-rounding, 0.02cr)
     (parsed units: the lakh divisor cancels, read_con_pat_nse.py GATE E)
Two modes: --calibrate reads cells we ALREADY store (hold-out) and reports the mismatch rate;
--residue reads the open cells and emits apply_agg_pat_fills.py proposals. Never writes a store.
"""
import argparse
import collections
import json
import os
import random
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import contextlib

import _nse_archive_revop as NAR

NAR.JAR = NAR.BF.nse_jar()
C = os.path.join(ROOT, "scripts", "_nsearch_cache")
R_NP = re.compile(r"net profit\s*\(?\+?\)?\s*/?\s*\(?loss\)?\s*\(?-?\)?\s*(for the period|after tax)", re.IGNORECASE)
R_EPS = re.compile(r"basic\s*eps", re.IGNORECASE)
R_EPS_AFTER = re.compile(r"basic\s*eps.*after", re.IGNORECASE)
R_FV = re.compile(r"face value", re.IGNORECASE)
R_PU = re.compile(r"paid.?up equity", re.IGNORECASE)


def listfile(s):
    return os.path.join(C, "list_{}.json".format(re.sub(r"[^A-Z0-9]", "_", s.upper())))


def candidates(sym, qe):
    names = [sym, *NAR.aliases(sym)]
    rows = []
    nolist = True
    for n in names:
        lp = listfile(n)
        if os.path.exists(lp):
            nolist = False
            with contextlib.suppress(Exception):
                rows += json.load(open(lp))
    if nolist:
        return None, names
    out = []
    for r in rows:
        if NAR.iso_qe(r.get("toDate") or "") != qe:
            continue
        if (r.get("consolidated") or "").lower().startswith("consolidated"):
            continue
        if (r.get("period") or "Quarterly") != "Quarterly":
            continue
        out.append(r)
    return out, names


def judge(sym, qe, row, names):
    link = row.get("resultDetailedDataLink") or ""
    if not link:
        return None, "no-detail-link", None
    if (row.get("cumulative") or "").lower().startswith("cumulative"):
        return None, "G4 list row declares Cumulative (YTD)", None
    rid = re.search(r"_(\d+)\.html?$", link)
    rid = rid.group(1) if rid else "x"
    path = os.path.join(C, "std_%s_%d_%s.html" % (re.sub(r"[^A-Z0-9]", "_", sym), qe, rid))
    try:
        html = NAR.get_detail(link, sym, path)
    except Exception as ex:
        return None, f"fetch-failed:{type(ex).__name__} (transport, NOT evidence)", None
    meta, rws = NAR.parse_detail(html)
    if not meta.get("Consolidated / Non-Consolidated") and not rws:
        return None, "empty-shell page (%d bytes)" % len(html), None
    if (meta.get("Symbol") or "").upper() not in {n.upper() for n in names}:
        return None, "G1 page symbol {} not in {}".format(meta.get("Symbol"), names), meta
    if NAR.iso_qe(meta.get("Period Ended", "")) != qe:
        return None, "G2 period %s != %d" % (meta.get("Period Ended"), qe), meta
    basis = (meta.get("Consolidated / Non-Consolidated") or "").strip().lower()
    if basis != "non-consolidated":
        return None, f"G3 basis {basis!r}", meta
    m = re.search(r"Cumulative\s*/\s*Non-?Cumulative\s*\|?\s*(Non-?Cumulative|Cumulative)", html, re.IGNORECASE)
    if m and m.group(1).lower().replace("-", "").startswith("cumulative"):
        return None, "G4 page declares Cumulative (YTD)", meta
    np_ = NAR.pick(rws, R_NP)
    if np_ is None:
        return None, "G5 no Net Profit row ({})".format(meta.get("fmt")), meta
    if abs(np_) < 1e-9:
        return None, "G5 blank template (Net Profit 0.00)", meta
    eps = NAR.pick(rws, R_EPS_AFTER) if NAR.pick(rws, R_EPS_AFTER) is not None else NAR.pick(rws, R_EPS)
    fv = NAR.pick(rws, R_FV)
    pu = NAR.pick(rws, R_PU)
    if eps is None or fv in (None, 0) or pu in (None, 0) or eps == 0:
        return None, f"G6 EPS identity not testable (eps={eps} fv={fv} pu={pu})", meta
    imp = eps * pu / fv
    d = meta.get("div", 100.0)
    tol = max(0.03 * max(abs(np_), abs(imp)), 0.005 * d / 100.0 * pu / fv, 0.02)
    if abs(imp - np_) > tol:
        return None, f"G6 EPS identity fails: EPS*PU/FV={imp:.2f} vs NP {np_:.2f} (tol {tol:.2f})", meta
    meta.update(
        {
            "np": round(np_, 2),
            "eps": eps * d,
            "fv": fv * d,
            "pu": round(pu, 2),
            "imp": round(imp, 2),
            "link": link,
            "filingDate": row.get("filingDate"),
        }
    )
    return round(np_, 2), "", meta


def run(cells, tag, sf):
    out = {}
    t0 = time.time()
    for i, (sym, qe) in enumerate(cells):
        cand, names = candidates(sym, qe)
        k = "%s|%d" % (sym, qe)
        if cand is None:
            out[k] = {"sym": sym, "qe": qe, "reason": f"no cached list for {names} (list API not called)"}
            continue
        if not cand:
            out[k] = {
                "sym": sym,
                "qe": qe,
                "reason": "no Non-Consolidated Quarterly row for this quarter in the cached list",
            }
            continue
        vals = []
        reasons = []
        for row in cand:
            v, why, meta = judge(sym, qe, row, names)
            if v is not None:
                vals.append((v, meta))
            else:
                reasons.append(why)
        if not vals:
            out[k] = {"sym": sym, "qe": qe, "reason": reasons[0] if reasons else "?", "all_reasons": reasons}
        elif len({v for v, _ in vals}) > 1:
            out[k] = {"sym": sym, "qe": qe, "reason": "multiple candidate pages DISAGREE %s" % [v for v, _ in vals]}
        else:
            v, meta = vals[0]
            stored = next((r[1] for r in sf.get(sym, []) if r[0] == qe), None)
            out[k] = {"sym": sym, "qe": qe, "value": v, "meta": meta, "stored": stored}
        if (i + 1) % 25 == 0:
            print("[%s %d/%d] %s (%.0fs)" % (tag, i + 1, len(cells), k, time.time() - t0))
            sys.stdout.flush()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--residue")
    ap.add_argument("--calibrate", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    sf = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    res = json.load(open(a.residue))  # [[sym, qe], ...]
    syms = sorted({s for s, _ in res})
    result = {}
    if a.calibrate:
        random.seed(7)
        pool = []
        for s in syms:
            for r in sf.get(s, []):
                if 20050101 <= r[0] <= 20141231 and r[1] is not None:
                    pool.append((s, r[0]))
        random.shuffle(pool)
        cal = pool[: a.calibrate]
        cr = run(cal, "calib", sf)
        judged = [v for v in cr.values() if "value" in v]
        mism = [v for v in judged if abs(v["value"] - v["stored"]) > max(0.05, 0.005 * abs(v["stored"]))]
        print(
            "CALIBRATION: %d cells asked, %d readable, %d MISMATCH (%.2f%%)"
            % (len(cal), len(judged), len(mism), 100.0 * len(mism) / max(1, len(judged)))
        )
        for v in mism[:20]:
            print("   ", v["sym"], v["qe"], "read", v["value"], "stored", v["stored"], v["meta"].get("link"))
        result["calibration"] = cr
    rr = run([tuple(x) for x in res], "residue", sf)
    result["residue"] = rr
    c = collections.Counter(("PASS" if "value" in v else v["reason"][:40]) for v in rr.values())
    print("RESIDUE:")
    [print("  %4d %s" % (n, k)) for k, n in c.most_common()]
    json.dump(result, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
