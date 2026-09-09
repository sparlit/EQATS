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
Injects a synthetic "Gold (INR, since 2006)" instrument into the backtest data
(docs/mf_history.bin + docs/mf_funds.json) so the Rotation / Category-rotation
tools on backtest.html can use gold all the way back to Apr 2006.

Gold-in-INR = international gold (COMEX futures GC=F, USD/oz, via Yahoo Finance)
              x USD-INR rate (INR=X). This is what an Indian gold fund effectively
              tracks (gold price + rupee depreciation). The daily series is cached
              in scripts/gold_inr.json (committed, source of truth) and refreshed
              opportunistically each run; if the fetch fails we fall back to cache.

This ONLY touches the two backtest data files — the mutual-funds dashboard
(built separately from mutual_funds.json) is unaffected, so the synthetic
instrument never shows up in the funds list.

Idempotent: re-running replaces the existing gold record. Safe to call at the
end of fetch_mf_returns.py (wrapped in try/except there) so it survives refreshes.

Run standalone:  python -X utf8 add_gold_instrument.py
"""
import bisect
import gzip
import json
import os
import time
import urllib.request

GOLD_CODE = "9000001"
GOLD_SHORT = "Gold (INR, since 2006) - Synthetic"
GOLD_CAT = "Commodities - Gold (synthetic)"
GOLD_AMC = "Synthetic (Intl gold x USDINR)"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "gold_inr.json")
BIN = os.path.join(ROOT, "docs", "mf_history.bin")
FUNDS = os.path.join(ROOT, "docs", "mf_funds.json")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"


def _yahoo(symbol):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + symbol
        + "?period1=1136073600&period2=1893456000&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        d = json.load(r)["chart"]["result"][0]
    ts, cl = d["timestamp"], d["indicators"]["quote"][0]["close"]
    m = {}
    for t, c in zip(ts, cl, strict=False):
        if c is None:
            continue
        m[int(time.strftime("%Y%m%d", time.gmtime(t)))] = c
    return sorted(m.items())


def fetch_gold_inr():
    """Return sorted list [[yyyymmdd, gold_inr], ...] from 2006-04, or None on failure."""
    try:
        gold = _yahoo("GC=F")  # USD/oz
        inr = _yahoo("INR=X")  # USDINR
        if len(gold) < 1000 or len(inr) < 1000:
            return None
        ik = [y for y, _ in inr]
        iv = [c for _, c in inr]

        def inr_on(y):
            i = bisect.bisect_right(ik, y) - 1
            return iv[i] if i >= 0 else iv[0]

        return [[y, round(g * inr_on(y), 2)] for y, g in gold if y >= 20060401]
    except Exception as e:
        print("  ! gold fetch failed:", e)
        return None


def load_cache():
    try:
        return json.load(open(CACHE))["series"]
    except Exception:
        return None


def main():
    fresh = fetch_gold_inr()
    if fresh:
        json.dump({"series": fresh}, open(CACHE, "w"))
        series = fresh
        print("  gold series refreshed from Yahoo: %d points (%s..%s)" % (len(series), series[0][0], series[-1][0]))
    else:
        series = load_cache()
        if not series:
            print("  ! no gold data (fetch failed and no cache) — skipping gold instrument")
            return
        print("  gold fetch failed — using cached series: %d points" % len(series))

    # load backtest data
    H = json.loads(gzip.decompress(open(BIN, "rb").read()))
    dates = H["dates"]

    gk = [s[0] for s in series]
    gv = [s[1] for s in series]

    def gprior(ymd):
        i = bisect.bisect_right(gk, ymd) - 1
        return gv[i] if i >= 0 else None

    start = bisect.bisect_left(dates, gk[0])  # first axis index >= gold's first date
    paise = []
    for i in range(start, len(dates)):
        v = gprior(dates[i])
        paise.append(round(v * 100))
    # pack: [startIdx, firstPaise, delta1, delta2, ...]
    packed = [start, paise[0]]
    for i in range(1, len(paise)):
        packed.append(paise[i] - paise[i - 1])
    H["data"][GOLD_CODE] = packed
    open(BIN, "wb").write(gzip.compress(json.dumps(H, separators=(",", ":")).encode(), 6))

    # update slim funds list (idempotent)
    funds = json.load(open(FUNDS))
    funds = [f for f in funds if str(f.get("code")) != GOLD_CODE]
    yrs = round(
        (dates[-1] // 10000 - dates[start] // 10000) + ((dates[-1] // 100 % 100) - (dates[start] // 100 % 100)) / 12.0,
        1,
    )
    funds.append(
        {"code": GOLD_CODE, "short": GOLD_SHORT, "plan": "Regular", "category": GOLD_CAT, "years": yrs, "amc": GOLD_AMC}
    )
    json.dump(funds, open(FUNDS, "w"), separators=(",", ":"))

    print(f"  injected {GOLD_CODE} into mf_history.bin (axis {dates[start]}..{dates[-1]}) + mf_funds.json ({yrs:.1f}y)")


if __name__ == "__main__":
    main()
