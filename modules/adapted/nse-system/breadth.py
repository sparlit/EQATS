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
Market Breadth (A4).
% of tracked universe above 50-EMA + advance/decline.
Cached per day. Used to confirm the regime gate.
"""
import datetime as dt

import db
import pandas as pd

SAMPLE = 400
HIST = 220


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS breadth_daily(
        date TEXT PRIMARY KEY, above50 REAL, adv REAL, dec REAL)""")


def _tracked(conn):
    rows = conn.execute(
        "SELECT symbol FROM universe_broad WHERE mcap_cr BETWEEN 1000 AND 8000 ORDER BY mcap_cr DESC LIMIT ?", (SAMPLE,)
    ).fetchall()
    return [r[0] for r in rows]


def compute(conn=None, force=False):
    own = False
    if conn is None:
        conn = db.get_conn()
        own = True
    today = dt.date.today().isoformat()
    _ensure(conn)

    if not force:
        r = conn.execute("SELECT above50, adv, dec FROM breadth_daily WHERE date=?", (today,)).fetchone()
        if r:
            out = {"above50": r[0], "adv": r[1], "dec": r[2]}
            if own:
                conn.close()
            return out

    above = adv = dec = tot = 0
    for sym in _tracked(conn):
        rows = conn.execute(
            "SELECT close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT ?", (sym, HIST)
        ).fetchall()
        if len(rows) < 60:
            continue
        closes = pd.Series([r[0] for r in reversed(rows)], dtype=float)
        e50 = closes.ewm(span=50, adjust=False).mean()
        tot += 1
        if closes.iloc[-1] > e50.iloc[-1]:
            above += 1
        if len(closes) >= 2:
            if closes.iloc[-1] > closes.iloc[-2]:
                adv += 1
            elif closes.iloc[-1] < closes.iloc[-2]:
                dec += 1

    above50 = round(above / max(1, tot), 3)
    conn.execute("INSERT OR REPLACE INTO breadth_daily VALUES (?,?,?,?)", (today, above50, adv, dec))
    conn.commit()
    out = {"above50": above50, "adv": adv, "dec": dec}
    if own:
        conn.close()
    return out


def breadth_ok(conn=None):
    """Bullish breadth: >50% above 50-EMA and advances >= declines."""
    b = compute(conn)
    return (b["above50"] >= 0.5) and (b["adv"] >= b["dec"])
