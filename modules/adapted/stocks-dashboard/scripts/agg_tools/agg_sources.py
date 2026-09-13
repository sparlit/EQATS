import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# -*- coding: utf-8 -*-
"""Aggregator readers for QUARTERLY REVENUE / PAT -- Moneycontrol, Trendlyne, Tickertape.

Sibling of the screener.in route (runbook §60). Same discipline, three more independent-ish
readers. Every endpoint below was DISCOVERED by loading the site in a browser and reading the
requests the page itself makes (memory: feedback-find-endpoints-in-js-bundle) -- none was guessed.
Full spec + how each was found: runbook §80.

  MC  page  https://www.moneycontrol.com/financials/<slug>/results/quarterly-results/<sc_id>
      XHR   https://appfeeds.moneycontrol.com/jsonapi/stocks/quarterly_results_responsive
                ?sc_id=<sc_id>&type_format=<quarterly|cons_quarterly>&start=0&limit=200
      quarterly=STANDALONE, cons_quarterly=CONSOLIDATED. No cookies, no Referer needed.
      Period key `yrc0` prints as "Jun '26".
  TL  page  https://trendlyne.com/fundamentals/financials/<tid>/<SYM>/<slug>/
      XHR   the page's <main id="fundamental_tables" data-tablesurl="..."> ->
            https://trendlyne.com/fundamentals/get-fundamental_results-v2/<tid>/<B32TOKEN>/
      REQUIRES the page's session cookie (csrftoken) + X-Requested-With + Referer; without them
      the host answers HTTP 444 and closes. Body carries BOTH bases in one payload.
  TT  page  https://www.tickertape.in/stocks/<slug>-<sid>   -> __NEXT_DATA__ props.pageProps
            keys "income-normal-interim" (quarters) / "income-normal-annual" (FYs).
      XHR   https://api.tickertape.in/stocks/financials/income/<sid>/<interim|annual>/normal?count=N
            ** api.tickertape.in/robots.txt is `User-agent: * / Disallow: /` -- MEASURED
            2026-08-11. This module therefore NEVER fetches that host; the spec is recorded because
            the task was to discover it, and the page route above serves the same rows (fewer of
            them: 10 quarters vs the API's 40). Set AGG_TT_API=1 only if that robots ever changes.

PACING is the site's own number, not mine: trendlyne.com/robots.txt sets `Crawl-delay: 10` for
ClaudeBot BY NAME (the repo already honours this in fetch_shp_seam_trendlyne.py); moneycontrol and
www.tickertape.in publish no crawl-delay, so 1.0s.

ID RESOLUTION IS GATED, never a name guess (memory: feedback-scrip-id-ticker-coincidence):
  MC  autosuggestion_solr rows print "<ISIN>, <NSE SYMBOL>, <BSE code>" -- we accept only the row
      whose SYMBOL token equals ours exactly. (MOIL's top two hits are IOC and Oil India.)
  TL  the fundamental sitemap URLs are literally /<tid>/<NSE SYMBOL>/<slug>/ -- exact symbol key.
  TT  the stocks sitemap gives slug-sid but no ticker, so the fetched page must report
      securityInfo.info.ticker == our symbol or the resolution is rejected.

Nothing here writes anything. Values are returned as the site prints them; the caller must run
agg_gate before a single number reaches a ledger.
"""
import contextlib
import gzip
import html as html_lib
import json
import os
import re
import sys
import time
from urllib.parse import quote

from curl_cffi import requests as cr

CACHE = os.path.join(os.path.expanduser("~"), ".cache", "agg_reader")
TL_PACE = 10.0  # trendlyne robots.txt Crawl-delay for ClaudeBot
MC_PACE = 1.0
TT_PACE = 1.0
UA_HDR = {"Accept-Language": "en-US,en;q=0.9"}
_LAST = {}
_SESS = {}


# ---------------------------------------------------------------- transport


def _pace(host, secs):
    t = _LAST.get(host)
    if t is not None:
        wait = secs - (time.time() - t)
        if wait > 0:
            time.sleep(wait)
    _LAST[host] = time.time()


def _sess(host):
    if host not in _SESS:
        _SESS[host] = cr.Session(impersonate="chrome")
    return _SESS[host]


def _cache_path(site, key):
    d = os.path.join(CACHE, site)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, re.sub(r"[^A-Za-z0-9._-]", "_", key) + ".gz")


