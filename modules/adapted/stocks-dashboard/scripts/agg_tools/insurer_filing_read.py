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
"""Read a general insurer's quarterly revenue out of its own BSE filing, with the §55 control.

Built 2026-08-11 to finish the GICRE consolidated-revenue block after the aggregator route proved
it could not (runbook §81f/§81j): every quarter we store for these names is NEWER than the gap, so
there is nothing to anchor an aggregator series on. The filing carries the number and its own proof.

METHOD
  1. Pages are chosen by their DECLARED basis, corruption-tolerantly — these packs are scanned and
     the text layer mangles words ("Annuore-1", "Premium Ean'J.ed"), so the detector matches
     fragments ('onsolidat', 'tandalon') rather than whole words (§51b).
  2. Columns are GEOMETRY, never list indices (§62): the printed date headers "(31/12/2020)" give
     an x-band each, and every figure is assigned to a band by its own x-centre. A row that drops a
     nil cell therefore cannot shift the rest, which is the §55b trap that produced silent wrong
     numbers for NIACL.
  3. The revenue is §55's general-insurer convention:
        Premium Earned (Net) + policyholders' Income from investments (net)
                             + shareholders' Income from investments
  4. ★ THE CONTROL, mandatory: the SAME filing's standalone page, same column, same legs, must
     reproduce the standalone revenue we ALREADY store for that quarter. It tests page, column,
     scale and every leg at once, against a known answer, per document. No control ⇒ no write.
  5. §44's duplicate trap: a consolidated figure is refused if it came from the page that just
     served as the standalone control.

Anything this refuses is a candidate for the vision rung (§57 r10) — refusing is the correct
outcome, reporting it as absent is not (§0/§57a).

  python3 -X utf8 scripts/agg_tools/insurer_filing_read.py --sym GICRE --scrip 540755 \
      --atts <guid.pdf>,<guid.pdf> --out /tmp/ins_reads.json
"""
import argparse
import json
import os
import re
import sys

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
import fetch_insurers as FI  # noqa: E402

CACHE = os.path.join(os.path.expanduser("~"), ".cache", "insurer_pdfs")
SCALE = {"lakh": 100.0, "lac": 100.0, "crore": 1.0, "million": 10.0, "mn": 10.0}
DATE_RE = re.compile(r"\(?(\d{2})[/.-](\d{2})[/.-](\d{4})\)?")
NUM_RE = re.compile(r"^\(?-?[\d,\s.]{1,20}\)?$")
CTRL_TOL = 0.005  # |std control - stored revS| / stored, i.e. 0.5%


def cached_pdf(o, att):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, att)
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        return p
    d = FI.fetch_pdf(o, att)
    if not d:
        return None
    open(p, "wb").write(d)
    return p


