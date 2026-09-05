# -*- coding: utf-8 -*-
"""NEW filter backtest: distance-from-52w-high <= 10, sorted by d52 ASCENDING (closest to high first).
No d52low / profit conditions. Nifty500 point-in-time membership. Monthly rebalance Mar2020 -> latest.
Intraday hb/lb per-mil decode (validated engine basis). Dumps scripts/_mine_d52.json."""
import json, gzip, bisect, calendar
from datetime import datetime, timedelta
D=json.loads(gzip.decompress(open('docs/sf_stock_data.bin','rb').read()))
data=D['data']; IDX=json.load(open('scripts/indices_history.json'))['Nifty 500']
SER={s:{'d':o['d'],'c':o['c'],'hb':o.get('hb'),'lb':o.get('lb')} for s,o in data.items()}
MAXD=max(o['d'][-1] for o in SER.values() if o['d'])
def di(s):return datetime(s//10000,(s//100)%100,s%100)
def toi(dt):return dt.year*10000+dt.month*100+dt.day
def members(dn):
    b=None
    for s in IDX:
        ed=int(s['effectiveDate'].replace('-',''))
        if ed<=dn and(b is None or ed>b[0]):b=(ed,s['symbols'])
    return set(b[1]) if b else set()
def price(s,dint):
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
def screen(dn):
    M=members(dn);rows=[]
    for s in SER:
        if s not in M or not SER[s]['d'] or len(SER[s]['d'])<15:continue
        p=price(s,dn)
        if p is None:continue
        h=hl(s,dn)
        if not h:continue
        hi,low=h
        if hi<=0:continue
        d52=(hi-p)/hi*100
        if d52>10:continue
        rows.append((s,round(d52,2),round(p,1)))
    rows.sort(key=lambda r:r[1]);return rows   # ascending: closest to 52w high first
ALLD=sorted({d for o in SER.values() for d in o['d']})  # every NSE trading day in the bin
import bisect as _b
def last_trading(dn):
    i=_b.bisect_right(ALLD,dn)-1
    return ALLD[i] if i>=0 else None
DATES=[]
for y in range(2020,2027):
    for m in range(1,13):
        if y==2020 and m<3:continue
        if y*100+m> MAXD//100: break
        cal=y*10000+m*100+calendar.monthrange(y,m)[1]
        asof=last_trading(min(cal,MAXD))           # market's last trading day of the month
        if asof: DATES.append(asof)
out={}
for dn in DATES:
    r=screen(dn)
    iso='%04d-%02d-%02d'%(dn//10000,(dn//100)%100,dn%100)
    out[iso]=r
json.dump(out,open('scripts/_mine_d52.json','w'),separators=(',',':'))
for iso in sorted(out):print('%s : %d'%(iso,len(out[iso])))
print('TOTAL months:%d  avg/mo:%.0f'%(len(out),sum(len(v) for v in out.values())/len(out)))