def _cached(site, key, ttl=86400 * 3):
    p = _cache_path(site, key)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < ttl:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return f.read()
    return None


def _store(site, key, text):
    with gzip.open(_cache_path(site, key), "wt", encoding="utf-8") as f:
        f.write(text)


def _get(host, url, pace, site, key, ttl=86400 * 3, headers=None, sess=None, tries=3):
    """Disk-cached GET. Returns text, or None when the site never answered 200."""
    hit = _cached(site, key, ttl)
    if hit is not None:
        return hit
    s = sess or _sess(host)
    for attempt in range(tries):
        _pace(host, pace)
        try:
            r = s.get(url, timeout=45, headers=dict(UA_HDR, **(headers or {})))
        except Exception:
            _SESS.pop(host, None)
            s = sess or _sess(host)
            continue
        if r.status_code == 404:
            return None  # a real absence on this site, do not retry
        if r.status_code != 200:
            time.sleep(2.0 * (attempt + 1))  # 444/429/5xx -> transport, per §61a mode 4
            continue
        _store(site, key, r.text)
        return r.text
    return None


# ---------------------------------------------------------------- period keys

_MON = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_LASTDAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def qe_from_label(lbl):
    """\"Jun '26\" / \"Jun 2026\" / \"JUN 2026\" -> 20260630. None when it is not a month-end period.

    Only 2-digit-year forms need the century rule; a site printing "Dec '98" means 1998.
    February is normalised to the 28th because our quarter keys never use Feb -- any Feb label is
    a non-standard period and is dropped by the caller's quarter-end filter anyway.
    """
    if not lbl:
        return None
    m = re.match(r"^\s*([A-Za-z]{3})[a-z]*\.?\s*'?(\d{2,4})\s*$", str(lbl))
    if not m:
        return None
    mon = _MON.get(m.group(1).lower())
    if not mon:
        return None
    y = int(m.group(2))
    if y < 100:
        # A fixed pivot ("<90 => 2000s") sent KENNAMET's real Dec-1989 annual column to 2089.
        # Anchor on the clock instead: nothing in a results table is dated past next year.
        y += 2000
        if y > time.gmtime().tm_year + 1:
            y -= 100
    return y * 10000 + mon * 100 + _LASTDAY[mon]


def _num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "--", "-", "N.A.", "NA", "nan", "None"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        f = float(s)
    except ValueError:
        return None
    return -f if neg else f


# ---------------------------------------------------------------- MONEYCONTROL

MC_SUGGEST = (
    "https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php?classic=true&query=%s&type=1&format=json"
)
MC_FEED = (
    "https://appfeeds.moneycontrol.com/jsonapi/stocks/quarterly_results_responsive"
    "?sc_id=%s&type_format=%s&start=0&limit=200"
)
_MC_IDS = None
_MC_IDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_agg_ids_mc.json")


def mc_id(sym):
    """-> {"sc_id","isin","bse","name"} or None. Accepts ONLY an exact NSE-symbol token match."""
    global _MC_IDS
    if _MC_IDS is None:
        _MC_IDS = json.load(open(_MC_IDS_PATH)) if os.path.exists(_MC_IDS_PATH) else {}
    if sym in _MC_IDS:
        return _MC_IDS[sym] or None
    # ⚠️ URL-ENCODE THE SYMBOL. `MC_SUGGEST % sym` on M&M sent `...&query=M&M&type=1`, so the
    # server saw query=M and the exact-symbol gate below never matched -- absence manufactured by
    # our own request (measured 2026-08-12: M&M and J&KBANK both came back "no exact symbol match";
    # encoded they resolve to sc_id MM and JKB). Memory: feedback-url-encode-symbol-queries.
    # Cache key bumped to sugg1_ so bodies fetched with the broken URL are not replayed.
    txt = _get("www.moneycontrol.com", MC_SUGGEST % quote(sym, safe=""), MC_PACE, "mc", "sugg1_" + sym, ttl=86400 * 30)
    hit = None
    if txt:
        try:
            rows = json.loads(txt)
        except ValueError:
            rows = []
        for r in rows if isinstance(rows, list) else []:
            dis = re.sub(r"<[^>]+>", "", (r.get("pdt_dis_nm") or "")).replace("&nbsp;", " ")
            m = re.search(r"(INE[0-9A-Z]{9}|IN[0-9A-Z]{10})\s*,\s*([A-Z0-9&_-]+)\s*,\s*(\d*)", dis)
            if not m or m.group(2) != sym:
                continue  # symbol token must be OURS, exactly
            # TWO codes come back and they are NOT interchangeable: the `sc_id` FIELD is the feed
            # key, while the code at the end of link_src is a legacy/SEO code that answers the
            # feed with 0 rows and no error (§61a mode 4 -- absence dressed as a 200). Measured
            # 2026-08-11: SPICEJET link=SJ01 -> 0 rows, sc_id=ML04 -> 73; MOIL M18 -> 0, M11 -> 67;
            # ALOKINDS AI54 -> 0, ATI -> 74. WESTLIFE happens to have both equal to DIC, which is
            # exactly how a wrong preference survives a one-company smoke test.
            sc = r.get("sc_id") or ""
            link = r.get("link_src") or ""
            lm = re.search(r"/([A-Z0-9]+)/?$", link)
            hit = {
                "sc_id": sc or (lm.group(1) if lm else ""),
                "sc_id_link": lm.group(1) if lm else "",
                "isin": m.group(1),
                "bse": m.group(3),
                "name": r.get("stock_name") or "",
            }
            break
    _MC_IDS[sym] = hit
    json.dump(_MC_IDS, open(_MC_IDS_PATH, "w"), indent=0, sort_keys=True)
    return hit


