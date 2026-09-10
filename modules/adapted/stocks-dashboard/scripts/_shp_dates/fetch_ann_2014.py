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


#!/usr/bin/env python3
"""SW-1 (quantmac round 5) — recover REAL SHP filing dates for Dec-2013..Mar-2016 from BSE's
ANNOUNCEMENTS stream  (2026-08-30).

WHY THIS ROUTE EXISTS AFTER P0 SAID THE STREAM WAS "WEAK": the 2026-08-23 probe tested it on
2006/2009/2012 windows only (HINDUNILVR-2009, CANFINHOME-2012, MUNJALSHOW-2006) — all before the
stream carries SHP filings. Re-probed 2026-08-30: from JANUARY 2014 the stream serves
"Company Update / Shareholding" rows with NEWS_DT to the second ("Shareholding Pattern For
March 31, 2014", JSWSTEEL 2014-04-16T12:03:45), 6/6 hits on 2014-2015 probes, 0/2 on 2012-2013
controls, and for Jun-2016 the NEWS_DT matches SHPQNewFormat's filing_date_time to the SECOND
(JSWSTEEL 2016-07-12T11:18:41 both routes). quantmac reports recovering 2,854 dates the same way.

WHAT IT DOES: for every shp_history cell with qe in Dec-2013..Mar-2016 (the last stretch of the
qe+21d convention era), query AnnSubCategoryGetData over [qe+1, qe+90], keep rows with
CATEGORYNAME 'Company Update' + SUBCATNAME containing 'Shareholding', match the HEADLINE/NEWSSUB
period to the exact quarter-end, take the EARLIEST such broadcast (first public disclosure),
apply the 15:30 gate (shp_dates.visible_date — same rule as the whole campaign), and journal to
scripts/shp_sub_dates.json (merge; existing entries NEVER overwritten). patch_history.py then
writes the sub slots. Refusals are journalled, never guessed:
  no-shp-row / period-unparsed / period-mismatch / conflicting-rows kept as evidence in
  _shp_dates/ann2014_results.json.

CONFIRMATIONS ARE LEDGERED TOO: a real broadcast that gates to exactly qe+21d still becomes a
ledger entry — the un-dating pass (build_engine_feed) treats LEDGER PRESENCE as the evidence
test for pre-Jun-2016 rows, so a confirmed convention date must be distinguishable from an
unevidenced one.

Usage: fetch_ann_2014.py [--threads 2] [--limit N]     # fetch + build results
       fetch_ann_2014.py --merge                       # merge results into shp_sub_dates.json
"""
import argparse
import datetime
import gzip
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, SCRIPTS)
import fetch_shp_bse_hist as H  # get() transport + scripcode resolution
import shp_dates as SD

RESULTS = os.path.join(HERE, "ann2014_results.json")
CACHE = os.path.join(HERE, "_ann2014_cache")
LEDGER = os.path.join(SCRIPTS, "shp_sub_dates.json")
QES = [20131231, 20140331, 20140630, 20140930, 20141231, 20150331, 20150630, 20150930, 20151231, 20160331]
WINDOW_DAYS = 90
_lk = threading.Lock()

MON = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
P_MONTH = re.compile(MON + r"\.?\s+(\d{1,2})\s*,?\s*(\d{4})", re.IGNORECASE)
P_NUM = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b")


def periods_of(txt):
    """Every quarter-end-looking date in the row text, as YYYYMMDD ints."""
    out = set()
    for m in P_MONTH.finditer(txt):
        mo = SD.MONTHS.get(m.group(1).lower()[:3])
        try:
            d, y = int(m.group(2)), int(m.group(3))
        except ValueError:
            continue
        if mo and SD.QEND_DAY.get(mo) == d:
            out.add(y * 10000 + mo * 100 + d)
    for m in P_NUM.finditer(txt):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if SD.QEND_DAY.get(mo) == d:
            out.add(y * 10000 + mo * 100 + d)
    return out


def iso_of(qe):
    return "%04d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)


def ann_window(code, qe):
    d0 = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
    d1, d2 = d0 + datetime.timedelta(days=1), d0 + datetime.timedelta(days=WINDOW_DAYS)
    cf = os.path.join(CACHE, "%d_%d.json.gz" % (code, qe))
    if os.path.exists(cf):
        return json.load(gzip.open(cf, "rt", encoding="utf-8"))
    rows, page = [], 1
    while page <= 8:
        url = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d"
            "&strCat=-1&strPrevDate=%s&strScrip=%d&strSearch=P&strToDate=%s&strType=C"
            "&subcategory=-1" % (page, d1.strftime("%Y%m%d"), code, d2.strftime("%Y%m%d"))
        )
        tab = json.loads(H.get(url)).get("Table", []) or []
        rows += tab
        if len(tab) < 50:
            break
        page += 1
    os.makedirs(CACHE, exist_ok=True)
    json.dump(rows, gzip.open(cf, "wt", encoding="utf-8"))
    return rows


