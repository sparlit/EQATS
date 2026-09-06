# -*- coding: utf-8 -*-
"""Per-month: list MISSES (Trendlyne surv-free not in ours) with failing criterion, and EXTRAS
(ours not in Trendlyne) with our metrics. Uses corrected per-mil intraday hb/lb (engine hl52)."""
import json, gzip, bisect
from datetime import datetime, timedelta
D=json.loads(gzip.decompress(open('docs/sf_stock_data.bin','rb').read()))
data=D['data']; FUND=json.load(open('docs/sf_fundamentals.json'))
IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
SER={s:{'d':o['d'],'c':o['c'],'hb':o.get('hb'),'lb':o.get('lb')} for s,o in data.items()}
mine=json.load(open('scripts/_mine_all.json'))
def di(s):return datetime(s//10000,(s//100)%100,s%100)
def toi(dt):return dt.year*10000+dt.month*100+dt.day
def members(ds):
    dn=int(ds.replace('-',''));b=None
    for s in IDX:
        ed=int(s['effectiveDate'].replace('-',''))
        if ed<=dn and(b is None or ed>b[0]):b=(ed,s['symbols'])
    return set(b[1]) if b else set()
def price(s,dint):
    if s not in SER:return None
    a=SER[s]['d'];i=bisect.bisect_right(a,dint)-1;return SER[s]['c'][i] if i>=0 else None
def hl(s,dint):
    a=SER[s]['d'];i=bisect.bisect_right(a,dint)-1
    if i<0:return None
    lo=toi(di(dint)-timedelta(days=365));hb=SER[s]['hb'];lb=SER[s]['lb'];c=SER[s]['c'];hi=-1e18;low=1e18;k=i
    while k>=0 and a[k]>=lo:
        ph=c[k]*(1000+hb[k])/1000 if hb else c[k]
        pl=c[k]*(1000-lb[k])/1000 if lb else c[k]
        if ph>hi:hi=ph
        if pl<low:low=pl
        k-=1
    return hi,low
def metrics(s,dint):
    if s not in SER or len(SER[s]['d'])<15:return 'no-price-history'
    p=price(s,dint);h=hl(s,dint)
    if p is None or not h:return 'no-price'
    hi,lo=h;d52=(hi-p)/hi*100;d52l=(p-lo)/lo*100
    arr=FUND.get(s);yo=None;bs=None
    if arr:
        for npi,ani in((3,4),(1,2)):
            cur=None
            for q in reversed(arr):
                if len(q)>ani and q[npi] is not None and q[ani] is not None and q[ani]<=dint:cur=q;break
            if not cur:continue
            bq=cur[0]-10000;base=next((q for q in arr if q[0]==bq and len(q)>npi and q[npi] is not None),None)
            if not base or base[npi]==0:continue
            yo=(cur[npi]-base[npi])/abs(base[npi])*100;bs=('con' if npi==3 else 'std');break
    return 'd52=%.1f d52low=%.0f profit=%s%s'%(d52,d52l,('%.0f%%'%yo if yo is not None else 'NOBASE'),'['+bs+']' if bs else '')
def faily(s,dint,M):
    if s not in M:return 'not-member'
    if s not in SER or len(SER[s]['d'])<15:return 'no-price-history'
    p=price(s,dint);h=hl(s,dint)
    if p is None or not h:return 'no-price'
    hi,lo=h;d52=(hi-p)/hi*100;d52l=(p-lo)/lo*100
    arr=FUND.get(s);yo=None
    if arr:
        for npi,ani in((3,4),(1,2)):
            cur=None
            for q in reversed(arr):
                if len(q)>ani and q[npi] is not None and q[ani] is not None and q[ani]<=dint:cur=q;break
            if not cur:continue
            bq=cur[0]-10000;base=next((q for q in arr if q[0]==bq and len(q)>npi and q[npi] is not None),None)
            if not base or base[npi]==0:continue
            yo=(cur[npi]-base[npi])/abs(base[npi])*100;break
    f=[]
    if not(d52<10):f.append('d52=%.1f%%(>10)'%d52)
    if not(d52l>100):f.append('d52low=%.0f%%(<100)'%d52l)
    if yo is None:f.append('no-base')
    elif yo<=0:f.append('profit=%.0f%%(<=0)'%yo)
    return '+'.join(f) if f else '??'
tl={}
for ln in open('scripts/_tl_full.txt'):
    ln=ln.rstrip('\n')
    if '|' in ln: d,s=ln.split('|',1);tl[d]=[x for x in s.split(',') if x]
for d in sorted(mine.keys()):
    dint=int(d.replace('-',''));M=members(d)
    sf=[x for x in tl.get(d,[]) if x in M];ours=set(mine.get(d,[]))
    miss=[x for x in sf if x not in ours];extra=[x for x in ours if x not in tl.get(d,[])]
    if not miss and not extra:continue
    print('=== %s  (TL-SF=%d ours=%d match=%d)'%(d,len(sf),len(ours),len([x for x in sf if x in ours])))
    for m in miss:print('   MISS  %-11s -> %s'%(m,faily(m,dint,M)))
    for e in extra:print('   EXTRA %-11s -> %s'%(e,metrics(e,dint)))
