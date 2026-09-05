# -*- coding: utf-8 -*-
"""Full-history sweep of the price-adjustment layer: which adjustments did the bake APPLY, and
which of those are phantoms (crashes divided out as splits)?  2026-09-02, runbook §124.

Reads the LIVE release bin (adjusted closes) against the raw NSE bhavcopy cache (raw closes/opens),
so for every symbol the cumulative applied factor is f = raw/adj, and every STEP in f is an
adjustment the bake applied at that bar.  Each step is then matched to the ledgers and, when no
ledger explains it, arbitrated by the ex-day OPEN (runbook §87c: a real corporate action opens at
the adjusted basis, (open/prev)/factor in [0.957,1.10]; an equity crash opens ~flat and falls
intraday, >= 1.18).

Also reports the mirror class: big raw moves that match a corporate-action fraction but were NOT
adjusted, split into "ledger has a factor but the tape does not" (JINDALSTEL-2008 class) and
"no ledger, open says CA" (ITC-2005 class).

Usage: python3 sweep_applied_steps.py <sf_stock_data.bin> <bhav_cache_dir> <out.json>
Nothing is written to any ledger or data file.
"""
import os, sys, re, json, gzip, time, ast
import numpy as np
from collections import defaultdict, Counter

BIN, CACHE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(HERE)

CA_FRACS = [1/2, 1/3, 2/3, 1/4, 3/4, 1/5, 2/5, 3/5, 1/6, 5/6, 1/8, 1/10, 1/20, 1/50, 2.0, 3.0, 4.0, 5.0, 10.0]
def ca_factor(r):
    if 0.75 <= r <= 1.30: return 1.0
    for f in CA_FRACS:
        if abs(r / f - 1) <= 0.08: return f
    return 1.0

t0 = time.time()
D = json.loads(gzip.decompress(open(BIN, 'rb').read()))
data = D['data'] if 'data' in D else D
syms = [s for s, v in data.items() if isinstance(v, dict) and v.get('d')]
print('bin: %d symbols, end %s, loaded %.0fs' % (len(syms), D.get('end'), time.time() - t0), flush=True)

# era-name -> bin-key bridge (same rule update_sf_data.raw_close uses)
rmap = json.load(open(os.path.join(SCR, '_rename_map.json')))
alias = {old: new for old, new in rmap.items() if new in data}

dates = {s: np.asarray(data[s]['d'], dtype=np.int64) for s in syms}
raw_c = {s: np.full(len(dates[s]), np.nan, dtype=np.float64) for s in syms}
raw_o = {s: np.full(len(dates[s]), np.nan, dtype=np.float64) for s in syms}
raw_t = {s: np.full(len(dates[s]), np.nan, dtype=np.float64) for s in syms}

files = sorted(f for f in os.listdir(CACHE) if re.fullmatch(r'\d{8}\.json', f))
print('cache: %d day files %s..%s' % (len(files), files[0][:8], files[-1][:8]), flush=True)
nrows = 0
for i, f in enumerate(files):
    ymd = int(f[:8])
    try: rows = json.load(open(os.path.join(CACHE, f)))
    except Exception: continue
    for r in rows:
        s = r[0]
        key = s if s in dates else alias.get(s)
        if key is None: continue
        arr = dates[key]; j = int(np.searchsorted(arr, ymd))
        if j < len(arr) and arr[j] == ymd:
            raw_c[key][j] = r[1]; raw_o[key][j] = r[6]; raw_t[key][j] = r[3]
            nrows += 1
    if i % 1000 == 0: print('  %s  %d rows matched  %.0fs' % (f[:8], nrows, time.time() - t0), flush=True)
print('raw rows matched: %d  (%.0fs)' % (nrows, time.time() - t0), flush=True)

# ---- ledgers -------------------------------------------------------------------------------
def jl(p, dflt):
    try: return json.load(open(os.path.join(SCR, p)))
    except Exception: return dflt
fact = defaultdict(dict); keep = defaultdict(set)
for fn in ('corp_actions.json', 'corp_actions_hist.json'):
    ca = jl(fn, {})
    for s, lst in ca.get('factors', {}).items():
        for d, f in lst: fact[s][int(d)] = float(f)
    for s, lst in ca.get('noadjust', {}).items():
        for d in lst: keep[s].add(int(d))
for s, lst in jl('phantom_crashes.json', {}).items():
    for d in lst: keep[s].add(int(d))
dem = defaultdict(dict)
for row in jl('demerger_adj.json', []):
    dem[row[0]][int(row[1])] = float(row[2])
rights = defaultdict(dict)
for row in jl('rights_terp.json', []):
    rights[row[0]][int(row[1])] = float(row[2])
# hard-coded lists inside update_sf_data.py (LEGACY_FALSE_CA, MANUAL_RIGHTS) — parse, don't import
src = open(os.path.join(SCR, 'update_sf_data.py'), encoding='utf-8').read()
def literal_after(name):
    i = src.find(name + ' = ['); j = src.find('\n]', i)
    return ast.literal_eval(src[i + len(name) + 3:j + 2])
try:
    for s, d in literal_after('LEGACY_FALSE_CA'): keep[s].add(int(d))
except Exception as ex: print('LEGACY parse failed:', ex)
try:
    for row in literal_after('MANUAL_RIGHTS'): rights[row[0]][int(row[1])] = float(row[2])
except Exception as ex: print('MANUAL_RIGHTS parse failed:', ex)
print('ledgers: factors %d syms / %d events; keep-drop %d syms / %d dates; demergers %d; rights %d' % (
    len(fact), sum(len(v) for v in fact.values()), len(keep), sum(len(v) for v in keep.values()),
    sum(len(v) for v in dem.values()), sum(len(v) for v in rights.values())), flush=True)

