#!/usr/bin/env python3
"""SPICEJET (BSE 500285): 22 wrong revenue cells + 5 missing rev_std + 7 wrong PAT slots.

Agent read 2026-08-18 of the actual BSE filings (validated by in-filing a+b=total arithmetic and
cross-filing comparative agreement; MoneyControl archived pages + screener corroborate):

1) WRONG PERIOD (one root cause: +2 column offset on 11e07421 p8, a scanned con statement):
   20201231 con held the 9M-Dec-2020 figures, 20210930 con the 9M-Dec-2021 figures, 20211231 con
   the Dec-2020 QUARTER figures. Proof from our own store: stored "20201231" con PAT -772.90 ==
   -600.52 + -105.61 + -66.78 (sum of the three quarter con PATs, i.e. the 9M) and stored
   "20210930" -1259.23 == -731.12 + -570.56 + 42.45. Both close to the paisa.
2) rev_con SYSTEMATICALLY held the a-line ("Income from operations" before other operating income)
   where the store-wide convention (measured 249/250 sampled quarters) is TOTAL revenue from
   operations. 12 cells corrected.
3) rev_std defects: 2 a-line cells, 1 cell holding TOTAL INCOME (30,735.03mn incl other income),
   2 con-value-in-std-slot cells, 2 aggregator-rounded cells re-read at filing precision.
4) 5 rev_std cells never extracted; values from the primary filings' standalone statements.
5) 20181231 std PAT held the consolidated figure (64.44); standalone as filed is 55.07
   (387b9f3c p2 row 7, 550.7mn).

All filings print Rupees in millions (/10 to crore). Twins written BOTH. Provenance goes to the
verify_fills_live-walked ledgers; superseded entries in vision_rev_fills / sweep_rev_fills /
screener_rev_fills / post2020_rev_detres_fills / _revgap_done are updated in place so no ledger
keeps asserting a value the store no longer holds.
"""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
SCR  = os.path.dirname(HERE)
ROOT = os.path.dirname(SCR)
S = 'SPICEJET'
WHEN = '2026-08-18 20:05 IST'

def load(p): return json.load(open(p))
def save(p, o, indent=None):
    sep = (',', ':') if indent is None else None
    json.dump(o, open(p, 'w'), separators=sep, indent=indent)

