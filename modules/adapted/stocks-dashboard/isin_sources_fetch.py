# -*- coding: utf-8 -*-
"""Stage NSE's own DATED security lists so the issuer sweep can see past our ISIN gaps.

The bin's `meta[sym].isin` comes from the bhavcopy's ISIN column, and NSE only started printing
that column in 2011 (measured on the live bin: every one of the 1,003 keys whose last bar is
2010 or earlier has NO isin, 30/30 of the keys that died in 2012 have one). It is also lost for
a merged key whose surviving side was a day-1 stub (TVSHLTD carries none although SUNCLAYTON,
the key it should have absorbed, carries INE105A01027). Both gaps hide exactly the defect the
sweep is hunting, so fill them from primary dated files:

  EQUITY_L.csv (live)          -> ISIN for every currently-listed symbol
  EQUITY_L.csv (Wayback)       -> ISIN as of the capture date, for symbols long dead

⚠️ A security list is keyed by SYMBOL, and NSE RE-ISSUES symbols (89, the DVL/DTIL chimera), so
a symbol->ISIN row is only evidence about the company that held that symbol ON THAT DATE. The
sweep therefore applies the live list only to keys still trading and an archived list only to
keys whose own bars straddle the capture date; this script just stages the bytes.

Run:  python3 scripts/isin_sources_fetch.py     -> scripts/_live/equity_l_*.csv
"""
import http.cookiejar, json, os, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_live")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120 Safari/537.36")
LIVE_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
CDX = ("http://web.archive.org/cdx/search/cdx?url=nseindia.com/content/equities/EQUITY_L.csv"
       "&output=json&fl=timestamp,statuscode&collapse=digest&limit=400")
# Only the pre-2012 captures add anything: every key whose last bar is 2011+ already carries a
# bhavcopy ISIN. Kept as a prefix test so a future re-run picks up any new early capture.
WANT_BEFORE = "2012"


def get(url, jar=None, timeout=60):
    op = (urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
          if jar is not None else urllib.request.build_opener())
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Referer": "https://www.nseindia.com/"})
    with op.open(req, timeout=timeout) as r:
        return r.read()


def stage(name, blob):
    head = blob[:200].decode("utf-8", "replace").upper()
    if "SYMBOL" not in head or "ISIN" not in head:
        print("  %s: not a security list (%r) — skipped" % (name, head[:60]))
        return 0
    p = os.path.join(OUT, name)
    with open(p, "wb") as f:
        f.write(blob)
    n = blob.count(b"\n") - 1
    print("  %s: %d rows, %d bytes" % (name, n, len(blob)))
    return n


def main():
    os.makedirs(OUT, exist_ok=True)
    print("live EQUITY_L:")
    stage("equity_l_live.csv", get(LIVE_URL, http.cookiejar.CookieJar()))

    print("Wayback captures before %s:" % WANT_BEFORE)
    rows = json.loads(get(CDX))[1:]
    for ts, status in rows:
        if status != "200" or ts >= WANT_BEFORE:
            continue
        url = "http://web.archive.org/web/%sid_/http://www.nseindia.com/content/equities/EQUITY_L.csv" % ts
        try:
            stage("equity_l_wb_%s.csv" % ts[:8], get(url))
        except Exception as e:
            print("  %s: %s" % (ts, e))


if __name__ == "__main__":
    main()
