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
"""Fetch the LIVE sf-data parts and rebuild docs/sf_stock_data.bin locally, so Node
grid/backtest harnesses analyse the same prices the site serves (DATA_RUNBOOK §0 / §7.0 —
the committed bin is a stale snapshot; the daily cron only force-pushes the sf-data repo).

Handles both layouts:
  by-date (sf_meta.deepFrom set): sf_recent_*.bin + sf_deep_*.bin, per-symbol arrays
          concatenated deep-first — exactly what the browser's ensureDeepHistory() does.
  legacy  (no deepFrom): by-symbol sf_stock_data_*.bin halves, plain dict merge.

Run: python fetch_live_sf.py          # overwrites docs/sf_stock_data.bin
Afterwards, if you don't want the tree dirty: git checkout docs/sf_stock_data.bin
"""
import gzip
import json
import os
import time
import urllib.request

BASE = "https://dhruvan246.github.io/sf-data/"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DST = os.path.join(ROOT, "docs", "sf_stock_data.bin")


def fetch(name):
    req = urllib.request.Request(BASE + name, headers={"User-Agent": "fetch_live_sf"})
    with urllib.request.urlopen(req) as r:
        return r.read()


def fetch_bin(name):
    print(f"fetching {name}…", flush=True)
    return json.loads(gzip.decompress(fetch(name)))


def main():
    M = json.loads(fetch("sf_meta.json?t=%d" % time.time()))
    print("live meta:", M, flush=True)
    full = None
    if M.get("deepFrom"):
        parts = [fetch_bin("sf_deep_%d.bin?v=%s" % (i + 1, M["end"])) for i in range(M.get("deep", 0))]
        parts += [fetch_bin("sf_recent_%d.bin?v=%s" % (i + 1, M["end"])) for i in range(M.get("recent", 1))]
        full = {k: v for k, v in parts[-1].items() if k not in ("data", "meta")}
        full["data"], full["meta"] = {}, {}
        for dp in parts:  # deep parts first, so recent arrays APPEND after
            full["meta"].update(dp.get("meta", {}))
            for sym, o in dp["data"].items():
                cur = full["data"].get(sym)
                if cur is None:
                    full["data"][sym] = o
                    continue
                n_cur, n_new = len(cur["d"]), len(o["d"])
                out = {}
                for k in set(cur) | set(o):
                    a, b = cur.get(k), o.get(k)
                    if isinstance(a, list) and len(a) == n_cur and isinstance(b, list) and len(b) == n_new:
                        out[k] = a + b
                    else:
                        out[k] = b if b is not None else a
                full["data"][sym] = out
        full["start"] = M.get("fullStart") or full.get("start")
    else:
        for i in range(M.get("parts", 2)):
            dp = fetch_bin("sf_stock_data_%d.bin?v=%s" % (i + 1, M.get("end", "")))
            if full is None:
                full = {k: v for k, v in dp.items() if k not in ("data", "meta")}
                full["data"], full["meta"] = {}, {}
            full["data"].update(dp["data"])
            full["meta"].update(dp.get("meta", {}))

    # same sanity gates split_sf_data.py enforces before publishing
    et = full["data"].get("ETERNAL")
    if "ZOMATO" in full["data"] or not et or len(et.get("d", [])) < 1000:
        msg = "ABORT: merged data looks UN-merged (ZOMATO present / ETERNAL short) — not writing"
        raise SystemExit(msg)
    with gzip.open(DST, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(full, f, separators=(",", ":"))
    print(
        "wrote %s: %d symbols, end=%s (verify vs live meta above)" % (DST, len(full["data"]), full.get("end")),
        flush=True,
    )


if __name__ == "__main__":
    main()
