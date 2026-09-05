# -*- coding: utf-8 -*-
"""CROSS-FILING for Q4/MARCH gaps. A March quarter (qe=YYYY0331) is rarely a standalone column in the
next-year MARCH filing (those show consolidated year-ENDED only). Instead we fetch the FOLLOWING JUNE
filing (same year), whose PRECEDING-quarter column = our March quarter. The deep-reader anchors the
CURRENT (June) column on stored npCon[June] and reads the preceding-quarter (March) consolidated column.
Keeps a PDF only if a consolidated profit page shows BOTH the June date and the March date. Caches to
_vpdf/SYM_QE_q4.pdf. Run: python -X utf8 crossfetch_q4.py <listfile.json>
"""
import os, sys, json, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import congap_recover as C
import bse_vision as BV
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf"); os.makedirs(VPDF, exist_ok=True)
LOG = os.path.join(HERE, "_crossfetchq4_log.json"); HB = os.path.join(HERE, "_crossfetchq4_hb.txt")
MONTHS = {1:"january",2:"february",3:"march",4:"april",5:"may",6:"june",7:"july",8:"august",9:"september",10:"october",11:"november",12:"december"}
DEC = re.compile(r'\(?-?[\d,]*\d\.\d\d\)?')
PFT = re.compile(r'profit.{0,6}(after tax|for the (period|quarter|year))|profit after tax|net profit|profit/\(loss\)', re.I)

def qe_date_patterns(qe):
    y, m, d = qe//10000, (qe//100)%100, qe%100
    mn = MONTHS[m]; pats = [
        "%02d/%02d/%d"%(d,m,y), "%02d-%02d-%d"%(d,m,y), "%02d.%02d.%d"%(d,m,y),
        "%s %d, %d"%(mn,d,y), "%d %s %d"%(d,mn,y), "%dth %s %d"%(d,mn,y),
        "%d %s, %d"%(d,mn,y), "%02d %s %d"%(d,mn,y), "%s %d,%d"%(mn,d,y), "%d/%d/%d"%(d,m,y)]
    return [p.lower() for p in pats]

def content_ok(pdf, qe, june):
    try: doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception: return False
    pq = qe_date_patterns(qe); pj = qe_date_patterns(june)
    for p in range(min(len(doc), 50)):
        t = doc[p].get_text(); low = t.lower()
        if "consolidated" not in low: continue
        if not PFT.search(low): continue
        if len(DEC.findall(t)) < 8: continue
        if any(x in low for x in pq) and any(x in low for x in pj):
            return True
    return False

def main():
    targets = json.load(open(sys.argv[1]))
    log = json.load(open(LOG)) if os.path.exists(LOG) else {}
    o = BV.session(); got = 0
    print("crossfetch_q4 targets:", len(targets), flush=True)
    for sym, qe in targets:
        key = "%s|%d" % (sym, qe)
        if log.get(key) in ("got", "no-match", "nocode"): continue
        june = (qe//10000)*10000 + 630
        cp = os.path.join(VPDF, "%s_%d_q4.pdf" % (sym, qe))
        if os.path.exists(cp): log[key] = "got"; got += 1; continue
        code = C.scrips.get(sym)
        if not code or sym in C.DEFUNCT: log[key] = "nocode"; continue
        lo, hi = C.window(june)
        try: fl = C.datebound(o, code, lo, hi)
        except Exception: fl = []
        best = None
        for a, att in fl[:14]:
            try: pdf = C.fetch(o, att)
            except Exception: pdf = None
            time.sleep(1.2)
            if not pdf: continue
            if content_ok(pdf, qe, june): best = pdf; break
        if best:
            open(cp, "wb").write(best); log[key] = "got"; got += 1; print("  GOT", key, flush=True)
        else:
            log[key] = "no-match"; print("  no-match", key, flush=True)
        json.dump(log, open(LOG, "w")); open(HB, "w").write(str(int(time.time())))
    print("CROSSFETCH_Q4 DONE. got %d." % got, flush=True)

if __name__ == "__main__":
    main()
