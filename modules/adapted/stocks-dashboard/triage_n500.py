# -*- coding: utf-8 -*-
"""Triage fetched N500 quarterly PDFs using WORD-COORDINATE row grouping (NSE PDFs put labels and
their column numbers in separate text blocks, so line-based parsing fails). For each (SYM,qe):
detect standalone/consolidated results pages, extract profit-row number arrays (current-quarter col
is typically nums[0]). Anchor: standalone profit-row nums[0] should == stored_std. Outputs
_triage_n500_out.json. Run: python -X utf8 triage_n500.py
"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fitz
HERE = os.path.dirname(os.path.abspath(__file__)); VPDF = os.path.join(HERE, "_vpdf")
FUND = os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")

PROF = re.compile(r'(profit|loss)\b.{0,45}(for the (period|quarter|year)|after tax|attributable|before tax)|net profit|profit/\(loss\)', re.I)
NUMW = re.compile(r'^\(?-?[\d,]+\.\d\d\)?$')

def tonum(t):
    t = t.strip()
    if not NUMW.match(t): return None
    neg = "(" in t; v = float(t.replace("(", "").replace(")", "").replace(",", ""))
    return -v if neg else v

def rows_of(page):
    words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,wno)
    if not words: return []
    items = sorted(words, key=lambda w: (round(w[1] / 3.0), w[0]))
    rows = []; cur = []; ly = None
    for w in items:
        yc = (w[1] + w[3]) / 2
        if ly is None or abs(yc - ly) < 5: cur.append(w)
        else: rows.append(cur); cur = [w]
        ly = yc
    if cur: rows.append(cur)
    return [sorted(r, key=lambda w: w[0]) for r in rows]

def main():
    fund = json.load(open(FUND))
    pairs = json.load(open(os.path.join(HERE, "_n500fetch2.json")))
    out = []
    for sym, qe in pairs:
        rec = {"sym": sym, "qe": qe}
        rows_f = fund.get(sym, [])
        srow = next((r for r in rows_f if r[0] == qe), None)
        rec["stored_std"] = srow[1] if srow else None
        rec["stored_con"] = srow[3] if srow else None
        p = os.path.join(VPDF, "%s_%d_nse.pdf" % (sym, qe))
        if not os.path.exists(p):
            rec["status"] = "nopdf"; out.append(rec); continue
        try: doc = fitz.open(p)
        except Exception as e:
            rec["status"] = "badpdf"; rec["err"] = str(e); out.append(rec); continue
        total_text = 0; con_pages = []; std_pages = []; unk_pages = []
        for pi in range(len(doc)):
            pg = doc[pi]; txt = pg.get_text(); total_text += len(txt); low = txt.lower()
            if "profit" not in low: continue
            if not any(k in low for k in ["quarter ended", "period ended", "year ended", "months ended", "particulars"]):
                continue
            H = pg.rect.height
            rws = rows_of(pg)
            # title detection from top 20% of page
            title = " ".join(w[4] for r in rws for w in r if w[1] < H * 0.20).lower()
            plines = []
            for r in rws:
                rtext = " ".join(w[4] for w in r)
                if not PROF.search(rtext): continue
                ns = [tonum(w[4]) for w in r]; ns = [x for x in ns if x is not None]
                if ns: plines.append([rtext.strip()[:62], ns])
            if not plines: continue
            iscon = "consolidated" in title
            isstd = "standalone" in title or ("unaudited" in title and "consolidated" not in title)
            entry = {"pg": pi, "lines": plines}
            if iscon: con_pages.append(entry)
            elif isstd: std_pages.append(entry)
            else: unk_pages.append(entry)
        rec["npages"] = len(doc); rec["text_chars"] = total_text
        rec["scanned"] = total_text < 400
        rec["con"] = con_pages[:2]; rec["std"] = std_pages[:2]; rec["unk"] = unk_pages[:2]
        rec["has_con"] = bool(con_pages)
        rec["status"] = "ok"
        out.append(rec); doc.close()
    json.dump(out, open(os.path.join(HERE, "_triage_n500_out.json"), "w"), indent=1)
    bycomp = {}
    for r in out: bycomp.setdefault(r["sym"], []).append(r)
    for sym in sorted(bycomp):
        rs = bycomp[sym]
        print("%-12s con=%d/4 std=%d unk=%d scan=%d miss=%d" % (
            sym, sum(1 for r in rs if r.get("has_con")),
            sum(1 for r in rs if r.get("std")), sum(1 for r in rs if r.get("unk") and not r.get("has_con")),
            sum(1 for r in rs if r.get("scanned")), sum(1 for r in rs if r.get("status") != "ok")), flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
