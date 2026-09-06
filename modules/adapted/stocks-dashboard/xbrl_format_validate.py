#!/usr/bin/env python3
"""PHASE B gate of PLAN_XBRL_FILER_FORMAT.md — does the NSE format signal PREDICT ebit presence?

The plan's premise is that an `ebit` hole means "this filer's format has no such line". The cheap
route proposed reading that format off the NSE filing list (bank flag B/F/N, XBRL filename prefix
BANKING_/NBFC_INDAS_/INDAS_). ⚠️ That is a filename convention, i.e. a HYPOTHESIS. This script
tests it against the one thing that matters: what build_revop.py actually produced.

  - If the signal is a good predictor, bank/nbfc quarters carry no ebit and industrial ones do,
    and Phase C can write date-bounded N/A from it.
  - If it is not, the shortcut is dead and format must come from the XBRL TAGS themselves
    (metrics_for() branches on InterestEarned / NetPremiumIncome / PremiumEarned), which means
    actually downloading files.

Counter-example already found by hand: BAJFINANCE is flagged NBFC_INDAS on nearly every recent
quarter and we hold ebit for ALL of them. This quantifies how general that is.
"""
import json, os, collections, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.dirname(HERE), 'docs')

FMT = json.load(open(os.path.join(HERE, 'xbrl_filer_format.json')))['symbols']
REVOP = json.load(open(os.path.join(DOCS, 'sf_revop.json')))
SLOT = {'rev': (1, 0), 'op': (3, 2), 'ebit': (8, 7)}


def present(cell, f):
    ci, si = SLOT[f]
    return bool(cell) and ((len(cell) > ci and cell[ci] is not None) or (len(cell) > si and cell[si] is not None))


def main():
    tab = collections.Counter()
    per_fmt_names = collections.defaultdict(lambda: collections.Counter())
    disagree = collections.Counter()
    for sym, per in FMT.items():
        rmap = REVOP.get(sym) or {}
        for qe, bases in per.items():
            cell = rmap.get(qe)
            if not cell:
                continue
            v = bases.get('con') or bases.get('std')
            fb, fp = v.get('fmt_by_bankflag'), v.get('fmt_by_prefix')
            if fp and fb and fp != fb:
                disagree[(fb, fp)] += 1
            fmt = fp or fb                      # prefix preferred, bank flag as fallback
            if not fmt:
                continue
            has_e, has_o = present(cell, 'ebit'), present(cell, 'op')
            tab[(fmt, has_e)] += 1
            per_fmt_names[fmt][sym] += 1 if has_e else 0

    print('=== does the NSE format signal predict ebit presence? ===')
    print(f"{'format':14s} {'ebit YES':>9s} {'ebit NO':>9s} {'n':>7s}  {'P(no ebit)':>10s}")
    formats = sorted({f for f, _ in tab})
    for f in formats:
        y, n = tab[(f, True)], tab[(f, False)]
        tot = y + n
        print(f'{f:14s} {y:9d} {n:9d} {tot:7d}  {100*n/tot if tot else 0:9.1f}%')

    print()
    if disagree:
        print('bank-flag vs prefix DISAGREEMENTS (flag, prefix) -> n:', dict(disagree))
    else:
        print('bank flag and filename prefix AGREE on every quarter where both exist.')

    print()
    print('VERDICT:')
    bad = 0
    for f in formats:
        y, n = tab[(f, True)], tab[(f, False)]
        tot = y + n
        if f in ('bank', 'nbfc', 'insurer') and y:
            print(f'  ✗ {f}: {y} of {tot} quarters flagged {f} DO carry ebit — the signal does not '
                  f'imply "no ebit line".')
            bad += 1
        if f == 'industrial' and n:
            print(f'  ✗ industrial: {n} of {tot} quarters flagged industrial carry NO ebit — those '
                  f'are real extraction gaps, not format.')
            bad += 1
    if not bad:
        print('  ✓ signal is clean: format fully explains ebit presence.')
    else:
        print('\n  => the filename/flag shortcut CANNOT be used to write N/A on its own.')
        print('     Phase C must key on the XBRL TAGS metrics_for() branches on, which means')
        print('     downloading the files. Record this so nobody rebuilds the shortcut.')

    # the useful residue either way: industrial-flagged quarters with no ebit = fill targets
    print()
    tgt = collections.Counter()
    for sym, per in FMT.items():
        rmap = REVOP.get(sym) or {}
        for qe, bases in per.items():
            cell = rmap.get(qe)
            if not cell:
                continue
            v = bases.get('con') or bases.get('std')
            fmt = v.get('fmt_by_prefix') or v.get('fmt_by_bankflag')
            if fmt == 'industrial' and not present(cell, 'ebit'):
                tgt[sym] += 1
    print(f'industrial-flagged quarters missing ebit: {sum(tgt.values())} across {len(tgt)} names')
    for s, n in tgt.most_common(20):
        print(f'   {s:14s} {n:3d}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
