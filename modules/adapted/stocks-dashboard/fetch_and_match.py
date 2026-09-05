#!/usr/bin/env python3
"""Staleness campaign (DATA_RUNBOOK §102/§103, PLAN_QUANTMAC_FIXES.md P2) — for every symbol in
target_list.json, fetch its full BSE announcement history over the target span and match each
target quarter-end to its REAL filing date, replacing apply_agg_pat_fills.py's quarter-end+45d
CONVENTION placeholder with the truth.

v3 (2026-08-20) — rewritten after the v2 full run's pre-apply audit (PLAN §E/§F/§G) found the v2
output unsafe to write. Four changes, each with a live proof case:

1. ★ LOOK-AHEAD FIX. v2 kept only a short intimation phrase-list and then took the EARLIEST
   candidate per quarter. An intimation ALWAYS precedes the result, so it won: PAGEIND qe20171231
   matched "Board Meeting On 08Th February 2018" (broadcast Jan 17) and would have stamped the
   results ~3 WEEKS early. Now every row is classified by the SHARED classify.py
   (result / secondary / intimation) and ranking is (class, then NEWS_DT) — a real result always
   beats a notice. Intimations are still COLLECTED (auditability, and they prove a quarter existed)
   but apply_redating.py refuses to write one.

2. ★ DATE EXTRACTION (classify.py). "Ended On", 2-digit years, and anchor-less quarter-end dates in
   results rows. Live proofs: SANWARIA "…Period Ended On 31.12.22" extracted nothing under v2;
   RANEHOLDIN's real row "Results - Financial Results March 31, 2024" also extracted nothing, so the
   NEXT-DAY newspaper ad won by default — which is why v2 produced 501 newspaper-sourced dates
   (472 of them late). Bug 4 was a SYMPTOM of this, not a separate defect.

3. SCRIPCODE CHAIN. v2 keyed on symbol == scrip_id twice and lost 251 symbols / 1,866 cells,
   including COLGATE (BSE "COLPAL"), CEAT ("CEATLTD"), TUBEINVEST ("TIINDIA"). Now:
   by_id -> master scrip_id -> NSE EQUITY_L symbol->ISIN -> normalized company name -> and then
   an explicit CLASSIFICATION of what is left ('nse-only' when the ISIN exists but no BSE code
   does; 'unresolved-alias' otherwise). Measured residue is reported, never guessed at.

4. ★ RAW-ROW CACHE. v2 stored only the winning match, so every matcher change cost another
   multi-hour BSE crawl — and worse, the audit could not even SEE the other dates in a row (my own
   "single-date" measurement was an artifact of that). Every candidate row is now written to
   raw_rows jsonl so any future matcher tweak re-matches OFFLINE in seconds.

The 15:30 IST gate, the future-date cap, the degenerate-response guard and the page cap are all
carried over from v2 unchanged — each was itself a live-found bug.

Output: {SYMBOL: {"matches": {"qe|basis": [news_dt, newssub, cls, [dates_in_row]]},
                  "candidates_seen": N, "scripcode": N|null, "scripcode_src": str|null,
                  "error": str|null}}
"""
import json, os, sys, time, datetime, csv, re
import urllib.request, urllib.error, gzip, http.cookiejar

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify import classify_row, row_dates          # THE shared rules — never re-implement

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TARGET_LIST = os.path.join(HERE, 'target_list.json')
OUT_PATH = os.path.join(HERE, 'fetch_results.json')
PROGRESS_PATH = os.path.join(HERE, 'progress.log')
RAW_PATH = os.path.join(HERE, 'raw_rows.jsonl')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/120 Safari/537.36')

CLASS_RANK = {'result': 0, 'secondary': 1, 'intimation': 2}


def _req(u, ref='https://www.bseindia.com/corporates/ann.html'):
    return urllib.request.Request(u, headers={'User-Agent': UA, 'Accept': '*/*',
                                              'Referer': ref, 'Origin': 'https://www.bseindia.com'})

_opener = None
def opener():
    global _opener
    if _opener is None:
        _opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        _opener.open(_req('https://www.bseindia.com/'), timeout=30).read()
    return _opener


def get(u, timeout=70):
    r = opener().open(_req(u), timeout=timeout)
    raw = r.read()
    if r.headers.get('Content-Encoding') == 'gzip':
        raw = gzip.decompress(raw)
    return raw.decode('utf-8', 'replace')


def get_json_retry(u, attempts=3, log=None):
    last = None
    for i in range(attempts):
        try:
            return json.loads(get(u, timeout=30))
        except Exception as e:
            last = e
            if log:
                log(f'    retry {i+1}/{attempts} after {type(e).__name__}: {e}')
            time.sleep(4 * (i + 1))
    raise last