def _num(tok):
    s = tok.replace(",", "").replace(" ", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if not re.match(r"^-?\d+(\.\d+)?$", s):
        return None
    v = float(s)
    return -v if neg else v


def lines_of(page, ytol=3.0):
    """Visual lines of (text, x0, x1) words, grouped by y — rows are geometry too."""
    rows = {}
    for x0, y0, x1, _y1, w, *_ in page.get_text("words"):
        rows.setdefault(round(y0 / ytol), []).append((x0, x1, w))
    out = []
    for k in sorted(rows):
        ws = sorted(rows[k])
        out.append((" ".join(w for _, _, w in ws), ws))
    return out


def columns(lines):
    """-> [(qe_int, xcentre)] from the printed date headers."""
    best = []
    for _text, ws in lines:
        hits = []
        for x0, x1, w in ws:
            m = DATE_RE.fullmatch(w.strip())
            if m:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                hits.append((y * 10000 + mo * 100 + d, (x0 + x1) / 2.0))
        if len(hits) > len(best):
            best = hits
    return best


def row_values(ws, cols, tol=28.0):
    """Assign each numeric token on a row to the nearest date column (x-band)."""
    out = {}
    for x0, x1, w in ws:
        if not NUM_RE.match(w.strip()):
            continue
        v = _num(w)
        if v is None:
            continue
        c = (x0 + x1) / 2.0
        qe, d = min(((q, abs(c - x)) for q, x in cols), key=lambda t: t[1])
        if d <= tol and qe not in out:
            out[qe] = v
    return out


def _legs(lines, cols, sc):
    """Find the three revenue legs on already-grouped lines. -> {qe: revenue} or {}."""
    prem = pol = sh = None
    seen_sh = False
    for text, ws in lines:
        t = text.lower()
        if "shareholder" in t and ("income in" in t or "account" in t):
            seen_sh = True
        if prem is None and re.search(r"premium\s*ea", t):
            prem = row_values(ws, cols)
        elif re.search(r"income\s*from\s*inv", t):
            vals = row_values(ws, cols)
            if not vals:
                continue
            if seen_sh:
                if sh is None:
                    sh = vals
            elif pol is None:
                pol = vals
    if not (prem and pol and sh):
        return {}
    return {qe: round((prem[qe] + pol[qe] + sh[qe]) / sc, 2) for qe in prem if qe in pol and qe in sh}


def read_page(page):
    """-> (basis, scale, {qe: revenue}) or (basis, None, {}) when the legs cannot be found.

    ★ THE LINE-TOLERANCE SWEEP. These scans do not keep a statement row on one visual line: on
    GICRE's Mar-2023 standalone page the figures of "Income from investments (net)" sit on their
    OWN line, ABOVE the label. A single ytol therefore finds the label with no numbers and reports
    "no revenue row" — the §61a mode-2 signature dressed as absence (memory: rows-are-geometry-too).
    So try several groupings; the mandatory standalone control downstream is what decides which
    grouping was right, so widening the hypothesis set is free (the §0 "test every scale before
    declaring a parse refused" argument, applied to rows instead of units).
    """
    head = page.get_text()[:2500].lower()
    basis = None
    if "onsolidat" in head and "tandalon" not in head:
        basis = "con"
    elif "tandalon" in head and "onsolidat" not in head:
        basis = "std"
    if basis is None:
        return None, None, {}
    sc = next((SCALE[k] for k in SCALE if k in head), None)
    if sc is None:
        return basis, sc, {}
    for ytol in (3.0, 5.0, 7.0, 9.0, 12.0):
        lines = lines_of(page, ytol)
        cols = columns(lines)
        if len(cols) < 3:
            continue
        out = _legs(lines, cols, sc)
        if out:
            return basis, sc, out
    return basis, sc, {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", required=True)
    ap.add_argument("--scrip", required=True)
    ap.add_argument("--atts", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))[a.sym]
    stored_s = {int(q): v[0] for q, v in revop.items() if v and v[0] is not None}
    stored_c = {int(q): v[1] for q, v in revop.items() if v and len(v) > 1 and v[1] is not None}

    o = FI.bse_session()
    results, diag = {}, []
    for att in a.atts.split(","):
        p = cached_pdf(o, att)
        if not p:
            diag.append({"att": att, "state": "BLOCKED-TRANSPORT"})
            continue
        doc = fitz.open(p)
        std_pages, con_pages = {}, {}
        for i, page in enumerate(doc):
            basis, _sc, vals = read_page(page)
            if not vals:
                continue
            (std_pages if basis == "std" else con_pages)[i] = vals
        # ---- the control: a standalone page must reproduce stored revS
        ctrl = None
        for i, vals in std_pages.items():
            ok = [
                (q, v, stored_s[q])
                for q, v in vals.items()
                if q in stored_s and abs(v - stored_s[q]) <= max(0.05, stored_s[q] * CTRL_TOL)
            ]
            bad = [(q, v, stored_s[q]) for q, v in vals.items() if q in stored_s and (q, v, stored_s[q]) not in ok]
            if len(ok) >= 1 and not bad:
                ctrl = {"page": i, "matches": ok}
                break
        rec = {"att": att, "std_pages": sorted(std_pages), "con_pages": sorted(con_pages), "control": ctrl}
        if not ctrl:
            rec["state"] = "NO-CONTROL (needs vision)"
            diag.append(rec)
            continue
        for i, vals in con_pages.items():
            if i == ctrl["page"]:
                continue  # §44 duplicate trap
            for qe, v in vals.items():
                if qe in stored_c:
                    continue
                prev = results.get(qe)
                if prev and abs(prev["value"] - v) > 0.05:
                    prev["conflict"] = v
                    continue
                results[qe] = {
                    "value": v,
                    "att": att,
                    "con_page": i,
                    "control_page": ctrl["page"],
                    "control_matches": ctrl["matches"],
                }
        rec["state"] = "OK"
        diag.append(rec)

    json.dump({"sym": a.sym, "reads": results, "diag": diag}, open(a.out, "w"), indent=1, sort_keys=True, default=str)
    print("%s: %d consolidated quarters read with a passing control" % (a.sym, len(results)))
    for qe in sorted(results):
        r = results[qe]
        print(
            "  %d = %10.2f   (con p%d, control p%d on %s)%s"
            % (
                qe,
                r["value"],
                r["con_page"],
                r["control_page"],
                ", ".join("%d=%.2f" % (q, v) for q, v, _ in r["control_matches"][:3]),
                "  ** CONFLICT {}".format(r["conflict"]) if "conflict" in r else "",
            )
        )
    for d in diag:
        if d.get("state") != "OK":
            print("  %-40s %s" % (d["att"][:38], d["state"]))


if __name__ == "__main__":
    main()