MC_ROWS = {
    # our field -> the MC row labels that could hold it, most specific first
    "rev_ops": ("Net Sales/Income from operations", "Interest Earned"),
    "rev_total": ("Total Income From Operations",),
    "pat_total": ("Net Profit/(Loss) For the Period", "P/L After Tax from Ordinary Activities"),
    "pat_own": ("Net P/L After M.I & Associates",),
    # ---- op / ebit (added 2026-08-12) -------------------------------------------------------
    # build_revop.py defines ebit = PBET + FinanceCosts - OtherIncome, i.e. operating profit AFTER
    # depreciation and BEFORE other income -- which is exactly what MC's "P/L Before Other Inc.,
    # Int., Excpt. Items & Tax" row is. `op` is Trendlyne's "Oper Profit" (paisa-matched, runbook
    # ~L900) = the same figure with depreciation added back, so it is DERIVED below, not a row.
    # ⚠️ THE LABEL DIFFERS BY ONE CHARACTER BETWEEN THE TWO PAYLOADS: the standalone table prints
    # "Other Inc. , Int." (space before the comma) and the consolidated one "Other Inc., Int.";
    # depreciation is "depreciat" standalone and "Depreciation" consolidated. Hardcoding either
    # spelling makes the other basis read as "this site has no such row" -- absence dressed as a
    # clean miss (§61a mode 4). Both spellings are candidates; Gate D still has to prove the row.
    "ebit_pre": ("P/L Before Other Inc. , Int., Excpt. Items & Tax", "P/L Before Other Inc., Int., Excpt. Items & Tax"),
    "ebit_post": ("P/L Before Int., Excpt. Items & Tax",),
    "dep": ("depreciat", "Depreciation"),
}

# Derived candidates: field -> (base, addend). Scored by the gate exactly like a printed row, so a
# company whose depreciation treatment does not reproduce our series is rejected, not "close enough".
MC_DERIVED = {
    "op_pre": ("ebit_pre", "dep"),
    "op_post": ("ebit_post", "dep"),
    # ★ THE TOP-DOWN SUBTOTAL (2026-09-05). MC's rows before 2008 print `--` for every P/L subtotal
    # ("P/L Before Other Inc...", "Total Income From Operations") while carrying every component
    # line, so op_pre simply does not exist there (~1,400 quarterly rows per year 1998-2007, measured).
    # ebit_der rebuilds that subtotal from the lines that ARE printed:
    #     ebit_der = Net Profit + Tax + Interest - Other Income - Exceptional - Extraordinary - Prior-yr adj
    # VALIDATED against MC's own printed subtotal wherever both exist: exact (<=0.011) on 49,526 of
    # 49,898 quarterly rows (99.25%) and 15,387 of 15,525 annual rows (99.11%), 2008-2026, all
    # resolved N500-era symbols. The bottom-up sum of expense lines scored 97.3%, adding the
    # adjustments back instead of subtracting scored 91.5% -- so this is the measured form, not a
    # guessed one. It is a CANDIDATE like the others: the gate still has to reproduce our stored
    # values with it (E1 anchors on the company's own 2018+ rows) before a derived cell is written.
    "op_der": ("ebit_der", "dep"),
}
# Lines the top-down subtotal is built from (label -> sign). Absent lines count as 0 -- a `--` on
# MC is "no such line in this filing", and the 99.25% above was measured with exactly that rule.
MC_TOPDOWN = (
    ("Net Profit/(Loss) For the Period", +1),
    ("Tax", +1),
    ("Interest", +1),
    ("Other Income", -1),
    ("Exceptional Items", -1),
    ("Extra Ordinary Items", -1),
    ("Prior Year Adjustments", -1),
)


