#!/usr/bin/env python3
"""Adjudicate dividend_sweep_results.json candidates the HGS way (PLAN H.1):

The sweep's pct_of_entry OVERSTATES for pre-split eras — the announcement's ₹/share is
era-nominal while the trade log's entry price is split-adjusted (BAJFINANCE 2005 read "416% of
entry" only because today's series divides that era by later bonuses). TRUTH requires the era
tape: find the actual ex-day on the bhavcopy (the day whose open gaps DOWN from prev_close by
roughly the dividend), then true materiality = amt / prev_close(era). Only >=2% earns a ledger
row [sym, exYmd, (prev-amt)/prev, close/prev] — cash out, market move stays (the HGS factor).

READ-ONLY: prints proposed rows; writing to demerger_adj.json stays a human-reviewed step.
Run: .venv python3 dividend_adjudicate.py   (needs NSE bhavcopy access via build_sf_data)
"""
import json, os, sys, datetime, re

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
import build_fundamentals as F
import build_sf_data as B

RES = os.path.join(HERE, 'dividend_sweep_results.json')


def main():
    res = json.load(open(RES))
    try:
        led = {(x[0], int(x[1])) for x in json.load(open(os.path.join(SCRIPTS, 'demerger_adj.json')))}
    except Exception:
        led = set()
    jar = None
    try:
        jar = F.nse_jar()
    except Exception as e:
        print('nse_jar:', e)

    cands = [(k, v) for k, v in res.items() if v.get('candidates')]
    print(f'candidate windows: {len(cands)}')
    proposals, rejected = [], []
    for key, v in cands:
        sym, e0, e1 = key.split('|')
        for c in v['candidates']:
            amt = c['amt']
            nd = (c['news_dt'] or '')[:10]
            if not nd:
                continue
            d0 = datetime.date.fromisoformat(nd)
            # scan the tape for the ex-day: open gaps down from prev_close by ~the dividend.
            # Window: announcement day .. +30d (record dates trail the declaration).
            best = None
            d = d0
            for _ in range(31):
                if d > datetime.date.today():
                    break
                try:
                    rows = B.fetch_day(d, jar)
                except Exception:
                    rows = None
                if rows:
                    row = next((r for r in rows if r[0] == sym), None)
                    if row:
                        close, prev, opn = row[1], row[2], row[6]
                        if prev and opn and prev > 0:
                            gap = prev - opn
                            # ex-day signature: the open drop explains >=50% of the dividend
                            # and isn't a 3x overshoot (that would be news, not the dividend)
                            if amt * 0.5 <= gap <= amt * 3:
                                score = abs(gap - amt)
                                if best is None or score < best[0]:
                                    best = (score, int(d.strftime('%Y%m%d')), prev, opn, close)
                d += datetime.timedelta(days=1)
            if best is None:
                rejected.append((sym, nd, amt, 'no ex-day gap signature within 30d'))
                continue
            _, exd, prev, opn, close = best
            true_pct = amt / prev * 100
            if true_pct < 2.0:
                rejected.append((sym, nd, amt, f'era materiality {true_pct:.2f}% < 2% (prev {prev})'))
                continue
            if (sym, exd) in led:
                rejected.append((sym, nd, amt, f'already ledgered at {exd}'))
                continue
            factor = round((prev - amt) / prev, 4)
            raw = round(close / prev, 4)
            proposals.append([sym, exd, factor, raw, amt, round(true_pct, 2)])
            print(f'PROPOSE ["{sym}", {exd}, {factor}, {raw}]  # Rs{amt} = {true_pct:.2f}% of era prev {prev}')
    print()
    for r in rejected:
        print('reject:', r)
    json.dump({'proposals': proposals,
               'rejected': [list(map(str, r)) for r in rejected]},
              open(os.path.join(HERE, 'dividend_adjudication.json'), 'w'), indent=1)
    print(f'\n{len(proposals)} proposals, {len(rejected)} rejected -> dividend_adjudication.json')


if __name__ == '__main__':
    main()
