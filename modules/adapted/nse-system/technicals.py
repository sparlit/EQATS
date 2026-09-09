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

import db


def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS technicals_daily(
        symbol TEXT, date TEXT, close REAL, dma20 REAL, dma50 REAL,
        dma200 REAL, rsi REAL, vol_ratio REAL, high52 REAL, low52 REAL,
        mom20 REAL, above200 INTEGER, PRIMARY KEY (symbol, date))""")


def compute_all():
    conn = db.get_conn()
    ensure(conn)
    today = dt.date.today().isoformat()
    conn.execute("DELETE FROM technicals_daily WHERE date=?", (today,))
    symbols = [r[0] for r in conn.execute("SELECT symbol FROM stocks WHERE active=1")]
    n = 0
    for sym in symbols:
        rows = conn.execute(
            "SELECT close, volume FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 260", (sym,)
        ).fetchall()
        rows = [r for r in rows if r[0] is not None and r[1] is not None]
        if len(rows) < 210:
            continue
        closes = [r[0] for r in reversed(rows)]
        vols = [r[1] for r in reversed(rows)]
        c = closes[-1]
        dma20 = sum(closes[-20:]) / 20
        dma50 = sum(closes[-50:]) / 50
        dma200 = sum(closes[-200:]) / 200
        hi52 = max(closes[-252:])
        lo52 = min(closes[-252:])
        vol20 = sum(vols[-20:]) / 20
        vol_ratio = vols[-1] / vol20 if vol20 else 0
        gains = 0.0
        losses = 0.0
        for i in range(len(closes) - 14, len(closes)):
            ch = closes[i] - closes[i - 1]
            if ch > 0:
                gains += ch
            else:
                losses -= ch
        rsi = 100.0 if losses == 0 else 100 - (100 / (1 + gains / losses))
        mom20 = c / closes[-21] - 1
        conn.execute(
            "INSERT OR REPLACE INTO technicals_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (sym, today, c, dma20, dma50, dma200, rsi, vol_ratio, hi52, lo52, mom20, 1 if c > dma200 else 0),
        )
        n += 1
    conn.commit()
    print(f"Technicals computed: {n} stocks")
    conn.close()


if len(sys.argv) > 1 and sys.argv[1] == "run":
    compute_all()
