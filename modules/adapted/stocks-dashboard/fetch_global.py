#!/usr/bin/env python3
"""Fetch the GLOBAL MARKETS dashboard -> docs/global.json.

Powers docs/global.html — "what moved overnight" for the Indian open: US / Europe /
Asia / India indices, commodities, crypto and FX/rates, each with last close, 1D/1W/
1M/YTD/1Y change, a 60-point sparkline, 52-week range position, and — our own twist —
each instrument's correlation to the Nifty 50 so the page can build a *global cue*
score for today's open weighted by what actually tracks India.

SOURCE: Yahoo Finance chart API (keyless, reachable from GitHub runners), same helper
as fetch_macro.py. STATELESS: rebuilt from scratch each run from ~2y of daily history,
so there is no accumulation to corrupt; a failed symbol just drops out and self-heals.

stdlib only + build_fundamentals (shared UA / _get opener).
"""
import datetime
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # _get / UA

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "global.json")
UA = B.UA

# ---- instrument catalogue --------------------------------------------------
# (id, Yahoo symbol, display name, group, unit/decimals)  — order within a group
# is the display order. "dp" = decimals to round the last price to.
INSTRUMENTS = [
    # --- US ---
    ("spx",    "^GSPC",     "S&P 500",            "US",          2),
    ("ndq",    "^IXIC",     "Nasdaq Composite",   "US",          2),
    ("dji",    "^DJI",      "Dow Jones",          "US",          2),
    ("rut",    "^RUT",      "Russell 2000",       "US",          2),
    ("vix",    "^VIX",      "VIX (fear index)",   "US",          2),
    # --- Europe ---
    ("ukx",    "^FTSE",     "FTSE 100",           "Europe",      2),
    ("dax",    "^GDAXI",    "DAX",                "Europe",      2),
    ("cac",    "^FCHI",     "CAC 40",             "Europe",      2),
    ("sx5e",   "^STOXX50E", "Euro Stoxx 50",      "Europe",      2),
    # --- Asia ---
    ("nkx",    "^N225",     "Nikkei 225",         "Asia",        2),
    ("hsi",    "^HSI",      "Hang Seng",          "Asia",        2),
    ("shc",    "000001.SS", "Shanghai Composite", "Asia",        2),
    ("kospi",  "^KS11",     "KOSPI",              "Asia",        2),
    ("twii",   "^TWII",     "Taiwan Weighted",    "Asia",        2),
    ("axjo",   "^AXJO",     "ASX 200",            "Asia",        2),
    # --- India (context / benchmark) ---
    ("nifty",  "^NSEI",     "Nifty 50",           "India",       2),
    ("sensex", "^BSESN",    "Sensex",             "India",       2),
    ("bank",   "^NSEBANK",  "Bank Nifty",         "India",       2),
    # --- Commodities ---
    ("gold",   "GC=F",      "Gold",               "Commodities", 1),
    ("silver", "SI=F",      "Silver",             "Commodities", 3),
    ("plat",   "PL=F",      "Platinum",           "Commodities", 1),
    ("copper", "HG=F",      "Copper",             "Commodities", 3),
    ("brent",  "BZ=F",      "Brent Crude",        "Commodities", 2),
    ("wti",    "CL=F",      "WTI Crude",          "Commodities", 2),
    ("natgas", "NG=F",      "Natural Gas",        "Commodities", 3),
    # --- Crypto ---
    ("btc",    "BTC-USD",   "Bitcoin",            "Crypto",      0),
    ("eth",    "ETH-USD",   "Ethereum",           "Crypto",      1),
    # --- FX & Rates ---
    ("usdinr", "INR=X",     "USD/INR",            "FX & Rates",  3),
    ("dxy",    "DX-Y.NYB",  "Dollar Index (DXY)", "FX & Rates",  2),
    ("eurusd", "EURUSD=X",  "EUR/USD",            "FX & Rates",  4),
    ("usdjpy", "JPY=X",     "USD/JPY",            "FX & Rates",  2),
    ("us10y",  "^TNX",      "US 10-Year Yield",   "FX & Rates",  2),
]

# groups shown as instrument cards vs. the FX rail (page treats these two the same
# but keeps FX/rates visually apart). Correlation-to-Nifty is meaningful for the
# risk assets; for India itself and FX it is dropped (None).
NIFTY_ID = "nifty"
NO_CORR = {"nifty", "sensex", "bank", "usdinr", "dxy", "eurusd", "usdjpy", "us10y", "vix"}

SPARK_N = 60          # sparkline points
CORR_N = 252          # ~1y of daily returns for correlation-to-Nifty