def mc_row_values(r):
    """{field: value, field_label: label} for ONE MC row -- printed rows, then every derived field.
    The single place the four MC readers (quarterly/annual x symbol/era) take their values from, so
    a candidate added here exists in all of them at once (the era readers used to lack MC_DERIVED
    entirely, which made every op cell on an ISIN-resolved symbol read as NOT-FOUND)."""
    vals = {}
    for field, labels in MC_ROWS.items():
        for lbl in labels:
            if lbl in r:
                v = _num(r[lbl])
                if v is not None:
                    vals[field] = v
                    vals[field + "_label"] = lbl
                    break
    pat = _num(r.get("Net Profit/(Loss) For the Period")) if "Net Profit/(Loss) For the Period" in r else None
    if pat is not None:
        tot = 0.0
        for lbl, sign in MC_TOPDOWN:
            v = _num(r[lbl]) if lbl in r else None
            tot += sign * (v or 0.0)
        vals["ebit_der"] = round(tot, 2)
        vals["ebit_der_label"] = "derived: PAT+Tax+Interest-OtherInc-Exceptional-ExtraOrd-PriorYrAdj"
    for field, (base, add) in MC_DERIVED.items():
        if vals.get(base) is not None and vals.get(add) is not None:
            vals[field] = round(vals[base] + vals[add], 2)
            vals[field + "_label"] = "{} + {}".format(vals[base + "_label"], vals[add + "_label"])
    return vals


def mc_quarters(sym, con):
    """-> ({qe:{field:value}}, note). Empty dict + note when the site has no such table."""
    ident = mc_id(sym)
    if not ident:
        return {}, "mc: no exact symbol match in autosuggest"
    tf = "cons_quarterly" if con else "quarterly"
    txt = _get(
        "appfeeds.moneycontrol.com", MC_FEED % (ident["sc_id"], tf), MC_PACE, "mc", "q_{}_{}".format(ident["sc_id"], tf)
    )
    if txt is None:
        return {}, "mc: BLOCKED-TRANSPORT (no 200 after retries)"
    try:
        rows = (json.loads(txt) or {}).get("data") or []
    except ValueError:
        return {}, "mc: unparseable body"
    if not isinstance(rows, list) or not rows:
        return {}, f"mc: empty {tf} table"
    out, dupes = {}, set()
    for r in rows:
        qe = qe_from_label(r.get("yrc0"))
        if qe is None or qe % 10000 not in (331, 630, 930, 1231):
            continue
        if qe in out:
            dupes.add(qe)  # restated duplicate column -> ambiguous, drop
            continue
        vals = mc_row_values(r)
        if vals:
            out[qe] = vals
    for qe in dupes:
        out.pop(qe, None)
    return out, "mc: %d quarters %s..%s%s" % (
        len(out),
        min(out, default="-"),
        max(out, default="-"),
        (" (%d duplicate period(s) dropped)" % len(dupes)) if dupes else "",
    )


# ---------------------------------------------------------------- TRENDLYNE

_TL_IDS = None
_TL_IDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_agg_ids_tl.json")
TL_SITEMAP = "https://trendlyne.com/fundamental-sitemap-quarter-result.xml"


def _tl_unescape(m):
    """Heal a cached id map written before the unescape fix -- `_agg_ids_tl.json` is committed and
    has a 14-day TTL, so without this the stale escaped keys would keep answering for two weeks."""
    return {html_lib.unescape(k): v for k, v in (m or {}).items()}


