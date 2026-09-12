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
"""EPS-anchored sweep: verify suspect consolidated-PAT cells (tiny |con|) against their
NSE integrated-filing consolidated XBRL. Detects filer tag-swaps
(ProfitOrLossAttributableToOwnersOfParent <-> ...NonControllingInterests) like GLENMARK Q4FY26.
See DATA_RUNBOOK 2d; confirmed fixes are journaled in scripts/attr_swap_fixes.json.
Resumable via _attr_swap_progress.json (untracked). Read-only: touches NO repo data files —
verdicts SWAPPED/MISMATCH_MANUAL must be anchored a 2nd way (PDF/Screener) before healing.
Run: python -X utf8 scripts/detect_attr_swap.py"""
import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PROG = os.path.join(HERE, "_attr_swap_progress.json")
sys.path.insert(0, HERE)
import contextlib

import build_fundamentals as B

fund = json.load(open(os.path.join(REPO, "docs", "sf_fundamentals.json"), encoding="utf-8"))

# ---- candidate list: 2025+ tiny-con signature (same rules as the scan) ----
cands = []
for sym, rec in fund.items():
    for r in rec:
        qe, std, con = r[0], r[1], r[3]
        if con is None or qe < 20250101 or abs(con) > 3.0:
            continue
        neigh = [abs(x[3]) for x in rec if x[3] is not None and x[0] != qe]
        neigh_med = sorted(neigh)[len(neigh) // 2] if neigh else None
        rule_std = std is not None and abs(std) >= 15 and abs(con) <= 0.15 * abs(std)
        rule_neigh = neigh_med is not None and neigh_med >= 25
        if rule_std or rule_neigh:
            cands.append({"sym": sym, "qe": qe, "std": std, "con": con})
cands.sort(key=lambda c: (c["sym"], c["qe"]))
print("candidates:", len(cands), flush=True)

prog = {}
if os.path.exists(PROG):
    prog = json.load(open(PROG))

h = {
    "User-Agent": B.UA,
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
}
jar = [None]


def warm():
    j = B.nse_jar()
    with contextlib.suppress(Exception):
        B._get(
            "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
            headers={"User-Agent": B.UA, "Accept": "text/html"},
            jar=j,
            timeout=30,
        )
    jar[0] = j


_cffi = {"s": None}


def cffi_get(url, hh):
    from curl_cffi import requests as cr

    if _cffi["s"] is None:
        s = cr.Session(impersonate="chrome")
        s.get("https://www.nseindia.com/", timeout=30)
        s.get("https://www.nseindia.com/companies-listing/corporate-filings-financial-results", timeout=30)
        _cffi["s"] = s
    r = _cffi["s"].get(url, headers=hh, timeout=90)
    if r.status_code != 200:
        _cffi["s"] = None
        raise RuntimeError("cffi HTTP %d" % r.status_code)
    return r.text


def fetch(url, hh, expect_json=False):
    for attempt in range(3):
        try:
            if attempt == 1:
                warm()
            body = cffi_get(url, hh) if attempt == 2 else B._get(url, headers=hh, jar=jar[0], timeout=90)
            if expect_json:
                return json.loads(body)
            return body
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))
    return None


def qe_windows(qe):
    y, mo, dy = qe // 10000, qe // 100 % 100, qe % 100
    start = datetime.date(y, mo, dy)
    end = min(start + datetime.timedelta(days=140), datetime.date.today())
    return start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y")


TAG = r'<in-(?:bse-fin|capmkt):%s contextRef="OneD"[^>]*>([^<]*)<'


def tagval(xml, name):
    m = re.search(TAG % name, xml)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def analyze(xml):
    total = tagval(xml, r"ProfitLossFor(?:The)?Period")
    owners = tagval(xml, "ProfitOrLossAttributableToOwnersOfParent")
    nci = tagval(xml, "ProfitOrLossAttributableToNonControllingInterests")
    bank = tagval(xml, "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates")
    eps = None
    for t in (
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsLossPerShareFromContinuingOperations",
        "BasicEarningsLossPerShare",
    ):
        eps = tagval(xml, t)
        if eps is not None:
            break
    paid = tagval(xml, "PaidUpValueOfEquityShareCapital")
    fv = tagval(xml, "FaceValueOfEquityShareCapital")
    shares = paid / fv if (paid and fv) else None
    return {"total": total, "owners": owners, "nci": nci, "bank": bank, "eps": eps, "shares": shares}