def bar_of(s, ymd):
    arr = dates[s]; j = int(np.searchsorted(arr, ymd))
    return j if j < len(arr) else None

PX_FLOOR = 0.25
steps = []; unapplied = []; zero_close = {}; cover = {}
by_day = Counter()
for s in syms:
    c = np.asarray(data[s]['c'], dtype=np.float64)
    op = np.asarray(data[s].get('op', [np.nan] * len(c)), dtype=np.float64)
    v = np.asarray(data[s].get('v', [0] * len(c)), dtype=np.float64)
    rc, ro = raw_c[s], raw_o[s]
    zc = int(np.sum((c == 0) & (v > 0)))
    if zc: zero_close[s] = zc
    ok = (rc > 0) & (c > 0)
    cover[s] = [int(ok.sum()), int(len(c))]
    fbar = {bar_of(s, d): f for d, f in fact.get(s, {}).items()}
    kbar = {bar_of(s, d) for d in keep.get(s, ())}
    dbar = {bar_of(s, d): f for d, f in dem.get(s, {}).items()}
    rbar = {bar_of(s, d): f for d, f in rights.get(s, {}).items()}
    f = np.where(ok, rc / np.where(c > 0, c, np.nan), np.nan)
    for j in range(1, len(c)):
        if not (ok[j] and ok[j - 1]): continue
        applied = f[j] / f[j - 1]
        raw_ratio = rc[j] / rc[j - 1]
        big = abs(applied - 1) > 0.03
        quant = (c[j] < PX_FLOOR or c[j - 1] < PX_FLOOR or rc[j] < PX_FLOOR or rc[j - 1] < PX_FLOOR)
        if big:
            og = (ro[j] / rc[j - 1]) / applied if (ro[j] > 0 and rc[j - 1] > 0) else None
            rec = {'sym': s, 'ymd': int(dates[s][j]), 'applied': round(float(applied), 5), 'raw_ratio': round(float(raw_ratio), 4),
                   'open_gap': (round(float(og), 3) if og else None), 'turnover': (float(raw_t[s][j]) if raw_t[s][j] == raw_t[s][j] else None),
                   'quant': bool(quant)}
            if j in fbar:
                rec['cls'] = 'official'; rec['ledger_f'] = fbar[j]
                if abs(applied / fbar[j] - 1) > 0.03: rec['cls'] = 'official_wrong_factor'
            elif j in dbar: rec['cls'] = 'demerger'; rec['ledger_f'] = dbar[j]
            elif j in rbar: rec['cls'] = 'rights'; rec['ledger_f'] = rbar[j]
            elif j in kbar: rec['cls'] = 'KEEPDROP_NOT_HONOURED'
            else:
                rec['cls'] = 'inferred'
                rec['verdict'] = ('crash-like' if og is not None and og >= 1.18 else 'CA-like' if og is not None and og <= 1.12 else 'ambiguous' if og is not None else 'no-open')
            steps.append(rec); by_day[int(dates[s][j])] += 1
        else:
            cf = ca_factor(raw_ratio)
            if cf != 1.0 and not quant:
                og = (ro[j] / rc[j - 1]) / cf if (ro[j] > 0 and rc[j - 1] > 0) else None
                rec = {'sym': s, 'ymd': int(dates[s][j]), 'raw_ratio': round(float(raw_ratio), 4), 'frac': cf,
                       'open_gap': (round(float(og), 3) if og else None), 'turnover': (float(raw_t[s][j]) if raw_t[s][j] == raw_t[s][j] else None)}
                if j in fbar: rec['cls'] = 'LEDGERED_BUT_UNAPPLIED'; rec['ledger_f'] = fbar[j]
                elif j in kbar or j in dbar or j in rbar: continue      # a kept drop the ledger asked for
                else:
                    rec['cls'] = 'unadjusted_move'
                    rec['verdict'] = ('CA-like' if og is not None and og <= 1.12 else 'crash-like' if og is not None and og >= 1.18 else 'ambiguous' if og is not None else 'no-open')
                unapplied.append(rec)
for r in steps: r['same_day_steps'] = by_day[r['ymd']]

summary = {
    'symbols': len(syms), 'raw_rows_matched': nrows,
    'steps_total': len(steps), 'steps_by_class': dict(Counter(r['cls'] for r in steps)),
    'inferred_by_verdict': dict(Counter(r.get('verdict') for r in steps if r['cls'] == 'inferred')),
    'inferred_phantom_candidates_by_year': dict(Counter(str(r['ymd'])[:4] for r in steps if r['cls'] == 'inferred' and r.get('verdict') == 'crash-like')),
    'unapplied_by_class': dict(Counter(r['cls'] for r in unapplied)),
    'unadjusted_move_by_verdict': dict(Counter(r.get('verdict') for r in unapplied if r['cls'] == 'unadjusted_move')),
    'zero_close_symbols': len(zero_close), 'zero_close_bars': sum(zero_close.values()),
    'symbols_with_no_raw_coverage': sum(1 for s in syms if cover[s][0] == 0),
    'elapsed_s': round(time.time() - t0),
}
json.dump({'summary': summary, 'steps': steps, 'unapplied': unapplied, 'zero_close': zero_close, 'coverage': cover}, open(OUT, 'w'))
print(json.dumps(summary, indent=1), flush=True)
# calibration case
for r in steps:
    if r['sym'] == 'YESBANK': print('YESBANK step', r)
for r in unapplied:
    if r['sym'] == 'YESBANK': print('YESBANK unapplied', r)
print('done %.0fs' % (time.time() - t0))
