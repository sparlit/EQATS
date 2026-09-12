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
"""Build the VOLUME SHOCKERS feed (docs/volume.json) — stocks trading many times their
own recent average volume today, the first sign of sudden interest.

This is a DERIVED view: it reads the delivery pipeline's rolling history
(docs/delivery_hist.json, refreshed every trading evening by fetch_delivery.py) plus the
dashboard slim meta for names / sectors / market-cap, and the F&O universe. No network.
Run it right after fetch_delivery.py in the same workflow.

VOLUME per stock/day:
  - exact NSE column TTL_TRD_QNTY when the cell carries it (cells written from 2026-07-20
    are [close, delivQty, delivPct, vol, turnLacs]);
  - else reconstructed as delivQty / (delivPct/100)  — exact up to the rounding of the
    stored delivery %, which is how the seed window (older 3-element cells) is filled until
    exact columns accrue over the next ~45 sessions.
TURNOVER ₹cr: exact TURNOVER_LACS/100 when present, else close * vol / 1e7.

A stock qualifies for the latest session when it has >= MIN_BASE prior non-null sessions and
  ratio = todayVol / mean(prior up-to-BASE_WIN vols) >= RATIO_FLOOR
and clears a small liquidity floor (turnover >= MIN_TURN_CR) so dead microcaps don't dominate.
The page does the finer ratio / turnover filtering client-side.

OUTPUT  docs/volume.json
  {"updated","date","from","to",
   "rows":[[sym,name,ltp,chg%,vol,avg20,ratio,turnCr,delivPct|null,sector,mcap|null,fno0/1,
            near52%|null,dir]...],   # dir: 1 up / -1 down / 0 flat  (latest session)
   "sectors":[[sector,count,upCount]...],       # sector mix of today's shockers
   "repeat":[[sym,name,nSess,bestRatio,lastDate]...],  # shockers >=RATIO_HI in last REPEAT_SESS
   "stats":{"n","medRatio","delivConf","up","down","fno","maxRatio","maxSym"}}

Run:  python -X utf8 scripts/build_volume.py
"""
import datetime
import gzip
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
HIST = os.path.join(DOCS, "delivery_hist.json")
SLIM = os.path.join(DOCS, "dash_slim.bin")
FNO = os.path.join(HERE, "fno_list.json")
OUT = os.path.join(DOCS, "volume.json")

BASE_WIN = 20  # baseline = mean over the prior up-to-20 sessions (today excluded)
MIN_BASE = 15  # need this many prior non-null sessions to score (recent listings wait)
RATIO_FLOOR = 2.0  # keep rows >= 2x for the page (its filter goes 2/3/5/10x)
RATIO_HI = 3.0  # "repeat shocker" threshold across recent sessions
MIN_TURN_CR = 0.05  # ₹5 lakh liquidity floor — drop dead stocks, keep true small-caps
REPEAT_SESS = 5  # look-back window for the repeat-shocker view


def cell_vol(c):
    """Exact TTL_TRD_QNTY if the cell carries it, else reconstruct from delivered qty / %."""
    if c is None:
        return None
    if len(c) >= 4 and c[3]:
        return float(c[3])
    if c[1] and c[2]:  # delivQty and delivPct present
        return c[1] * 100.0 / c[2]
    return None


def cell_turn_cr(c, vol):
    """Exact TURNOVER_LACS/100 if present, else close*vol/1e7."""
    if c is not None and len(c) >= 5 and c[4]:
        return c[4] / 100.0
    if vol and c and c[0]:
        return c[0] * vol / 1e7
    return None


def score_day(arr, i, meta_ok):
    """Return a shocker row for stock-array `arr` at session index i, or None.
    Row: [ltp, chg%, vol, avg20, ratio, turnCr, delivPct, dir]."""
    cell = arr[i]
    if cell is None:
        return None
    vol = cell_vol(cell)
    if not vol or vol <= 0:
        return None
    prior = []
    for c in arr[:i]:
        v = cell_vol(c)
        if v:
            prior.append(v)
    prior = prior[-BASE_WIN:]
    if len(prior) < MIN_BASE:
        return None
    avg = statistics.mean(prior)
    if avg <= 0:
        return None
    ratio = vol / avg
    if ratio < RATIO_FLOOR:
        return None
    turn = cell_turn_cr(cell, vol)
    if turn is None or turn < MIN_TURN_CR:
        return None
    close = cell[0]
    prev = None
    for c in arr[i - 1 :: -1] if i else []:
        if c and c[0]:
            prev = c[0]
            break
    chg = round((close - prev) / prev * 100.0, 1) if prev else None
    dp = cell[2]
    dr = 0 if chg is None else (1 if chg > 0.05 else -1 if chg < -0.05 else 0)
    return [
        round(close, 2),
        chg,
        round(vol),
        round(avg),
        round(ratio, 1),
        round(turn, 2),
        (round(dp, 1) if dp is not None else None),
        dr,
    ]


