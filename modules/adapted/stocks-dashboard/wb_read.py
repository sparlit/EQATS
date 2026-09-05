# -*- coding: utf-8 -*-
"""Read an archived NSE results.jsp page (Wayback) into declared period/type/scale + PAT."""
import re, html, json, urllib.request, gzip, io, time

MON={'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}

def fetch(ts, original, tries=3):
    url="https://web.archive.org/web/%sid_/%s" % (ts, original)
    for a in range(tries):
        try:
            req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Accept-Encoding':'gzip'})
            with urllib.request.urlopen(req, timeout=60) as r:
                b=r.read()
                if r.headers.get('Content-Encoding')=='gzip':
                    b=gzip.GzipFile(fileobj=io.BytesIO(b)).read()
                return b.decode('utf-8','replace')
        except Exception as e:
            if a==tries-1: return None
            time.sleep(2)
    return None

def parse(t):
    """-> dict or None. Reads DECLARED period role/type/scale — never regexes a number by date."""
    if not t: return None
    txt=re.sub(r'<[^>]+>',' ',t); txt=html.unescape(txt); txt=re.sub(r'\s+',' ',txt)
    if 'Financial Results' not in txt: return None
    out={}
    m=re.search(r'NSE Symbol\s+([A-Z0-9&_-]+)', txt)
    out['symbol']=m.group(1) if m else None
    m=re.search(r'Company\s+(.+?)\s+NSE Symbol', txt)
    out['company']=m.group(1).strip() if m else None
    m=re.search(r'Result Period\s+(\d{2}-[A-Z]{3}-\d{4})\s+to\s+(\d{2}-[A-Z]{3}-\d{4})\s*\(([^)]*)\)', txt)
    if not m: return None
    out['from'],out['to'],out['period_role']=m.group(1),m.group(2),m.group(3).strip()
    m=re.search(r'Result Type\s+(.+?)\s+(?:Non\s+)?Banking Financial Results', txt)
    out['result_type']=m.group(1).strip() if m else None
    # 'Non-Cumulative' CONTAINS 'Cumulative' -- a bare substring test flagged every true quarter as
    # cumulative (found 2026-09-05 by wb_rev.py; wbgate never used this field, it tests the token itself).
    rt_ = out['result_type'] or ''
    out['cumulative']= bool('Cumulative' in rt_ and 'Non-Cumulative' not in rt_)
    out['bank']= ('Non Banking Financial Results' not in txt) and ('Banking Financial Results' in txt)
    m=re.search(r'Financial Results\s+\(Rs\.\s*([a-zA-Z]+)\)', txt)
    out['scale']=m.group(1).lower() if m else None
    def num(label):
        m=re.search(re.escape(label)+r'\s+(-?[\d,]+\.\d\d)', txt)
        return float(m.group(1).replace(',','')) if m else None
    out['net_profit']=num('Net Profit(+)/Loss(-)')
    out['adj_net_profit']=num('Adjusted Net Profit(+)/ Loss(-)')
    out['net_sales']=num('Net Sales')
    out['eps']=num('Basic EPS (in Rs.)')
    out['paidup']=num('Paid-up Equity Share Capital')
    # months spanned
    df,dt=out['from'],out['to']
    a=(int(df[7:11]),MON[df[3:6]]); b=(int(dt[7:11]),MON[dt[3:6]])
    out['months']=(b[0]-a[0])*12+(b[1]-a[1])+1
    div={'lakhs':100.0,'lakh':100.0,'crores':1.0,'crore':1.0,'million':10.0,'millions':10.0}.get(out['scale'])
    out['div']=div
    out['pat_cr']= (out['net_profit']/div) if (out['net_profit'] is not None and div) else None
    return out


def face_of(t):
    import re, html
    txt=re.sub(r'<[^>]+>',' ',t); txt=html.unescape(txt); txt=re.sub(r'\s+',' ',txt)
    m=re.search(r'Face Value of Share \(in Rs\.\)\s+([\d,]+\.\d\d)', txt)
    return float(m.group(1).replace(',','')) if m else None
