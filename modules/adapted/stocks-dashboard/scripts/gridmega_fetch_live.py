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
"""Stage the LIVE data the mega grid reads from `scripts/_live/` (DATA_RUNBOOK §7.0/§7.4).

grid_search_mega.js loads ONLY from scripts/_live/ so a grid run analyses exactly the
bytes the site serves, never the stale committed snapshot. This script rebuilds that
directory from the live GitHub Pages origins:

  stock_data_live.bin  <- stocks-dashboard/stock_data.bin   (indicesHistory/fnoHistory/startTs)
  p1_new.bin           <- sf-data parts, merged per-symbol (deep first, recent appended)
  p2_new.bin           <- empty stub (the engine merges p1+p2; one file is enough)
  fund_live.json       <- stocks-dashboard/sf_fundamentals.json
  shp_live.json        <- stocks-dashboard/shp_engine.json
  nifty_live.json      <- stocks-dashboard/nifty.json
  nifty500_live.json   <- stocks-dashboard/nifty500.json

Run: python3 scripts/gridmega_fetch_live.py
"""
import gzip
import json
import os
import sys
import time
import urllib.request

SF = "https://dhruvan246.github.io/sf-data/"
SITE = "https://dhruvan246.github.io/stocks-dashboard/"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_live")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridmega_fetch_live"})
    with urllib.request.urlopen(req) as r:
        return r.read()


def main():
    os.makedirs(OUT, exist_ok=True)
    M = json.loads(get(SF + "sf_meta.json?t=%d" % time.time()))
    print("live sf meta:", M, flush=True)

    # ---- sf price/turnover parts: deep first so recent arrays APPEND after (browser order)
    parts = []
    for i in range(M.get("deep", 0)):
        print("fetching sf_deep_%d.bin…" % (i + 1), flush=True)
        parts.append(json.loads(gzip.decompress(get(SF + "sf_deep_%d.bin?v=%s" % (i + 1, M["end"])))))
    for i in range(M.get("recent", 1)):
        print("fetching sf_recent_%d.bin…" % (i + 1), flush=True)
        parts.append(json.loads(gzip.decompress(get(SF + "sf_recent_%d.bin?v=%s" % (i + 1, M["end"])))))

    full = {k: v for k, v in parts[-1].items() if k not in ("data", "meta")}
    full["data"], full["meta"] = {}, {}
    for dp in parts:
        full["meta"].update(dp.get("meta", {}))
        for sym, o in dp["data"].items():
            tgt = full["data"].setdefault(sym, {})
            for key, arr in o.items():
                if isinstance(arr, list):
                    tgt.setdefault(key, []).extend(arr)
                else:
                    tgt[key] = arr
    full["end"] = M["end"]
    full.setdefault("start", M.get("fullStart"))

    # rename guard — the engine aborts on this, catch it here with a clearer message
    if "ZOMATO" in full["data"] or "ETERNAL" not in full["data"]:
        sys.exit("rename sanity failed: ZOMATO present or ETERNAL missing in live sf-data")

    nbars = sum(len(o.get("d", [])) for o in full["data"].values())
    print("merged: %d symbols, %d bars, end=%s" % (len(full["data"]), nbars, full["end"]), flush=True)

    with open(os.path.join(OUT, "p1_new.bin"), "wb") as f:
        f.write(gzip.compress(json.dumps(full, separators=(",", ":")).encode(), 6))
    with open(os.path.join(OUT, "p2_new.bin"), "wb") as f:
        f.write(gzip.compress(b'{"data":{},"meta":{}}', 6))

    # ---- site files (stock_data.bin is already gzip; copy the bytes through)
    for src, dst in [
        ("stock_data.bin", "stock_data_live.bin"),
        ("sf_fundamentals.json", "fund_live.json"),
        ("shp_engine.json", "shp_live.json"),
        ("nifty.json", "nifty_live.json"),
        ("nifty500.json", "nifty500_live.json"),
    ]:
        print(f"fetching {src}…", flush=True)
        b = get(SITE + src + "?t=%d" % time.time())
        with open(os.path.join(OUT, dst), "wb") as f:
            f.write(b)
        print(f"  {dst}  {len(b) / 1e6:.1f} MB", flush=True)

    print("\n_live/ staged. sf end = {}".format(full["end"]))


if __name__ == "__main__":
    main()