def is_candidate(row):
    """Broad net: anything mentioning a result. Classification (and refusal) happens later —
    v2 dropped intimations here, which hid them from the audit AND from the ranking."""
    text = ((row.get('NEWSSUB') or '') + ' ' + (row.get('HEADLINE') or '')).lower()
    return 'result' in text


# ---------------------------------------------------------------- scripcode resolution chain
def _norm_name(x):
    x = (x or '').lower()
    x = re.sub(r'\b(ltd|limited|india|indian|the|company|co|corp|corporation|pvt|private|and|&)\b', ' ', x)
    return re.sub(r'[^a-z0-9]', '', x)


def load_scripcode_maps():
    by_id = json.load(open(os.path.join(ROOT, 'scripts', 'bse_scrips.json')))['by_id']
    by_isin = json.load(open(os.path.join(ROOT, 'scripts', 'bse_scrips.json')))['by_isin']
    master = json.load(open(os.path.join(ROOT, 'scripts', '_bse_master_all.json')))
    master_by_scripid, master_by_isin, master_by_name = {}, {}, {}
    for row in master:
        cd = row.get('SCRIP_CD')
        try:
            cd = int(cd)
        except (TypeError, ValueError):
            continue
        sid = row.get('scrip_id')
        if sid and sid not in master_by_scripid:
            master_by_scripid[sid] = cd
        isin = (row.get('ISIN_NUMBER') or '').strip()
        if isin and isin not in master_by_isin:
            master_by_isin[isin] = cd
        for f in ('Scrip_Name', 'Issuer_Name'):
            k = _norm_name(row.get(f))
            if k and k not in master_by_name:
                master_by_name[k] = cd
    # NSE EQUITY_L.csv: SYMBOL -> ISIN (fetched live 2026-08-20; nsearchives serves it even
    # though a www.nseindia.com warmup 403s — see memory feedback-a-wall-is-a-route)
    nse_isin, nse_name = {}, {}
    p = os.path.join(HERE, 'nse_equity_l.csv')
    if os.path.exists(p):
        for r in csv.DictReader(open(p)):
            sym = (r.get('SYMBOL') or '').strip()
            isin = (r.get(' ISIN NUMBER') or r.get('ISIN NUMBER') or '').strip()
            if sym:
                if isin:
                    nse_isin[sym] = isin
                nse_name[sym] = (r.get('NAME OF COMPANY') or '').strip()
    # our own symbol -> company name (docs/search_index.json), for the name bridge
    sym_name = {}
    sp = os.path.join(ROOT, 'docs', 'search_index.json')
    if os.path.exists(sp):
        for row in json.load(open(sp)).get('s', []):
            if isinstance(row, list) and len(row) >= 2:
                sym_name[row[0]] = row[1]
    return {'by_id': by_id, 'by_isin': by_isin, 'm_scripid': master_by_scripid,
            'm_isin': master_by_isin, 'm_name': master_by_name,
            'nse_isin': nse_isin, 'nse_name': nse_name, 'sym_name': sym_name}


def resolve_scripcode(sym, M):
    """-> (scripcode|None, source_label). Never guesses: an unresolved symbol is CLASSIFIED
    ('nse-only' when it has an ISIN that no BSE map knows) so the residue is measurable."""
    if sym in M['by_id']:
        return M['by_id'][sym], 'by_id'
    if sym in M['m_scripid']:
        return M['m_scripid'][sym], 'master_scripid'
    isin = M['nse_isin'].get(sym)
    if isin:
        cd = M['by_isin'].get(isin) or M['m_isin'].get(isin)
        if cd:
            return int(cd), 'nse_isin'
    for nm in (M['sym_name'].get(sym), M['nse_name'].get(sym)):
        k = _norm_name(nm)
        if k and k in M['m_name']:
            return M['m_name'][k], 'name_bridge'
    if isin:
        return None, 'nse-only'          # listed on NSE, absent from every BSE map
    return None, 'unresolved-alias'


MAX_PAGES_PER_SYMBOL = 120


def fetch_symbol_rows(scripcode, d1, d2, log=None):
    today = datetime.date.today().strftime('%Y%m%d')
    if d2 > today:
        d2 = today
    out, page = [], 1
    while True:
        if log:
            log(f'    page {page} (d1={d1} d2={d2})')
        u = ('https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?'
             f'pageno={page}&strCat=-1&strPrevDate={d1}&strToDate={d2}'
             f'&strScrip={scripcode}&strSearch=P&strType=C&subcategory=-1')
        j = get_json_retry(u, log=log)
        tbl = j.get('Table', []) or []
        t1 = j.get('Table1', [])
        if not t1 and tbl:
            raise RuntimeError(f'degenerate BSE response (Table1 empty, {len(tbl)} null-ish rows) '
                               f'at page {page} d1={d1} d2={d2}')
        total = (t1[0].get('ROWCNT') if t1 else 0) or 0
        for row in tbl:
            if is_candidate(row):
                out.append(row)
        if not tbl or page * 50 >= total:
            break
        page += 1
        if page > MAX_PAGES_PER_SYMBOL:
            raise RuntimeError(f'page cap exceeded (total={total} rows)')
    return out


