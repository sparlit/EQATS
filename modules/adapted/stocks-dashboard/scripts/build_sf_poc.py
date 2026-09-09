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
PROOF-OF-CONCEPT: build a SURVIVORSHIP-FREE daily price+turnover database for
2019-2020 (covers the COVID crash) from NSE daily bhavcopies — which include
every stock that traded each day, INCLUDING ones delisted/dead today.

Two bhavcopy formats are handled:
  * 2020+ : https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
  * <2020 : https://nsearchives.nseindia.com/content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip (zip)

Split/bonus adjustment: NSE reports a corporate-action-adjusted PREV_CLOSE, so we
chain daily returns close/prev_close into a clean adjusted index per symbol.

Output: scripts/sf_poc.json.gz  = {meta:{...}, data:{SYM:{d:[YYYYMMDD],c:[adjClose],t:[turnoverLacs]}}}
Run:  python -X utf8 build_sf_poc.py [START] [END]   (defaults 2019-01-01 .. 2020-12-31)
"""
import csv
import datetime
import gzip
import http.cookiejar
import io
import json
import os
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "sf_poc.json.gz")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

START = datetime.date(2019, 1, 1)
END = datetime.date(2020, 12, 31)
if len(sys.argv) > 1:
    START = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
if len(sys.argv) > 2:
    END = datetime.datetime.strptime(sys.argv[2], "%Y-%m-%d").date()


def jar():
    j = http.cookiejar.CookieJar()
    try:
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
        op.open(urllib.request.Request("https://www.nseindia.com/", headers={"User-Agent": UA}), timeout=20).read()
    except Exception:
        pass
    return j


def get(url, j, timeout=30):
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(j))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/"})
    with op.open(req, timeout=timeout) as r:
        return r.read()


def parse_rows(text):
    """Yield (symbol, close, prevclose, turnover_lacs) for EQ/BE rows. Handles both formats."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return
    hdr = [h.strip().upper() for h in rows[0]]

    def idx(*names):
        for n in names:
            if n in hdr:
                return hdr.index(n)
        return -1

    iS = idx("SYMBOL")
    iSer = idx("SERIES")
    iC = idx("CLOSE_PRICE", "CLOSE")
    iP = idx("PREV_CLOSE", "PREVCLOSE")
    iT = idx("TURNOVER_LACS", "TOTTRDVAL")
    if iS < 0 or iC < 0:
        return
    for r in rows[1:]:
        if len(r) <= max(iS, iC):
            continue
        ser = r[iSer].strip() if iSer >= 0 else "EQ"
        if ser not in ("EQ", "BE"):
            continue
        try:
            c = float(r[iC])
            p = float(r[iP]) if iP >= 0 and r[iP].strip() else 0.0
            t = float(r[iT]) if iT >= 0 and r[iT].strip() else 0.0
        except ValueError:
            continue
        if c > 0:
            yield r[iS].strip(), c, p, t


def fetch_day(d, j):
    ddmmyyyy = d.strftime("%d%m%Y")
    new = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
    old = "https://nsearchives.nseindia.com/content/historical/EQUITIES/%d/%s/cm%02d%s%dbhav.csv.zip" % (
        d.year,
        MON[d.month - 1],
        d.day,
        MON[d.month - 1],
        d.year,
    )
    # newer dates: try new csv first; older: try zip first
    order = [new, old] if d.year >= 2020 else [old, new]
    for url in order:
        try:
            blob = get(url, j)
            if url.endswith(".zip"):
                z = zipfile.ZipFile(io.BytesIO(blob))
                text = z.read(z.namelist()[0]).decode("utf-8", "replace")
            else:
                text = blob.decode("utf-8", "replace")
            if "SYMBOL" in text[:200].upper():
                return list(parse_rows(text))
        except Exception:
            continue
    return None


def main():
    j = jar()
    acc = {}  # sym -> list of (yyyymmdd, close, prevclose, turnover)
    d = START
    tried = got = 0
    while d <= END:
        if d.weekday() < 5:
            tried += 1
            rows = fetch_day(d, j)
            if rows:
                got += 1
                ymd = int(d.strftime("%Y%m%d"))
                for sym, c, p, t in rows:
                    acc.setdefault(sym, []).append((ymd, c, p, t))
            if tried % 100 == 0:
                print("  ...%s  days fetched %d/%d  symbols %d" % (d, got, tried, len(acc)))
            if tried % 250 == 0:
                j = jar()
            time.sleep(0.35)
        d += datetime.timedelta(days=1)
    print("Fetched %d/%d trading days; %d distinct symbols" % (got, tried, len(acc)))

    # current (survivor) universe to tag dead stocks + borrow industry/name
    cur = {}
    try:
        import base64
        import re

        h = open(os.path.join(ROOT, "docs", "nse-bse-dashboard.html"), encoding="utf-8").read()
        b64 = re.search(r'<script id="compressedData"[^>]*>([A-Za-z0-9+/=]+)</script>', h).group(1)
        D = json.loads(gzip.decompress(base64.b64decode(b64)))
        for m in D["meta"].values():
            cur[m["symbol"]] = {"name": m.get("name"), "industry": m.get("industry") or m.get("sector")}
    except Exception as e:
        print("  (could not load current meta:", e, ")")

    data, meta = {}, {}
    dead = 0
    for sym, obs in acc.items():
        obs.sort()
        ds, cs, ts = [], [], []
        adj = None
        for i, (ymd, c, p, t) in enumerate(obs):
            if adj is None:
                adj = c
            else:
                ret = (c / p) if (p and p > 0) else (c / obs[i - 1][1] if obs[i - 1][1] else 1.0)
                adj = adj * ret
            ds.append(ymd)
            cs.append(round(adj, 2))
            ts.append(round(t, 1))
        if len(ds) < 20:
            continue
        data[sym] = {"d": ds, "c": cs, "t": ts}
        alive = sym in cur
        if not alive:
            dead += 1
        meta[sym] = {
            "name": (cur.get(sym) or {}).get("name") or sym,
            "ind": (cur.get(sym) or {}).get("industry") or "Unknown",
            "alive": alive,
        }
    print("Kept %d symbols (>=20 days); %d are DELISTED/absent-from-current-data" % (len(data), dead))

    blob = gzip.compress(
        json.dumps(
            {"start": START.isoformat(), "end": END.isoformat(), "meta": meta, "data": data}, separators=(",", ":")
        ).encode(),
        6,
    )
    open(OUT, "wb").write(blob)
    print(f"Wrote {OUT} ({len(blob) / 1048576:.2f} MB)")


if __name__ == "__main__":
    main()
