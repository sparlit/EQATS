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
"""
Coverage campaign STEP 5 (full-depth): FII/DII holdings 2010-12 -> 2016-03 from Wayback-archived
Moneycontrol shareholding-pattern pages.

Why this source (probe trail in scripts/COVERAGE_CAMPAIGN.md progress log + memory
`project-stocks-shp-bse-backfill`): BSE deleted all pre-2016 SHP data from its current systems
(quarter labels exist, every data endpoint returns empty templates); NSE's APIs are rolling-window
only; BSE's own aspx pages were never archived with old qtrids. Moneycontrol's old company-facts
pages, however, server-rendered the FULL Clause-35 table (Promoter total, MF/UTI, FI/Banks,
Insurance, FII rows + Institutions subtotal) and the Wayback Machine holds ~134k captures of them
across ~7,000 companies, dense from 2011 to 2016, with explicit per-quarter URLs
(/company-facts/<slug>/shareholding-pattern/<scId>/<qtrid>.00 — the qtrid numbering IS BSE's own:
29=Mar-2001, 75=Sep-2012, 88=Dec-2015, 90=Jun-2016).

DATE CONVENTION (decided 2026-08-02, user driving full coverage; flagged per-cell): these pages
carry no submission dates (BSE deleted them). Visibility date = QUARTER-END + 21 DAYS — the
Clause-35 filing deadline of that era. Every cell in this ledger is marked approx; regenerating
with a different lag is a one-flag re-run (--lag N). Monthly-rebalance backtests behave identically
for +21 vs +30 (both reveal the quarter at the following month-end).

Identity guard: every parsed page must state the expected BSE scripcode / NSE symbol / ISIN in its
header line ("BSE: 500325|NSE: RELIANCE|ISIN: INE002A01018") — mismatch -> page discarded (same
philosophy as bse_fetch.py's identity guard).

Subcommands (run in order; everything cached under scripts/_shp_wb_cache/, all resumable):
  python fetch_shp_wayback_mc.py map        # N500 2009-2016 members -> MC (slug, scId), autosuggest + CDX-slug name match
  python fetch_shp_wayback_mc.py frontier   # build the (slug, qtrid) -> capture fetch list from the CDX census
  python fetch_shp_wayback_mc.py sample 8   # fetch+parse a few pages, print results (prototype check)
  python fetch_shp_wayback_mc.py harvest    # full paced fetch (hours; single-thread, 429-backoff; resumable)
  python fetch_shp_wayback_mc.py ledger     # seam-calibrate column convention vs 2016+ XBRL cells, write ledger
"""
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_shp_wb_cache")
os.makedirs(CACHE, exist_ok=True)
PAGES = os.path.join(CACHE, "pages")
os.makedirs(PAGES, exist_ok=True)
CDX_FILE = os.path.join(CACHE, "cdx_mc.json")
MAP_FILE = os.path.join(CACHE, "map.json")
FRONTIER_FILE = os.path.join(CACHE, "frontier.json")
PARSED_FILE = os.path.join(CACHE, "parsed.json")
LEDGER_OUT = os.path.join(HERE, "shp_fill_hist_2010_2016.json.gz")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
LAG_DAYS = 21 if "--lag" not in sys.argv else int(sys.argv[sys.argv.index("--lag") + 1])


def http_get(url, timeout=60, accept="text/html"):
    r = urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept}), timeout=timeout
    )
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def qe_of_qtrid(q):
    """BSE quarter-id -> quarter-end date. 29 = Mar-2001, +1 per quarter (75=Sep-2012, 90=Jun-2016)."""
    m = 3 + 3 * (q - 29)
    y = 2001 + (m - 1) // 12
    mm = ((m - 1) % 12) + 1
    return datetime.date(y, mm, {3: 31, 6: 30, 9: 30, 12: 31}[mm])


def qtrid_of_label(label):
    """'September 2012' -> 75. Returns None if not a clean quarter label."""
    m = re.match(r"(March|June|September|December)\s+(20\d\d)$", label.strip())
    if not m:
        return None
    mm = {"March": 3, "June": 6, "September": 9, "December": 12}[m.group(1)]
    return 29 + (int(m.group(2)) - 2001) * 4 + (mm - 3) // 3


def norm_name(s):
    s = re.sub(r"\b(ltd|limited|the|co|company|corp|corporation|india|&)\b", "", (s or "").lower())
    return re.sub(r"[^a-z0-9]", "", s)


