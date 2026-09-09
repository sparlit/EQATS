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
"""Probe the YEAR-LATER filing for the 15 scanned 2018 cells before spending the vision rung.

WHY THIS COMES FIRST. The diagnostic labels a cell `scanned-results-docs` from the documents in its
own window (qe+8d..qe+160d) — the company's OWN filing for that quarter. But for a pre-2019 con
cell that document is the wrong one to be looking at twice over:

  * §84 — BSE no longer serves pre-Oct-2018 attachments at all, so for Mar/Jun-2018 there is no
    document to render; and
  * §51a — a 2018 annual filing routinely carries CONSOLIDATED ANNUAL ONLY (GAIL's Mar-2019 filing,
    checked page by page under vision: consolidated P&L and consolidated segment report, both
    FY-only, no quarterly consolidated column anywhere).

The document that DOES carry a 2018 quarter's consolidated figure is the **year-later filing**: once
consolidated quarterlies became compulsory from FY2020, the Dec-2019 filing prints Dec-2018 as its
year-ago comparative — and that filing is post-Oct-2018, so it is both fetchable AND text-bearing.
Rendering a scan is the expensive rung; checking a text-bearing document a year later is free.

Reports, per cell: whether a year-later filing exists, whether it has a consolidated P&L page, and
whether that page prints the TARGET quarter's date in its header (§55b column identification).

  python -X utf8 scripts/fill2020_tools/probe_yearlater_2018.py
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

import backfill_revop_gaps as BG  # noqa: E402
import bse_resolve  # noqa: E402
import fetch_insurers as FI  # noqa: E402
import fitz  # noqa: E402

DIAG = os.path.join(HERE, "_diag_rev2018.json")
OUT = os.path.join(HERE, "_yearlater_probe_2018.json")


def scrip_map():
    by = bse_resolve.by_id()
    try:
        for r in json.load(open(os.path.join(SCRIPTS, "_bse_master_all.json"))):
            sid = (r.get("scrip_id") or "").upper()
            if sid and sid not in by and (r.get("Segment") or "Equity") == "Equity":
                by[sid] = r["SCRIP_CD"]
    except Exception:
        pass
    return by


def date_tokens(qe):
    """Every way a filing might print this quarter-end in a column header."""
    d = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
    mon = d.strftime("%b")
    return [
        d.strftime("%d.%m.%Y"),
        d.strftime("%d/%m/%Y"),
        d.strftime("%d-%m-%Y"),
        "%d-%s-%d" % (d.day, mon, d.year),
        "%d %s %d" % (d.day, mon, d.year),
        "%s %d, %d" % (d.strftime("%B"), d.day, d.year),
        "%d-%s-%s" % (d.day, mon, str(d.year)[2:]),
    ]


def main():
    diag = json.load(open(DIAG))
    if "--all-open" in sys.argv:
        # SIZE THE WHOLE RESIDUE, not just the scanned cells. The year-later route closed 15 of 15
        # vision cells; this measures how much of the rest it could reach before anyone spends a pass.
        revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
        tg = json.load(open(os.path.join(HERE, "_rev2018_targets.json")))
        cells = []
        for sym, v in sorted(tg.items()):
            for qe in v.get("revC", []):
                row = (revop.get(sym) or {}).get(str(qe))
                if not row or len(row) < 2 or row[1] is None:
                    cells.append("%s|%d|con" % (sym, qe))
        lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        if lim:
            cells = cells[:lim]
    else:
        cells = [k for k, v in diag.items() if str((v or {}).get("stage", "")).startswith("scanned")]
    by = scrip_map()
    o = FI.bse_session()
    out = {}
    for key in sorted(cells):
        sym, qe, _basis = key.split("|")
        qe = int(qe)
        scrip = by.get(sym)
        rec = {"scrip": scrip}
        if not scrip:
            rec["verdict"] = "no bse scrip"
            out[key] = rec
            print("%-24s no scrip" % key)
            continue
        yl = qe + 10000  # the SAME quarter, one year later
        d = datetime.date(yl // 10000, (yl // 100) % 100, yl % 100)
        lo, hi = d + datetime.timedelta(days=8), d + datetime.timedelta(days=110)
        try:
            fils = FI.datebound(o, str(scrip), lo.strftime("%Y%m%d"), hi.strftime("%Y%m%d")) or []
        except Exception as ex:
            fils = []
            rec["err"] = type(ex).__name__
        toks = date_tokens(qe)
        best = None
        for annd, att, _sub in fils[:6]:
            raw, _ = BG.cached_pdf(o, att)
            if not raw:
                continue
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
            except Exception:
                continue
            for pi in range(min(len(doc), 40)):
                txt = doc[pi].get_text()
                if not BG.PL_PAGE.search(txt) and not re.search(r"interest\s+earned", txt, re.IGNORECASE):
                    continue
                head = txt[:1500]
                is_con = bool(BG.CON_HDR.search(head))
                hits = [t for t in toks if t in txt]
                if is_con and hits:
                    best = {"ann": annd, "att": att, "page": pi, "date_tokens_found": hits[:3], "chars": len(txt)}
                    break
            if best:
                break
        rec["year_later_filings"] = len(fils)
        rec["hit"] = best
        rec["verdict"] = (
            "CONSOLIDATED page printing the target date FOUND in the year-later filing"
            if best
            else "no consolidated page printing the target date"
        )
        out[key] = rec
        print("%-24s ylfilings=%-2d  %s" % (key, len(fils), rec["verdict"]))
    json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
    n = sum(1 for v in out.values() if v.get("hit"))
    print("\n%d of %d scanned cells have a TEXT-BEARING consolidated page a year later" % (n, len(cells)))
    print(f"wrote {os.path.basename(OUT)}")


if __name__ == "__main__":
    main()
