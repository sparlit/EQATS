#!/usr/bin/env python3
"""Portfolio widget feed — CLOUD edition (runs in GitHub Actions, not on the Mac).

Reads the holdings blob from the token-addressed supabase row, prices it with the
live-quote worker, and writes back a percentages-ONLY payload:
    {day, total, mtd, dayTxt, totalTxt, mtdTxt, asOf, ts}
No stock names, no portfolio names, no rupee amounts ever leave this script — the
phone widget must reveal nothing to whoever picks the phone up.

Tokens come from the environment (repo secrets); nothing sensitive is printed.

  python3 scripts/portfolio_feed.py                      # one shot
  python3 scripts/portfolio_feed.py --loop 30 --every 120  # loop 30 min, push every 120 s
"""
import base64, datetime, gzip, json, os, sys, time, urllib.request

SUPA   = 'https://nebjnsndgrhumnkuipqy.supabase.co/rest/v1/rpc/'
ANON   = 'sb_publishable_MDlQwiVc5deii91__UNeDg_z9r4Fk98'
OWNER  = 'sw_owner_8Kq2Lm9Xp4Rt7v'          # already public in docs/sw-sync.js
WORKER = 'https://stocksworld-quotes.dhruvan2510.workers.dev/?quotes='
SLIM   = 'https://dhruvan246.github.io/stocks-dashboard/dash_slim.bin'
EPOCH  = datetime.date(1996, 1, 1)
UA     = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'

HOLD_TOKEN = os.environ.get('PF_HOLDINGS_TOKEN', '').strip()
FEED_TOKEN = os.environ.get('PF_FEED_TOKEN', '').strip()


def _post(fn, payload, timeout=40):
    req = urllib.request.Request(SUPA + fn, data=json.dumps(payload).encode(), headers={
        'apikey': ANON, 'Authorization': 'Bearer ' + ANON,
        'Content-Type': 'application/json', 'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode().strip()
    return json.loads(body) if body else None


def load_holdings():
    row = _post('pf_feed_get', {'token': HOLD_TOKEN})
    if not row or 'z' not in row:
        sys.exit('holdings row not found — is PF_HOLDINGS_TOKEN right, and has push_holdings.py run?')
    return json.loads(gzip.decompress(base64.b64decode(row['z'])))


def quotes(syms):
    req = urllib.request.Request(WORKER + ','.join(sorted(syms)), headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r).get('data', {})


def month_end_baseline(hold):
    """Closing prices on the last trading session of LAST month, by symbol.

    Computed once per run: the bin is ~2 MB, and last month's closes only change
    when the pipeline backfills, which a single run need not chase.
    """
    req = urllib.request.Request(SLIM, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        series = json.loads(gzip.decompress(r.read()))['series']
    cut = (datetime.date.today().replace(day=1) - EPOCH).days
    best = None
    for h in hold:
        d = series.get(h.get('hist') or '', {}).get('d')
        if not d:
            continue
        prev = [x for x in d if x < cut]
        if prev and (best is None or prev[-1] > best):
            best = prev[-1]
    if best is None:
        return None, None
    px = {}
    for h in hold:
        s = series.get(h.get('hist') or '')
        if not s:
            continue
        hit = [(o, p) for o, p in zip(s['d'], s['p']) if o <= best]
        if hit:
            px[h['hist']] = hit[-1][1] / 100.0
    return px, str(EPOCH + datetime.timedelta(days=best))


def compute(doc, base_px):
    hold = doc['holdings']
    q = quotes({h['live'] for h in hold if h.get('live')})
    value = cost = day = 0.0
    bv = nv = 0.0
    priced = 0
    for h in hold:
        if h.get('live') and h['live'] in q:
            px = q[h['live']]['ltp']
            prev = q[h['live']].get('prevClose', px)
            priced += 1
        elif h.get('manualPx') is not None:
            px = h['manualPx']
            prev = h.get('manualPrev', px)
        else:
            continue
        value += h['qty'] * px
        cost += h['qty'] * h['avg']
        day += h['qty'] * (px - prev)
        b = (base_px or {}).get(h.get('hist'))
        if b:
            bv += h['qty'] * b
            nv += h['qty'] * px
    if not (value > 0 and cost > 0):
        raise SystemExit('refusing to publish a feed with no priced holdings')

    day_pct = day / (value - day) * 100
    tot_pct = (value - cost) / cost * 100
    mtd = round(nv / bv * 100 - 100, 2) if bv > 0 else None
    sgn = lambda v: None if v is None else ('+%.2f%%' % v if v >= 0 else '%.2f%%' % v)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    return {
        'day': round(day_pct, 2), 'total': round(tot_pct, 2), 'mtd': mtd,
        'dayTxt': sgn(day_pct), 'totalTxt': sgn(tot_pct), 'mtdTxt': sgn(mtd),
        'n': len(hold), 'priced': priced,
        'asOf': now.strftime('%Y-%m-%d %H:%M'), 'ts': int(time.time()), 'src': 'ci',
    }


def push(feed):
    ok = _post('pf_feed_set', {'secret': OWNER, 'token': FEED_TOKEN, 'payload': feed})
    if ok is not True:
        raise SystemExit('supabase rejected the feed write: %r' % ok)


def main():
    if not HOLD_TOKEN or not FEED_TOKEN:
        sys.exit('PF_HOLDINGS_TOKEN and PF_FEED_TOKEN must be set')
    args = sys.argv[1:]
    loop_min = int(args[args.index('--loop') + 1]) if '--loop' in args else 0
    every = int(args[args.index('--every') + 1]) if '--every' in args else 120

    doc = load_holdings()
    base_px, base_date = month_end_baseline(doc['holdings'])
    print('loaded %d holdings; month-end baseline %s (%d symbols)'
          % (len(doc['holdings']), base_date, len(base_px or {})))

    deadline = time.time() + loop_min * 60
    n = 0
    while True:
        try:
            feed = compute(doc, base_px)
            push(feed)
            n += 1
            # Deliberately NOT logging the percentages: this repo is public, and
            # its Actions logs are readable by anyone. Counts prove the push worked
            # without publishing how the portfolio is doing.
            print('%s  pushed ok (%d priced of %d)' % (feed['asOf'], feed['priced'], feed['n']))
        except SystemExit:
            raise
        except Exception as e:                    # one bad tick must not end the session
            print('tick failed (continuing): %s' % e, file=sys.stderr)
        if time.time() + every > deadline:
            break
        time.sleep(every)
    print('pushed %d update(s)' % n)


if __name__ == '__main__':
    main()