# ---------------------------------------------------------------- map
def cmd_census(qfilter=None):
    """(Re)build the CDX census that map/frontier read. The original 134k-row census lived only in
    the gitignored cache and went with the 2026-08-03 disk cleanup.

    ⚠ Use PAGE pagination, not resumeKey, and do NOT push a regex filter server-side: a wildcard
    prefix this size + regex makes CDX scan too far and it answers 504. `showNumPages` on the bare
    prefix returns ~214 bounded pages; each one comes back fine and we filter locally."""
    idx = "https://web.archive.org/cdx/search/cdx?url=moneycontrol.com/company-facts/*"
    npages = int(http_get(idx + "&showNumPages=true", timeout=180).strip() or 0)
    print("census: %d CDX pages" % npages, flush=True)
    want = {int(q) for q in qfilter} if qfilter else None
    rows, kept = [], 0
    for pg in range(npages):
        url = idx + "&output=json&collapse=urlkey&fl=original,timestamp&page=%d" % pg
        data = None
        for attempt in range(4):
            try:
                data = json.loads(http_get(url, timeout=180, accept="application/json") or "[]")
                break
            except Exception as e:
                print("   page %d retry %d (%r)" % (pg, attempt, e), flush=True)
                time.sleep(10 * (attempt + 1))
        if data is None:
            print("   page %d GAVE UP" % pg, flush=True)
            continue
        body = data[1:] if data and data[0] and data[0][0] == "original" else data
        for r in body:
            if len(r) < 2:
                continue
            orig = r[0]
            m = re.search(r"company-facts/([^/]+)/shareholding-pattern/([^/?#]+)(?:/(\d+))?", orig)
            if not m:
                continue
            if want is not None and (not m.group(3) or int(m.group(3)) not in want):
                continue
            rows.append([orig, r[1]])
            kept += 1
        if pg % 20 == 0 or pg == npages - 1:
            print("   page %d/%d — %d shareholding captures kept" % (pg, npages, kept), flush=True)
        time.sleep(1.0)
    json.dump(rows, open(CDX_FILE, "w"))
    print("CENSUS: %d captures -> %s" % (len(rows), CDX_FILE), flush=True)


def cmd_map():
    D = json.loads(
        gzip.decompress(
            urllib.request.urlopen(
                urllib.request.Request(
                    "https://dhruvan246.github.io/stocks-dashboard/dash_slim.bin", headers={"User-Agent": UA}
                ),
                timeout=90,
            ).read()
        )
    )
    snaps = [s for s in D["indicesHistory"]["Nifty 500"] if "2009-01-01" <= s["effectiveDate"] <= "2017-01-01"]
    members = set()
    for s in snaps:
        members.update(s["symbols"])
    members.discard("Symbol")
    print("N500 members in any 2009-2016 snapshot:", len(members), flush=True)

    # normalize old symbols to CURRENT bin keys via the rename map (transitive)
    try:
        ren = json.load(open(os.path.join(HERE, "_rename_map.json")))
    except Exception:
        ren = {}

    def cur_sym(s):
        seen = set()
        while s in ren and s not in seen:
            seen.add(s)
            s = ren[s]
        return s

    targets = {}
    for s in members:
        targets.setdefault(cur_sym(s), set()).add(s)
    print("distinct current-key targets:", len(targets), flush=True)

    scrips = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))
    by_id = scrips["by_id"]
    isin_of = {}
    for isin, v in scrips.get("by_isin", {}).items():
        isin_of[v if isinstance(v, str) else str(v)] = isin

    # company names for the name-match fallback (shp_history _names + slug list from CDX)
    try:
        names = json.load(open(os.path.join(HERE, "shp_history.json"), encoding="utf-8")).get("_names", {})
    except Exception:
        names = {}
    cdx = json.load(open(CDX_FILE))
    slug_index = {}
    for orig, _ts in cdx:
        m = re.search(r"company-facts/([^/]+)/shareholding", orig)
        if m:
            slug_index.setdefault(norm_name(m.group(1)), m.group(1))

    out = json.load(open(MAP_FILE)) if os.path.exists(MAP_FILE) else {}
    todo = [t for t in sorted(targets) if t not in out]
    print("to map:", len(todo), flush=True)
    for i, sym in enumerate(todo):
        entry = None
        code = by_id.get(sym)
        for q in {sym} | targets[sym]:
            try:
                t = http_get(
                    f"https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php?classic=true&query={urllib.parse.quote(str(q))}&type=1&format=json",
                    timeout=25,
                )
                for cand in json.loads(t) or []:
                    dis = cand.get("pdt_dis_nm") or ""
                    link = cand.get("link_src") or ""
                    scid = cand.get("sc_id") or ""
                    mslug = re.search(r"stockpricequote/[^/]+/([^/]+)/", link)
                    # identity: displayed line carries "ISIN, NSESYM, SCRIPCODE"
                    ok = False
                    if code and re.search(r"\b%d\b" % code, dis):
                        ok = True
                    if re.search(rf"\b{re.escape(str(q))}\b", dis):
                        ok = True
                    if ok and mslug and scid:
                        entry = {"slug": mslug.group(1), "scid": scid, "via": f"autosuggest:{q}"}
                        break
            except Exception:
                pass
            if entry:
                break
            time.sleep(0.35)
        if not entry:
            nm = names.get(sym) or ""
            slug = slug_index.get(norm_name(nm)) or slug_index.get(norm_name(sym))
            if slug:
                entry = {"slug": slug, "scid": None, "via": "cdx-name-match"}
        out[sym] = entry
        if (i + 1) % 25 == 0:
            json.dump(out, open(MAP_FILE, "w"), indent=0)
            print("  ...%d/%d mapped (%d ok)" % (i + 1, len(todo), sum(1 for v in out.values() if v)), flush=True)
    json.dump(out, open(MAP_FILE, "w"), indent=0)
    ok = sum(1 for v in out.values() if v)
    print("MAP DONE: %d/%d resolved (%d unmapped — reported, not guessed)" % (ok, len(out), len(out) - ok), flush=True)


