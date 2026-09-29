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
    conn.execute("""CREATE TABLE IF NOT EXISTS events(
        date TEXT, symbol TEXT, kind TEXT, text TEXT)""")


def detect():
    conn = db.get_conn()
    ensure(conn)

    # Use the two most recent dates that actually have technicals data
    dates = [r[0] for r in conn.execute("SELECT DISTINCT date FROM technicals_daily ORDER BY date DESC LIMIT 2")]
    if len(dates) < 2:
        print("Events: need at least 2 days of technicals — run daily update first")
        conn.close()
        return

    latest_date = dates[0]
    prev_date = dates[1]

    conn.execute("DELETE FROM events WHERE date=?", (latest_date,))

    cur = {r[0]: r for r in conn.execute("SELECT * FROM technicals_daily WHERE date=?", (latest_date,))}
    pre = {r[0]: r for r in conn.execute("SELECT * FROM technicals_daily WHERE date=?", (prev_date,))}

    ev = []
    for sym, t in cur.items():
        p = pre.get(sym)
        if p is None:
            continue
        # technicals_daily column indices:
        # 0 symbol, 1 date, 2 close, 3 dma20, 4 dma50, 5 dma200,
        # 6 rsi, 7 vol_ratio, 8 high52, 9 low52, 10 mom20, 11 above200
        if p[11] == 0 and t[11] == 1:
            ev.append((sym, "CROSS_UP_200", f"{sym} crossed ABOVE 200-day average"))
        if p[11] == 1 and t[11] == 0:
            ev.append((sym, "CROSS_DOWN_200", f"{sym} fell BELOW 200-day average"))
        if t[7] is not None and t[7] >= 2.5:
            ev.append((sym, "VOL_SPIKE", f"{sym} volume {t[7]:.1f}x 20-day average"))
        if (
            t[2] is not None
            and t[8] is not None
            and p[2] is not None
            and p[8] is not None
            and t[2] >= t[8] * 0.995
            and p[2] < p[8] * 0.995
        ):
            ev.append((sym, "NEW_52W_HIGH", f"{sym} touched 52-week high"))
        if p[3] is not None and p[4] is not None and t[3] is not None and t[4] is not None:
            if p[3] <= p[4] and t[3] > t[4]:
                ev.append((sym, "GOLDEN_CROSS", f"{sym} 20DMA crossed above 50DMA"))
            if p[3] >= p[4] and t[3] < t[4]:
                ev.append((sym, "DEATH_CROSS", f"{sym} 20DMA crossed below 50DMA"))
        if t[6] is not None and t[6] >= 70:
            ev.append((sym, "OVERBOUGHT", f"{sym} RSI {t[6]:.0f}"))
        if t[6] is not None and t[6] <= 30:
            ev.append((sym, "OVERSOLD", f"{sym} RSI {t[6]:.0f}"))

    rec_now = {r[0] for r in conn.execute("SELECT symbol FROM pipeline WHERE status='Recommended'")}
    seen = {r[0] for r in conn.execute("SELECT DISTINCT symbol FROM events WHERE kind='NEW_RECOMMENDED'")}
    for sym in rec_now - seen:
        ev.append((sym, "NEW_RECOMMENDED", f"{sym} entered Recommended"))

    for sym, kind, text in ev:
        conn.execute("INSERT INTO events VALUES (?,?,?,?)", (latest_date, sym, kind, text))
    conn.commit()
    print(f"Events detected for {latest_date}: {len(ev)}")
    conn.close()


if len(sys.argv) > 1 and sys.argv[1] == "run":
    detect()
