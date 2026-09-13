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
"""Completeness audit + fix: add every ALIVE price-universe symbol that's missing from
sf_fundamentals.json. Uses build_fundamentals.fetch_symbol (BOTH NSE endpoints: old
corporates-financial-results for 2017-2024 history + integrated for 2025+), so old companies
get full history and recent IPOs get whatever exists. Symbols NSE genuinely doesn't serve
return empty and stay absent. Resumable + incremental flush. NSE-only (won't touch BSE run)."""
import concurrent.futures
import gzip
import json
import os
import threading

import build_fundamentals as bf

DOCS = os.path.join(os.path.dirname(bf.HERE), "docs", "sf_fundamentals.json")
OUT = bf.OUT
BIN = os.path.join(os.path.dirname(bf.HERE), "docs", "sf_stock_data.bin")


def main():
    data = json.load(open(DOCS))
    D = json.loads(gzip.decompress(open(BIN, "rb").read()))
    meta = D.get("meta", {})
    alive = [s for s in D["data"] if meta.get(s, {}).get("alive") is not False]
    missing = sorted(s for s in alive if s not in data or not data.get(s))
    print("alive symbols missing fundamentals: %d" % len(missing))
    _tl = threading.local()

    def jar():
        if not getattr(_tl, "jar", None):
            _tl.jar = bf.nse_jar()
        return _tl.jar

    def do(sym):
        try:
            out = bf.fetch_symbol(sym, jar())
            if out is None:
                _tl.jar = bf.nse_jar()
                out = bf.fetch_symbol(sym, _tl.jar)
        except Exception:
            out = None
        return sym, out

    lock = threading.Lock()
    done = added = quarters = 0

    def flush():
        for path in (DOCS, OUT):  # atomic: write tmp then rename, so a
            tmp = path + ".tmp"  # mid-write crash can't corrupt the live file
            json.dump(data, open(tmp, "w"), separators=(",", ":"))
            os.replace(tmp, path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for sym, out in ex.map(do, missing):
            done += 1
            with lock:
                if out:
                    data[sym] = out
                    added += 1
                    quarters += len(out)
                if done % 25 == 0 or done == len(missing):
                    flush()
                    print("  ...%d/%d  added=%d  quarters=%d" % (done, len(missing), added, quarters))
    flush()
    print(
        "DONE. added %d symbols (%d quarters) from NSE. %d genuinely not served."
        % (added, quarters, len(missing) - added)
    )


if __name__ == "__main__":
    main()
