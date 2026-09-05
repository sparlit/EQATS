"""
Market Breadth (A4).
% of tracked universe above 50-EMA + advance/decline.
Cached per day. Used to confirm the regime gate.
"""
import datetime as dt
import pandas as pd
import db

SAMPLE = 400
HIST = 220

def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS breadth_daily(
        date TEXT PRIMARY KEY, above50 REAL, adv REAL, dec REAL)""")

def _tracked(conn):
    rows = conn.execute(
        "SELECT symbol FROM universe_broad "
        "WHERE mcap_cr BETWEEN 1000 AND 8000 "
        "ORDER BY mcap_cr DESC LIMIT ?", (SAMPLE,)).fetchall()
    return [r[0] for r in rows]

def compute(conn=None, force=False):
    own = False
    if conn is None:
        conn = db.get_conn()
        own = True
    today = dt.date.today().isoformat()
    _ensure(conn)

    if not force:
        r = conn.execute(
            "SELECT above50, adv, dec FROM breadth_daily WHERE date=?",
            (today,)).fetchone()
        if r:
            out = {"above50": r[0], "adv": r[1], "dec": r[2]}
            if own:
                conn.close()
            return out

    above = adv = dec = tot = 0
    for sym in _tracked(conn):
        rows = conn.execute(
            "SELECT close FROM prices_daily WHERE symbol=? "
            "ORDER BY date DESC LIMIT ?", (sym, HIST)).fetchall()
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
    conn.execute("INSERT OR REPLACE INTO breadth_daily VALUES (?,?,?,?)",
                 (today, above50, adv, dec))
    conn.commit()
    out = {"above50": above50, "adv": adv, "dec": dec}
    if own:
        conn.close()
    return out

def breadth_ok(conn=None):
    """Bullish breadth: >50% above 50-EMA and advances >= declines."""
    b = compute(conn)
    return (b["above50"] >= 0.5) and (b["adv"] >= b["dec"])