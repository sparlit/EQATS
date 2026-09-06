#!/usr/bin/env python3
"""PHASE A of scripts/PLAN_XBRL_FILER_FORMAT.md — sweep the NSE filing list for filer FORMAT.

WHY THIS EXISTS
  An `ebit` hole in sf_revop is either "this filer's format has no such line" (-> N/A) or "an
  industrial filer we failed to extract" (-> a real fill). build_revop.py::metrics_for() returns
  ebit=None for bank / NBFC / life-insurer / general-insurer formats and computes it only for
  industrial ones. Telling those apart per name is what this sweep feeds.

  ⚠️ It must NOT be decided from the pattern in our own sf_revop — that is the circular inference
  DATA_RUNBOOK §63 forbids (USER-CAUGHT; it was 63% wrong last time).

THE CHEAP ROUTE (measured 2026-08-16)
  No XBRL downloads are needed to get format. The per-symbol list returns, per FILING, a `bank`
  flag (B/F/N) and an `xbrl` URL whose FILENAME PREFIX is the format (BANKING_ / NBFC_INDAS_ /
  INDAS_ / NONINDAS_). ~127 calls total.

  ★ Format belongs to the FILING, not the company — BAJFINANCE's flag flips F/N in BOTH directions.
  Output is therefore keyed per (symbol, quarter-end, basis), never per symbol.

TRAPS THIS HANDLES (all measured, see the plan §3)
  - rows:0 is a DIAGNOSIS, never absence (§57a rule 1). SBILIFE / ICICIGI / SPICEJET all return 0
    and all certainly file. Logged as not-found-via:nse-list, never as "no filings".
  - Silent truncation: ABBOTINDIA returned 1 row against 31 quarters held. Short lists are flagged.
  - `xbrl` can be the literal string "-", not null. Truthy-test the VALUE.
  - Date-range queries silently return 0; only ?symbol=&period=Quarterly works.
  - The bare nseindia root 403s; warm the jar on the listing page.

USAGE
  python3 scripts/xbrl_format_sweep.py            # sweep every queue name (resumable)
  python3 scripts/xbrl_format_sweep.py SYM1 SYM2  # just these
  python3 scripts/xbrl_format_sweep.py --report   # re-emit outputs from cache, no network
"""
import gzip, http.cookiejar, json, os, re, socket, sys, time, urllib.parse, urllib.request

socket.setdefaulttimeout(30)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, 'docs')
CACHE = os.path.join(HERE, '_nse_list_cache')
os.makedirs(CACHE, exist_ok=True)
OUT_FMT = os.path.join(HERE, 'xbrl_filer_format.json')
OUT_REF = os.path.join(HERE, '_xbrl_format_refusals.json')

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
LIST_PAGE = 'https://www.nseindia.com/companies-listing/corporate-filings-financial-results'
API = ('https://www.nseindia.com/api/corporates-financial-results'
       '?index=equities&symbol=%s&period=Quarterly')
PAUSE = 1.6           # be polite; the whole sweep is ~127 calls
SHORT_LIST = 8        # fewer rows than this for a name we hold many quarters for = suspicious

JAR = None


def _get(url, hdr=None):
    req = urllib.request.Request(url, headers=hdr or {
        'User-Agent': UA, 'Accept': '*/*', 'Referer': LIST_PAGE})
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))
    r = op.open(req, timeout=30)
    d = r.read()
    if r.headers.get('Content-Encoding') == 'gzip':
        d = gzip.decompress(d)
    return d.decode('utf-8', 'replace')


def warm():
    """Fresh cookie jar. NOTE: the bare root 403s — warm on the listing page only (measured)."""
    global JAR
    JAR = http.cookiejar.CookieJar()
    try:
        _get(LIST_PAGE, hdr={'User-Agent': UA, 'Accept': 'text/html'})
    except Exception as e:
        print(f'   [warm failed: {type(e).__name__}]', flush=True)


PREFIX_RE = re.compile(r'/xbrl/([A-Za-z]+(?:_[A-Za-z]+)*)_\d')
# prefix / bank-flag -> the build_revop.py metrics_for() branch it implies.
# ⚠️ A filename convention is a HYPOTHESIS until Phase B tests it against the actual tags.
FORMAT_OF = {'BANKING': 'bank', 'NBFC_INDAS': 'nbfc', 'INDAS': 'industrial',
             'NONINDAS': 'industrial', 'INSURANCE': 'insurer'}
BANKFLAG_OF = {'B': 'bank', 'F': 'nbfc', 'N': 'industrial'}


def prefix_of(url):
    if not url or url.strip() in ('-', ''):
        return None
    m = PREFIX_RE.search(url)
    return m.group(1).upper() if m else None


