# -*- coding: utf-8 -*-
"""
PROOF OF CONCEPT: extract quarterly net profit for insurers (absent from NSE) from
BSE's scanned-image result PDFs via OCR. Validates feasibility/accuracy before any
scale-up. Saves each matched P&L page as _ocr_<sym>.png for human/visual validation.

Pipeline per symbol:
  FinancialResult/w (newest quarter zip) -> standalone PDF -> render page (PyMuPDF)
  -> OCR (RapidOCR) -> spatial row-group the "net profit after tax" line -> first
  numeric column = current quarter -> apply Lakh/Crore unit.

WARNING - the FinancialResult route this POC is built on is ENTITY-POISONED. The endpoint has been
observed to IGNORE scripcode entirely and serve BSE Limited's OWN results to every caller (measured
2026-08-18: byte-identical payload for 532885/500325/500002/532525/540777, and asking for HDFCLIFE
540777 returns a zip holding "BSE SA FR Jun'2026_Signed.pdf"). This POC has no identity guard of its
own, and its `\bsa\b` pick matches that very file - so unguarded it would print BSE Ltd's net profit
under an insurer's name. The quarter list therefore now goes through bse_fetch.quarters(), which
probes the endpoint and REFUSES rather than return another company's filings. Production reads use
the announcement-attachment route instead (fetch_insurers.py / fetch_bse_fund.py).
"""
import urllib.request, json, gzip, io, zipfile, re, sys, os, fitz
from rapidocr_onnxruntime import RapidOCR
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_fetch as B          # for quarters(): the ONE guarded reader of FinancialResult

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
OCR = RapidOCR()

# (symbol, BSE scripcode) — major insurers, all missing from our NSE-sourced data
INSURERS = [
    ("HDFCLIFE", 540777), ("SBILIFE", 540719), ("ICICIPRULI", 540133),
    ("ICICIGI", 540716), ("LICI", 543526), ("GICRE", 540755),
    ("NIACL", 540769), ("STARHEALTH", 543412), ("GODIGIT", 543940),
]

def get(url, b=False):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*',
          'Referer': 'https://www.bseindia.com/', 'Origin': 'https://www.bseindia.com'})
    r = urllib.request.urlopen(req, timeout=45); raw = r.read()
    if r.headers.get('Content-Encoding') == 'gzip': raw = gzip.decompress(raw)
    return raw if b else raw.decode('utf-8', 'replace')

def num(s):
    s = s.strip().replace(' ', '')
    if not re.fullmatch(r'\(?-?[\d,]+(?:\.\d+)?\)?', s): return None
    v = float(s.strip('()').replace(',', ''))
    return -v if s.startswith('(') else v

# label patterns in priority order (PAT = profit AFTER tax / for the period)
PAT = [r'net profit after tax', r'profit\s*/?\s*\(?loss\)?\s*after tax',
       r'\bprofit after tax\b', r'profit for the (?:period|quarter)', r'net profit\s*/?\s*\(?loss\)?']

_OP = []
def _session():
    if not _OP: _OP.append(B.session())
    return _OP[0]

def extract(sym, code):
    # GUARDED: B.quarters() raises if the endpoint is ignoring scripcode. Never inline the raw
    # FinancialResult call again - that is what made this POC able to read the wrong company.
    qs = B.quarters(_session(), code)
    if not qs: return (sym, code, '?', None, 'no zip link', None)
    qe, link = qs[0]
    qlabel = str(qe)
    z = zipfile.ZipFile(io.BytesIO(get('https://www.bseindia.com' + link, b=True)))
    pdfs = [n for n in z.namelist() if n.lower().endswith('.pdf') and 'present' not in n.lower()]
    pick = (next((n for n in pdfs if re.search(r'standalone|\bsa\b', n, re.I)), None)
            or next((n for n in pdfs if 'financ' in n.lower() or 'result' in n.lower()), None)
            or (pdfs[0] if pdfs else None))
    if not pick: return (sym, code, qlabel, None, 'no pdf', None)
    doc = fitz.open(stream=z.read(pick), filetype='pdf')
    for pi in range(len(doc)):
        pix = doc[pi].get_pixmap(dpi=200); png = pix.tobytes('png')
        res, _ = OCR(png)
        if not res: continue
        boxes = [{'t': t, 'x': sum(p[0] for p in b) / 4, 'y': sum(p[1] for p in b) / 4} for b, t, sc in res]
        unit = 0.01 if any(re.search(r'in lakh', bx['t'], re.I) for bx in boxes) else \
               (1.0 if any(re.search(r'in crore', bx['t'], re.I) for bx in boxes) else None)
        lbl = None
        for pat in PAT:
            cand = [bx for bx in boxes if re.search(pat, bx['t'], re.I) and not re.search(r'before tax|comprehensive|exceptional', bx['t'], re.I)]
            if cand: lbl = cand[0]; break
        if not lbl: continue
        row = [bx for bx in boxes if abs(bx['y'] - lbl['y']) < 12 and bx['x'] > lbl['x'] + 5]
        nums = [num(bx['t']) for bx in sorted(row, key=lambda b: b['x'])]
        nums = [n for n in nums if n is not None]
        open('_ocr_%s.png' % sym, 'wb').write(png)
        cr = (nums[0] * unit) if (nums and unit) else None
        return (sym, code, qlabel, cr, lbl['t'][:42], ('Lakh' if unit == 0.01 else 'Crore' if unit == 1 else '?'))
    return (sym, code, qlabel, None, 'no PAT label found', None)

def main():
    syms = [s for s in INSURERS if not sys.argv[1:] or s[0] in sys.argv[1:]]
    print('%-12s %-8s %-10s %-14s %-6s %s' % ('SYMBOL', 'SCRIP', 'FY', 'NETPROFIT(cr)', 'UNIT', 'MATCHED LABEL'))
    for sym, code in syms:
        try:
            s, c, q, cr, lbl, unit = extract(sym, code)
            print('%-12s %-8d %-10s %-14s %-6s %s' % (sym, code, q, ('%.2f' % cr) if cr is not None else 'FAIL', unit or '-', lbl))
        except RuntimeError as e:
            # endpoint-level refusal (see B.quarters) - applies to every symbol, so stop here
            # rather than print the same failure nine times.
            print('\nABORTED - %s' % e); return 1
        except Exception as e:
            print('%-12s %-8d ERROR %s' % (sym, code, str(e)[:50]))

if __name__ == "__main__":
    sys.exit(main() or 0)
