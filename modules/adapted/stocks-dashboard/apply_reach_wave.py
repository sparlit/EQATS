#!/usr/bin/env python3
"""Reach-class fills: pre-listing quarters recovered from comparative columns / offer docs.

Context (2026-08-18): the coverage engine's short-history N/A rule (build_coverage_matrix.js
REACH) is wired to the BLEND profit family only; its Std and Con mirrors never got it, so a
newly-listed company's pre-existence counted as a coverage gap on those params. Rather than
mirror the rule blind, the quarters it reaches for were READ. These are the ones that exist.

Every value carries the CARRYING filing's own announce date (never the quarter's own era) and
was anchored to a stored value reproduced from the SAME table.

Independently re-verified by the parent session (not taken on the reader's word):
  FLUOROCHEM 20190331 - the FY20 filing prints BOTH a 'Quarter ended 31 March 2019' and a
    'Year ended 31 March 2019' column for the demerged Chemical Business Undertaking. Geometric
    extraction of 122f0872 p8/p21: quarter col x~603 = 58,104 lakh std / x~581 = 58,471 owners
    con; the YEAR cols (x~679 = 18,995 std, x~655 = 19,632 con) are separate. Decisive check:
    those year columns (189.95 / 196.32) equal the SUM of our four stored FY20 quarters
    (111.72+16.68+32.99+28.56 and 112.38+14.86+40.57+28.51) to the paisa. The 581.04 includes a
    (47,915) lakh 'tax pertaining to earlier periods' ITAT credit printed in that same quarter
    column; PBT 148.82 + 432.22 tax credit = 581.04 closes.
  CAMPUS 20200930 - investor deck (BSE Reg-30 attachment 4eee005e, 2022-11-11) slide 21 prints
    PAT bars 101.1 | (77.3) | 282.4 | 547.2 | 229.5 | 313.2 | 145.4 against labels Q2FY20 |
    Q2FY21 | Q2FY22 | Q3FY22 | Q4FY22 | Q1FY23 | Q2FY23. Q2FY21 = Sep-2020 = (77.3)mn = -7.73cr.
    BASIS proven by exclusion, since the deck never says it: the Q4FY22 exchange filing prints
    both bases and FY21 PAT is 268.63 con vs (165.03) std - the deck's 268.7 can only be con
    (434mn discriminator); Q3FY22 547.18 con vs 235.27 std matches the deck's 547.2 (312mn
    discriminator). Two bars in the same series reproduce our stored CON cells exactly
    (Q2FY22 282.4 == 28.24, Q3FY22 547.2 == 54.72). Total-vs-owners <=0.02cr (FY21 NCI -0.11mn).

Deliberately NOT written, and why:
  CAMPUS 20190930 con 10.11 (Q2FY20 bar, same slide, same anchors) - REAL, but it would become
    the symbol's oldest row by 5 quarters with nothing around it. Per the CELLO precedent (§99)
    a lone old row moves the engine's oldest-row boundary and converts quarters no one ever
    published into 'visible gaps'. It cannot help any factor (TTM needs 8 consecutive) and can
    only manufacture holes. Recorded in the queue file instead.
  CAMPUS 20201231 con 38.86 -> 38.63 - the reader derives it 9MFY21(RHP p79) minus H1FY21(DRHP),
    i.e. ACROSS two documents, which is the same rule that barred its Jun-2020 fill. Flagged for
    its own read, not applied. (Our 38.86 is itself an unanchored qe+45 stamp - worth the read.)
  CAMPUS 20210331 std -5.67 -> -8.67 - in-document arithmetic lock reported (PBT 257.52 - tax
    344.18, EPS -0.29) but not re-verified here; flagged with the above.
"""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(HERE); ROOT = os.path.dirname(SCR)
WHEN = '2026-08-18 20:30 IST'

