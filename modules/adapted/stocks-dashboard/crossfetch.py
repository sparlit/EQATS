# -*- coding: utf-8 -*-
"""CROSS-FILING fetch: for a gap (sym, qe) we fetch the NEXT-YEAR same-quarter filing (qe+1yr), whose
comparative columns carry qe as the YEAR-AGO quarter. We keep only a PDF that has a CONSOLIDATED profit
page showing BOTH the qe_next date (current col) AND the qe date (year-ago col) -> a real comparative
table. The deep-reader then anchors the year-ago column on stored npStd[qe] (exact) and/or the current
column on stored npCon[qe_next], and reads the consolidated year-ago value. Caches to _vpdf/SYM_QE_xf.pdf
(distinct name, never clobbers the period-filing). Run: python -X utf8 crossfetch.py <listfile.json>
"""
import os, sys, json, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import congap_recover as C
import bse_vision as BV
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf"); os.makedirs(VPDF, exist_ok=True)
LOG = os.path.join(HERE, "_crossfetch_log.json"); HB = os.path.join(HERE, "_crossfetch_hb.txt")
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

def content_ok(pdf, qe, qnext):
    try: doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception: return False
    pq = qe_date_patterns(qe); pn = qe_date_patterns(qnext)
    for p in range(min(len(doc), 50)):
        t = doc[p].get_text(); low = t.lower()
        if "consolidated" not in low: continue
        if not PFT.search(low): continue
        if len(DEC.findall(t)) < 8: continue
        if any(x in low for x in pq) and any(x in low for x in pn):
            return True
    return False

def main():
    targets = json.load(open(sys.argv[1]))
    log = json.load(open(LOG)) if os.path.exists(LOG) else {}
    o = BV.session(); got = 0
    print("crossfetch targets:", len(targets), flush=True)
    for sym, qe in targets:
        key = "%s|%d" % (sym, qe)
        if log.get(key) in ("got", "no-match", "nocode"): continue
        qnext = qe + 10000
        cp = os.path.join(VPDF, "%s_%d_xf.pdf" % (sym, qe))
        if os.path.exists(cp): log[key] = "got"; got += 1; continue
        code = C.scrips.get(sym)
        if not code or sym in C.DEFUNCT: log[key] = "nocode"; continue
        lo, hi = C.window(qnext)
        try: fl = C.datebound(o, code, lo, hi)
        except Exception: fl = []
        best = None
        for a, att in fl[:14]:
            try: pdf = C.fetch(o, att)
            except Exception: pdf = None
            time.sleep(1.2)
            if not pdf: continue
            if content_ok(pdf, qe, qnext): best = pdf; break
        if best:
            open(cp, "wb").write(best); log[key] = "got"; got += 1; print("  GOT", key, flush=True)
        else:
            log[key] = "no-match"; print("  no-match", key, flush=True)
        json.dump(log, open(LOG, "w")); open(HB, "w").write(str(int(time.time())))
    print("CROSSFETCH DONE. got %d cross-filing PDFs." % got, flush=True)

if __name__ == "__main__":
    main()
