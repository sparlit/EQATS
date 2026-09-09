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


import datetime as dt
import sys
import time

import db
import yfinance as yf

from config import HISTORY_YEARS, SLEEP_SECONDS


def fetch_one(conn, symbol):
    meta = conn.execute("SELECT last_date FROM price_meta WHERE symbol=?", (symbol,)).fetchone()
    last = meta[0] if meta else None
    if last:
        start = (dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
    else:
        start = (dt.date.today() - dt.timedelta(days=365 * HISTORY_YEARS)).isoformat()
    if start > dt.date.today().isoformat():
        return 0

    tk = yf.Ticker(symbol + ".NS")
    df = tk.history(start=start, auto_adjust=True)
    if df.empty:
        return 0

    rows = [
        (symbol, str(idx.date()), float(o), float(h), float(l), float(c), float(v))
        for idx, o, h, l, c, v in zip(
            df.index, df["Open"], df["High"], df["Low"], df["Close"], df["Volume"], strict=False
        )
    ]
    conn.executemany("INSERT OR REPLACE INTO prices_daily VALUES (?,?,?,?,?,?,?)", rows)

    last_row = conn.execute("SELECT MAX(date), COUNT(*) FROM prices_daily WHERE symbol=?", (symbol,)).fetchone()
    conn.execute(
        "INSERT OR REPLACE INTO price_meta VALUES (?,?,?,?)",
        (symbol, last_row[0], last_row[1], dt.datetime.now().isoformat()),
    )
    conn.commit()
    return len(rows)


def run(show_every=1):
    conn = db.get_conn()
    symbols = [r[0] for r in conn.execute("SELECT symbol FROM stocks WHERE active=1 ORDER BY symbol")]
    total = len(symbols)
    failed = []
    for i, sym in enumerate(symbols, 1):
        ok = False
        for attempt in range(3):
            try:
                n = fetch_one(conn, sym)
                if show_every:
                    print(f"[{i}/{total}] {sym}: +{n} rows")
                ok = True
                break
            except Exception as e:
                print(f"[{i}/{total}] {sym} attempt {attempt + 1} failed: {e}")
                time.sleep(5 * (attempt + 1))
        if not ok:
            failed.append(sym)
        time.sleep(SLEEP_SECONDS)

    print("FAILED SYMBOLS:", failed or "none")
    total_rows = conn.execute("SELECT COUNT(*) FROM prices_daily").fetchone()[0]
    print(f"Total price rows in database: {total_rows}")
    conn.close()
    return failed


if len(sys.argv) > 1 and sys.argv[1] == "run":
    run()
