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
"""Owners-vs-total PAT verifier (§116 class) — reads a company's OWN filed consolidated result PDF
from the BSE announcement archive and extracts the three attribution lines:

    Profit (Loss) for the period      <- TOTAL   (== what we currently serve in patC)
      Attributable to Owners/Equity holders of the parent   <- OWNERS (the platform basis)
      Non-controlling / Minority interest                    <- NCI

A proposal is emitted ONLY when, for one column under one unit scale, the filing's own arithmetic
CLOSES (owners + NCI == total within tolerance) AND that total matches our stored patC value. Both
gates together pin the column (current quarter) and the scale, and make a stray/OCR misread fail
closed — exactly the §116d discipline (the identity is the gate, not the comparison).

NO write. Emits JSON proposals to stdout / --out for human review before fund_cell_fix.json.

Usage:
  python3 scripts/owners_total_verify.py --cells GOLDIAM|20250630|patC[,...]
  python3 scripts/owners_total_verify.py --sym GOLDIAM            # all its unreconciled cells
  python3 scripts/owners_total_verify.py --all --out /tmp/reach.json   # every unreconciled cell (reach measure)
  python3 scripts/owners_total_verify.py --sym GOLDIAM --ocr       # allow free rapidocr on image P&Ls
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_insurers as FI  # bse_session, datebound, fetch_pdf, qe_from_ann, prevq
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UNREC = os.path.join(HERE, "owners_basis_unreconciled.json")
DOCS_FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
SCRIPS = os.path.join(HERE, "bse_scrips.json")

# --- row label classifiers (applied in PRIORITY order: NCI, then OWNERS, then TOTAL) --------
_NCI = re.compile(r"(non[- ]?controlling|minority)\s*interest", re.IGNORECASE)
# owners / equity-holders attribution line (Format A "Owners of the Company" sub-line, or the
# LUPIN-style "Net profit after taxes attributable to owners of the Company")
_OWN = re.compile(
    r"(owners?|equity ?(holders?|shareholders?))\s*(of\s*(the\s*)?)?(company|parent|holding|group)", re.IGNORECASE
)
_OWN2 = re.compile(r"attributable.{0,25}(owners?|equity ?holders?|shareholders?)", re.IGNORECASE)
# the group total profit line (pre-attribution): "Profit for the period", "Profit after tax",
# possibly "... and before non-controlling interest"
_TOTAL = re.compile(r"(profit|loss)[\s/()a-z]{0,40}(for the (period|quarter|year|half)|after tax)", re.IGNORECASE)
# lines that must NEVER be read as the group-total line
_VETO_TOTAL = re.compile(
    r"before tax|comprehensive|segment|exceptional|\bother\b|per share|earnings per"
    r"|\beps\b|ratio|paid.?up|dividend|reserve|revenue|income from|expense"
    r"|total tax|deferred|associate",
    re.IGNORECASE,
)
_NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")


def tv(w):
    w = w.strip().replace(",", "").replace("(", "-").replace(")", "")
    w = w.rstrip("-")  # trailing dash sometimes = column sep
    if w in ("", "-"):
        return None
    try:
        return float(w)
    except Exception:
        return None


def _isnum(tok):
    return bool(_NUM.match(tok.replace(",", "").replace(" ", "")))


def line_groups(words):
    """words = list of (x0,y0,x1,y1,text). Group into visual lines by baseline (<=4pt)."""
    ws = sorted(words, key=lambda w: (round(w[1] / 3), w[0]))
    lines, cur, cy = [], [], None
    for w in ws:
        if cy is None or abs(w[1] - cy) <= 4:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
        cy = w[1]
    if cur:
        lines.append(cur)
    return lines


def row_numbers(line):
    """Return [(x_center, value), ...] for numeric cells on a line, left to right."""
    out = []
    for w in sorted(line, key=lambda w: w[0]):
        t = w[4]
        if _isnum(t):
            v = tv(t)
            if v is not None:
                out.append(((w[0] + w[2]) / 2, v))
    return out


def label_of(line):
    return " ".join(w[4] for w in sorted(line, key=lambda w: w[0]) if not _isnum(w[4])).strip().lower()


def classify(lab):
    """Return 'nci' | 'owners' | 'total' | None for a row label, in priority order.
    A 'profit ... BEFORE non-controlling/minority interest' line is the pre-attribution GROUP
    TOTAL, not the NCI line, so it is routed to 'total' before the _NCI test can claim it."""
    if re.search(r"before\s+(non[- ]?controlling|minority)", lab):
        return "total" if _TOTAL.search(lab) else None
    if _NCI.search(lab):
        return "nci"
    if _OWN.search(lab) or _OWN2.search(lab):
        return "owners"
    if _TOTAL.search(lab) and not _VETO_TOTAL.search(lab):
        return "total"
    return None


def extract_blocks(pdf, ocr=False):
    """Return one dict per consolidated page carrying attribution rows:
    {page, con, totals:[row...], owners:[row...], ncis:[row...]} — each row is [(xc,val)...]."""
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception:
        return []
    N = min(len(doc), 60)
    blocks = []
    con = None
    for p in range(N):
        t = doc[p].get_text()
        low = t.lower()
        if "consolidated" in low and "standalone" not in low:
            con = True
        elif re.search(r"standalone", low) and "consolidated" not in low:
            con = False
        if t.strip():
            words = doc[p].get_text("words")
        elif ocr:
            words = FI._ocr_words(doc[p])
            if "consolidated" in " ".join(w[4] for w in words).lower():
                con = True
        else:
            continue
        if not words:
            continue
        totals, owners, ncis = [], [], []
        for ln in line_groups(words):
            lab = label_of(ln)
            if not lab:
                continue
            nums = row_numbers(ln)
            if not nums:
                continue
            k = classify(lab)
            if k == "nci":
                ncis.append(nums)
            elif k == "owners":
                owners.append(nums)
            elif k == "total":
                totals.append(nums)
        if owners and ncis:
            blocks.append({"page": p, "con": bool(con), "totals": totals, "owners": owners, "ncis": ncis})
    return blocks


def reconcile(block, stored, tol_abs=0.11, tol_rel=0.0002):
    """Across every (owners_row, nci_row) pair and column x, find where owners+nci closes to a
    total (explicit total row at the same x if present, else owners+nci) that ALSO matches `stored`,
    under one unit scale. Returns list of unique proposals.

    Tolerance is near-exact (0.11cr flat, plus 0.02%% for very large filers) so the total==stored gate
    genuinely pins the current-quarter column and the identity is filer-rounding-tight, not a fuzzy
    match that could latch onto a neighbouring column or the comprehensive-income block."""

    def close(a, b):
        return abs(a - b) <= max(tol_abs, abs(b) * tol_rel)

    def nearest(row, xc, xt=26):
        best = None
        for x, v in row:
            if abs(x - xc) <= xt and (best is None or abs(x - xc) < abs(best[0] - xc)):
                best = (x, v)
        return best[1] if best else None

    results = []
    for div in (1.0, 100.0, 10.0, 1000.0):
        for orow in block["owners"]:
            for xc, ov in orow:
                o = ov / div
                for nrow in block["ncis"]:
                    nv = nearest(nrow, xc)
                    if nv is None:
                        continue
                    n = nv / div
                    # explicit total at this column, from any total row
                    t_expl = None
                    for trow in block["totals"]:
                        cand = nearest(trow, xc)
                        if cand is not None:
                            tt = cand / div
                            if close(o + n, tt):
                                t_expl = tt
                                break
                    if block["totals"] and t_expl is None:
                        # there ARE total rows but none reconcile with owners+nci at this column -> reject
                        continue
                    t = t_expl if t_expl is not None else (o + n)
                    if not close(t, stored):
                        continue
                    # neighbour anchors: the total-row values immediately to the RIGHT of the matched
                    # current-quarter column are the prior-quarter and year-ago quarter (standard
                    # [curQ, prevQ, yagoQ, ...YTD/year] layout). Captured for provenance.
                    trow = block["totals"][0] if block["totals"] else orow
                    sorted(v2 for v2 in trow)  # (xc,val) tuples sort by xc
                    right = [round(v / div, 2) for x2, v in sorted(trow) if x2 > xc + 8]
                    results.append(
                        {
                            "owners": round(o, 2),
                            "nci": round(n, 2),
                            "total": round(t, 2),
                            "div": div,
                            "col_x": round(xc, 1),
                            "explicit_total": t_expl is not None,
                            "prevq_total": right[0] if len(right) > 0 else None,
                            "yago_total": right[1] if len(right) > 1 else None,
                        }
                    )
    uniq = {}
    for r in results:
        if abs(r["owners"] - stored) < 0.011:
            continue  # owners == total: no owners-vs-total defect, nothing to heal
        # prefer explicit-total proposals when the owners value coincides
        if r["owners"] not in uniq or (r["explicit_total"] and not uniq[r["owners"]]["explicit_total"]):
            uniq[r["owners"]] = r
    return list(uniq.values())


def load_stored():
    return json.load(open(DOCS_FUND))


def stored_patC(fund, sym, qe):
    for r in fund.get(sym, []):
        if r[0] == qe:
            return r[3] if len(r) > 3 else None
    return None


def verify_cell(o, scrips, fund, sym, qe, ocr=False, pause=1.0):
    code = scrips.get(sym)
    stored = stored_patC(fund, sym, qe)
    base = {"sym": sym, "qe": qe, "stored": stored, "code": code}
    if not code:
        return {**base, "status": "no-scripcode"}
    if stored is None:
        return {**base, "status": "no-stored-cell"}
    import datetime

    qd = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
    lo = (qd + datetime.timedelta(days=1)).strftime("%Y%m%d")
    hi = (qd + datetime.timedelta(days=210)).strftime("%Y%m%d")  # ~7 months covers late Q4 filings
    # window: from quarter-end to ~7 months later
    try:
        filings = FI.datebound(o, code, lo, hi)
    except Exception as ex:
        return {**base, "status": "fetch-err:" + str(ex)[:40]}
    cand = sorted([(a, att, sub) for (a, att, sub) in filings if FI.qe_from_ann(a) == qe])
    if not cand:
        return {**base, "status": "no-filing", "n_filings": len(filings)}
    tried = []
    for annd, att, _sub in cand[:4]:
        pdf = FI.fetch_pdf(o, att)
        time.sleep(pause)
        if not pdf:
            tried.append((annd, "no-pdf"))
            continue
        blocks = extract_blocks(pdf, ocr=False)
        props = []
        for b in blocks:
            props += [dict(p, page=b["page"], con=b["con"], ann=annd, att=att) for p in reconcile(b, stored)]
        if not props and ocr:
            blocks = extract_blocks(pdf, ocr=True)
            for b in blocks:
                props += [
                    dict(p, page=b["page"], con=b["con"], ann=annd, att=att, via="ocr") for p in reconcile(b, stored)
                ]
        if props:
            # prefer consolidated-page proposals
            props.sort(key=lambda p: 0 if p.get("con") else 1)
            return {**base, "status": "OK", "proposals": props}
        tried.append((annd, "no-attribution-block-text" + ("+ocr" if ocr else "")))
    return {**base, "status": "unread", "tried": tried}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cells", default="")
    ap.add_argument("--sym", default="")
    ap.add_argument(
        "--sweepsym",
        default="",
        help="comma list of symbols: verify EVERY con quarter "
        "in sf_fundamentals (heal-the-row), not just the unreconciled ones",
    )
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="")
    ap.add_argument("--pause", type=float, default=1.0)
    args = ap.parse_args()

    scrips = json.load(open(SCRIPS))["by_id"]
    fund = load_stored()
    unrec = json.load(open(UNREC))["cells"]

    targets = []
    if args.cells:
        for k in args.cells.split(","):
            k = k.strip()
            if not k:
                continue
            sym, qe, _ = k.split("|")
            targets.append((sym, int(qe)))
    elif args.sym:
        for k in unrec:
            if k.split("|")[0] == args.sym:
                targets.append((k.split("|")[0], int(k.split("|")[1])))
    elif args.sweepsym:
        want = {x.strip() for x in args.sweepsym.split(",") if x.strip()}
        for s in want:
            for row in fund.get(s, []):
                if len(row) > 3 and row[3] is not None:  # has a con value
                    targets.append((s, int(row[0])))
    elif args.all:
        for k in unrec:
            s, q, _ = k.split("|")
            targets.append((s, int(q)))
    targets = sorted(set(targets))
    if args.limit:
        targets = targets[: args.limit]

    o = FI.bse_session()
    time.sleep(0.5)
    out = []
    for sym, qe in targets:
        r = verify_cell(o, scrips, fund, sym, qe, ocr=args.ocr, pause=args.pause)
        out.append(r)
        st = r["status"]
        extra = ""
        if st == "OK":
            p = r["proposals"][0]
            extra = "  owners={} nci={} total={} (div={} con={}) via={}".format(
                p["owners"], p["nci"], p["total"], p["div"], p.get("con"), p.get("via", "text")
            )
        print("%-12s %d  %-10s%s" % (sym, qe, st, extra), flush=True)
    if args.out:
        json.dump(out, open(args.out, "w"), indent=1)
        print("wrote", args.out)
    # summary
    from collections import Counter

    print("STATUS:", dict(Counter(r["status"].split(":")[0] for r in out)))


if __name__ == "__main__":
    main()
