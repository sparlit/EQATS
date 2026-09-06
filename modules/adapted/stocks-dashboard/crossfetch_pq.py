# -*- coding: utf-8 -*-
"""CROSS-FILING preceding-quarter route (general). For a gap qe, fetch the NEXT-quarter filing (qe+1Q);
its PRECEDING-quarter column = qe. Keep a PDF only if a consolidated profit page shows BOTH the next-q
date (current) and the qe date (preceding). Anchor at read time on stored npCon[next_q]. This is a SECOND
route for quarters that no-matched the year-ago route (crossfetch.py). Caches _vpdf/SYM_QE_pq.pdf.
Run: python -X utf8 crossfetch_pq.py <listfile.json>
"""
import os, sys, json, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import congap_recover as C
import bse_vision as BV
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf"); os.makedirs(VPDF, exist_ok=True)
LOG = os.path.join(HERE, "_crossfetchpq_log.json"); HB = os.path.join(HERE, "_crossfetchpq_hb.txt")
MONTHS = {1:"january",2:"february",3:"march",4:"april",5:"may",6:"june",7:"july",8:"august",9:"september",10:"october",11:"november",12:"december"}
DEC = re.compile(r'\(?-?[\d,]*\d\.\d\d\)?')
PFT = re.compile(r'profit.{0,6}(after tax|for the (period|quarter|year))|profit after tax|net profit|profit/\(loss\)', re.I)

def nextq(q):
    y, md = q//10000, q%10000
    return {331:y*10000+630, 630:y*10000+930, 930:y*10000+1231, 1231:(y+1)*10000+331}[md]

def qe_date_patterns(qe):
    y, m, d = qe//10000, (qe//100)%100, qe%100
    mn = MONTHS[m]; pats = [
        "%02d/%02d/%d"%(d,m,y), "%02d-%02d-%d"%(d,m,y), "%02d.%02d.%d"%(d,m,y),
        "%s %d, %d"%(mn,d,y), "%d %s %d"%(d,mn,y), "%dth %s %d"%(d,mn,y),
        "%d %s, %d"%(d,mn,y), "%02d %s %d"%(d,mn,y), "%s %d,%d"%(mn,d,y), "%d/%d/%d"%(d,m,y)]
    return [p.lower() for p in pats]

def content_ok(pdf, qe, nq):
    try: doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception: return False
    pq = qe_date_patterns(qe); pn = qe_date_patterns(nq)
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
    print("crossfetch_pq targets:", len(targets), flush=True)
    for sym, qe in targets:
        key = "%s|%d" % (sym, qe)
        if log.get(key) in ("got", "no-match", "nocode"): continue
        nq = nextq(qe)
        cp = os.path.join(VPDF, "%s_%d_pq.pdf" % (sym, qe))
        if os.path.exists(cp): log[key] = "got"; got += 1; continue
        code = C.scrips.get(sym)
        if not code or sym in C.DEFUNCT: log[key] = "nocode"; continue
        lo, hi = C.window(nq)
        try: fl = C.datebound(o, code, lo, hi)
        except Exception: fl = []
        best = None
        for a, att in fl[:14]:
            try: pdf = C.fetch(o, att)
            except Exception: pdf = None
            time.sleep(1.2)
            if not pdf: continue
            if content_ok(pdf, qe, nq): best = pdf; break
        if best:
            open(cp, "wb").write(best); log[key] = "got"; got += 1; print("  GOT", key, flush=True)
        else:
            log[key] = "no-match"; print("  no-match", key, flush=True)
        json.dump(log, open(LOG, "w")); open(HB, "w").write(str(int(time.time())))
    print("CROSSFETCH_PQ DONE. got %d." % got, flush=True)

if __name__ == "__main__":
    main()