# ---------------------------------------------------------------- frontier
def cmd_frontier():
    cdx = json.load(open(CDX_FILE))
    mp = json.load(open(MAP_FILE))
    want_slugs = {v["slug"]: sym for sym, v in mp.items() if v}
    print("mapped slugs:", len(want_slugs), flush=True)

    # captures per slug: explicit-qtrid ones directly keyed; no-qtrid kept as candidates
    explicit = defaultdict(dict)  # slug -> qtrid -> (ts, original)
    generic = defaultdict(list)  # slug -> [(ts, original)]
    for orig, ts in cdx:
        m = re.search(r"company-facts/([^/]+)/shareholding-pattern/([^/?#]+)(?:/(\d+))?", orig)
        if not m:
            continue
        slug = m.group(1)
        if slug not in want_slugs:
            continue
        q = m.group(3)
        if q:
            q = int(q)
            if 29 <= q <= 89 and (q not in explicit[slug] or ts < explicit[slug][q][0]):
                explicit[slug][q] = (ts, orig)
        else:
            generic[slug].append((ts, orig))

    frontier = []
    for slug, sym in want_slugs.items():
        for q, (ts, orig) in explicit[slug].items():
            frontier.append({"sym": sym, "slug": slug, "qtrid": q, "ts": ts, "url": orig})
        # generic captures fill quarters the explicit set misses: spread them by capture date, keep
        # at most one per quarter-of-capture (the page shows the then-latest quarter)
        seen_q = set(explicit[slug])
        by_qtr_bucket = {}
        for ts, orig in sorted(generic[slug]):
            d = datetime.date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
            approx_q = 29 + (d.year - 2001) * 4 + (d.month - 1) // 3 - 1  # quarter probably displayed
            if approx_q in seen_q or approx_q in by_qtr_bucket:
                continue
            by_qtr_bucket[approx_q] = (ts, orig)
        for q, (ts, orig) in by_qtr_bucket.items():
            frontier.append({"sym": sym, "slug": slug, "qtrid": None, "ts": ts, "url": orig})
    json.dump(frontier, open(FRONTIER_FILE, "w"), indent=0)
    n_exp = sum(1 for f in frontier if f["qtrid"] is not None)
    print(
        "FRONTIER: %d fetches (%d explicit-qtrid, %d generic)" % (len(frontier), n_exp, len(frontier) - n_exp),
        flush=True,
    )


# ---------------------------------------------------------------- parse
ROW_LABELS = {
    "prom": r"Total shareholding of Promoter and Promoter Group\s*\(A\)",
    "mf": r"Mutual Funds\s*/\s*UTI",
    "banks": r"Financial Institutions\s*/\s*Banks",
    "govt": r"Central Government\s*/\s*State Government",
    "ins": r"Insurance Companies",
    "fii": r"Foreign Institutional Investors",
    "qfi": r"Qualified Foreign Investor",
    "vcf": r"^Venture Capital Funds",  # DOMESTIC VC — anchored, so it cannot also
    "fvci": r"Foreign Venture Capital Investors",  # match the Foreign VC row below it
    "inst_sub": r"\(1\)\s*Institutions.*?Sub Total",  # handled specially below
    "pubtot": r"Total Public shareholding\s*\(B\)",  # for the promoter-less fallback
}


