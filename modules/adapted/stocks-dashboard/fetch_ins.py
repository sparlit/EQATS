# -*- coding: utf-8 -*-
"""INSURER-aware fetch: insurers file IRDAI-format results (Policyholders' Revenue A/c + Shareholders'
Profit & Loss A/c) with 'Premium earned' / 'Income from investments' instead of 'Revenue from
operations' -- so fetch_con.py's REV gate rejected them. This fetches the BSE result attachment for each
insurer gap-quarter and keeps the one that has a CONSOLIDATED insurer P&L (consolidated + a profit-after-
tax/profit-for-period row + premium/policyholders/shareholders). Caches to _vpdf/SYM_QE.pdf. Does NOT
touch _vp2_read. Run: python -X utf8 fetch_ins.py
"""
import os, sys, json, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import congap_recover as C
import bse_vision as BV
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf"); os.makedirs(VPDF, exist_ok=True)
d = json.load(open(os.path.join(HERE, "..", "docs", "sf_fundamentals.json")))
tgt = json.load(open(os.path.join(HERE, "_congap_targets.json")))
LOG = os.path.join(HERE, "_fetchins_log.json")
HB = os.path.join(HERE, "_fetchins_hb.txt")
INS = {"LICI","SBILIFE","HDFCLIFE","ICICIPRULI","ICICIGI","GICRE","NIACL","STARHEALTH","MFSL"}
PAT = re.compile(r'profit\s*/?\s*\(?\s*(loss\)?\s*)?(after tax|for the (period|quarter|year))|profit after tax|net profit', re.I)
INSWORD = re.compile(r'(premium|policyholder|shareholder|income from investment)', re.I)
DEC = re.compile(r'\d[\d,]*\.\d\d')

def con(s, qe):
    for r in d.get(s, []):
        if r[0] == qe: return r[3]
    return None

def has_con_ins_pl(pdf):
    """True if some page is a CONSOLIDATED insurer P&L: 'consolidated' + a PAT row + insurer terms +
    a dense numeric table."""
    try: doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception: return False
    for p in range(min(len(doc), 60)):
        t = doc[p].get_text(); low = t.lower()
        if "consolidated" not in low: continue
        if not PAT.search(t): continue
        if not INSWORD.search(t): continue
        if len(DEC.findall(t)) < 8: continue
        return True
    return False

def main():
    log = json.load(open(LOG)) if os.path.exists(LOG) else {}
    work = []
    for s, qs in tgt.items():
        if s not in INS: continue
        for q in qs:
            if con(s, q) is not None: continue
            if os.path.exists(os.path.join(VPDF, "%s_%d.pdf" % (s, q))): continue   # already have one
            work.append((s, q))
    o = BV.session(); got = 0
    print("INSURER fetch targets (nopdf):", len(work), flush=True)
    for s, q in work:
        key = "%s|%d" % (s, q)
        if log.get(key) in ("got", "no-con"): continue
        code = C.scrips.get(s)
        if not code or s in C.DEFUNCT:
            log[key] = "nocode"; continue
        lo, hi = C.window(q)
        try: fl = [(a, att) for a, att in C.datebound(o, code, lo, hi) if C.qe_from_ann(a) == q]
        except Exception: fl = []
        best = None
        for a, att in fl[:6]:
            try: pdf = C.fetch(o, att)
            except Exception: pdf = None
            time.sleep(1.5)
            if not pdf: continue
            if has_con_ins_pl(pdf): best = pdf; break
        if best:
            open(os.path.join(VPDF, "%s_%d.pdf" % (s, q)), "wb").write(best)
            log[key] = "got"; got += 1; print("  GOT", key, flush=True)
        else:
            log[key] = "no-con"
        json.dump(log, open(LOG, "w")); open(HB, "w").write(str(int(time.time())))
    print("INSURER FETCH DONE. fetched %d consolidated insurer PDFs." % got, flush=True)

if __name__ == "__main__":
    main()