def main():
    h = json.load(open(HIST, encoding="utf-8"))
    days, stocks = h["days"], h["stocks"]
    if not days:
        print("no sessions in delivery_hist.json — run fetch_delivery.py first", flush=True)
        sys.exit(1)
    last = len(days) - 1

    # names / sector / mcap / 52w — slim meta is keyed 'RELIANCE.NS'; re-key by bare symbol
    meta = {}
    try:
        raw = json.loads(gzip.decompress(open(SLIM, "rb").read())).get("meta") or {}
        meta = {(v.get("symbol") or k.split(".")[0]).upper(): v for k, v in raw.items()}
    except Exception:
        print("WARN: dash_slim.bin unreadable — names/sectors will be blank", flush=True)
    try:
        fno = set(json.load(open(FNO, encoding="utf-8")).get("stocks") or [])
    except Exception:
        fno = set()

    rows = []
    for sym, arr in stocks.items():
        m = meta.get(sym)
        if not m or not m.get("name"):  # mainboard equities only (need a real name)
            continue
        r = score_day(arr, last, m)
        if r is None:
            continue
        ltp, chg, vol, avg, ratio, turn, dp, dr = r
        _h52, d52 = m.get("h52"), m.get("d52")
        # distance below the 52w high, from the meta drawdown (d52 is % below high, negative)
        near = round(d52, 1) if isinstance(d52, (int, float)) else None
        rows.append(
            [
                sym,
                m["name"],
                ltp,
                chg,
                vol,
                avg,
                ratio,
                turn,
                dp,
                m.get("sector") or "—",
                round(m.get("mcap"), 0) if m.get("mcap") else None,
                1 if sym in fno else 0,
                near,
                dr,
            ]
        )
    rows.sort(key=lambda x: -x[6])  # by ratio desc

    # sector mix of today's shockers
    sec = {}
    for x in rows:
        s = sec.setdefault(x[9], [0, 0])
        s[0] += 1
        if x[13] > 0:
            s[1] += 1
    sectors = sorted(([s, c, u] for s, (c, u) in sec.items()), key=lambda z: -z[1])

    # repeat shockers over the last REPEAT_SESS sessions (ratio >= RATIO_HI on any of them)
    rep = {}
    lo = max(0, len(days) - REPEAT_SESS)
    for sym, arr in stocks.items():
        m = meta.get(sym)
        if not m or not m.get("name"):
            continue
        for i in range(lo, len(days)):
            r = score_day(arr, i, m)
            if r and r[4] >= RATIO_HI:
                a = rep.setdefault(sym, [m["name"], 0, 0.0, 0])
                a[1] += 1
                a[2] = max(a[2], r[4])
                a[3] = max(a[3], days[i])
    repeat = sorted(
        ([s, a[0], a[1], round(a[2], 1), a[3]] for s, a in rep.items() if a[1] >= 2), key=lambda z: (-z[2], -z[3])
    )

    ratios = [x[6] for x in rows]
    stats = {
        "n": len(rows),
        "medRatio": round(statistics.median(ratios), 1) if ratios else 0,
        "delivConf": sum(1 for x in rows if x[8] is not None and x[8] >= 50),
        "up": sum(1 for x in rows if x[13] > 0),
        "down": sum(1 for x in rows if x[13] < 0),
        "fno": sum(1 for x in rows if x[11]),
        "maxRatio": rows[0][6] if rows else 0,
        "maxSym": rows[0][0] if rows else "",
    }

    ist = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(
            {
                "updated": ist.strftime("%Y-%m-%d %H:%M"),
                "date": str(days[last]),
                "from": str(days[0]),
                "to": str(days[last]),
                "rows": rows,
                "sectors": sectors,
                "repeat": repeat,
                "stats": stats,
            },
            f,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    print(
        "Wrote %s (%.0f KB) — %d shockers on %s, median %.1fx, top %s %.0fx, %d F&O, %d deliv-conf"
        % (
            OUT,
            os.path.getsize(OUT) / 1024.0,
            stats["n"],
            days[last],
            stats["medRatio"],
            stats["maxSym"],
            stats["maxRatio"],
            stats["fno"],
            stats["delivConf"],
        ),
        flush=True,
    )
    for x in rows[:6]:
        print("  %-11s %6.1fx  vol %9d avg %8d  ₹%8.1f cr  %s" % (x[0], x[6], x[4], x[5], x[7], x[9]), flush=True)


if __name__ == "__main__":
    main()
