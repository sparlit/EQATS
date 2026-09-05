# -*- coding: utf-8 -*-
"""Phantom detector v3 (runbook §126) — the STRADDLING level test, robust to the exact ex-date.
v2 over-flagged real splits whose factor the bin dated 1-2 days off the true ex (muhurat/settlement), and
demergers (raw doesn't drop by the full factor). This compares the raw PRICE LEVEL well before vs well
after the event, straddling any date ambiguity:

    pre  = median raw close in [ex-18d, ex-4d]      (before any nearby ex-date)
    post = median raw close in [ex+4d, ex+18d]      (after it has fully settled)
    level_step = post / pre

REAL     level_step within 15% of the applied factor  -> the raw price genuinely re-based near this date
         (split / bonus / consolidation / demerger / crash). The bake's factor is justified. LEAVE.
PHANTOM  applied factor differs from 1 by >8% but level_step stayed ~1 (0.85..1.18) -> the raw level did
         NOT change across the event; the factor is fabricated. The pre-event history is mis-scaled.
REVIEW   partial / illiquid / no straddle window.

Excludes orphan-source keys (real data lives under the rename target) and ETFs/funds up front.
Usage: phantom_straddle.py <scan2.json | sweep_out.json> <bin> <cache> <out.json>
"""
import os, sys, re, json, gzip, datetime
from statistics import median
from collections import Counter

SRC, BIN, CACHE, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(HERE)
raw = json.load(open(SRC))
if isinstance(raw, dict) and 'steps' in raw: items = [{'sym': s['sym'], 'ymd': s['ymd'], 'applied': s['applied'], 'quant': s.get('quant'), 'turnover': s.get('turnover')} for s in raw['steps']]
else: items = [{'sym': r['sym'], 'ymd': r['ymd'], 'applied': r['applied'], 'quant': False, 'turnover': r.get('turnover')} for r in raw]
D = json.loads(gzip.decompress(open(BIN, 'rb').read())); data = D.get('data', D); meta = D.get('meta', {})
rmap = json.load(open(os.path.join(SCR, '_rename_map.json')))
alias_of = {}
for o, n in rmap.items(): alias_of.setdefault(n, set()).add(o)

def is_stub(sym):
    e = data.get(sym)
    if not e: return True
    ds = e['d']; span = (ds[-1] // 10000) - (ds[0] // 10000) + 1
    return len(ds) < span * 40
def is_etf(sym):
    nm = (meta.get(sym, {}) or {}).get('name', '')
    return bool(re.search(r'ETF|BeES|Bees|Exchange Traded|\bGold\b|\bSilver\b|Liquid|Nifty|Sensex|Bharat Bond|GILT', nm, re.I)) or bool(re.search(r'ETF|BEES|SLVR|GOLD|SILVER|LIQUID|IETF|BOND', sym))

_day = {}
def dayfile(ymd):
    if ymd not in _day:
        p = os.path.join(CACHE, '%d.json' % ymd)
        try: _day[ymd] = {r[0]: r for r in json.load(open(p))} if os.path.exists(p) else {}
        except Exception: _day[ymd] = {}
    return _day[ymd]
def rclose(names, ymd):
    df = dayfile(ymd)
    for nm in names:
        r = df.get(nm)
        if r and r[1]: return r[1]
    return None
def window_med(names, d0, lo, hi):
    vals = []
    for k in range(lo, hi + 1):
        v = rclose(names, int((d0 + datetime.timedelta(days=k)).strftime('%Y%m%d')))
        if v: vals.append(v)
    return median(vals) if len(vals) >= 2 else None

cand = [it for it in items if it['ymd'] >= 20020102 and not it.get('quant') and abs(it['applied'] - 1) > 0.03]
skip_stub = skip_etf = 0
out = []; t = 0
for it in cand:
    sym, ymd, f = it['sym'], it['ymd'], it['applied']
    if rmap.get(sym) or is_stub(sym): skip_stub += 1; continue
    if is_etf(sym): skip_etf += 1; continue
    names = [sym] + sorted(alias_of.get(sym, ()))
    d0 = datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100)
    pre = window_med(names, d0, -18, -4); post = window_med(names, d0, 4, 18)
    level = (post / pre) if (pre and post) else None
    if level is None: v = 'REVIEW-nowin'
    elif 0.85 <= (level / f) <= 1.15: v = 'REAL'
    elif 0.85 <= level <= 1.18 and abs(f - 1) > 0.08: v = 'PHANTOM'
    else: v = 'REVIEW'
    out.append({'sym': sym, 'ymd': ymd, 'applied': round(f, 4), 'dir': 'up' if f >= 1 else 'down',
                'level_step': round(level, 4) if level else None, 'pre': pre, 'post': post,
                'verdict': v, 'name': (meta.get(sym, {}) or {}).get('name', ''), 'turnover': it.get('turnover')})
    t += 1
    if t % 1500 == 0: print('  %d' % t, flush=True)

byv = Counter(r['verdict'] for r in out)
json.dump(out, open(OUT, 'w'), indent=1)
print('candidates %d | skipped orphan/stub %d, etf %d | judged %d' % (len(cand), skip_stub, skip_etf, len(out)))
print('=== verdicts ===', dict(byv))
ph = sorted([r for r in out if r['verdict'] == 'PHANTOM'], key=lambda r: -(r['turnover'] or 0))
print('\nCONFIRMED PHANTOM (live equity, level unchanged across event): %d' % len(ph))
for r in ph:
    print('  %-11s %d applied=%.3f %s level_step=%s pre=%s post=%s  %s'
          % (r['sym'], r['ymd'], r['applied'], r['dir'], r['level_step'], r['pre'], r['post'], r['name'][:24]))