def parse_mc_page(html, expect_code=None, expect_syms=(), slug=None):
    """-> dict(qtrid, cols{slot: (pctAB, pctABC)}) or None. Identity-guarded."""
    # identity, strongest first: "BSE: 500325|NSE: RELIANCE" line (2012+ pages); fallback for the
    # 2011-era pages (no codes line): the <title>'s company name must match the URL slug we chose
    # ("3M India >> Shareholding Pattern - ..." vs slug "3mindia") — the slug itself was identity-
    # guarded against scripcode/ISIN at map time.
    ident = re.search(r"BSE:\s*(\d{6})\s*(?:\||&#124;)?\s*NSE:\s*([A-Z0-9&\-]+)", html)
    tm = re.search(
        r"<title>\s*([^<]*?)\s*(?:&gt;&gt;|>>)\s*Shareholding Pattern\s*-\s*((?:March|June|September|December)\s+20\d\d)",
        html,
    )
    if not tm:
        tm2 = re.search(r"Shareholding Pattern\s*-\s*((?:March|June|September|December)\s+20\d\d)", html)
        if not tm2:
            return None
        title_co, qlabel = None, tm2.group(1)
    else:
        title_co, qlabel = tm.group(1), tm.group(2)
    if ident:
        code, nsym = int(ident.group(1)), ident.group(2).strip().upper()
        if expect_code and code != expect_code and nsym not in {s.upper() for s in expect_syms}:
            return None
    elif expect_code:
        tco = norm_name(title_co or "")
        tsl = norm_name(slug or "")
        if not tco or not tsl or not (tco in tsl or tsl in tco):
            return None
    q = qtrid_of_label(qlabel)
    if not q:
        return None

    import html as _html

    text = re.sub(r"<[^>]+>", "\x01", html)
    cells = [re.sub(r"[\s\xa0]+", " ", _html.unescape(c)).strip() for c in text.split("\x01")]
    cells = [c for c in cells if c]

    def row_nums(i):
        nums = []
        for c2 in cells[i + 1 : i + 9]:
            c2 = c2.replace(",", "").strip()
            if c2 in ("-", ""):
                nums.append(None)
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?", c2):
                nums.append(float(c2))
            else:
                break
        return nums

    def pair(nums):
        # row shape: n_holders, total_shares, demat_shares, pct(A+B)[, pct(A+B+C)][, pledged...]
        if len(nums) >= 5:
            return (nums[3], nums[4])
        if len(nums) == 4:
            return (nums[3], nums[3])
        return None

    def find_row(label_rx, lo=0, hi=None):
        rx = re.compile(label_rx, re.IGNORECASE)
        for i in range(lo, hi if hi is not None else len(cells)):
            if rx.search(cells[i]):
                p = pair(row_nums(i))
                if p:
                    return p
        return None

    out = {}
    # promoter total: anywhere on the page (unique label)
    p = find_row(ROW_LABELS["prom"])
    if p:
        out["prom"] = p
    p = find_row(ROW_LABELS["pubtot"])
    if p:
        out["pubtot"] = p
    # institution rows ONLY inside the "(1) Institutions" ... "Sub Total" block — for PSUs the
    # PROMOTER block also contains a "Central Government / State Government(s)" row (President of
    # India), which must not be read as the institutional-government row.
    blk_lo = blk_hi = None
    for rx in (r"\(1\)\s*Institutions?\s*$", r"^Institutions$"):  # prefer the explicit (1) marker
        for i, c in enumerate(cells):
            if re.search(rx, c, re.IGNORECASE):
                blk_lo = i
                for j in range(i + 1, min(i + 160, len(cells))):
                    if re.fullmatch(r"Sub\s*Total", cells[j], re.IGNORECASE):
                        blk_hi = j + 1
                        break
                break
        if blk_lo is not None:
            break
    if blk_lo is not None:
        hi = blk_hi if blk_hi is not None else min(blk_lo + 160, len(cells))
        for slot in ("mf", "banks", "govt", "ins", "fii", "qfi", "vcf", "fvci"):
            p = find_row(ROW_LABELS[slot], blk_lo, hi)
            if p:
                out[slot] = p
        if blk_hi is not None:
            p = pair(row_nums(blk_hi - 1))
            if p:
                out["inst_sub"] = p
    if "fii" not in out and "mf" not in out and "inst_sub" not in out:
        return None
    return {"qtrid": q, "cols": out}


# ---------------------------------------------------------------- fetch machinery
def wb_fetch(ts, orig):
    # Pages are cached GZIPPED — the raw-HTML cache hit 1.23 GB and filled the disk mid-run
    # (OSError 28) on 2026-08-03. Plain .html files from before that are still read if present.
    key = re.sub(r"[^A-Za-z0-9]+", "_", orig[-90:]) + "_" + ts
    cf = os.path.join(PAGES, key + ".html.gz")
    legacy = os.path.join(PAGES, key + ".html")
    if os.path.exists(cf):
        with gzip.open(cf, "rt", encoding="utf-8") as fh:
            return fh.read(), True
    if os.path.exists(legacy):
        return open(legacy, encoding="utf-8").read(), True
    url = f"https://web.archive.org/web/{ts}id_/{orig}"
    delay = 60
    for attempt in range(6):
        try:
            html = http_get(url, timeout=90)
            with gzip.open(cf + ".tmp", "wt", encoding="utf-8", compresslevel=6) as fh:
                fh.write(html)
            os.replace(cf + ".tmp", cf)
            return html, False
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                print("  rate-limited (%d), sleeping %ds" % (e.code, delay), flush=True)
                time.sleep(delay)
                delay = min(delay * 2, 600)
            elif e.code == 404:
                with gzip.open(cf, "wt", encoding="utf-8") as fh:
                    fh.write("")  # negative-cache
                return "", False
            else:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            # transient network trouble (Wayback outage windows) — brief in-run retry; if it
            # persists, raise so the caller logs FETCH FAIL and a later re-run picks it up
            if attempt >= 2:
                raise
            print(f"  net-error ({e!r}), sleeping 25s", flush=True)
            time.sleep(25)
    msg = f"gave up on {url}"
    raise RuntimeError(msg)