# (qe, slot, was, now)  slots: 0 revS, 1 revC, 4 patS, 5 patC
REVOP = [
 (20180630, 0, 2184.28, 2220.39), (20180630, 1, 2185.47, 2221.59),
 (20181231, 0, None,    2486.81), (20181231, 1, 2383.98, 2488.58),
 (20190331, 0, None,    2531.25), (20190331, 1, 2480.97, 2534.70),
 (20190630, 0, 2922.54, 3002.07), (20190630, 1, 2922.54, 3002.85),
 (20190930, 0, 3073.50, 2845.26), (20190930, 1, 2761.51, 2848.01),
 (20191231, 0, 3542.70, 3647.13), (20191231, 1, 3542.70, 3656.36),
 (20200331, 1, 2778.76, 2867.02),
 (20200630, 1, 489.59,  521.04),
 (20201231, 0, None,    1686.62), (20201231, 1, 3157.04, 1691.65),
 (20210331, 1, 1829.77, 1888.19),
 (20210630, 1, 1083.24, 1125.00),
 (20210930, 0, None,    1342.60), (20210930, 1, 4592.43, 1345.44),
 (20211231, 0, None,    2259.30), (20211231, 1, 1635.79, 2262.65),
 (20220331, 0, 1812.59, 1865.70),
 (20230630, 0, 2002.00, 2001.74), (20230630, 1, 1917.43, 2003.59),
 (20240331, 0, 1719.00, 1719.37), (20240331, 1, 1663.53, 1738.38),
 # pat mirrors on the three wrong-period rows + 20181231 std
 (20181231, 4, None,     55.07),
 (20201231, 4, None,    -56.96), (20201231, 5, -772.90,  -66.78),
 (20210930, 4, None,   -561.70), (20210930, 5, -1259.23, -570.56),
 (20211231, 4, None,     23.28), (20211231, 5, -66.78,     42.45),
]
# fund rows: (qe, idx, was, now)  idx: 1 std, 3 con
FUND = [
 (20181231, 1, 64.44, 55.07),
 (20201231, 1, -772.90, -56.96), (20201231, 3, -772.90, -66.78),
 (20210930, 1, -1259.23, -561.70), (20210930, 3, -1259.23, -570.56),
 (20211231, 1, -66.78, 23.28), (20211231, 3, -66.78, 42.45),
]
SRC = {
 20180630: 'e02dc037 p1 (std) / con page, Q1FY19 filing ann 20180814',
 20181231: '387b9f3c p2 std-only pack ann 20190211; con from d216b0fc p7 comparative',
 20190331: '6bac33dc p2 + cbed4fa4 p2/p10, Q4FY19 filing ann 20190528',
 20190630: 'Q1FY20 filing ann 20190809/10',
 20190930: 'primary Nov-2019 filing ann 20191113 (std cell held TOTAL INCOME 30,735.03mn)',
 20191231: 'd216b0fc p2/p6, Q3FY20 filing ann 20200214',
 20200331: '08dc49d9 Q4FY20 filing ann 20200729',
 20200630: 'Q1FY21 filing ann 20200810-0915',
 20201231: '58bc06fd p2/p8, Q3FY21 filing ann 20210210',
 20210331: 'Q4FY21 filing ann 20210530',
 20210630: 'a604ce22 p7, Q1FY22 filing ann 20210813',
 20210930: 'a9ee59f8 p2/p10, Q2FY22 filing ann 20211112',
 20211231: '11e07421 p2/p8, Q3FY22 filing ann 20220215',
 20220331: '1c-aa80 p2 + Q1FY23 comparative (63,635.75-45,509.84 cross-check), ann 20220831',
 20230630: 'Q1FY24 filing ann 20230712 (was screener crore-rounded)',
 20240331: 'Q4FY24 filing ann 20240715 (was screener crore-rounded / a-line)',
}
EV = ('SPICEJET agent read 2026-08-18: every filing validated by a-line + b-line = Total RFO '
      'across all columns and cross-filing comparative agreement; values in Rs millions /10. '
      'Wrong-period trio proven by 9M = sum-of-quarters closing to the paisa in our own store.')

# ---- twins: revop -------------------------------------------------------------------------
n_rev = 0
for path in (os.path.join(ROOT, 'docs', 'sf_revop.json'), os.path.join(SCR, 'revop_fundamentals.json')):
    o = load(path)
    rows = o[S]
    for qe, slot, was, now in REVOP:
        r = rows[str(qe)]
        assert (r[slot] is None and was is None) or abs(r[slot] - was) < 0.005, \
            'revop %s %s slot%d holds %r, expected %r' % (path, qe, slot, r[slot], was)
        r[slot] = now
        n_rev += 1
    save(path, o)
# ---- twins: fund --------------------------------------------------------------------------
n_pat = 0
for path in (os.path.join(ROOT, 'docs', 'sf_fundamentals.json'), os.path.join(SCR, 'fundamentals.json')):
    o = load(path)
    for qe, idx, was, now in FUND:
        row = [r for r in o[S] if r[0] == qe]
        assert len(row) == 1, 'fund %s row %s' % (path, qe)
        assert abs(row[0][idx] - was) < 0.005, \
            'fund %s %s idx%d holds %r, expected %r' % (path, qe, idx, row[0][idx], was)
        row[0][idx] = now
        n_pat += 1
    save(path, o)

# ---- provenance: verify-walked ledgers ----------------------------------------------------
p = os.path.join(SCR, 'std_rev_detres_fills.json'); led = load(p)
for qe, slot, was, now in REVOP:
    if slot != 0: continue
    led['%s|%d' % (S, qe)] = {
        'revS': now, 'was': was, 'ann': None,
        'applied': WHEN + (' std-fill' if was is None else ' CORRECTION'),
        'src': 'BSE 500285 ' + SRC[qe], 'evidence': EV}
save(p, led, indent=1)

