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
"""Re-fetch the RESULTS attachment for a cell, by subject, and keep every candidate.

WHY. `_bse_comparative_rev.py` walks the announcement window in date order and takes the first
few attachments. In practice the first filing in the window is very often NOT the results:
  * RAIN 2014-08-14  — a board-outcome cover letter that says "the results are being sent separately"
  * LTF  2019-09-30  — an OCTOBER 2020 letter about subsidiary board meetings
  * STYRENIX 2016-03 — a director-appointment intimation
  * THERMAX 2015-06  — a Reg-30 stake-acquisition intimation
Each of those went into the vision queue as "the filing", and one was auto-parsed into a wrong
number. The real P&L is a sibling attachment in the same window.

WHAT THIS DOES. For each (sym, qe): resolve the BSE scrip, take the stored announce date, list
the window (+-21 calendar days, real date arithmetic — see _shift in the sibling tool for why),
and download EVERY attachment whose subject looks like results. Records per candidate: pages,
whether a text layer exists, and whether any page names a standalone statement. A text-bearing
standalone page can then be read positionally, which is both cheaper and more reliable than a
vision read (measured 2026-08-24: five for five, positional reads refuted the auto-parser).

One BSE session PER SYMBOL — a shared jar gets throttled into empty lists (§57c).

Run: python -X utf8 scripts/_bse_results_refetch.py --cells <json>   # [[SYM, QE], ...]
"""
import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import fetch_insurers as FI
import fitz

OUTDIR = os.path.join(HERE, "_bse_refetch_pdfs")
os.makedirs(OUTDIR, exist_ok=True)
MANIFEST = os.path.join(HERE, "_bse_refetch_manifest.json")

R_RESULT = re.compile(r"result|financial|outcome", re.IGNORECASE)
R_NOT = re.compile(
    r"newspaper|advertis|investor (present|meet)|analyst|transcript|schedule of|"
    r"trading window|material subsidiar|appointment|resignation|allotment|"
    r"annual report|agm|postal ballot|credit rating|acquisition",
    re.IGNORECASE,
)


def shift(yyyymmdd, days):
    d = str(yyyymmdd)
    return (datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8])) + datetime.timedelta(days=days)).strftime("%Y%m%d")


def main():
    argv = sys.argv
    cells = json.load(open(argv[argv.index("--cells") + 1]))
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}
    scrips = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
    ex = os.path.join(HERE, "_bse_scrips_extra.json")
    if os.path.exists(ex):
        for k, v in json.load(open(ex)).items():
            scrips.setdefault(k, v)
    man = json.load(open(MANIFEST)) if os.path.exists(MANIFEST) else {}
    for sym, qe in cells:
        qe = int(qe)
        key = "%s|%d" % (sym, qe)
        if key in man:
            continue
        code = scrips.get(sym)
        frow = fmap.get(sym, {}).get(qe)
        if not code or not frow or not frow[2]:
            man[key] = {"error": "no scrip or no announce date"}
            continue
        ann = frow[2]
        o = FI.bse_session()
        time.sleep(2.0)
        try:
            rows = FI.datebound(o, str(code), shift(ann, -21), shift(ann, 21))
        except Exception as e:
            man[key] = {"error": f"datebound {type(e).__name__}"}
            continue
        cands = []
        for dt, att, sub in rows:
            if not R_RESULT.search(sub) or R_NOT.search(sub):
                continue
            p = os.path.join(OUTDIR, "%s_%d_%s" % (sym, qe, att.replace("/", "_")))
            if not os.path.exists(p):
                try:
                    d = FI.fetch_pdf(o, att)
                except Exception:
                    d = None
                if not d:
                    continue
                open(p, "wb").write(d)
                time.sleep(0.4)
            try:
                doc = fitz.open(p)
            except Exception:
                continue
            npg = len(doc)
            textpages, stdpages = [], []
            for i in range(npg):
                t = doc[i].get_text()
                if len(t.strip()) > 200:
                    textpages.append(i)
                    if re.search(r"standalone|unconsolidated", t, re.IGNORECASE):
                        stdpages.append(i)
            doc.close()
            cands.append(
                {
                    "date": dt,
                    "subject": sub[:70],
                    "pdf": p,
                    "pages": npg,
                    "text_pages": textpages[:8],
                    "standalone_text_pages": stdpages[:8],
                }
            )
        man[key] = {"ann": ann, "scrip": code, "candidates": cands}
        best = [c for c in cands if c["standalone_text_pages"]]
        print(
            "%-22s ann=%s | %d result-like filings | %d with a STANDALONE TEXT page"
            % (key, ann, len(cands), len(best)),
            flush=True,
        )
        for c in cands:
            print(
                "      %s %2dpg text%s std%s  %s"
                % (c["date"], c["pages"], c["text_pages"][:3], c["standalone_text_pages"][:3], c["subject"][:52]),
                flush=True,
            )
        json.dump(man, open(MANIFEST, "w"), indent=1, sort_keys=True)
    n_std = sum(1 for v in man.values() if any(c.get("standalone_text_pages") for c in v.get("candidates", [])))
    print("DONE: %d cells, %d now have a standalone TEXT page" % (len(man), n_std), flush=True)


if __name__ == "__main__":
    main()