def match_targets(rows, targets):
    """Index every row under EVERY date it mentions, then per target quarter pick the best
    candidate: a real result outranks a re-publication, which outranks a notice; within a class
    the EARLIEST broadcast wins (first public disclosure is what a backtest could have seen)."""
    enriched = []
    for row in rows:
        sub, head = row.get('NEWSSUB') or '', row.get('HEADLINE') or ''
        cls = classify_row(sub, head)
        dates = row_dates(row, cls)
        enriched.append((row, cls, dates))
    by_qe = {}
    for row, cls, dates in enriched:
        for qe in dates:
            by_qe.setdefault(qe, []).append((row, cls, dates))
    matches = {}
    for qe, basis, _old in targets:
        cands = by_qe.get(qe)
        if not cands:
            continue
        basis_word = 'standalone' if basis == 'std' else 'consolidated'

        def _key(c):
            # CLASS FIRST. v3's first cut pre-filtered on the basis word and only then ranked by
            # class, which let RANEHOLDIN's newspaper ad beat the real filing purely because the
            # ad's headline happened to read "(standalone & consolidated)". A genuine result with
            # no basis word must always outrank a re-publication that has one.
            row_, cls_, _ = c
            txt = ((row_.get('NEWSSUB') or '') + (row_.get('HEADLINE') or '')).lower()
            return (CLASS_RANK.get(cls_, 9), 0 if basis_word in txt else 1,
                    row_.get('NEWS_DT') or '9999')

        row, cls, dates = min(cands, key=_key)
        matches[f'{qe}|{basis}'] = [row.get('NEWS_DT'), row.get('NEWSSUB'), cls, sorted(dates)]
    return matches


def main(target_list_path=TARGET_LIST, out_path=OUT_PATH, progress_path=PROGRESS_PATH,
         raw_path=RAW_PATH, limit=None):
    targets = json.load(open(target_list_path))
    M = load_scripcode_maps()
    results = json.load(open(out_path)) if os.path.exists(out_path) else {}
    symbols = list(targets.keys())
    if limit:
        symbols = symbols[:limit]

    def log(msg):
        with open(progress_path, 'a') as f:
            f.write(f'{datetime.datetime.now().isoformat()} {msg}\n')

    done, t0 = 0, time.time()
    for sym in symbols:
        if sym in results:
            continue
        log(f'START {sym} ({done+1}/{len(symbols)})')
        rows_targets = targets[sym]
        scripcode, src = resolve_scripcode(sym, M)
        entry = {'scripcode': scripcode, 'scripcode_src': src, 'candidates_seen': 0,
                 'matches': {}, 'error': None}
        if scripcode is None:
            entry['error'] = src                      # 'nse-only' | 'unresolved-alias'
            log(f'  SKIP {sym}: {src}')
        else:
            qes = [r[0] for r in rows_targets]
            d1 = (datetime.date(qes[0] // 10000, (qes[0] // 100) % 100, qes[0] % 100)
                  - datetime.timedelta(days=10)).strftime('%Y%m%d')
            d2 = (datetime.date(qes[-1] // 10000, (qes[-1] // 100) % 100, qes[-1] % 100)
                  + datetime.timedelta(days=120)).strftime('%Y%m%d')
            try:
                rows = fetch_symbol_rows(scripcode, d1, d2, log=log)
                entry['candidates_seen'] = len(rows)
                entry['matches'] = match_targets(rows, rows_targets)
                with open(raw_path, 'a') as rf:       # F4: never crawl twice for a matcher tweak
                    rf.write(json.dumps({'sym': sym, 'scripcode': scripcode, 'rows': rows},
                                        separators=(',', ':')) + '\n')
                log(f'  DONE {sym}: {len(rows)} candidates, '
                    f'{len(entry["matches"])}/{len(rows_targets)} matched')
            except Exception as e:
                entry['error'] = f'{type(e).__name__}: {e}'
                log(f'  FAILED {sym}: {entry["error"]}')
        results[sym] = entry
        done += 1
        if done % 5 == 0 or done == len(symbols):
            json.dump(results, open(out_path, 'w'))
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta_min = ((len(symbols) - done) / rate / 60) if rate > 0 else -1
            log(f'CHECKPOINT done={done}/{len(symbols)} rate={rate:.2f}/s eta_min={eta_min:.1f}')
        time.sleep(0.3)
    json.dump(results, open(out_path, 'w'))
    with open(progress_path, 'a') as f:
        f.write(f'{datetime.datetime.now().isoformat()} COMPLETE done={len(results)}\n')


if __name__ == '__main__':
    main()
