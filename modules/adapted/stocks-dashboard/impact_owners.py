# -*- coding: utf-8 -*-
"""Compare screen results under TOTAL PAT (current) vs OWNERS-ATTRIBUTABLE (proposed) across all
comparison months. Reports every month where the qualifying SET or RANKING changes.
Does NOT modify the live file."""
import json, gzip, bisect, copy, calendar
from datetime import datetime, timedelta
D=json.loads(gzip.decompress(open('docs/sf_stock_data.bin','rb').read()))
data=D['data']
FUND_TOTAL=json.load(open('docs/sf_fundamentals.json'))
OWN=json.load(open('scripts/_reattr_owners.json'))   # 'SYM|qe' -> owners cr (1697 stocks)
IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
SER={s:{'d':o['d'],'c':o['c'],'h':o.get('h'),'l':o.get('l')} for s,o in data.items()}

BACKFILL={"CEMPRO|20250331":113.55,"CEMPRO|20260331":242.17,
          "ACUTAAS|20250331":62.48,"ACUTAAS|20251231":107.96,"ACUTAAS|20260331":131.76}

# build OWNERS variant: npCon -> owners value (comprehensive file + filing backfills)
FUND_OWN=copy.deepcopy(FUND_TOTAL)
n=0
for sym,arr in FUND_OWN.items():
    for r in arr:
        if r[3] is None: continue
        k='%s|%d'%(sym,r[0])
        a=BACKFILL.get(k)
        if a is None: a=OWN.get(k)
        if a is not None and abs(a-r[3])>0.005:
            r[3]=a; n+=1
print('owners-variant: changed %d consolidated quarters'%n)

def di(s):return datetime(s//10000,(s//100)%100,s%100)
def toi(dt):return dt.year*10000+dt.month*100+dt.day
def members(ds):
    dn=int(ds.replace('-',''));b=None
    for s in IDX:
        ed=int(s['effectiveDate'].replace('-',''))
        if ed<=dn and(b is None or ed>b[0]):b=(ed,s['symbols'])
    return set(b[1]) if b else set()
def price(s,dint):
    a=SER[s]['d'];i=bisect.bisect_right(a,dint)-1;return SER[s]['c'][i] if i>=0 else None
def hl(s,dint):
    a=SER[s]['d'];i=bisect.bisect_right(a,dint)-1
    if i<0:return None
    lo=toi(di(dint)-timedelta(days=365));h=SER[s]['h'];l=SER[s]['l'];c=SER[s]['c'];hi=-1e18;low=1e18;k=i
    while k>=0 and a[k]>=lo:
        ph=h[k] if h else c[k];pl=l[k] if l else c[k]
        if ph>hi:hi=ph
        if pl<low:low=pl
        k-=1
    return hi,low
def yoy(FUND,sym,dint):
    arr=FUND.get(sym)
    if not arr:return None
    for npi,ani in((3,4),(1,2)):
        cur=None
        for q in reversed(arr):
            if len(q)>ani and q[npi] is not None and q[ani] is not None and q[ani]<=dint:cur=q;break
        if not cur:continue
        bq=cur[0]-10000;base=next((q for q in arr if q[0]==bq and len(q)>npi and q[npi] is not None),None)
        if not base:continue
        b=base[npi];c=cur[npi]
        if b==0:continue
        return (c-b)/abs(b)*100
    return None
def screen(FUND,ds):
    dint=int(ds.replace('-',''));M=members(ds);rows=[]
    for s in SER:
        if s not in M or not SER[s]['d'] or len(SER[s]['d'])<15:continue
        p=price(s,dint)
        if p is None:continue
        h=hl(s,dint)
        if not h:continue
        hi,low=h
        if hi<=0 or low<=0 or not((hi-p)/hi*100<10 and (p-low)/low*100>100):continue
        y=yoy(FUND,s,dint)
        if y is None or y<=0:continue
        rows.append((s,round(y,1)))
    rows.sort(key=lambda r:-r[1]); return rows

# all comparison month-ends
DATES=[]
for y in range(2020,2027):
    for m in range(1,13):
        if y==2020 and m<3: continue
        if y==2026 and m>6: continue
        DATES.append("%04d-%02d-%02d"%(y,m,calendar.monthrange(y,m)[1]))

set_changes=0; rank_changes=0
for ds in DATES:
    a=screen(FUND_TOTAL,ds); b=screen(FUND_OWN,ds)
    sa=[x[0] for x in a]; sb=[x[0] for x in b]
    setA=set(sa); setB=set(sb)
    added=setB-setA; removed=setA-setB
    if added or removed:
        set_changes+=1
        print('%s  SET CHANGE  +%s  -%s'%(ds, sorted(added) or '-', sorted(removed) or '-'))
    elif sa!=sb:
        rank_changes+=1
        # show first rank difference
        diff=[(i+1,sa[i],sb[i]) for i in range(len(sa)) if sa[i]!=sb[i]][:3]
        print('%s  RANK CHANGE  %s'%(ds, diff))
print('=== SUMMARY: %d months with SET changes, %d months with rank-only changes, of %d months ==='%(set_changes,rank_changes,len(DATES)))