def verdict(a, stored_cr):
    cr = 1e7
    eps, sh = a["eps"], a["shares"]
    own, nci, _total = a["owners"], a["nci"], a["total"]
    if own is None and nci is None:
        # no attributable tags: stored should be total (or bank row)
        return "NO_ATTR_TAGS", None
    if eps is None or not sh:
        return "NO_EPS_ANCHOR", None
    tol = max(0.03, abs(eps) * 0.03)
    e_own = abs((own or 0) / sh - eps)
    e_nci = abs((nci or 0) / sh - eps) if nci is not None else None
    if e_own <= tol:
        return "OK_OWNERS_MATCH_EPS", round((own or 0) / cr, 2)
    if e_nci is not None and e_nci <= tol and e_own > 3 * tol:
        return "SWAPPED", round(nci / cr, 2)
    # neither matches cleanly
    return "MISMATCH_MANUAL", None


results = {}
nsym = 0
for c in cands:
    key = "%s|%d" % (c["sym"], c["qe"])
    if key in prog:
        results[key] = prog[key]
        continue
    sym, qe = c["sym"], c["qe"]
    frm, to = qe_windows(qe)
    out = {"sym": sym, "qe": qe, "stored_con": c["con"], "std": c["std"]}
    try:
        rows = []
        for idx in ("equities", "sme"):
            u = (
                f"https://www.nseindia.com/api/integrated-filing-results?index={idx}&period=Quarterly"
                f"&from_date={frm}&to_date={to}&symbol={sym}&page=1&size=50"
            )
            try:
                j = fetch(u, h, expect_json=True)
            except Exception:
                continue
            rows = [
                r
                for r in (j.get("data") or [])
                if r.get("symbol") == sym
                and B.iso(r.get("qe_Date")) == str(qe)
                and "consol" in (r.get("consolidated") or "").lower()
                and (r.get("xbrl") or "").startswith("http")
            ]
            if rows:
                break
        if not rows:
            out["verdict"] = "NO_CON_FILING_FOUND"
        else:
            xml = fetch(rows[0]["xbrl"], {"User-Agent": B.UA, "Referer": "https://www.nseindia.com/"})
            a = analyze(xml)
            v, correct = verdict(a, c["con"])
            out.update(
                {
                    "verdict": v,
                    "correct_con": correct,
                    "xbrl": rows[0]["xbrl"],
                    "owners_raw": a["owners"],
                    "nci_raw": a["nci"],
                    "total_raw": a["total"],
                    "eps": a["eps"],
                    "shares": a["shares"],
                }
            )
    except Exception as e:
        out["verdict"] = "ERROR"
        out["error"] = str(e)[:200]
    results[key] = out
    prog[key] = out
    json.dump(prog, open(PROG, "w"))
    nsym += 1
    print("%-40s %s %s" % (key, out["verdict"], out.get("correct_con", "")), flush=True)
    time.sleep(1.2)

# summary
sw = [r for r in results.values() if r["verdict"] == "SWAPPED"]
manual = [r for r in results.values() if r["verdict"] in ("MISMATCH_MANUAL", "NO_EPS_ANCHOR", "ERROR")]
print("\n==== SUMMARY ====")
print("checked:", len(results), "| SWAPPED:", len(sw), "| manual-review:", len(manual))
for r in sw:
    print(
        "SWAPPED  %-12s %d stored=%s correct=%s (eps=%s)"
        % (r["sym"], r["qe"], r["stored_con"], r["correct_con"], r["eps"])
    )
for r in manual:
    print(
        "MANUAL   %-12s %d stored=%s verdict=%s %s"
        % (r["sym"], r["qe"], r["stored_con"], r["verdict"], r.get("error", ""))
    )