def tl_ids(refresh=False):
    """{SYMBOL: [tid, slug]} straight off Trendlyne's own sitemap -- the URLs key on NSE symbol."""
    global _TL_IDS
    if _TL_IDS is not None and not refresh:
        return _TL_IDS
    if os.path.exists(_TL_IDS_PATH) and not refresh:
        _TL_IDS = _tl_unescape(json.load(open(_TL_IDS_PATH)))
        return _TL_IDS
    txt = _get("trendlyne.com", TL_SITEMAP, TL_PACE, "tl", "sitemap_qr", ttl=86400 * 14)
    m = {}
    for tid, s, slug in re.findall(
        r"<loc>https://trendlyne\.com/fundamentals/financials/(\d+)/([^/]+)/([^/]*)/</loc>", txt or ""
    ):
        # ★ THE SITEMAP IS XML, SO `&` ARRIVES AS `&amp;` (2026-08-26). Keying the map on the raw
        # match stored `M&amp;M`, and every caller passes our clean `M&M` -- so all ten ampersand
        # tickers (M&M, M&MFIN, J&KBANK, GVT&D, ARE&M, IL&FSENGG, IL&FSTRANS, S&SPOWER, SURANAT&P,
        # GMRP&UI) fell straight through to "symbol absent from trendlyne fundamental sitemap".
        # A refusal is only as good as its flag: that one claimed the SOURCE had no row when in
        # fact we had never looked it up. This is the same escape that produced the `M&AMP;M`
        # phantom keys retracted in runbook §114 -- there the escaped string became a store key,
        # here it became a lookup key; unescape at the source in both cases.
        m.setdefault(html_lib.unescape(s), [int(tid), slug])
    if m:
        _TL_IDS = m
        json.dump(m, open(_TL_IDS_PATH, "w"), indent=0, sort_keys=True)
    return _TL_IDS or {}


TL_ROWS = {
    "rev_ops": ("SR_Q",),  # = OperatingIncome + OtherOperatingIncome
    "rev_total": ("TOTAL_SR_Q",),  # incl. other income; banks: interest+other income
    "pat_total": ("NP_Q", "PL_After_TaxFromOrdineryActivities_Q"),
    "pat_own": ("NetPLAfterMIAssociates_Q",),
}


def tl_quarters(sym, con):
    ids = tl_ids()
    if sym not in ids:
        return {}, "tl: symbol absent from trendlyne fundamental sitemap"
    tid, slug = ids[sym]
    page_url = "https://trendlyne.com/fundamentals/financials/%d/%s/%s/" % (tid, sym, slug)
    sess = _sess("trendlyne.com")
    page = _get("trendlyne.com", page_url, TL_PACE, "tl", f"page_{sym}", sess=sess)
    if page is None:
        return {}, "tl: BLOCKED-TRANSPORT on the company page"
    m = re.search(r'data-tablesurl="([^"]+)"', page)
    if not m:
        return {}, "tl: page has no data-tablesurl (layout changed?)"
    api = m.group(1)
    if not sess.cookies.get("csrftoken"):
        # the API 444s without the page's session; force a live page hit to mint the cookie
        _pace("trendlyne.com", TL_PACE)
        with contextlib.suppress(Exception):
            sess.get(page_url, timeout=45, headers=UA_HDR)
    txt = _get(
        "trendlyne.com",
        api,
        TL_PACE,
        "tl",
        f"api_{sym}",
        sess=sess,
        headers={"X-Requested-With": "XMLHttpRequest", "Referer": page_url, "Accept": "*/*"},
    )
    if txt is None:
        return {}, "tl: BLOCKED-TRANSPORT on get-fundamental_results-v2 (444 without session?)"
    try:
        body = (json.loads(txt) or {}).get("body") or {}
    except ValueError:
        return {}, "tl: unparseable body"
    dump = (body.get("quarterlyDataDump") or {}).get("consolidated" if con else "standalone") or {}
    out = {}
    for lbl, row in dump.items():
        qe = qe_from_label(lbl)
        if qe is None or qe % 10000 not in (331, 630, 930, 1231):
            continue
        vals = {}
        for field, keys in TL_ROWS.items():
            for k in keys:
                if row.get(k) is not None:
                    v = _num(row[k])
                    if v is not None:
                        vals[field] = v
                        vals[field + "_label"] = k
                        break
        if vals:
            out[qe] = vals
    return out, "tl: %d quarters %s..%s" % (len(out), min(out, default="-"), max(out, default="-"))


# ---------------------------------------------------------------- TICKERTAPE

_TT_IDS = None
_TT_IDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_agg_ids_tt.json")
TT_SITEMAP = "https://www.tickertape.in/sitemaps/stocks/sitemap.xml"
TT_ROWS = {"rev_total": ("qIncTrev",), "pat_total": ("qIncNinc",)}