# sym, qe, std, annStd, con, annCon, rev_std, rev_con, src, anchor
F = [
 ('FLUOROCHEM', 20190331, 581.04, 20200731, 584.71, 20200731, 681.88, 710.02,
  'BSE 500401 attachment 122f0872-0022-4f33-a2a5-86065a36527f.pdf, FY20 audited results, std p8 / con p21, column "Corresponding Quarter ended 31 March 2019 in respect of the demerged Chemical Business Undertaking"',
  'same table reproduces stored 20200331 (28.56 std / 28.51 con owners) and 20191231 (32.99 / 40.57) EXACT; and the table\'s FY20 year column 189.95/196.32 == the sum of our four stored FY20 quarters'),
 ('VALIANTORG', 20190930, 31.23, 20201113, 31.23, 20201113, 142.56, 163.86,
  'BSE 540145 attachment d34bc2be-1474-4579-8ba9-42229ce81ce9.pdf, Q2FY21 filing 13-Nov-2020, Annexure I, printed column "3 Months ended 30th Sep 2019 (unaudited)", Ind-AS restated (filing note 2)',
  'same table reproduces stored 20200630 24.68 EXACT on both bases; con owners 3,123.01 + NCI (41.74) == total 3,081.27'),
 ('VALIANTORG', 20190630, 41.25, 20201113, 41.25, 20201113, 162.73, 189.79,
  'same filing, same-table two-column derivation: printed H1FY20 7,248.34 minus printed Sep-2019 quarter 3,123.01 = 4,125.33 lakh (std); con owners identical derivation, NCI identity closes (74.61 - (41.74) = 116.35)',
  'same table reproduces stored 20200630 24.68 EXACT; no Q1FY21 filing exists (BSE results gap May->Nov 2020) so the derivation is the only route'),
 ('RAILTEL', 20191231, 42.71, 20210322, 43.23, 20210322, 258.14, 270.20,
  'BSE 543265 Q3FY21 filing (first listed-era filing, 22-Mar-2021), year-ago columns',
  'std Dec-2020 69.34 EXACT in the same table; con via FY20 minus 9M residue = 22.79 == stored 20200331 con EXACT'),
 ('INDIGOPNTS', 20191231, 14.52, 20210514, None, None, 171.62, None,
  'BSE 543258 catch-up filing "Quarter and Nine Month ended Dec-31-2020" (14-May-2021); press release inside the filing restates the year-ago quarter',
  'Dec-2020 18.78 EXACT in the same filing'),
 ('EQUITASBNK', 20190930, 49.48, 20201109, None, None, 639.47, None,
  'BSE 543243 Q2FY21 filing (9-Nov-2020), year-ago column; all six columns close PBT-tax=PAT to the paisa and the H1 identity pins the column',
  'stored 20200930 102.99 EXACT in the same table'),
 ('EQUITASBNK', 20191231, 94.08, 20210128, None, None, 676.71, None,
  'BSE 543243 Q3FY21 filing (28-Jan-2021), year-ago column; 9M identity pins the column',
  'stored 20201231 110.70 EXACT in the same table'),
 ('PRINCEPIPE', 20190331, 29.90, 20200625, None, None, 498.97, None,
  'BSE 542907 Q4FY20 filing (25-Jun-2020), year-ago column, vision read of the scan, arithmetic-locked; auditor notes the comparative is management-certified',
  'double anchor in the same table: stored 20200331 28.28 and 20191231 24.28 EXACT'),
 ('FIVESTAR', 20210331, 88.44, 20220427, None, None, 277.28, None,
  'BSE DEBT segment "Reg. 52 - Financial Result" audited FY22 filing (27-Apr-2022) in quarterly format - a real filing, but dated BEFORE the equity listing (2022-11-21), so the engine treats the row as a pre-listing carry-in for its oldest-row test (§99). Date recorded as measured.',
  'stored 20220331 117.88 and 20211231 118.12 EXACT in the same table; FY22 sum reconciles +-0.01'),
 ('CAMPUS', 20200930, None, None, -7.73, 20221111, None, 108.52,
  'BSE 543523 Reg-30 Investor Presentation attachment 4eee005e-8588-4242-917d-aaec97553021.pdf (11-Nov-2022) slide 21 quarterly PAT bar series; basis proven by exclusion against the Q4FY22 filing which prints both bases (FY21 268.63 con vs (165.03) std; Q3FY22 547.18 con vs 235.27 std)',
  'two bars in the same series reproduce stored CON cells EXACT: Q2FY22 282.4mn == 28.24, Q3FY22 547.2mn == 54.72. Figure is total con PAT; FY21 NCI -0.11mn so owners differ by <=0.02cr'),
]
# announce-date corrections (§99: a stamp that predates the tape is not a filing date)
ANN = [('FLUOROCHEM', 20190630, 20190814, 20191116,
        'Q2FY20 filing (board 14-Nov-2019, NSE dissemination 16-Nov-2019) is the CARRYING filing: it prints Jun-2019 as its preceding-quarter column and reproduces both stored values EXACT (std 11,172 / con owners 11,238 lakh). The stored 20190814 is a qe+45 default stamped before the company was listed (first bar 2019-10-16), i.e. a §99 phantom date, not a filing.')]
# straight value corrections in the revop twin
REVOP_FIX = [('FLUOROCHEM', 20190930, 4, 3.01, 16.68,
   'revop pat_std slot held 3.01 while sf_fundamentals holds the correct 16.68. The filer\'s own Q2FY20 standalone XBRL carries ProfitLossForPeriod=30,100,000 (3.01cr), contradicting its own board-approved PDF which prints 1,668 lakh = 16.68 TWICE across independent filings (Q2FY20 current column, Q3FY20 preceding column) with PBT 3,201 - tax 1,533 closing exactly. Filer XBRL typo; the PDF wins.')]