p = os.path.join(SCR, 'conpat_filing_fills.json'); led = load(p)
for qe, slot, was, now in REVOP:
    if slot == 1:
        led['%s|%d|con_rev' % (S, qe)] = {
            'rev_con': now, 'was': was, 'when': WHEN,
            'src': 'BSE 500285 ' + SRC[qe],
            'evidence': EV + ' rev_con convention = TOTAL revenue from operations (a+b), not the a-line.'}
    if slot == 5:
        led['%s|%d|con' % (S, qe)] = {
            'con': now, 'was': was, 'when': WHEN,
            'src': 'BSE 500285 ' + SRC[qe],
            'evidence': EV + ' Owners share; wrong-period +2 column offset corrected.'}
save(p, led, indent=1)

p = os.path.join(SCR, 'std_pat_detres_fills.json'); led = load(p)
for qe, idx, was, now in FUND:
    if idx != 1: continue
    led['%s|%d' % (S, qe)] = {
        'std': now, 'was': was, 'applied': WHEN + ' CORRECTION',
        'basis': 'standalone', 'src': 'BSE 500285 ' + SRC[qe], 'evidence': EV}
save(p, led, indent=1)

# ---- supersede stale provenance -----------------------------------------------------------
NOTE = 'SUPERSEDED %s: see std_rev_detres_fills/conpat_filing_fills SPICEJET entries (filing re-read)' % WHEN
p = os.path.join(SCR, 'vision_rev_fills.json'); led = load(p); nn = 0
for qe, basis, now in ((20200331,'con',2867.02),(20210331,'con',1888.19),(20210930,'con',1345.44),
                       (20211231,'con',2262.65),(20220331,'std',1865.70)):
    k = '%s|%d' % (S, qe)
    if k in led and basis in led[k]:
        led[k][basis]['rev'] = now; led[k][basis]['src'] = NOTE + ' | was: ' + led[k][basis]['src']; nn += 1
save(p, led, indent=1); print('vision_rev_fills superseded:', nn)

p = os.path.join(SCR, 'sweep_rev_fills.json'); led = load(p); nn = 0
for key, field, now in (('SPICEJET|20180630|revS','revS',2220.39),('SPICEJET|20190630|revS','revS',3002.07),
                        ('SPICEJET|20190930|revS','revS',2845.26),('SPICEJET|20191231|revS','revS',3647.13),
                        ('SPICEJET|20210630|revC','revC',1125.00)):
    if key in led:
        e = led[key]; e[field] = now
        e['superseded'] = NOTE; nn += 1
save(p, led, indent=1); print('sweep_rev_fills superseded:', nn)

p = os.path.join(SCR, 'screener_rev_fills.json'); led = load(p); nn = 0
for key, now in (('SPICEJET|20230630|revS', 2001.74), ('SPICEJET|20240331|revS', 1719.37)):
    if key in led:
        led[key]['revS'] = now; led[key]['superseded'] = NOTE; nn += 1
save(p, led, indent=1); print('screener_rev_fills superseded:', nn)

p = os.path.join(SCR, '_revgap_done.json'); led = load(p); nn = 0
for key, now in (('SPICEJET|20200331', 2867.02), ('SPICEJET|20191231', 3656.36)):
    if key in led and 'con' in led[key]:
        led[key]['con']['rev'] = now; led[key]['con']['src'] = NOTE; nn += 1
save(p, led, indent=1); print('_revgap_done superseded:', nn)

# post2020_rev_detres_fills holds only std cells the agent verified CORRECT (20200331/0630/0930/
# 20210331) - untouched by design.

# ---- rekey skips for the 5 filled quarters ------------------------------------------------
p = os.path.join(SCR, '_revgap_skips.json'); led = load(p); nn = 0
for qe in (20181231, 20190331, 20201231, 20210930, 20211231):
    k = '%s|%d' % (S, qe)
    if k in led:
        led['_FILLED_%s_%d' % (S, qe)] = led.pop(k); nn += 1
save(p, led, indent=1); print('_revgap_skips rekeyed:', nn)

print('revop cells written (x2 twins): %d   fund cells written (x2 twins): %d' % (n_rev, n_pat))
