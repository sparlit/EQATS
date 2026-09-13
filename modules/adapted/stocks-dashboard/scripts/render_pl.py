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
"""Render the consolidated-P&L page(s) of a company's BSE-filed result to PNG for a vision read.
For scanned filings where the text layer has no attribution block. Locates the page by OCR/text
keyword scan (consolidated + owners/non-controlling), renders at high DPI, prints stored value + paths.

Usage: python3 scripts/render_pl.py OUTDIR SYM|QE [SYM|QE ...]
"""
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_insurers as FI
import fitz
from owners_total_verify import classify, label_of, line_groups, row_numbers

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOOSE = "--loose" in sys.argv
scrips = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))

CON = re.compile(r"consolidat", re.IGNORECASE)
ATTR = re.compile(r"attributable|non[- ·]?controlling|minorit|owners of|equity ?holder", re.IGNORECASE)
PROFIT = re.compile(r"profit.{0,25}(period|year|after tax)|total comprehensive", re.IGNORECASE)
DEC = re.compile(r"\(?\d[\d,]*\.\d\d")


def page_score(txt, loose=False):
    """A P&L attribution page carries the attribution keywords AND is a DENSE numeric table.
    The auditor-note page has the same words but in prose (few numbers) — numeric density separates
    them. Returns (has_attr_and_profit, decimal_number_count)."""
    if not ATTR.search(txt):
        # loose fallback: a dense P&L page without the exact keyword (scan may drop 'attributable')
        if loose and PROFIT.search(txt):
            dens = len(DEC.findall(txt))
            return (1, dens) if dens >= 20 else (0, 0)
        return (0, 0)
    dens = len(DEC.findall(txt))
    thr = 6 if loose else 8
    key = 2 if (PROFIT.search(txt) and dens >= (8 if loose else 12)) else (1 if dens >= thr else 0)
    return (key, dens)


def storedcon(s, q):
    return next((r[3] for r in fund.get(s, []) if r[0] == q), None)


def find_and_render(o, sym, qe, outdir, dpi=230):
    code = scrips.get(sym)
    stored = storedcon(sym, qe)
    if not code:
        return {"sym": sym, "qe": qe, "err": "no-scripcode"}
    qd = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
    lo = (qd + datetime.timedelta(days=1)).strftime("%Y%m%d")
    hi = (qd + datetime.timedelta(days=210)).strftime("%Y%m%d")
    filings = FI.datebound(o, code, lo, hi)
    cand = sorted([(a, att, sub) for a, att, sub in filings if FI.qe_from_ann(a) == qe])
    if not cand:
        return {"sym": sym, "qe": qe, "stored": stored, "err": "no-filing"}
    for annd, att, _sub in cand[:4]:
        pdf = FI.fetch_pdf(o, att)
        time.sleep(0.6)
        if not pdf:
            continue
        try:
            doc = fitz.open(stream=pdf, filetype="pdf")
        except Exception:
            continue
        N = min(len(doc), 45)
        pages_score = []
        con_state = False
        for p in range(N):
            t = doc[p].get_text()
            txt = t if t.strip() else " ".join(w[4] for w in FI._ocr_words(doc[p]))
            if CON.search(txt):
                con_state = True
            key, dens = page_score(txt, loose=LOOSE)
            if key:
                conbonus = 1 if ("consolidat" in txt.lower() or con_state) else 0
                pages_score.append(((key + conbonus, dens), p))
        pages_score.sort(reverse=True)
        rendered = []
        for score, p in pages_score[: (4 if LOOSE else 2)]:
            pix = doc[p].get_pixmap(dpi=dpi)
            fn = os.path.join(outdir, f"{sym}_{qe}_p{p}.png")
            pix.save(fn)
            rendered.append((p, score, fn))
        if rendered:
            return {"sym": sym, "qe": qe, "stored": stored, "ann": annd, "att": att, "pages": rendered}
    return {"sym": sym, "qe": qe, "stored": stored, "err": "no-attribution-page"}


def main():
    outdir = sys.argv[1]
    os.makedirs(outdir, exist_ok=True)
    cells = []
    for a in sys.argv[2:]:
        if a.startswith("--") or "|" not in a:
            continue
        parts = a.split("|")
        cells.append((parts[0], int(parts[1])))
    o = FI.bse_session()
    time.sleep(0.5)
    for sym, qe in cells:
        r = find_and_render(o, sym, qe, outdir)
        if r.get("pages"):
            print(f"{sym} {qe}  stored={r['stored']}  ann={r['ann']}")
            for p, sc, fn in r["pages"]:
                print(f"    page {p} (score {sc}): {fn}")
        else:
            print(f"{sym} {qe}  stored={r.get('stored')}  -> {r.get('err')}")


if __name__ == "__main__":
    main()