def load(p): return json.load(open(p))
def dump(p, o): json.dump(o, open(p, 'w'), separators=(',', ':'))

ins_f = upd_f = ins_r = 0
for path in (os.path.join(ROOT,'docs','sf_fundamentals.json'), os.path.join(SCR,'fundamentals.json')):
    o = load(path)
    for sym, qe, std, astd, con, acon, _rs, _rc, _s, _a in F:
        rows = o.setdefault(sym, [])
        ex = [r for r in rows if r[0] == qe]
        assert not ex, '%s %s already has a fund row: %r' % (sym, qe, ex)
        assert all(r[0] != qe for r in rows), 'dup guard'
        rows.append([qe, std, astd, con, acon]); rows.sort(key=lambda r: r[0]); ins_f += 1
    for sym, qe, was, now, _ev in ANN:
        r = [x for x in o[sym] if x[0] == qe][0]
        # The twins are NOT mirrors: measured 2026-08-18, 4,085 rows differ and 713 symbols exist
        # only in docs/, with scripts/fundamentals.json systematically the LAGGING copy (nulls
        # where docs holds a value). So the pre-value assert accepts either the stale stamp we are
        # replacing or a null - but never some THIRD value, which would mean another writer got
        # here first and must be adjudicated rather than overwritten.
        assert r[2] in (was, None) and r[4] in (was, None), \
            '%s %s ann is %r/%r, expected %r or None' % (sym, qe, r[2], r[4], was)
        r[2] = r[4] = now; upd_f += 1
    dump(path, o)

for path in (os.path.join(ROOT,'docs','sf_revop.json'), os.path.join(SCR,'revop_fundamentals.json')):
    o = load(path)
    for sym, qe, std, _as, con, _ac, rs, rc, _s, _a in F:
        if rs is None and rc is None: continue
        cell = o.setdefault(sym, {})
        if str(qe) in cell:      # twin-lag: a revop row may exist in one file and not the other
            c = cell[str(qe)]
            assert all(c[i] is None for i in (0, 1)), \
                '%s %s revop row already holds revenue %r - adjudicate, do not overwrite' % (sym, qe, c[:2])
            c[0], c[1] = rs, rc
            if c[4] is None: c[4] = std
            if c[5] is None: c[5] = con
            ins_r += 1
            continue
        cell[str(qe)] = [rs, rc, None, None, std, con, 0, None, None]
        o[sym] = {k: cell[k] for k in sorted(cell)}
        ins_r += 1
    for sym, qe, slot, was, now, _ev in REVOP_FIX:
        c = o[sym][str(qe)]
        assert c[slot] == was, '%s %s slot%d holds %r, expected %r' % (sym, qe, slot, c[slot], was)
        c[slot] = now
    dump(path, o)

# provenance in the ledgers verify_fills_live walks
p = os.path.join(SCR,'std_pat_detres_fills.json'); led = load(p)
for sym, qe, std, astd, con, acon, rs, rc, src, anc in F:
    if std is None: continue
    led['%s|%d' % (sym, qe)] = {'std': std, 'ann': astd, 'applied': WHEN + ' reach-class fill (pre-listing quarter from a comparative column / offer doc)',
                                'basis': 'standalone', 'src': src, 'evidence': anc}
json.dump(led, open(p,'w'), indent=1)

p = os.path.join(SCR,'conpat_filing_fills.json'); led = load(p)
for sym, qe, std, astd, con, acon, rs, rc, src, anc in F:
    if con is not None:
        led['%s|%d|con' % (sym, qe)] = {'con': con, 'annCon': acon, 'when': WHEN, 'basis': 'con',
                                        'src': src, 'evidence': anc}
    if rc is not None:
        led['%s|%d|con_rev' % (sym, qe)] = {'rev_con': rc, 'when': WHEN, 'src': src, 'evidence': anc}
json.dump(led, open(p,'w'), indent=1)

p = os.path.join(SCR,'std_rev_detres_fills.json'); led = load(p)
for sym, qe, std, astd, con, acon, rs, rc, src, anc in F:
    if rs is None: continue
    led['%s|%d' % (sym, qe)] = {'revS': rs, 'ann': astd, 'applied': WHEN + ' reach-class fill',
                                'src': src, 'evidence': anc}
json.dump(led, open(p,'w'), indent=1)

p = os.path.join(SCR,'ann_date_fills.json'); led = load(p)
for sym, qe, was, now, ev in ANN:
    led['%s|%d' % (sym, qe)] = {'ann': now, 'was': was, 'src': 'carrying-filing read ' + WHEN, 'evidence': ev}
json.dump(led, open(p,'w'), indent=1)

print('fund rows inserted (x2 twins): %d' % ins_f)
print('fund ann corrections (x2)    : %d' % upd_f)
print('revop rows inserted (x2)     : %d' % ins_r)