def iso_qe(s):
    """'31-Dec-2024' -> 20241231"""
    M = {m: i for i, m in enumerate(
        ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}
    m = re.match(r'(\d{1,2})-([A-Za-z]{3})-(\d{4})', (s or '').strip())
    return int('%04d%02d%02d' % (int(m.group(3)), M[m.group(2).title()], int(m.group(1)))) if m else None


def fund_alias():
    src = open(os.path.join(DOCS, 'backtest-engine.js')).read()
    m = re.search(r'FUND_ALIAS\s*=\s*(\{.*?\})\s*;', src, re.S)
    if not m:
        return {}
    return json.loads(re.sub(r'(\w+)\s*:', r'"\1":', m.group(1)).replace("'", '"'))


def targets():
    q = json.load(open(os.path.join(HERE, 'n500_cov_queue.json')))
    return sorted({r['symbol'] for r in q['rows'] if r['param'] in ('ebit', 'op', 'rev')})


def fetch_symbol(sym):
    """-> (rows, err). Retries once with a fresh jar (the list API is cookie-gated and flaky)."""
    for attempt in (1, 2):
        try:
            raw = _get(API % urllib.parse.quote(sym, safe=''))
            j = json.loads(raw)
            if isinstance(j, dict):
                j = j.get('data') or []
            return (j if isinstance(j, list) else []), None
        except Exception as e:
            err = f'{type(e).__name__}: {str(e)[:80]}'
            if attempt == 1:
                warm()
                time.sleep(2.0)
            else:
                return None, err
    return None, 'unreachable'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    report_only = '--report' in sys.argv
    syms = args or targets()
    alias = fund_alias()
    revop = json.load(open(os.path.join(DOCS, 'sf_revop.json')))

    if not report_only:
        warm()
        print(f'sweeping {len(syms)} symbols (cache {CACHE})', flush=True)
        for i, s in enumerate(syms, 1):
            cf = os.path.join(CACHE, f'{re.sub(r"[^A-Z0-9]", "_", s.upper())}.json')
            if os.path.exists(cf):
                continue
            cands = [s] + ([alias[s]] if alias.get(s) else [])
            got, err, used = None, None, None
            for c in cands:
                rows, e = fetch_symbol(c)
                if rows:
                    got, used = rows, c
                    break
                err = e or err
                time.sleep(PAUSE)
            json.dump({'symbol': s, 'queried': cands, 'used': used,
                       'rows': got if got is not None else [],
                       'error': err, 'n': len(got or [])},
                      open(cf, 'w'))
            n = len(got or [])
            print(f'  {i:3d}/{len(syms)} {s:14s} rows={n:4d}{"  ERR " + err if err and not n else ""}', flush=True)
            time.sleep(PAUSE)

    # ---------------- build outputs from cache ----------------
    fmt, refusals = {}, []
    resolved = 0
    for s in syms:
        cf = os.path.join(CACHE, f'{re.sub(r"[^A-Z0-9]", "_", s.upper())}.json')
        if not os.path.exists(cf):
            refusals.append({'symbol': s, 'why': 'not-fetched', 'route': 'nse-list'})
            continue
        c = json.load(open(cf))
        rows = c.get('rows') or []
        held = len(revop.get(s) or revop.get(alias.get(s, ''), {}) or {})
        if not rows:
            # ⚠️ §57a rule 1 — a route with no rows is NOT evidence the filings do not exist.
            refusals.append({'symbol': s, 'why': 'zero-rows', 'route': 'not-found-via:nse-list',
                             'queried': c.get('queried'), 'error': c.get('error'),
                             'quarters_we_hold': held,
                             'note': 'NOT absence — escalate down the §57 ladder'})
            continue
        if held and len(rows) < min(SHORT_LIST, held):
            refusals.append({'symbol': s, 'why': 'short-list', 'route': 'nse-list',
                             'rows': len(rows), 'quarters_we_hold': held,
                             'note': 'possible silent truncation — verify before trusting'})
        per = {}
        for r in rows:
            qe = iso_qe(r.get('toDate'))
            if not qe:
                continue
            basis = 'con' if str(r.get('consolidated', '')).strip().lower() == 'consolidated' else 'std'
            pre = prefix_of(r.get('xbrl'))
            bf = (r.get('bank') or '').strip().upper()
            per.setdefault(str(qe), {})[basis] = {
                'bank': bf or None, 'prefix': pre,
                'fmt_by_prefix': FORMAT_OF.get(pre) if pre else None,
                'fmt_by_bankflag': BANKFLAG_OF.get(bf),
                'xbrl': r.get('xbrl') if (r.get('xbrl') or '').strip() not in ('-', '') else None,
                'filed': r.get('filingDate') or r.get('broadCastDate'),
            }
        if per:
            fmt[s] = per
            resolved += 1

    json.dump({'_doc': 'Phase A of PLAN_XBRL_FILER_FORMAT.md. Per (symbol, quarter-end, basis): the '
                       'NSE filing list\'s bank flag and XBRL filename prefix. fmt_by_* are '
                       'HYPOTHESES from a filename convention — Phase B must test them against the '
                       'actual XBRL tags that build_revop.py::metrics_for() branches on.',
               '_generated': time.strftime('%Y-%m-%d %H:%M IST'),
               'symbols': fmt}, open(OUT_FMT, 'w'), indent=1)
    json.dump({'_doc': 'Names this route could not answer for. A zero here is a DIAGNOSIS, never '
                       'absence (DATA_RUNBOOK §57a rule 1).',
               'refusals': refusals}, open(OUT_REF, 'w'), indent=1)

    # ---------------- the gate: name every unresolved symbol ----------------
    print(f'\nresolved {resolved} of {len(syms)}')
    if refusals:
        print(f'UNRESOLVED / SUSPECT: {len(refusals)}')
        for r in refusals:
            extra = f" rows={r.get('rows')}" if 'rows' in r else ''
            print(f"   {r['symbol']:14s} {r['why']:12s} held={r.get('quarters_we_hold', '?')}{extra}")
    print(f'\nwrote {OUT_FMT}\nwrote {OUT_REF}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