def fetch_yahoo(sym):
    """Ordered [(date, close)] daily history (~2y) for a Yahoo symbol."""
    now = int(time.time())
    p1 = now - 800 * 86400            # ~2.2 years back
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + sym +
           "?period1=%d&period2=%d&interval=1d" % (p1, now))
    j = json.loads(B._get(url, headers={"User-Agent": UA}, timeout=30))
    res = j["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    out = []
    for t, c in zip(res["timestamp"], closes):
        if c is None:
            continue
        out.append((time.strftime("%Y-%m-%d", time.gmtime(t)), float(c)))
    return out


def pct(cur, base):
    if base is None or base == 0 or cur is None:
        return None
    return round((cur - base) / abs(base) * 100, 2)


def value_n_ago(series, n):
    """close n trading sessions before the last one (series = [(date,close)])."""
    if len(series) <= n:
        return None
    return series[-1 - n][1]


def value_on_or_before(series, iso):
    """last close on or before an ISO date, for YTD / 1y anchors."""
    v = None
    for d, c in series:
        if d <= iso:
            v = c
        else:
            break
    return v


def returns_map(series):
    """{date: daily % return} over the last CORR_N+1 sessions."""
    tail = series[-(CORR_N + 1):]
    out = {}
    for i in range(1, len(tail)):
        p0 = tail[i - 1][1]
        if p0:
            out[tail[i][0]] = (tail[i][1] - p0) / p0
    return out


def correlation(a, b):
    """Pearson correlation of two {date: value} maps over their shared dates."""
    keys = sorted(set(a) & set(b))
    if len(keys) < 40:
        return None
    xs = [a[k] for k in keys]
    ys = [b[k] for k in keys]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / math.sqrt(sxx * syy), 2)


def build_one(inst, nifty_ret):
    _id, sym, name, group, dp = inst
    series = fetch_yahoo(sym)
    if len(series) < 30:
        raise ValueError("history too short (%d rows)" % len(series))

    last_date, last = series[-1]
    prev = value_n_ago(series, 1)
    today = datetime.date.today().isoformat()
    year_start = last_date[:4] + "-01-01"
    y1_iso = (datetime.date.fromisoformat(last_date) -
              datetime.timedelta(days=365)).isoformat()

    tail = [c for _, c in series[-260:]]           # ~52 trading weeks
    hi52, lo52 = max(tail), min(tail)
    rng = hi52 - lo52
    range_pos = round((last - lo52) / rng, 3) if rng > 0 else None

    corr = None
    if _id not in NO_CORR and nifty_ret:
        corr = correlation(returns_map(series), nifty_ret)

    return {
        "id": _id, "name": name, "group": group, "symbol": sym, "dp": dp,
        "last": round(last, dp), "last_date": last_date,
        "prev": round(prev, dp) if prev is not None else None,
        "stale": last_date < today,                # region already closed / pre-update
        "d1":  pct(last, prev),
        "w1":  pct(last, value_n_ago(series, 5)),
        "m1":  pct(last, value_n_ago(series, 21)),
        "ytd": pct(last, value_on_or_before(series, year_start)),
        "y1":  pct(last, value_on_or_before(series, y1_iso)),
        "hi52": round(hi52, dp), "lo52": round(lo52, dp), "range_pos": range_pos,
        "corr": corr,
        "spark": [round(c, dp) for _, c in series[-SPARK_N:]],
    }


def main():
    ok, fail = [], []

    # Nifty first so every other instrument can correlate against it.
    nifty_ret = {}
    try:
        nifty_series = fetch_yahoo("^NSEI")
        nifty_ret = returns_map(nifty_series)
    except Exception as e:
        print("WARN nifty returns unavailable (%s) — corr will be null" % str(e)[:60],
              file=sys.stderr)

    rows = []
    for inst in INSTRUMENTS:
        try:
            rows.append(build_one(inst, nifty_ret))
            ok.append(inst[0])
        except Exception as e:
            fail.append("%s (%s)" % (inst[0], str(e)[:60]))
        time.sleep(0.15)   # be gentle with Yahoo

    if len(rows) < 10:
        print("ERROR only %d instruments fetched — refusing to write" % len(rows),
              file=sys.stderr)
        sys.exit(1)

    # group in catalogue order, keep FX/rates separate as the "fx" rail
    order = {}
    for i, inst in enumerate(INSTRUMENTS):
        order[inst[0]] = i
    rows.sort(key=lambda r: order[r["id"]])

    groups, fx = {}, []
    for r in rows:
        if r["group"] == "FX & Rates":
            fx.append(r)
        else:
            groups.setdefault(r["group"], []).append(r)

    as_of = max(r["last_date"] for r in rows)
    out = {
        "as_of": as_of,
        "updated": datetime.datetime.now(datetime.timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "Yahoo Finance",
        "groups": groups,
        "fx": fx,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

    print("wrote docs/global.json | %d instruments, %d fx | as_of %s"
          % (sum(len(v) for v in groups.values()), len(fx), as_of))
    print("OK:", ", ".join(ok))
    if fail:
        print("FAILED:", "; ".join(fail), file=sys.stderr)


if __name__ == "__main__":
    main()
