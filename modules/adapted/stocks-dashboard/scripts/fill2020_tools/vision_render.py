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
"""VISION RUNG (§17b) — render the scanned pages of a cell's filings so they can be READ.

Used for the 15 cells the 2018 campaign's diagnostic put in `scanned-no-text` /
`scanned-results-docs`: a document demonstrably exists and is legible to a human, but has no text
layer (or so few characters per page that no regex reaches it), so every text-based route is out.

Two modes, and the split matters because of the standing rule that FINE IMAGE DETAIL IS A GUESS,
NOT A READ (memory: feedback-image-detail-reads-are-guesses — misread 5+ times):

  --contact  render pages at low DPI to FIND the consolidated statement page. Cheap, and its only
             job is navigation; no number is ever taken from a contact sheet.
  --crop     render ONE page at high DPI, optionally a band of it, so the figures are large enough
             to read without inference. Numbers are only ever taken from these.

  python -X utf8 scripts/fill2020_tools/vision_render.py --cell SYM|QE|con [--contact]
  python -X utf8 scripts/fill2020_tools/vision_render.py --cell SYM|QE|con --page N [--band 0.0,0.6]
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

import backfill_revop_gaps as BG  # noqa: E402
import bse_resolve  # noqa: E402
import fetch_insurers as FI  # noqa: E402
import fitz  # noqa: E402

OUTDIR = os.environ.get("VISION_OUT", "/tmp/vision2018")


def filings_for(sym, qe):
    by = bse_resolve.by_id()
    try:
        for r in json.load(open(os.path.join(SCRIPTS, "_bse_master_all.json"))):
            sid = (r.get("scrip_id") or "").upper()
            if sid and sid not in by and (r.get("Segment") or "Equity") == "Equity":
                by[sid] = r["SCRIP_CD"]
    except Exception:
        pass
    scrip = by.get(sym)
    if not scrip:
        return None, []
    o = FI.bse_session()
    d = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
    lo, hi = d + datetime.timedelta(days=8), d + datetime.timedelta(days=160)
    return o, (FI.datebound(o, str(scrip), lo.strftime("%Y%m%d"), hi.strftime("%Y%m%d")) or [])


def main():
    argv = sys.argv
    cell = argv[argv.index("--cell") + 1]
    sym, qe, _basis = cell.split("|")
    qe = int(qe)
    page_no = int(argv[argv.index("--page") + 1]) if "--page" in argv else None
    doc_i = int(argv[argv.index("--doc") + 1]) if "--doc" in argv else None
    band = argv[argv.index("--band") + 1] if "--band" in argv else None
    os.makedirs(OUTDIR, exist_ok=True)

    o, fils = filings_for(sym, qe)
    if not fils:
        print("no filings listed")
        return
    docs = []
    for i, (annd, att, sub) in enumerate(fils[:10]):
        raw, _ = BG.cached_pdf(o, att)
        if not raw:
            print("  doc %d ann=%s 404 (runbook §84 if pre-Oct-2018)  %s" % (i, annd, sub[:60]))
            continue
        try:
            d = fitz.open(stream=raw, filetype="pdf")
        except Exception:
            print("  doc %d unopenable" % i)
            continue
        chars = sum(len(d[p].get_text()) for p in range(min(len(d), 30)))
        docs.append((i, annd, sub, d))
        print("  doc %d ann=%s pages=%-3d chars=%-7d %s" % (i, annd, len(d), chars, sub[:60]))

    if page_no is None:
        # contact mode: render the first pages of the biggest doc so the statement can be located
        if doc_i is None:
            docs.sort(key=lambda t: -len(t[3]))
        pick = [t for t in docs if doc_i is None or t[0] == doc_i][:1]
        if not pick:
            print("no doc")
            return
        i, annd, sub, d = pick[0]
        for p in range(min(len(d), 14)):
            pm = d[p].get_pixmap(dpi=70)
            fp = os.path.join(OUTDIR, "%s_%d_doc%d_p%02d.png" % (sym, qe, i, p))
            pm.save(fp)
        print("\ncontact sheet -> %s  (doc %d, %d pages at 70dpi)" % (OUTDIR, i, min(len(d), 14)))
        return

    i, annd, sub, d = next(t for t in docs if doc_i is None or t[0] == doc_i)
    pg = d[page_no]
    clip = None
    if band:
        a, b = [float(x) for x in band.split(",")]
        r = pg.rect
        clip = fitz.Rect(r.x0, r.y0 + a * r.height, r.x1, r.y0 + b * r.height)
    pm = pg.get_pixmap(dpi=220, clip=clip)
    fp = os.path.join(
        OUTDIR,
        "%s_%d_doc%d_p%02d_hi%s.png" % (sym, qe, i, page_no, ("_{}".format(band.replace(",", "-"))) if band else ""),
    )
    pm.save(fp)
    print("wrote %s  (%dx%d)" % (fp, pm.width, pm.height))


if __name__ == "__main__":
    main()
