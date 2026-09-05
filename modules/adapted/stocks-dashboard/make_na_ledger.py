#!/usr/bin/env python3
"""Emit scripts/coverage_na_ledger.json — adjudicated NOT-APPLICABLE verdicts for the coverage page.

Campaign: scripts/N500_COVERAGE_100_CAMPAIGN.md (Phase 1/2). User decision 2026-08-16: option A —
banking-format filers are marked N/A for `ebit` rather than having a meaningless EBIT derived.

WHY A LEDGER AND NOT HARDCODED NAMES
  The builder must never carry a list of companies. Every N/A is a claim about a specific filer,
  and a claim needs evidence attached to it that a later session can audit or overturn. The builder
  reads this file; Phase 2 keeps appending to it as names are adjudicated.

EVIDENCE STANDARD (campaign §3 C1)
  reader_1 must NOT be our own data — "never infer absence from our own gaps" is the rule this
  exists to satisfy. Each entry records what was actually read, per name, with the date. Where a
  second independent reader has been obtained it is recorded too; where it has not, the field says
  so plainly rather than being left to look complete.
"""
import json, os, re, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'docs')
TODAY = '2026-08-16'

# --- measured 2026-08-16 by fetching screener.in/company/<SYM>/consolidated/ ONE NAME AT A TIME and
# reading the quarterly table's row labels. Banking-format filers show `Financing Profit` +
# `Financing Margin %` where every other filer shows `Operating Profit` + `OPM %`; neither layout
# carries an EBIT row at all (screener publishes no EBIT for ANY company — ours is derived as
# Operating Profit − Depreciation, verified on SUNPHARMA Jun-2026: 4417.67 − 738.7 = 3678.95 =
# our ebit_con to the paisa).
BANKING_FORMAT = [
    'AUBANK', 'AXISBANK', 'BANDHANBNK', 'BANKBARODA', 'BANKINDIA', 'CANBK', 'CENTRALBK', 'CSBBANK',
    'CUB', 'DCBBANK', 'EQUITASBNK', 'FEDERALBNK', 'HDFCBANK', 'ICICIBANK', 'IDBI', 'IDFCFIRSTB',
    'INDIANB', 'INDUSINDBK', 'IOB', 'J&KBANK', 'KARURVYSYA', 'KOTAKBANK', 'KTKBANK', 'MAHABANK',
    'PNB', 'RBLBANK', 'SBIN', 'SOUTHBANK', 'TMB', 'UCOBANK', 'UJJIVANSFB', 'UNIONBANK', 'YESBANK',
]

# Second reader obtained per name. MoneyControl serves banks the RBI banking format (Interest
# Earned / Interest Expended / Operating Profit before Provisions and contingencies / Provisions)
# with no EBIT row — confirmed exactly for HDFCBANK, whose PPOP 30,996 equals our op_con 30996.0.
# MC rate-limited the batch after that, so the rest are NOT yet second-read. Recorded honestly:
# a name with one reader says so, and Phase 2 upgrades it.
SECOND_READER = {
    'HDFCBANK': 'moneycontrol.com consolidated quarterly results 2026-08-16 — RBI banking format, '
                'no EBIT row (searched all 79 row labels); "Operating Profit before Provisions and '
                'contingencies" = 30,996 == our sf_revop op_con 30996.0 for 20260630',
}


def main():
    REVOP = json.load(open(os.path.join(DOCS, 'sf_revop.json')))
    src = open(os.path.join(DOCS, 'backtest-engine.js')).read()
    m = re.search(r'FUND_ALIAS\s*=\s*(\{.*?\})\s*;', src, re.S)
    alias = json.loads(re.sub(r'(\w+)\s*:', r'"\1":', m.group(1)).replace("'", '"')) if m else {}

    def rmap(s):
        return REVOP.get(s) or REVOP.get(alias.get(s, ''), {})

    def ebit_n(s):
        d = rmap(s)
        return len(d), sum(1 for c in d.values()
                           if (len(c) > 8 and c[8] is not None) or (len(c) > 7 and c[7] is not None))

    entries, warn = {}, []
    for s in sorted(BANKING_FORMAT):
        nq, ne = ebit_n(s)
        if nq == 0:
            warn.append(f'{s}: no sf_revop rows — NOT added')
            continue
        if ne > 0:
            # our own data disagrees with the verdict; do not silently N/A over it
            warn.append(f'{s}: sf_revop holds {ne} ebit quarter(s) — NOT added, needs adjudication')
            continue
        entries[s] = {
            'class': 'C1',
            'reader_1': f'screener.in/company/{s}/consolidated/ quarterly table read {TODAY}: '
                        'banking format — "Financing Profit"/"Financing Margin %" in place of '
                        '"Operating Profit"/"OPM %"; no EBIT row in either layout',
            'reader_2': SECOND_READER.get(s, 'NOT YET SECOND-READ — MoneyControl rate-limited '
                                             f'{TODAY} after the first name; Phase 2 to complete'),
            'our_data': f'sf_revop: ebit null in all {nq} quarters (corroboration only — never '
                        'the basis for the verdict)',
            'decision': 'user 2026-08-16 chose option A: mark N/A rather than derive a '
                        'PPOP-minus-depreciation number that would not mean EBIT (interest is '
                        'already deducted before PPOP for a bank)',
            'adjudicated': TODAY,
        }

    out = os.path.join(ROOT, 'scripts', 'coverage_na_ledger.json')
    # ⚠️ MERGE, never overwrite. This generator only knows the BANKING_FORMAT verdicts; the ledger
    # also carries hand-adjudicated entries (the 35 screener-layout lenders, INDIANB's retraction
    # record, the _-prefixed findings blocks). An overwrite here silently deleted none of them only
    # because nobody re-ran this after 2026-08-16 — fixed 2026-08-16 so it never can.
    doc = {}
    if os.path.exists(out):
        doc = json.load(open(out))
    doc.setdefault('_doc', 'Adjudicated NOT-APPLICABLE verdicts consumed by build_coverage_matrix.js. '
                           'Keyed param -> symbol. A symbol here is excluded from that parameter\'s '
                           'DENOMINATOR on the coverage page (not counted as covered, and not counted '
                           'as missing). Optional "from"/"to" (YYYY-MM-DD) bound the verdict to a date '
                           'range; absent means all dates. Every entry carries per-name evidence — no '
                           'category rules.')
    doc.setdefault('_campaign', 'scripts/N500_COVERAGE_100_CAMPAIGN.md')
    doc['_updated'] = TODAY
    doc.setdefault('ebit', {})
    doc['ebit'].update(entries)          # refresh only the entries this generator owns
    with open(out, 'w') as f:
        json.dump(doc, f, indent=1, sort_keys=False)
    print(f'wrote {out}')
    print(f'  ebit: {len(entries)} symbols marked N/A')
    print(f'  second-read: {sum(1 for v in entries.values() if not v["reader_2"].startswith("NOT YET"))} of {len(entries)}')
    for w in warn:
        print(f'  ⚠ {w}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
