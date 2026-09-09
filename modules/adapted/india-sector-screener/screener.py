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


"""Fetch Indian equity prices and build the weekly sector screener dataset.

Writes data.json next to this file. Run via run_weekly.sh.

Method
------
Yahoo's own NSE sectoral index series (^CNXAUTO, ^CNXFMCG, ...) update
erratically — several were a month stale when this was built — so sector
performance is computed bottom-up from constituent stocks instead.

For each stock we take daily closes, group them into ISO weeks, and define the
weekly return as (last close of week W) / (last close of week W-1) - 1. A sector's
weekly return is the MEDIAN of its constituents' weekly returns: equal-weighted
and robust to a single heavyweight or a single blow-up dragging the whole sector.
Breadth (share of constituents that rose) is reported alongside, because a median
alone cannot distinguish a broad drift from a narrow one.
"""

import concurrent.futures
import datetime as dt
import json
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

from universe import BENCHMARKS, SECTORS, all_symbols

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"


def fetch_series(symbol, attempts=3):
    """Daily (date, close) pairs for one Yahoo symbol, oldest first."""
    url = CHART.format(sym=urllib.parse.quote(symbol))
    last_err = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = json.load(resp)
            result = payload["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            stamps = result["timestamp"]
            series = [
                (dt.datetime.utcfromtimestamp(t).date(), c)
                for t, c in zip(stamps, closes, strict=False)
                if c is not None
            ]
            name = result["meta"].get("longName") or result["meta"].get("shortName")
            currency = result["meta"].get("currency")
            return series, name, currency
        except Exception as exc:
            last_err = exc
            time.sleep(1.5 * (i + 1))
    msg = f"{symbol}: {last_err}"
    raise RuntimeError(msg)


def resolve(root):
    """Try the NSE listing, fall back to BSE. Returns a stock record or None."""
    for suffix, exch in ((".NS", "NSE"), (".BO", "BSE")):
        try:
            series, name, _ = fetch_series(root + suffix)
        except RuntimeError:
            continue
        if len(series) < 30:
            continue
        # Reject a listing that has gone stale (Yahoo keeps serving dead series).
        if (dt.date.today() - series[-1][0]).days > 10:
            continue
        return {
            "root": root,
            "symbol": root + suffix,
            "exchange": exch,
            "name": name or root,
            "series": series,
        }
    return None


def week_key(d):
    """ISO (year, week) - the bucket a trading day belongs to."""
    iso = d.isocalendar()
    return (iso[0], iso[1])


def weekly_closes(series):
    """[(week_key, last_trading_day, close)] ordered oldest -> newest."""
    buckets = {}
    for d, c in series:
        buckets[week_key(d)] = (d, c)  # later day in the same week overwrites
    return [(k, *buckets[k]) for k in sorted(buckets)]


def pct(new, old):
    return None if not old else (new / old - 1.0) * 100.0


def returns_for(series):
    """Weekly / monthly / quarterly returns plus the week's own span."""
    weeks = weekly_closes(series)
    if len(weeks) < 2:
        return None
    (_, cur_day, cur_close) = weeks[-1]
    (_, prev_day, prev_close) = weeks[-2]

    # Trading days that fall inside the current (latest) ISO week.
    cur_key = weeks[-1][0]
    days_in_week = [d for d, _ in series if week_key(d) == cur_key]

    closes = [c for _, c in series]
    return {
        "last": cur_close,
        "week": pct(cur_close, prev_close),
        "week_start": days_in_week[0].isoformat(),
        "week_end": cur_day.isoformat(),
        "baseline": prev_day.isoformat(),  # close the weekly return is measured from
        "sessions": len(days_in_week),
        "month": pct(cur_close, closes[-22]) if len(closes) >= 22 else None,
        "quarter": pct(cur_close, closes[-64]) if len(closes) >= 64 else None,
        "year": pct(cur_close, closes[0]) if len(closes) >= 200 else None,
        "high_52w": max(closes),
        "from_high": pct(cur_close, max(closes)),
    }


def build():
    roots = all_symbols()
    print(f"resolving {len(roots)} constituents ...")
    stocks = {}
    failed = []
    with concurrent.futures.ThreadPoolExecutor(10) as pool:
        for rec in pool.map(resolve, roots):
            if rec is None:
                continue
            stocks[rec["root"]] = rec
    for r in roots:
        if r not in stocks:
            failed.append(r)
    print(f"  resolved {len(stocks)}, unresolved {len(failed)}: {failed}")

    # Per-stock metrics
    metrics = {}
    for root, rec in stocks.items():
        m = returns_for(rec["series"])
        if not m or m["week"] is None:
            continue
        m.update(
            root=root,
            symbol=rec["symbol"],
            exchange=rec["exchange"],
            name=rec["name"],
        )
        metrics[root] = m

    if not metrics:
        msg = "no usable price data - aborting, keeping previous data.json"
        raise SystemExit(msg)

    # The screener's week is the one most stocks share.
    spans = {}
    for m in metrics.values():
        spans[(m["week_start"], m["week_end"])] = spans.get((m["week_start"], m["week_end"]), 0) + 1
    (week_start, week_end), _ = max(spans.items(), key=lambda kv: kv[1])
    sessions = max(m["sessions"] for m in metrics.values())
    # Modal baseline: the prior week's closing day most constituents measure from.
    bl = {}
    for m in metrics.values():
        bl[m["baseline"]] = bl.get(m["baseline"], 0) + 1
    baseline = max(bl.items(), key=lambda kv: kv[1])[0]
    complete = dt.date.fromisoformat(week_end).weekday() >= 4  # Fri or later

    # Sector aggregates
    sectors = []
    for sector, members in SECTORS.items():
        rows = [metrics[r] for r in members if r in metrics]
        if len(rows) < 3:
            continue
        wk = [r["week"] for r in rows]
        up = sum(1 for v in wk if v > 0)
        rows_sorted = sorted(rows, key=lambda r: r["week"], reverse=True)
        sectors.append(
            {
                "sector": sector,
                "week": statistics.median(wk),
                "mean": statistics.fmean(wk),
                "month": statistics.median([r["month"] for r in rows if r["month"] is not None] or [0]),
                "quarter": statistics.median([r["quarter"] for r in rows if r["quarter"] is not None] or [0]),
                "count": len(rows),
                "advancers": up,
                "decliners": len(rows) - up,
                "breadth": 100.0 * up / len(rows),
                "best": rows_sorted[0]["root"],
                "best_week": rows_sorted[0]["week"],
                "worst": rows_sorted[-1]["root"],
                "worst_week": rows_sorted[-1]["week"],
                "stocks": [
                    {
                        "root": r["root"],
                        "name": r["name"],
                        "symbol": r["symbol"],
                        "exchange": r["exchange"],
                        "last": r["last"],
                        "week": r["week"],
                        "month": r["month"],
                        "quarter": r["quarter"],
                        "from_high": r["from_high"],
                    }
                    for r in rows_sorted
                ],
            }
        )
    sectors.sort(key=lambda s: s["week"], reverse=True)

    # Benchmarks
    benchmarks = []
    for sym, label in BENCHMARKS:
        try:
            series, _, _ = fetch_series(sym)
        except RuntimeError as exc:
            print(f"  benchmark {sym} unavailable: {exc}")
            continue
        m = returns_for(series)
        if not m or m["week"] is None:
            continue
        if (dt.date.today() - dt.date.fromisoformat(m["week_end"])).days > 10:
            print(f"  benchmark {sym} stale ({m['week_end']}) - skipped")
            continue
        benchmarks.append({"symbol": sym, "label": label, **m})

    universe = sorted(metrics.values(), key=lambda m: m["week"], reverse=True)
    data = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "week_start": week_start,
        "week_end": week_end,
        "baseline": baseline,
        "week_complete": complete,
        "sessions": sessions,
        "universe_size": len(metrics),
        "unresolved": failed,
        "benchmarks": benchmarks,
        "sectors": sectors,
        "gainers": [
            {k: m[k] for k in ("root", "name", "symbol", "exchange", "last", "week", "month", "quarter")}
            for m in universe[:15]
        ],
        "losers": [
            {k: m[k] for k in ("root", "name", "symbol", "exchange", "last", "week", "month", "quarter")}
            for m in universe[-15:][::-1]
        ],
        "sector_of": {r["root"]: s["sector"] for s in sectors for r in s["stocks"]},
    }

    # encoding is explicit everywhere: Python defaults to the locale encoding on
    # Windows (cp1252), which cannot represent the rupee sign or the arrows.
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    print(f"wrote {OUT}: week {week_start} -> {week_end}, {len(sectors)} sectors, {len(metrics)} stocks")
    return data


if __name__ == "__main__":
    build()