def cmd_sample(n):
    frontier = json.load(open(FRONTIER_FILE))
    scrips = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))["by_id"]
    picks = frontier[:: max(1, len(frontier) // n)][:n]
    for f in picks:
        html, cached = wb_fetch(f["ts"], f["url"])
        res = parse_mc_page(html, expect_code=scrips.get(f["sym"]), expect_syms=(f["sym"],), slug=f["slug"])
        print(
            f["sym"],
            f["slug"],
            "qtrid=",
            f["qtrid"],
            "ts=",
            f["ts"],
            "->",
            (dict(qtrid=res["qtrid"], **dict(res["cols"].items())) if res else "PARSE-NONE"),
            flush=True,
        )
        if not cached:
            time.sleep(1.3)


def cmd_harvest(workers=5):
    """Paced parallel fetch. The 2026-08-03 run went single-threaded at 1.25s and took ~6h for
    12,691 fetches, then recorded its own verdict: zero 429s across ~20k requests, so the caution
    was wasted. Default is 5 connections now, each still pacing, with the same exponential 429
    backoff in wb_fetch — on pushback the whole pool slows because every worker sleeps. Resumable
    exactly as before: _done is keyed by ts|url and checkpointed under a lock."""
    frontier = json.load(open(FRONTIER_FILE))
    scrips = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))["by_id"]
    parsed = json.load(open(PARSED_FILE)) if os.path.exists(PARSED_FILE) else {}
    done_urls = set(parsed.get("_done", []))
    cells = parsed.get("cells", {})
    todo = [f for f in frontier if (f["ts"] + "|" + f["url"]) not in done_urls]
    print("harvest: %d queued, %d already done, %d workers" % (len(todo), len(done_urls), workers), flush=True)

    import threading
    from concurrent.futures import ThreadPoolExecutor

    lock = threading.Lock()
    state = {"n": 0, "new": 0, "fail": 0}

    def one(f):
        uk = f["ts"] + "|" + f["url"]
        try:
            html, cached = wb_fetch(f["ts"], f["url"])
        except Exception as e:
            with lock:
                state["fail"] += 1
                if state["fail"] <= 15:
                    print("  FETCH FAIL {}: {!r}".format(f["url"][:90], e), flush=True)
            return
        res = (
            parse_mc_page(html, expect_code=scrips.get(f["sym"]), expect_syms=(f["sym"],), slug=f["slug"])
            if html
            else None
        )
        with lock:
            if res and 29 <= res["qtrid"] <= 89:
                key = "%s|%d" % (f["sym"], res["qtrid"])
                if key not in cells:
                    cells[key] = {"cols": res["cols"], "src": "wb:{}:{}".format(f["ts"], f["slug"])}
                    state["new"] += 1
            done_urls.add(uk)
            state["n"] += 1
            if state["n"] % 100 == 0:
                json.dump({"_done": sorted(done_urls), "cells": cells}, open(PARSED_FILE, "w"))
                print(
                    "  ...%d/%d fetched, %d cells, %d fails" % (state["n"], len(todo), len(cells), state["fail"]),
                    flush=True,
                )
        if not cached:
            time.sleep(1.25)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    json.dump({"_done": sorted(done_urls), "cells": cells}, open(PARSED_FILE, "w"))
    print(
        "HARVEST DONE: %d cells across %d fetches (%d new, %d fails)"
        % (len(cells), len(done_urls), state["new"], state["fail"]),
        flush=True,
    )


