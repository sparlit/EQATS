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


"""
NSE Delivery % Scanner.
High delivery % (>50-60%) = real buying, not F&O churn.
Low delivery % (<30%) on big green candle = speculative, likely to fade.

Fetches bhavcopy CSV from NSE archives, stores daily delivery data,
computes rolling delivery metrics, and flags accumulation/distribution.

Tables:
  delivery_daily(date, symbol, traded_qty, deliverable_qty,
                 delivery_pct, close, created_at)

Usage:
  python delivery.py fetch [YYYY-MM-DD]   -> fetch bhavcopy for date
  python delivery.py backfill [N]          -> backfill last N trading days
  python delivery.py top [N]              -> show top delivery% today
  python delivery.py accum [N]            -> show accumulation candidates
  python delivery.py symbol SYMBOL        -> delivery history for symbol
"""
import contextlib
import csv
import datetime as dt
import io
import json
import os
import sys
import zipfile

import db

try:
    import requests
except ImportError:
    requests = None

NSE_BHAV_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
NSE_BHAV_URL_ALT = "https://archives.nseindia.com/content/historical/EQUITIES/cm/cm{date2}bhav.csv.zip"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

MIN_TRADED_QTY = 50000


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS delivery_daily(
        date TEXT, symbol TEXT, traded_qty INTEGER,
        deliverable_qty INTEGER, delivery_pct REAL,
        close REAL, created_at TEXT,
        PRIMARY KEY(date, symbol))""")


def _session():
    if requests is None:
        msg = "requests not installed"
        raise ImportError(msg)
    s = requests.Session()
    s.headers.update(HEADERS)
    with contextlib.suppress(Exception):
        s.get("https://www.nseindia.com/", timeout=10)
    return s


def _parse_csv(text):
    """Parse NSE bhavcopy CSV -> list of dicts."""
    rows = []
    reader = csv.DictReader(io.StringIO(text))
    for r in reader:
        sym = (r.get("SYMBOL") or r.get("Symbol") or r.get(" SYMBOL") or "").strip()
        series = (r.get("SERIES") or r.get("Series") or r.get(" SERIES") or "").strip()
        if series not in ("EQ", "BE", "BZ"):
            continue
        if not sym or "$" in sym or " " in sym:
            continue
        try:
            traded = int(
                float(
                    (
                        r.get("TTL_TRD_QNTY")
                        or r.get("TOTAL_TRADED_QTY")
                        or r.get("TOTTRDQTY")
                        or r.get(" TTL_TRD_QNTY")
                        or "0"
                    )
                    .strip()
                    .replace(",", "")
                )
            )
            deliv = int(
                float(
                    (r.get("DELIV_QTY") or r.get("DELIVERABLE_QTY") or r.get("DELVPRCNT") or r.get(" DELIV_QTY") or "0")
                    .strip()
                    .replace(",", "")
                )
            )
            pct_raw = (
                (r.get("DELIV_PER") or r.get("DLY_QT_TO_TRD_QT") or r.get("DELIV_PERC") or r.get(" DELIV_PER") or "")
                .strip()
                .replace(",", "")
            )
            close_raw = (
                (r.get("CLOSE_PRICE") or r.get("CLOSE") or r.get(" CLOSE_PRICE") or "0").strip().replace(",", "")
            )
            close = float(close_raw) if close_raw else 0.0
        except (ValueError, TypeError):
            continue
        if traded < MIN_TRADED_QTY:
            continue
        if deliv > 0 and traded > 0:
            pct = round(100.0 * deliv / traded, 2)
        elif pct_raw:
            try:
                pct = round(float(pct_raw), 2)
            except ValueError:
                pct = 0.0
        else:
            pct = 0.0
        rows.append(
            {
                "symbol": sym,
                "traded_qty": traded,
                "deliverable_qty": deliv,
                "delivery_pct": pct,
                "close": close,
            }
        )
    return rows


def fetch(date_str=None):
    """Fetch bhavcopy for a date, store delivery data."""
    if date_str is None:
        date_str = dt.date.today().isoformat()
    d = dt.date.fromisoformat(date_str)
    fmt1 = d.strftime("%d%m%Y")
    fmt2 = d.strftime("%d%b%Y").upper()
    d.strftime("%d-%b-%Y").upper()
    sess = _session()
    text = None
    # Try primary URL
    try:
        url = NSE_BHAV_URL.format(date=fmt1)
        resp = sess.get(url, timeout=30)
        if resp.status_code == 200 and len(resp.text) > 500:
            text = resp.text
    except Exception as e:
        print(f"[DELIVERY] primary URL failed: {e}")
    # Try alternate (zip)
    if text is None:
        try:
            url = NSE_BHAV_URL_ALT.format(date2=fmt2)
            resp = sess.get(url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 500:
                z = zipfile.ZipFile(io.BytesIO(resp.content))
                fname = z.namelist()[0]
                text = z.read(fname).decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"[DELIVERY] alt URL failed: {e}")
    if text is None:
        print(f"[DELIVERY] no bhavcopy for {date_str} (holiday or not available yet)")
        return 0
    rows = _parse_csv(text)
    if not rows:
        print(f"[DELIVERY] parsed 0 rows for {date_str}")
        return 0
    conn = db.get_conn()
    _ensure(conn)
    now = dt.datetime.now().isoformat(timespec="seconds")
    saved = 0
    for r in rows:
        conn.execute(
            "INSERT OR REPLACE INTO delivery_daily VALUES (?,?,?,?,?,?,?)",
            (date_str, r["symbol"], r["traded_qty"], r["deliverable_qty"], r["delivery_pct"], r["close"], now),
        )
        saved += 1
    conn.commit()
    conn.close()
    print(f"[DELIVERY] {date_str}: saved {saved} rows")
    return saved


def backfill(n_days=30):
    """Fetch last N trading days of bhavcopy data."""
    today = dt.date.today()
    saved_total = 0
    for i in range(n_days):
        d = today - dt.timedelta(days=i)
        if d.weekday() >= 5:  # skip weekends
            continue
        ds = d.isoformat()
        conn = db.get_conn()
        _ensure(conn)
        exists = conn.execute("SELECT COUNT(*) FROM delivery_daily WHERE date=?", (ds,)).fetchone()[0]
        conn.close()
        if exists > 50:
            continue
        try:
            n = fetch(ds)
            saved_total += n
        except Exception as e:
            print(f"[DELIVERY] {ds} failed: {e}")
    print(f"[DELIVERY] backfill complete: {saved_total} total rows")
    return saved_total


def top(n=30, date_str=None):
    """Show top delivery% stocks for a date."""
    conn = db.get_conn()
    _ensure(conn)
    if date_str is None:
        row = conn.execute("SELECT MAX(date) FROM delivery_daily").fetchone()
        date_str = row[0] if row and row[0] else dt.date.today().isoformat()
    rows = conn.execute(
        "SELECT symbol, delivery_pct, traded_qty, deliverable_qty, close "
        "FROM delivery_daily WHERE date=? AND delivery_pct > 0 "
        "ORDER BY delivery_pct DESC LIMIT ?",
        (date_str, n),
    ).fetchall()
    conn.close()
    print(f"[DELIVERY] top {n} by delivery% on {date_str}:")
    for sym, pct, tq, dq, cl in rows:
        print(f"   {sym:<14} {pct:5.1f}%  traded {tq:>10,}  deliv {dq:>10,}  close ₹{cl:.2f}")
    return [
        {
            "symbol": r[0],
            "delivery_pct": r[1],
            "traded_qty": r[2],
            "deliverable_qty": r[3],
            "close": r[4],
            "date": date_str,
        }
        for r in rows
    ]


def accumulation(n=30, min_days=5, min_avg_del=55.0):
    """Find stocks with consistently high delivery% over recent sessions
    (institutional accumulation signal)."""
    conn = db.get_conn()
    _ensure(conn)
    dates = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT date FROM delivery_daily ORDER BY date DESC LIMIT ?", (min_days + 5,)
        ).fetchall()
    ]
    if len(dates) < min_days:
        conn.close()
        print("[DELIVERY] not enough data for accumulation scan")
        return []
    recent_dates = dates[:min_days]
    rows = conn.execute(
        """
        SELECT symbol, AVG(delivery_pct) as avg_del,
               COUNT(*) as days,
               SUM(deliverable_qty) as total_deliv,
               MAX(close) as last_close
        FROM delivery_daily
        WHERE date IN ({})
        AND delivery_pct > 0
        GROUP BY symbol
        HAVING days >= ? AND avg_del >= ?
        ORDER BY avg_del DESC
        LIMIT ?
    """.format(",".join(f"'{d}'" for d in recent_dates)),
        (min_days, min_avg_del, n),
    ).fetchall()
    conn.close()
    out = []
    print(f"[DELIVERY] accumulation candidates (avg delivery >= {min_avg_del}% over {min_days} sessions):")
    for sym, avg, days, tot, cl in rows:
        print(f"   {sym:<14} avg {avg:5.1f}%  {days} sessions  total deliv {tot:>12,}  close ₹{cl:.2f}")
        out.append(
            {"symbol": sym, "avg_delivery_pct": round(avg, 1), "sessions": days, "total_deliverable": tot, "close": cl}
        )
    return out


def for_symbol(symbol, limit=30):
    """Delivery history for a symbol."""
    conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute(
        "SELECT date, delivery_pct, traded_qty, deliverable_qty, close "
        "FROM delivery_daily WHERE symbol=? "
        "ORDER BY date DESC LIMIT ?",
        (symbol.upper(), limit),
    ).fetchall()
    conn.close()
    return [
        {"date": r[0], "delivery_pct": r[1], "traded_qty": r[2], "deliverable_qty": r[3], "close": r[4]} for r in rows
    ]


def delivery_score(symbol, conn=None, lookback=10):
    """0.0–1.0 score: avg delivery% over last `lookback` sessions,
    normalized to 0-1 range (30%=0.0, 80%=1.0)."""
    own = conn is None
    if own:
        conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute(
        "SELECT delivery_pct FROM delivery_daily WHERE symbol=? AND delivery_pct > 0 ORDER BY date DESC LIMIT ?",
        (symbol.upper(), lookback),
    ).fetchall()
    if own:
        conn.close()
    if not rows or len(rows) < 3:
        return None
    avg = sum(r[0] for r in rows) / len(rows)
    score = max(0.0, min(1.0, (avg - 30.0) / 50.0))
    return round(score, 3)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "top"
    if cmd == "fetch":
        d = sys.argv[2] if len(sys.argv) > 2 else None
        fetch(d)
    elif cmd == "backfill":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        backfill(n)
    elif cmd == "top":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        top(n)
    elif cmd == "accum":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        accumulation(n)
    elif cmd == "symbol":
        sym = sys.argv[2].upper() if len(sys.argv) > 2 else "DIXON"
        for r in for_symbol(sym):
            print(f"   {r['date']}  {r['delivery_pct']:5.1f}%  traded {r['traded_qty']:>10,}  close ₹{r['close']:.2f}")
    elif cmd == "score":
        sym = sys.argv[2].upper() if len(sys.argv) > 2 else "DIXON"
        print(f"{sym}: delivery_score = {delivery_score(sym)}")
    else:
        top()
