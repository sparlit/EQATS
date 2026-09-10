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
"""Turn a gate-passed screener TARGET into the EXACT filing figure (runbook §57 rung 3b, step 2).

screener.in prints crore-rounded integers. We store filing precision. So screener is never the
final authority -- it is the SEARCH KEY. Knowing the answer is "about 2752" makes the PDF read
trivial and, crucially, ELIMINATES THE COLUMN-INDEX GUESS that produced the BALKRISIND/SWANCORP
near-misses: we do not pick column 0 or column i, we pick the cell in a revenue-labelled row whose
value (at some declared scale) lands within +-1.0 of the target. That cell IS the quarter.

Falls back to the rounded screener value, journalled with precision="crore-rounded", rather than
leaving the cell empty -- user directive 2026-08-06: a sourced approximate beats a hole, as long as
the provenance says so out loud.

  python -X utf8 scripts/fill2020_tools/refine_from_filing.py /tmp/screener_gate.json
"""
import datetime
import importlib.util
import json
import os
import re
import sys
import time

WT = os.path.expanduser("~/stocks-wt/fill2020")
sys.path.insert(0, os.path.join(WT, "scripts"))
os.chdir(WT)
import fetch_insurers as FI  # noqa: E402
import fitz  # noqa: E402

_s = importlib.util.spec_from_file_location("brg", os.path.join(WT, "scripts", "backfill_revop_gaps.py"))
BRG = importlib.util.module_from_spec(_s)
_s.loader.exec_module(BRG)

# corruption-tolerant (glyph swaps a->o, t->l seen in BSE PDFs, runbook §51)
REV_ROW = re.compile(
    r"(t[o0]tal\s+inc[o0]me\s+fr[o0]m\s+[o0]pera|revenue\s+fr[o0]m\s+[o0]pera|"
    r"inc[o0]me\s+fr[o0]m\s+[o0]pera|net\s+sales|t[o0]tal\s+revenue|"
    r"t[o0]tal\s+inc[o0]me)",
    re.IGNORECASE,
)
NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")


def nums_after(lines, n, k=14):
    out = []
    for x in lines[n + 1 : n + 1 + k]:
        x = x.strip()
        if NUM.match(x):
            neg = x.startswith("(")
            try:
                v = float(x.strip("()").replace(",", ""))
            except ValueError:
                continue
            out.append(-v if neg else v)
        elif out:
            break
    return out


def hunt(doc, target):
    """Find the exact figure in a revenue-labelled row that matches `target` at some scale."""
    best = None
    for pi in range(len(doc)):
        lines = [x.strip() for x in doc[pi].get_text().split("\n")]
        for n, x in enumerate(lines):
            if not REV_ROW.search(x):
                continue
            for v in nums_after(lines, n):
                for sc, un in ((1.0, "crore"), (10.0, "million"), (100.0, "lakh")):
                    got = v / sc
                    if abs(got - target) <= max(1.0, abs(target) * 0.004):
                        cand = (abs(got - target), round(got, 2), "p%d %s /%s row=%r raw=%s" % (pi, un, un, x[:38], v))
                        if best is None or cand[0] < best[0]:
                            best = cand
    return best


def main():
    gate = json.load(open(sys.argv[1]))
    tg = json.load(open("/tmp/mar25.json"))
    out = {}
    for key, g in sorted(gate.items()):
        sym, _qe, field = key.split("|")
        meta = tg.get(sym) or {}
        target = g["val"]
        rec = {"field": field, "screener": target, "src": "screener.in gate-validated", "gate": g["note"]}
        if not meta.get("scrip"):
            rec.update(value=target, precision="crore-rounded", exact=False)
            out[key] = rec
            print("  %-11s %-5s = %-9s crore-rounded (no scrip for filing refine)" % (sym, field, target))
            continue
        sess = FI.bse_session()
        d0 = datetime.datetime.strptime(str(meta["ann"]), "%Y%m%d").date()
        fils = (
            FI.datebound(
                sess,
                str(meta["scrip"]),
                (d0 - datetime.timedelta(days=8)).strftime("%Y%m%d"),
                (d0 + datetime.timedelta(days=8)).strftime("%Y%m%d"),
            )
            or []
        )
        hit = None
        for _annd, att, _sub in fils[:5]:
            raw, _ = BRG.cached_pdf(sess, att)
            if not raw:
                continue
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
            except Exception:
                continue
            hit = hunt(doc, target)
            doc.close()
            if hit:
                break
        if hit:
            rec.update(
                value=hit[1],
                precision="filing-exact",
                exact=True,
                src="bse-filing-pdf (located via screener target)",
                where=hit[2],
            )
            print("  %-11s %-5s = %-9s EXACT  %s" % (sym, field, hit[1], hit[2]))
        else:
            rec.update(value=target, precision="crore-rounded", exact=False)
            print("  %-11s %-5s = %-9s crore-rounded (target not located in PDF)" % (sym, field, target))
        out[key] = rec
        time.sleep(0.5)
    json.dump(out, open("/tmp/mar25_final.json", "w"), indent=1)
    print("\nresolved %d cells (%d filing-exact)" % (len(out), sum(1 for v in out.values() if v.get("exact"))))


if __name__ == "__main__":
    main()