def cmd_nshpass():
    """Second pass over the CACHED pages only — no refetch — pulling the total shareholder count.

    The MC Clause-35 table's first numeric column is the holder count per row, and the
    "Total (A)+(B)+(C)" row carries the whole-company figure (SUNDARMFIN Sep-2016 = 22,227).
    parse_mc_page never captured it, which is why ~4,118 MC-sourced cells have correct percentages
    and no nsh. Emits a COUNT-ONLY side-ledger so it can be merged into slot 6 without touching a
    single percentage."""
    frontier = json.load(open(FRONTIER_FILE))
    scrips = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))["by_id"]
    out, seen, miss = {}, 0, 0
    for f in frontier:
        key = re.sub(r"[^A-Za-z0-9]+", "_", f["url"][-90:]) + "_" + f["ts"]
        cf = os.path.join(PAGES, key + ".html.gz")
        if not os.path.exists(cf):
            continue
        try:
            with gzip.open(cf, "rt", encoding="utf-8") as fh:
                page = fh.read()
        except Exception:
            continue
        seen += 1
        res = parse_mc_page(page, expect_code=scrips.get(f["sym"]), expect_syms=(f["sym"],), slug=f["slug"])
        if not res or not (29 <= res["qtrid"] <= 89):
            continue
        import html as _h

        cells = [
            re.sub(r"[\s\xa0]+", " ", _h.unescape(c)).strip() for c in re.sub(r"<[^>]+>", "\x01", page).split("\x01")
        ]
        cells = [c for c in cells if c]
        n = None
        for i, c in enumerate(cells):
            if re.fullmatch(r"Total \(A\)\+\(B\)\+\(C\)", c):
                for c2 in cells[i + 1 : i + 4]:
                    v = c2.replace(",", "").strip()
                    if re.fullmatch(r"\d+", v) and int(v) > 0:
                        n = int(v)
                        break
                break
        if n is None:
            miss += 1
            continue
        qe = qe_of_qtrid(res["qtrid"]).isoformat()
        out.setdefault(f["sym"], {})[qe] = n
    path = os.path.join(HERE, "shp_fill_nsh_pre2016.json.gz")
    total = sum(len(v) for v in out.values())
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(
            {
                "_meta": {
                    "source": "wayback moneycontrol Clause-35, Total (A)+(B)+(C) holder column",
                    "note": "COUNT ONLY — merge into slot 6, never touches percentages",
                    "pages_read": seen,
                    "companies": len(out),
                    "cells": total,
                },
                "counts": out,
            },
            fh,
        )
    print(
        "NSH PASS: %d cached pages read, %d counts across %d companies, %d pages had no total row -> %s"
        % (seen, total, len(out), miss, path),
        flush=True,
    )


