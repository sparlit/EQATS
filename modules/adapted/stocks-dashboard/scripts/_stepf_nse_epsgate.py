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
"""STEP F — fill 2005-2014 cells that have NO stored PAT, by EPS-reconciling NSE archive pages.

WHY THIS EXISTS
`_nse_archive_revop.py` is PAT-ANCHORED: `if not frow: continue` silently skips any cell with no
stored fundamentals row. Of the 795 open 2005-2014 cells, 697 have no stored PAT, so that tool
can never reach them — it is structurally limited, not source-limited. This step proves the PAT
instead of anchoring it, using four fields the same NSE detail page already prints:

    shares  = paid-up equity capital / face value
    implied = net profit / shares
    land only if |implied - printed EPS| <= max(2% of EPS, 0.05)

UNIT TRAP — THE THING THAT MAKES THIS CORRECT
`_nse_archive_revop.parse_detail` divides EVERY parsed value by the declared unit divisor
(lakhs=100 etc.). That is right for currency rows but WRONG for the two per-share rows: face
value and EPS are rupees-per-share, not lakhs. Un-corrected, a ₹10 face value reads as 0.10 and a
₹0.44 EPS reads as 0.00, and the reconciliation is nonsense. Both are multiplied back by
meta['div'] here. Verified on RPOWER: pat 105.68cr, eqcap 2396.80cr, fv ₹10 -> 239.68cr shares ->
implied 0.44 == printed 0.44.

HOW STRONG IS THIS GATE, HONESTLY
Measured on 17 cached pages: 9 reconcile, 8 do not (~53%). The failures are not noise — some
filers print a YEAR-TO-DATE EPS against a quarterly PAT (HIMACHLFUT is ~3x off, the shape of a
9-month figure), and some leave EPS at 0.00. So this gate is materially weaker than STEP E's
detres version, which reconciled near-perfectly. That is fine and by design: a PASS is real
proof (four independently printed fields agreeing, which also pins the scale), a MISMATCH is
refused. Expect roughly half the target cells to land, and do not "loosen the tolerance" to
raise that — the mismatches are exactly the cells where the identity does not hold.

Run:  python -X utf8 -u scripts/_stepf_nse_epsgate.py --gaps _gaps_0514_all.json [--limit N]
Writes: scripts/pre2015_reads_f.json / pre2015_attempted_f.json
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import _nse_archive_revop as N  # noqa: E402

OUTP = os.path.join(HERE, "pre2015_reads_f.json")
ATTP = os.path.join(HERE, "pre2015_attempted_f.json")

EPS_PREF = [
    r"^basic\s*&?\s*diluted eps after extra",
    r"^basic eps after extra",
    r"^diluted eps after extra",
    r"^basic\s*&?\s*diluted eps before extra",
    r"^basic eps before extra",
    r"^diluted eps before extra",
    r"\beps\b",
]
PAT_PREF = [
    r"^net profit\s*\(\+\)\s*/\s*loss\s*\(-\)\s*for the period",
    r"^net profit.*for the period",
    r"^net profit.*after tax",
]


def rowmap(rows):
    d = {}
    for l, v in rows:
        d.setdefault(l.strip(), v)
    return d


def grab(d, pats):
    for p in pats:
        for k, v in d.items():
            if re.search(p, k, re.IGNORECASE):
                return v, k
    return None, None


def main():
    argv = sys.argv
    gapf = argv[argv.index("--gaps") + 1] if "--gaps" in argv else "_gaps_0514_all.json"
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None

    gaps = json.load(open(os.path.join(HERE, gapf), encoding="utf8"))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf8"))
    revop_now = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json"), encoding="utf8"))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}

    out = json.load(open(OUTP, encoding="utf8")) if os.path.exists(OUTP) else {}
    att = json.load(open(ATTP, encoding="utf8")) if os.path.exists(ATTP) else {}
    N.JAR = N.BF.nse_jar()

    syms = sorted(gaps)
    if limit:
        syms = syms[:limit]
    land = ref = 0
    fv_seen = {}
    for si, sym in enumerate(syms, 1):
        want = {int(q) for q in gaps[sym] if str(q) not in out.get(sym, {}) and f"{sym}|{q}" not in att}
        if not want:
            continue
        try:
            rows = N.list_rows(sym)
        except Exception:
            continue
        if not rows:
            for qe in want:
                att["%s|%d" % (sym, qe)] = {"reason": "no-nse-filings-any-era"}
                ref += 1
            continue
        # First pass over this company's filings: collect every non-zero face value it ever
        # printed. Used only as a fallback below, and only when UNANIMOUS.
        fvs = set()
        for r in rows:
            if not r.get("resultDetailedDataLink"):
                continue
            link0 = r["resultDetailedDataLink"]
            dp0 = os.path.join(N.CACHE, re.sub(r"[^A-Za-z0-9_.]", "_", link0.rsplit("/", 1)[-1]))
            if not os.path.exists(dp0):
                continue  # cache-only: never fetch extra pages just for this
            try:
                m0, p0 = N.parse_detail(open(dp0, encoding="utf8", errors="replace").read())
            except Exception:
                continue
            v0, _ = grab(rowmap(p0), [r"face value"])
            if v0:
                f0 = v0 * (m0.get("div", 100.0) or 100.0)
                if f0 > 0:
                    fvs.add(round(f0, 2))
        if len(fvs) == 1:
            fv_seen[sym] = fvs.pop()

        for r in rows:
            qe = N.iso_qe(r.get("toDate"))
            if qe not in want or not r.get("resultDetailedDataLink"):
                continue
            link = r["resultDetailedDataLink"]
            dp = os.path.join(N.CACHE, re.sub(r"[^A-Za-z0-9_.]", "_", link.rsplit("/", 1)[-1]))
            try:
                html = N.get_detail(link, sym, dp)
            except Exception:
                continue  # transient -> stays retryable
            meta, prows = N.parse_detail(html)
            basis = "con" if "Non" not in (meta.get("Consolidated / Non-Consolidated") or "Non") else "std"
            if basis != "std":
                continue  # this dataset's cells are STANDALONE
            div = meta.get("div", 100.0) or 100.0
            d = rowmap(prows)
            pat, _ = grab(d, PAT_PREF)
            eps, _ = grab(d, EPS_PREF)
            eq, _ = grab(d, [r"paid-up equity share capital"])
            fv, _ = grab(d, [r"face value"])
            if None in (pat, eps, eq, fv):
                att["%s|%d" % (sym, qe)] = {"reason": f"gate-F inputs missing (pat={pat} eps={eps} eq={eq} fv={fv})"}
                ref += 1
                continue
            # per-share rows are NOT in lakhs -- undo parse_detail's blanket unit division
            fv_r, eps_r = fv * div, eps * div
            if fv_r <= 0:
                # Some filings leave Face Value blank/0 (ANDHRSUGAR Dec-2005). Face value is a
                # COMPANY CONSTANT, so borrowing it from another filing of the same company is an
                # INDEPENDENT input, not circular -- the EPS identity is still doing the proving.
                # Only borrow when every other filing agrees on one value, so a genuine
                # split/consolidation in the window can never be papered over.
                fv_r = fv_seen.get(sym)
                if not fv_r:
                    att["%s|%d" % (sym, qe)] = {"reason": "gate-F face-value non-positive and none borrowable"}
                    ref += 1
                    continue
            # A near-zero EPS cannot prove anything: the 0.05 floor tolerance would let almost any
            # implied value through (AKSHOPTFBR Sep-2006 "passed" as 0.00 == -0.00). Refuse rather
            # than bank a degenerate match.
            if abs(eps_r) < 0.10:
                att["%s|%d" % (sym, qe)] = {"reason": f"gate-F EPS too small to prove ({eps_r:.4f})"}
                ref += 1
                continue
            shares = eq / fv_r
            if shares <= 0:
                att["%s|%d" % (sym, qe)] = {"reason": "gate-F share count non-positive"}
                ref += 1
                continue
            implied = pat / shares
            tol = max(0.02 * abs(eps_r), 0.05)
            if abs(implied - eps_r) > tol:
                att["%s|%d" % (sym, qe)] = {
                    "reason": f"gate-F EPS FAILS implied={implied:.4f} seen={eps_r:.4f} tol={tol:.4f}"
                }
                ref += 1
                continue
            isbank = meta.get("fmt") == "Banking"
            isfin = isbank or any(
                c[6] == 1 for c in (revop_now.get(sym) or {}).values() if len(c) > 6 and c[6] is not None
            )
            if isbank:
                rev = N.pick(prows, N.R_REV_BANK)
            else:
                rev = N.pick(prows, N.R_REV_IND, N.R_REV_IND2, N.R_REV_IND3)
                if rev is None:
                    rev = N.pick(prows, N.R_REV_SIGNED)
                if rev is None:
                    rev = N.pick(prows, N.R_REV_IND5)
            if rev is None and isfin:
                rev = N.pick(prows, N.R_REV_TOTINC)
            stored = fmap.get(sym, {}).get(qe)
            if stored and stored[1] is not None and abs(stored[1] - pat) > max(2.0, 0.03 * abs(pat)):
                att["%s|%d" % (sym, qe)] = {
                    "reason": f"gate-F disagrees with stored PAT ({stored[1]:.2f} vs {pat:.2f})"
                }
                ref += 1
                continue
            out.setdefault(sym, {})[str(qe)] = {
                "rev": round(rev, 2) if (rev is not None and rev > 0) else None,
                "op": None,
                "pat": round(pat, 2),
                "basis": "std",
                "fin": 1 if isfin else 0,
                "gate": "E",
                "ann": 0,
                "ann_approx": True,
                "derived": None,
                "src": "nse-archive {} | GATE-E EPS-recon implied={:.4f} seen={:.4f} (eqcap={:.2f} fv={:.2f})".format(
                    link.rsplit("/", 1)[-1], implied, eps_r, eq, fv_r
                ),
            }
            land += 1
            print(
                "%-12s %d  rev=%9s pat=%9.2f  EPS %.2f==%.2f"
                % (sym, qe, (f"{rev:.2f}") if (rev and rev > 0) else "None", pat, eps_r, implied),
                flush=True,
            )
        if si % 20 == 0:
            _dump(out, att)
            print("  [%d/%d] landed=%d refused=%d" % (si, len(syms), land, ref), flush=True)
        time.sleep(0.3)
    _dump(out, att)
    print("DONE landed=%d refused=%d" % (land, ref), flush=True)


def _dump(out, att):
    json.dump(out, open(OUTP, "w", encoding="utf8"), indent=0, sort_keys=True)
    json.dump(att, open(ATTP, "w", encoding="utf8"), indent=0, sort_keys=True)


if __name__ == "__main__":
    main()
