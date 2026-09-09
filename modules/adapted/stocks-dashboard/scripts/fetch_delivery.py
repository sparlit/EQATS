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
"""Fetch NSE daily DELIVERY data and compute DELIVERY SPIKES (conviction accumulation):
high delivered quantity vs a stock's own recent baseline + price up = someone is taking
delivery, not day-trading.

SOURCE — the daily full bhavcopy with delivery columns, on the archives host (plain UA,
CI-proven), one file PER DATE:
  https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
  cols: SYMBOL, SERIES, DATE1, PREV_CLOSE, ..., CLOSE_PRICE, ..., TTL_TRD_QNTY,
        TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER   (values space-padded;
        DELIV_* is '-' on non-deliverable series). Published ~19:00 IST on trading days.
  Dated URLs make the pipeline SELF-HEALING: each run walks forward from the last stored
  session and fetches whatever is missing (holidays 404 / return empty and are skipped).

OUTPUTS
  docs/delivery_hist.json  (fetcher state + page detail; NOT page-critical)
     {"days":[YYYYMMDD ints, last KEEP_SESS sessions],
      "stocks":{SYM:[[close, delivQty, delivPct, vol, turnLacs] | null per day]}}
     (cells widened 2026-07-20 for build_volume.py — Volume Shockers; older cells written
      before then are length 3, so any consumer must index defensively, not unpack)
  docs/delivery.json       (the page feed)
     {"updated","from","to",
      "spikes":[[date, sym, name, close, chgPct, delivCr, delivPct, avg20Pct, qtyMult]...],
      "today":[[sym, name, close, chgPct, delivCr, delivPct]...]}  # top TODAY_TOP by value

SPIKE RULE (a day/stock qualifies when ALL hold; baselines use the PRIOR up-to-20
in-window sessions, needing >=MIN_BASE non-null points):
  - mcap >= MCAP_FLOOR (dash_slim meta) and a known company name
  - delivered value >= MIN_DELIV_CR (close*qty/1e7)
  - qtyMult = delivQty / median(prior delivQty) >= QTY_MULT
  - delivPct >= MIN_DPCT  (churn days have low delivery %)
  - close change vs previous stored session >= MIN_CHG_PCT (conviction BUYING; also makes
    corp-action days self-exclude, since unadjusted closes gap down through splits)

Run:  python -X utf8 scripts/fetch_delivery.py       (append missing sessions + rebuild)
      first run with no state seeds the last KEEP_SESS sessions (~45 fetches).
"""
import csv
import datetime
import gzip
import io
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # _get / UA

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
HIST = os.path.join(DOCS, "delivery_hist.json")
OUT = os.path.join(DOCS, "delivery.json")
SLIM = os.path.join(DOCS, "dash_slim.bin")

KEEP_SESS = 45  # sessions of history kept (baseline 20 + display window 25)
BASE_WIN = 20  # baseline = median over the prior up-to-20 sessions
MIN_BASE = 10  # need this many non-null baseline points
MCAP_FLOOR = 100.0  # cr
MIN_DELIV_CR = 1.0  # delivered value floor
QTY_MULT = 3.0  # delivered qty >= 3x own median
MIN_DPCT = 30.0  # delivery % of traded qty
MIN_CHG_PCT = 1.0  # price up on the day
TODAY_TOP = 400  # biggest deliveries table
MAX_BACKWALK = 80  # calendar days to walk when seeding

URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_%02d%02d%04d.csv"


def fetch_day(d):
    """-> {SYM: (close, dq, dpct, vol, turnLacs)} for EQ rows, or None if the file isn't
    there (holiday). vol = TTL_TRD_QNTY (col 10), turnLacs = TURNOVER_LACS (col 11) — the
    Volume Shockers page (build_volume.py) consumes these; delivery uses cols 0/1/2 only.
    Old 3-element cells from before this widened schema are handled downstream."""
    try:
        t = B._get(URL % (d.day, d.month, d.year), headers={"User-Agent": B.UA}, timeout=60)
    except Exception:
        return None
    if len(t) < 10000:
        return None
    out = {}
    for r in csv.reader(io.StringIO(t)):
        if len(r) < 15 or r[1].strip() != "EQ":
            continue
        sym = r[0].strip().upper()
        try:
            close = float(r[8])
            vol = None if r[10].strip() in ("-", "") else int(float(r[10]))
            tlac = None if r[11].strip() in ("-", "") else float(r[11])
            dq = None if r[13].strip() in ("-", "") else int(float(r[13]))
            dp = None if r[14].strip() in ("-", "") else float(r[14])
        except Exception:
            continue
        if sym and close > 0:
            out[sym] = (close, dq, dp, vol, tlac)
    return out if len(out) > 500 else None