# ---------------------------------------------------------------- ledger (+ seam calibration)
def cmd_ledger():
    parsed = json.load(open(PARSED_FILE))
    cells = parsed["cells"]
    hist = json.load(open(os.path.join(HERE, "shp_history.json"), encoding="utf-8"))

    # ⚠ SOURCE DEFECT, found by this gate on the first run (2026-08-03): for qtrid 88 (Dec-2015)
    # and 89 (Mar-2016) Moneycontrol's own pages carry an EMPTY "Foreign Institutional Investors"
    # row — all "-" — for EVERY company including large caps with obvious foreign holding (verified
    # on ACC, both quarters). MC's pipeline evidently broke when SEBI restructured the format; the
    # data is absent at source, not mis-parsed. FII fill-rate is 94-99% for every qtrid <= 87 and
    # exactly 0% at 88/89. Those two quarters are DROPPED — writing them would fabricate fii=0 for
    # ~840 company-quarters, the precise failure mode parse_shp's "never zero-default" rule exists
    # to prevent. Effective ledger window is therefore Dec-2010 .. Sep-2015.
    # ⚠ 2026-08-03 verdict, CORRECTED 2026-08-09: qtrid 88 (Dec-2015) and 89 (Mar-2016) DO have an
    # empty "Foreign Institutional Investors" row on every MC page — that part was right — but the
    # data is NOT absent. The institutions Sub Total is printed and correct, and the foreign block
    # sits in the un-itemised remainder. Every q<=87 cell already passes the reconciliation gate
    # below, i.e. inst_sub = fii + dii + govt + qfi holds to 1pp across the whole harvest, so at
    # 88/89 we INVERT the same identity: fii = inst_sub - (mf + banks + ins + govt + qfi + vcf).
    # That is arithmetic, not a guess — and it is checked against the Jun-2016 XBRL cells we parse
    # ourselves, one quarter away (SEAM_GATE below), instead of the 3-quarter drift the original
    # calibration had to live with. Proof it works: HDFCBANK q88 residual 39.78 vs our own
    # Jun-2016 39.59.
    USABLE_MAX_Q = 89
    DERIVE_QS = (88, 89)  # quarters where fii is derived from the subtotal
    SEAM_MAX_MEDIAN = 3.0  # median |q89 derived - Jun-2016 parsed| that must not be exceeded

    # SEAM CALIBRATION. The two candidate columns are "% of (A+B)" and "% of (A+B+C)", where C is
    # the GDR/custodian block; they are IDENTICAL for companies without GDRs, so the choice only
    # matters for the GDR subset — which is where this measures. Anchor = the trusted 2016 XBRL
    # cells; nearest usable harvested quarter is Sep-2015, so a ~3-quarter drift is baked into the
    # absolute numbers and only the RELATIVE AB-vs-ABC comparison is meaningful.
    best = {}
    for key, c in cells.items():
        sym, q = key.split("|")
        q = int(q)
        if q > USABLE_MAX_Q:
            continue
        p = c["cols"].get("fii")
        if not p or (p[0] is None and p[1] is None):
            continue
        if sym not in best or q > best[sym][0]:
            best[sym] = (q, p)
    diffs = {"AB": [], "ABC": []}
    gdr = {"AB": [], "ABC": []}
    for sym, (q, p) in best.items():
        anchor = None
        for qe in ("2016-06-30", "2016-09-30"):
            v = (hist.get(sym) or {}).get(qe)
            if v:
                anchor = v
                break
        if not anchor:
            continue
        ab, abc = p[0], p[1]
        if ab is None or abc is None:
            continue
        diffs["AB"].append(abs(ab - anchor[1]))
        diffs["ABC"].append(abs(abc - anchor[1]))
        if abs(ab - abc) > 0.5:  # GDR company: the columns actually differ
            gdr["AB"].append(abs(ab - anchor[1]))
            gdr["ABC"].append(abs(abc - anchor[1]))

    def med(v):
        v = sorted(v)
        return v[len(v) // 2] if v else None

    mAB, mABC, gAB, gABC = med(diffs["AB"]), med(diffs["ABC"]), med(gdr["AB"]), med(gdr["ABC"])
    print(
        "seam vs 2016 XBRL fii — all n=%d: AB=%s ABC=%s | GDR-subset n=%d: AB=%s ABC=%s"
        % (len(diffs["AB"]), mAB, mABC, len(gdr["AB"]), gAB, gABC),
        flush=True,
    )
    if mAB is None or len(diffs["AB"]) < 50:
        raise SystemExit("STOP: too little seam overlap (%d) to calibrate" % len(diffs["AB"]))
    if gABC is None or len(gdr["AB"]) < 5:
        msg = "STOP: no GDR-subset overlap — cannot discriminate the two column conventions"
        raise SystemExit(msg)
    use_abc = gABC <= gAB
    col = 1 if use_abc else 0
    print("chosen column convention:", "%of(A+B+C)" if use_abc else "%of(A+B)", flush=True)
    # Drift over ~3 quarters is expected; a definition mismatch would show up far larger than this.
    if min(mAB, mABC) > 4.0:
        msg_0 = f"STOP: best convention still has median seam {min(mAB, mABC):.2f}pp — definitions don't line up, refusing to write"
        raise SystemExit(msg_0)

    fills = defaultdict(dict)
    dropped = Counter()
    derived_cells = []
    for key, c in cells.items():
        sym, q = key.split("|")
        q = int(q)
        if q > USABLE_MAX_Q:
            dropped["beyond-usable-qtr"] += 1
            continue
        qe = qe_of_qtrid(q)
        cols = c["cols"]

        def val(slot):
            p = cols.get(slot)
            if not p:
                return None
            return p[col] if p[col] is not None else p[1 - col]

        # fii is the primary factor AND proof the institutions block parsed — never default it to
        # 0.0 (that is indistinguishable from a genuine zero holding and silently poisons screens).
        fii = val("fii")
        derived = False
        if fii is None and q in DERIVE_QS:
            # foreign = the institutions subtotal minus the rows itemised as DOMESTIC. Do NOT also
            # subtract qfi: at 88/89 the foreign block lands on whichever row survives the format
            # change (HDFCBANK q88 leaves it un-itemised, q89 puts 39.63 on the QFI row) and both
            # readings must end up in fii. NO CLAMP — a negative residual means the block did not
            # parse, and max(0, ...) would turn that into a fabricated "no foreign holding".
            inst0 = val("inst_sub")
            dom = sum(val(k) or 0.0 for k in ("mf", "banks", "ins", "govt", "vcf"))
            if inst0 is None:
                dropped["derive-no-subtotal"] += 1
                continue
            resid = inst0 - dom
            if resid < -0.5 or resid > 100.0:
                dropped["derive-bad-residual"] += 1
                continue
            fii = round(max(resid, 0.0), 2) if resid >= -0.5 else None
            derived = True
        if fii is None:
            dropped["no-fii"] += 1
            continue
        prom = val("prom")
        if prom is None:
            # Promoter-less filers (ITC, the old private-sector banks, MCX) print DASHES in every
            # promoter row, which parses as None — and 122 cells died here in the first run. The
            # page still asserts the fact arithmetically: on the %of(A+B) basis prom + pub = 100
            # exactly, so a "Total Public shareholding (B)" of >= 99 IS the promoter total stated
            # as its complement. Only claimed when pub_AB >= 99 — a company with a real promoter
            # whose row merely failed to parse cannot sneak through as prom = 0.
            pt = cols.get("pubtot")
            pab = pt[0] if pt and pt[0] is not None else None
            if pab is not None and pab >= 99.0:
                prom = round(max(0.0, 100.0 - pab), 2)
            else:
                dropped["no-promoter-total"] += 1
                continue
        mf = val("mf") or 0.0
        dii = mf + (val("banks") or 0.0) + (val("ins") or 0.0)
        # reconciliation gate mirroring parse_shp: itemized institutions ≈ subtotal (when present)
        inst = val("inst_sub")
        if inst is not None and not derived:  # derived cells satisfy it by construction
            item_sum = fii + dii + (val("govt") or 0.0) + (val("qfi") or 0.0)
            if abs(item_sum - inst) > 1.0:
                dropped["inst-recon"] += 1
                continue
        if derived:
            derived_cells.append((sym, qe, fii))
        if not (0.0 <= prom <= 100.0) or not (0.0 <= fii <= 100.0) or not (0.0 <= dii <= 100.0):
            dropped["out-of-range"] += 1
            continue
        sub = (qe + datetime.timedelta(days=LAG_DAYS)).isoformat()
        fills[sym][qe.isoformat()] = [
            round(prom, 2),
            round(fii, 2),
            round(dii, 2),
            round(mf, 2),
            round(val("ins") or 0.0, 2),
            sub,
            None,
            c["src"] + ":approx+%dd" % LAG_DAYS,
        ]
    # SEAM GATE for the derived 88/89 cells: Mar-2016 is ONE quarter from the Jun-2016 cells we
    # parse ourselves from BSE's XBRL, so a bad derivation shows up immediately. If the median
    # disagreement is worse than SEAM_MAX_MEDIAN, drop every derived cell rather than write them.
    seam = []
    for sym, qe, fii in derived_cells:
        if qe.isoformat() != "2016-03-31":
            continue
        nxt = (hist.get(sym) or {}).get("2016-06-30")
        if nxt:
            seam.append(abs(fii - nxt[1]))
    seam_med = med(seam)
    print(
        "DERIVED 88/89: %d cells; Mar-2016 vs our Jun-2016 XBRL — n=%d median %s pp"
        % (len(derived_cells), len(seam), seam_med),
        flush=True,
    )
    if derived_cells:
        if seam_med is None or len(seam) < 25:
            print("  seam sample too small (%d) — dropping every derived cell" % len(seam), flush=True)
            keep = set()
        elif seam_med > SEAM_MAX_MEDIAN:
            print(
                f"  median {seam_med:.2f}pp > {SEAM_MAX_MEDIAN:.1f}pp — derivation NOT validated, dropping every derived cell",
                flush=True,
            )
            keep = set()
        else:
            keep = {(sym, qe.isoformat()) for sym, qe, _ in derived_cells}
            print("  derivation VALIDATED — keeping %d cells" % len(keep), flush=True)
        for sym, qe, _ in derived_cells:
            k = (sym, qe.isoformat())
            if k not in keep and qe.isoformat() in fills.get(sym, {}):
                del fills[sym][qe.isoformat()]
                dropped["derive-seam-gate"] += 1
        for sym in [k for k, v in fills.items() if not v]:
            del fills[sym]

    total = sum(len(v) for v in fills.values())
    meta = {
        "window": ["2010-12-31", "2016-03-31"],
        "derived_88_89": len(derived_cells),
        "derived_seam_median_pp": seam_med,
        "source": "wayback moneycontrol company-facts",
        "date_convention": "QE+%dd (SEBI Clause-35 deadline) — APPROXIMATE, no real filing dates exist" % LAG_DAYS,
        "column_convention": "%of(A+B+C)" if use_abc else "%of(A+B)",
        "seam_median_pp": {"all_AB": mAB, "all_ABC": mABC, "gdr_AB": gAB, "gdr_ABC": gABC},
        "companies": len(fills),
        "cells": total,
        "dropped": dict(dropped),
    }
    with gzip.open(LEDGER_OUT, "wt", encoding="utf-8") as fh:
        json.dump({"_meta": meta, "fills": fills}, fh, separators=(",", ":"))
    print("LEDGER: %d companies, %d cells -> %s" % (len(fills), total, LEDGER_OUT), flush=True)
    print(json.dumps(meta, indent=1), flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "census":
        cmd_census([int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else None)
    elif cmd == "map":
        cmd_map()
    elif cmd == "frontier":
        cmd_frontier()
    elif cmd == "sample":
        cmd_sample(int(sys.argv[2]) if len(sys.argv) > 2 else 6)
    elif cmd == "harvest":
        cmd_harvest(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    elif cmd == "nshpass":
        cmd_nshpass()
    elif cmd == "ledger":
        cmd_ledger()
    else:
        print(__doc__)