def _tt_slugs(refresh=False):
    txt = _get("www.tickertape.in", TT_SITEMAP, TT_PACE, "tt", "sitemap_stocks", ttl=86400 * 14)
    return re.findall(r"<loc>https://www\.tickertape\.in/stocks/([^<]+)</loc>", txt or "")


def _tt_props(slug):
    txt = _get("www.tickertape.in", f"https://www.tickertape.in/stocks/{slug}", TT_PACE, "tt", f"page_{slug}")
    if txt is None:
        return None
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', txt, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))["props"]["pageProps"]
    except Exception:
        return None


def tt_resolve(sym, name_hint=""):
    """slug whose PAGE reports securityInfo.info.ticker == sym. A name match alone is a guess."""
    global _TT_IDS
    if _TT_IDS is None:
        _TT_IDS = json.load(open(_TT_IDS_PATH)) if os.path.exists(_TT_IDS_PATH) else {}
    if sym in _TT_IDS:
        return _TT_IDS[sym] or None
    if not name_hint:
        # a company NAME is only used to shortlist candidates; the ticker check below is the gate,
        # so borrowing the name from the other two sites cannot introduce a wrong binding.
        ids = tl_ids()
        name_hint = ids[sym][1].replace("-", " ") if sym in ids else (mc_id(sym) or {}).get("name") or ""
    slugs = _tt_slugs()
    toks = [
        t
        for t in re.split(r"[^a-z0-9]+", (name_hint or "").lower())
        if len(t) > 2 and t not in ("ltd", "limited", "the", "india", "and", "company", "corporation", "industries")
    ]
    cands = []
    for s in slugs:
        base = s.rsplit("-", 1)[0].lower()
        score = sum(1 for t in toks if t in base)
        if score:
            cands.append((score, len(base), s))
    cands.sort(key=lambda x: (-x[0], x[1]))
    hit = None
    for _, _, slug in cands[:6]:
        p = _tt_props(slug)
        tk = (((p or {}).get("securityInfo") or {}).get("info") or {}).get("ticker")
        if tk == sym:
            hit = slug
            break
    _TT_IDS[sym] = hit
    json.dump(_TT_IDS, open(_TT_IDS_PATH, "w"), indent=0, sort_keys=True)
    return hit


def tt_quarters(sym, con, name_hint=""):
    """Tickertape carries ONE basis per company -- whatever `reporting` on the rows says.

    So `con` is not a request parameter here: it is a filter. Rows whose declared reporting is not
    the basis asked for are dropped, and the note says so. (Measured 2026-08-11: the API's `view`
    dimension is normal|margin|growth, i.e. presentation, not basis.)
    """
    slug = tt_resolve(sym, name_hint)
    if not slug:
        return {}, f"tt: no page whose ticker equals {sym}"
    if os.environ.get("AGG_TT_API") == "1":
        sid = slug.rsplit("-", 1)[-1]
        txt = _get(
            "api.tickertape.in",
            f"https://api.tickertape.in/stocks/financials/income/{sid}/interim/normal?count=100",
            TT_PACE,
            "tt",
            f"api_{sid}",
        )
        rows = ((json.loads(txt) or {}).get("data") or []) if txt else []
        src = "api"
    else:
        p = _tt_props(slug)
        rows = (p or {}).get("income-normal-interim") or []
        src = "page"
    want = "consolidated" if con else "standalone"
    out, other = {}, set()
    for r in rows:
        rep = (r.get("reporting") or "").lower()
        end = r.get("endDate") or ""
        qe = None
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(end))
        if m:
            qe = int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))
        if qe is None or qe % 10000 not in (331, 630, 930, 1231):
            continue
        if rep != want:
            other.add(rep or "?")
            continue
        vals = {}
        for field, keys in TT_ROWS.items():
            for k in keys:
                if r.get(k) is not None:
                    vals[field] = float(r[k])
                    vals[field + "_label"] = k
                    break
        if vals:
            out[qe] = vals
    note = "tt(%s): %d quarters %s..%s" % (src, len(out), min(out, default="-"), max(out, default="-"))
    if other:
        note += "; company reports {} only".format("/".join(sorted(other)))
    return out, note


# ---------------------------------------------------------------- ANNUAL (the §60d lever)

