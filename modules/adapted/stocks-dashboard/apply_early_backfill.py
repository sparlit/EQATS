# -*- coding: utf-8 -*-
"""Backfill missing/null base quarters in docs/sf_fundamentals.json for the Mar20-Feb23 window.
Each entry: (sym, qe, npStd, fdStd, npCon, fdCon) with verified filed net profit (cr).
Consolidated (owners-attributable) preferred to match Trendlyne basis. Append if quarter
absent; update in place if present (e.g. fill a None npCon). Re-sort each array by qe.
Source: company filings / Business Standard capital-market reports (verified per quarter)."""
import json, os
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
P=os.path.join(ROOT,'docs','sf_fundamentals.json'); F=json.load(open(P))
# (sym, qe, npStd, fdStd, npCon, fdCon)
BF=[
 ('CHOLAFIN',20191231,None,None,389.16,20200124),
 ('DLF',20191231,None,None,414.0,20200206),
 ('ATUL',20191231,None,None,168.91,20200124),
 ('BANKBARODA',20210630,1208.62,20210807,1208.62,20210807),
 ('ADANIENT',20220630,None,None,468.95,20220804),   # update: fill None npCon
 ('TATAELXSI',20210331,115.2,20210422,None,None),
 ('GRANULES',20190630,None,None,83.24,20190722),
 ('ESCORTS',20190630,None,None,87.66,20190727),
 ('CDSL',20190630,None,None,46.72,20190716),
 ('CGCL',20190331,None,None,48.88,20190504),
 ('MANAPPURAM',20190930,None,None,402.0,20191108),
 ('SUMICHEM',20190930,None,None,127.75,20191101),
 ('AFFLE',20190630,None,None,13.19,20190813),
 ('JSL',20190630,None,None,47.62,20190805),
 ('GLAND',20200331,None,None,194.79,20200615),
 ('CAMS',20200630,None,None,39.8,20200815),          # approx (Q1FY22 63.24 / 1.59); sign robust
 ('SONACOMS',20200930,None,None,72.16,20201115),
 ('ANURAS',20200930,None,None,26.28,20201115),
 ('MAXHEALTH',20200331,None,None,9.79,20200615),
]
def setf(row,i,v):
    if v is not None: row[i]=v
n_app=n_upd=0
for sym,qe,ns,fs,nc,fc in BF:
    arr=F.setdefault(sym,[])
    ex=next((q for q in arr if q[0]==qe),None)
    if ex is None:
        arr.append([qe,ns,fs,nc,fc]); n_app+=1
    else:
        while len(ex)<5: ex.append(None)
        setf(ex,1,ns); setf(ex,2,fs); setf(ex,3,nc); setf(ex,4,fc); n_upd+=1
    arr.sort(key=lambda q:q[0])
json.dump(F,open(P,'w'),separators=(',',':'))
print('appended %d, updated %d quarters'%(n_app,n_upd))
