#!/usr/bin/env python3
"""Daily spot closes for the four F&O indices, for days where bhavcopy has no
UndrlygPric (old format <= 2024-07-05). Source: Yahoo v8 chart API (the site's
established index-history route, runbook §"index history source").

Writes scripts/fo_spot.json  {SYM: {iso_date: close}}
Merged into the store by build_fo_store.py; days with neither UndrlygPric nor a
spot row are flagged spot-NA in the store (engine then refuses Spot-as-ATM there).
"""
import json, os, sys, time

from curl_cffi import requests as cr

YH = {
    "NIFTY":      "^NSEI",
    "BANKNIFTY":  "^NSEBANK",
    "FINNIFTY":   "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",   # no real Yahoo history (1 row) — NSE official is the only source
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
OUT = os.path.join(os.path.dirname(__file__), "fo_spot.json")

def fetch(sym_yh):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym_yh}"
           "?period1=1420070400&period2=9999999999&interval=1d")
    r = cr.get(url, impersonate="chrome", timeout=60)   # plain urllib gets 429'd
    d = r.json()
    res = d["chart"]["result"][0]
    ts = res.get("timestamp") or []
    closes = res["indicators"]["quote"][0].get("close") or []
    out = {}
    import datetime as dt
    for t, c in zip(ts, closes):
        if c is None:
            continue
        iso = dt.datetime.fromtimestamp(t, dt.timezone(dt.timedelta(hours=5, minutes=30))).date().isoformat()
        out[iso] = round(float(c), 2)
    return out

def main():
    data = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for sym, yh in YH.items():
        try:
            got = fetch(yh)
            if len(got) < 100 and sym in ("NIFTY", "BANKNIFTY"):
                print(f"{sym}: only {len(got)} rows - REFUSING to overwrite", file=sys.stderr)
                continue
            data[sym] = got
            print(f"{sym}: {len(got)} days  {min(got)}..{max(got)}")
        except Exception as e:
            print(f"{sym}: FAILED {e}", file=sys.stderr)
        time.sleep(1.0)
    json.dump(data, open(OUT, "w"), separators=(",", ":"))
    print("wrote", OUT)

if __name__ == "__main__":
    main()