MC_YEAR = (
    "https://appfeeds.moneycontrol.com/jsonapi/stocks/yearly_results_responsive"
    "?sc_id=%s&type_format=%s&start=0&limit=200"
)


def mc_annuals(sym, con):
    ident = mc_id(sym)
    if not ident:
        return {}, "mc: no exact symbol match in autosuggest"
    tf = "cons_yearly" if con else "yearly"
    txt = _get(
        "appfeeds.moneycontrol.com", MC_YEAR % (ident["sc_id"], tf), MC_PACE, "mc", "y_{}_{}".format(ident["sc_id"], tf)
    )
    if txt is None:
        return {}, "mc: BLOCKED-TRANSPORT"
    try:
        rows = (json.loads(txt) or {}).get("data") or []
    except ValueError:
        return {}, "mc: unparseable body"
    out = {}
    for r in rows if isinstance(rows, list) else []:
        qe = qe_from_label(r.get("yrc0"))
        if qe is None:
            continue
        # the same derivation as the quarterly table, so Gate A5's FY identity can be run on
        # op/ebit as well -- an annual table missing the derived field is a silent NO-TEST (§81e)
        vals = mc_row_values(r)
        if vals:
            out.setdefault(qe, vals)
    return out, "mc: %d FYs %s..%s" % (len(out), min(out, default="-"), max(out, default="-"))


def tl_annuals(sym, con):
    _q, note = tl_quarters(sym, con)  # primes the cache; payload holds both tables
    ids = tl_ids()
    if sym not in ids:
        return {}, note
    txt = _cached("tl", f"api_{sym}")
    if txt is None:
        return {}, "tl: annual payload not cached (quarterly read failed first)"
    try:
        body = (json.loads(txt) or {}).get("body") or {}
    except ValueError:
        return {}, "tl: unparseable body"
    dump = (body.get("annualDataDump") or {}).get("consolidated" if con else "standalone") or {}
    out = {}
    for lbl, row in dump.items():
        qe = qe_from_label(lbl)  # "TTM" and friends fall out here
        if qe is None:
            continue
        vals = {}
        for field, keys in TL_ROWS.items():
            for k in keys:
                kk = k.replace("_Q", "_A")
                for cand in (kk, k):
                    if row.get(cand) is not None and _num(row[cand]) is not None:
                        vals[field] = _num(row[cand])
                        vals[field + "_label"] = cand
                        break
                if field in vals:
                    break
        if vals:
            out[qe] = vals
    return out, "tl: %d FYs %s..%s" % (len(out), min(out, default="-"), max(out, default="-"))


def tt_annuals(sym, con, name_hint=""):
    slug = tt_resolve(sym, name_hint)
    if not slug:
        return {}, f"tt: no page whose ticker equals {sym}"
    p = _tt_props(slug)
    rows = (p or {}).get("income-normal-annual") or []
    want = "consolidated" if con else "standalone"
    out, other = {}, set()
    for r in rows:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(r.get("endDate") or ""))
        if not m:
            continue
        qe = int(m.group(1)) * 10000 + int(m.group(2)) * 100 + int(m.group(3))
        rep = (r.get("reporting") or "").lower()
        if rep != want:
            other.add(rep or "?")
            continue
        if r.get("incTrev") is not None:
            out[qe] = {"rev_total": float(r["incTrev"]), "rev_total_label": "incTrev"}
    note = "tt: %d FYs %s..%s" % (len(out), min(out, default="-"), max(out, default="-"))
    if other:
        note += "; company reports {} only".format("/".join(sorted(other)))
    return out, note


READERS = {"mc": mc_quarters, "tl": tl_quarters, "tt": tt_quarters}
ANNUALS = {"mc": mc_annuals, "tl": tl_annuals, "tt": tt_annuals}


def read_annual(site, sym, con, name_hint=""):
    if site == "tt":
        return tt_annuals(sym, con, name_hint)
    return ANNUALS[site](sym, con)


def read(site, sym, con, name_hint=""):
    if site == "tt":
        return tt_quarters(sym, con, name_hint)
    return READERS[site](sym, con)


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "WESTLIFE"
    for site in ("mc", "tl", "tt"):
        for con in (False, True):
            q, note = read(site, sym, con)
            print("%-3s %-3s %s" % (site, "CON" if con else "STD", note))
            for qe in sorted(q)[-3:]:
                print("      %d %s" % (qe, {k: v for k, v in q[qe].items() if not k.endswith("_label")}))