def main():
    today = datetime.date.today()
    days, stocks = [], {}
    try:
        h = json.load(open(HIST, encoding="utf-8"))
        days, stocks = h["days"], h["stocks"]
    except Exception:
        pass

    # --- walk forward from the last stored session (or seed backward) ---
    if days:
        start = datetime.date(days[-1] // 10000, days[-1] // 100 % 100, days[-1] % 100) + datetime.timedelta(days=1)
    else:
        start = today - datetime.timedelta(days=MAX_BACKWALK)
        print("no state — seeding the last ~%d sessions" % KEEP_SESS, flush=True)
    added = 0
    d = start
    while d <= today:
        # ALL calendar days — weekend special sessions (budget Saturdays, weekend muhurat,
        # DR-drill Saturdays) are real trading days the old weekday()<5 filter dropped.
        got = fetch_day(d)
        if got:
            # NSE's dated URL can re-serve the prior day's file on non-trading days. A file
            # whose closes are ~all identical to the last stored session is that misdirect,
            # not a session — skip it (protects the now-enumerated ordinary weekends).
            same = tot = 0
            for sym, cell in got.items():
                arr = stocks.get(sym)
                if arr and arr[-1]:
                    tot += 1
                    if abs(arr[-1][0] - cell[0]) < 0.005:
                        same += 1
            if tot > 500 and same / tot > 0.99:
                print(f"  {d.isoformat()}: duplicate of last session — skipped", flush=True)
            else:
                ymd = d.year * 10000 + d.month * 100 + d.day
                for arr in stocks.values():
                    arr.append(None)
                for sym, cell in got.items():
                    arr = stocks.get(sym)
                    if arr is None:
                        arr = stocks[sym] = [None] * (len(days) + 1)
                    arr[-1] = list(cell)
                days.append(ymd)
                added += 1
                print("  +%s (%d stocks)" % (d.isoformat(), len(got)), flush=True)
        time.sleep(0.25)  # after every attempt — a miss is still an HTTP request
        d += datetime.timedelta(days=1)
    print("appended %d sessions (now %d)" % (added, len(days)), flush=True)
    if not days:
        print("no sessions at all — nothing to write", flush=True)
        sys.exit(1)

    # --- trim to KEEP_SESS and drop dead symbols ---
    if len(days) > KEEP_SESS:
        cut = len(days) - KEEP_SESS
        days = days[-KEEP_SESS:]
        for sym in list(stocks):
            stocks[sym] = stocks[sym][cut:]
    for sym in list(stocks):
        if not any(stocks[sym]):
            del stocks[sym]

    # --- names + mcap from the daily dashboard slim payload ---
    # slim meta is keyed 'RELIANCE.NS' (Yahoo-style suffix) — re-key by the bare NSE symbol
    meta = {}
    try:
        raw = json.loads(gzip.decompress(open(SLIM, "rb").read())).get("meta") or {}
        meta = {(v.get("symbol") or k.split(".")[0]).upper(): v for k, v in raw.items()}
    except Exception:
        print("WARN: dash_slim.bin unreadable — spikes will be empty", flush=True)

    # --- spikes over the stored window ---
    spikes = []
    for sym, arr in stocks.items():
        m = meta.get(sym)
        if not m or not m.get("mcap") or m["mcap"] < MCAP_FLOOR or not m.get("name"):
            continue
        prior_dq, prev_close = [], None
        for i in range(len(arr)):
            cell = arr[i]
            if cell is None:
                continue
            close, dq, dp = cell[0], cell[1], cell[2]
            if dq is not None:
                base = [x for x in prior_dq[-BASE_WIN:] if x]
                if len(base) >= MIN_BASE and prev_close and dp is not None:
                    med = statistics.median(base)
                    dcr = dq * close / 1e7
                    chg = (close - prev_close) / prev_close * 100.0
                    if (
                        med > 0
                        and dq >= QTY_MULT * med
                        and dcr >= MIN_DELIV_CR
                        and dp >= MIN_DPCT
                        and chg >= MIN_CHG_PCT
                    ):
                        prior_dp = [c[2] for c in arr[:i] if c and c[2] is not None][-BASE_WIN:]
                        avgp = round(statistics.median(prior_dp), 1) if prior_dp else None
                        spikes.append(
                            [
                                days[i],
                                sym,
                                m["name"],
                                close,
                                round(chg, 1),
                                round(dcr, 2),
                                round(dp, 1),
                                avgp,
                                round(dq / med, 1),
                            ]
                        )
                prior_dq.append(dq)
            if close:
                prev_close = close
    spikes.sort(key=lambda r: (r[0], r[5]), reverse=True)

    # --- biggest deliveries today ---
    last_i = len(days) - 1
    today_rows = []
    for sym, arr in stocks.items():
        cell = arr[last_i]
        m = meta.get(sym)
        if not cell or cell[1] is None or not m or not m.get("name"):
            continue
        close, dq, dp = cell[0], cell[1], cell[2]
        prevs = [c[0] for c in arr[:last_i] if c and c[0]]
        chg = round((close - prevs[-1]) / prevs[-1] * 100.0, 1) if prevs else None
        today_rows.append([sym, m["name"], close, chg, round(dq * close / 1e7, 2), dp])
    today_rows.sort(key=lambda r: -(r[4] or 0))
    today_rows = today_rows[:TODAY_TOP]

    ist = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump({"days": days, "stocks": stocks}, f, separators=(",", ":"))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(
            {
                "updated": ist.strftime("%Y-%m-%d %H:%M"),
                "from": str(days[0]),
                "to": str(days[-1]),
                "spikes": spikes,
                "today": today_rows,
            },
            f,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    print(
        "Wrote %s (%.0f KB, %d spikes over %d sessions) + %s (%.1f MB, %d stocks)"
        % (OUT, os.path.getsize(OUT) / 1024.0, len(spikes), len(days), HIST, os.path.getsize(HIST) / 1e6, len(stocks)),
        flush=True,
    )
    ds = sorted({r[0] for r in spikes}, reverse=True)[:3]
    for dd in ds:
        top = [r for r in spikes if r[0] == dd][:3]
        print(
            "  %d: %d spikes | %s"
            % (dd, sum(1 for r in spikes if r[0] == dd), ", ".join(f"{r[1]} {r[5]:.0f}cr {r[8]:.0f}x" for r in top)),
            flush=True,
        )


if __name__ == "__main__":
    main()