def fetch_one(sym, qe, code, stored_sub):
    try:
        rows = ann_window(code, qe)
    except Exception as e:
        return sym, qe, {"verdict": "fetch-fail", "err": repr(e)}
    shp = [
        r
        for r in rows
        if str(r.get("CATEGORYNAME") or "").strip().lower() == "company update"
        and "shareholding" in str(r.get("SUBCATNAME") or "").lower()
    ]
    if not shp:
        return sym, qe, {"verdict": "no-shp-row", "rows": len(rows)}
    matches = []
    for r in shp:
        txt = "{} | {}".format(r.get("HEADLINE") or "", r.get("NEWSSUB") or "")
        pers = periods_of(txt)
        if qe in pers:
            matches.append((str(r.get("NEWS_DT") or ""), txt.strip()[:140]))
        elif not pers:
            matches.append((None, txt.strip()[:140]))
    dated = sorted(m for m in matches if m[0])
    if not dated:
        if matches:
            return sym, qe, {"verdict": "period-unparsed", "n_shp": len(shp), "sample": matches[0][1]}
        return sym, qe, {"verdict": "period-mismatch", "n_shp": len(shp)}
    ts = dated[0][0]  # earliest matching broadcast = first disclosure
    sub, gated = SD.visible_date(ts)
    if sub is None:
        return sym, qe, {"verdict": "bad-ts", "ts": ts}
    lag = SD.ts_parts(ts)[0]
    d0 = datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)
    db = datetime.date(lag // 10000, (lag // 100) % 100, lag % 100)
    if not (0 < (db - d0).days <= 120):
        return sym, qe, {"verdict": "lag-out-of-band", "ts": ts}
    return (
        sym,
        qe,
        {"verdict": "dated", "ts": ts, "sub": sub, "gated_1530": gated, "headline": dated[0][1], "stored": stored_sub},
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--merge", action="store_true")
    a = ap.parse_args()

    if a.merge:
        merge()
        return

    hist = json.load(open(os.path.join(SCRIPTS, "shp_history.json"), encoding="utf-8"))
    names = hist.get("_names", {})
    cmap, by_name = H.build_codemap(names)
    res = json.load(open(RESULTS, encoding="utf-8")) if os.path.exists(RESULTS) else {}
    todo = []
    for sym, qs in hist.items():
        if sym.startswith("_") or not isinstance(qs, dict):
            continue
        code = None
        for qe in QES:
            cell = qs.get(iso_of(qe))
            if not isinstance(cell, list) or len(cell) < 6:
                continue
            key = "%s|%d" % (sym, qe)
            if key in res:
                continue
            if code is None:
                code = H.resolve(sym, cmap, by_name, names)
            if code is None:
                res[key] = {"verdict": "no-scripcode"}
                continue
            todo.append((sym, qe, code, str(cell[5] or "")))
    if a.limit:
        todo = todo[: a.limit]
    print("fetch: %d cells to go, %d threads" % (len(todo), a.threads))
    t0, n = time.time(), 0
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        futs = [ex.submit(fetch_one, *t) for t in todo]
        for fu in as_completed(futs):
            sym, qe, v = fu.result()
            with _lk:
                res["%s|%d" % (sym, qe)] = v
                n += 1
                if n % 200 == 0:
                    json.dump(res, open(RESULTS, "w", encoding="utf-8"))
                    print(
                        "  %d/%d (%.1f/s) %s"
                        % (
                            n,
                            len(todo),
                            n / max(1e-9, time.time() - t0),
                            dict(Counter(x["verdict"] for x in res.values())),
                        ),
                        flush=True,
                    )
    json.dump(res, open(RESULTS, "w", encoding="utf-8"))
    print("done:", dict(Counter(x["verdict"] for x in res.values())))


def merge():
    """Merge dated results into scripts/shp_sub_dates.json (existing entries win)."""
    res = json.load(open(RESULTS, encoding="utf-8"))
    led = json.load(open(LEDGER, encoding="utf-8"))
    hist = json.load(open(os.path.join(SCRIPTS, "shp_history.json"), encoding="utf-8"))
    st = Counter()
    for key, v in sorted(res.items()):
        if v.get("verdict") != "dated":
            st[v.get("verdict") or "?"] += 1
            continue
        if key in led:
            st["already-ledgered"] += 1
            continue
        sym, qe = key.split("|")
        qe = int(qe)
        cell = (hist.get(sym) or {}).get(iso_of(qe))
        if not isinstance(cell, list) or len(cell) < 6:
            st["cell-gone"] += 1
            continue
        stored = int(str(cell[5] or "0").replace("-", "") or 0)
        if not SD.is_convention(qe, stored):
            # a real date someone else measured — never overwrite; record disagreement if any
            st["stored-not-convention" if stored != v["sub"] else "confirms-existing"] += 1
            continue
        led[key] = {
            "sub": v["sub"],
            "ts": v["ts"],
            "src": "ann-stream",
            "prov": "bse:AnnSubCategoryGetData NEWS_DT (SW-1 r5 2014-16 recovery)",
            "gated_1530": v["gated_1530"],
            "was": stored,
        }
        st["merged" + ("-confirm" if v["sub"] == stored else "")] += 1
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), indent=0, sort_keys=True)
    print("merge:", dict(st))
    print("ledger now %d entries" % len([k for k in led if not k.startswith("_")]))


if __name__ == "__main__":
    main()
