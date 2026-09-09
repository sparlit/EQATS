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
Daily P(WIN) cache — one scoring pass per symbol per day.
Makes /api/toppicks, /api/radar, /api/swing/signals instant.
"""
import datetime as dt
import json

import db
import meta_model


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS pwin_daily(
        symbol TEXT, date TEXT, p_win REAL, why TEXT,
        PRIMARY KEY (symbol, date))""")


def get_map(conn=None):
    """symbol -> p_win for the latest cached day."""
    own = conn is None
    if own:
        conn = db.get_conn()
    _ensure(conn)
    d = conn.execute("SELECT MAX(date) FROM pwin_daily").fetchone()[0]
    out = {}
    if d:
        for sym, p in conn.execute("SELECT symbol, p_win FROM pwin_daily WHERE date=?", (d,)).fetchall():
            out[sym] = p
    if own:
        conn.close()
    return out


def get_why(conn, symbol):
    d = conn.execute("SELECT MAX(date) FROM pwin_daily").fetchone()[0]
    r = conn.execute("SELECT why FROM pwin_daily WHERE symbol=? AND date=?", (symbol, d)).fetchone()
    return json.loads(r[0]) if r and r[0] else []


def refresh_all(limit=600):
    """Score smallcap band + core once; skip already-cached symbols."""
    conn = db.get_conn()
    _ensure(conn)
    d = dt.date.today().isoformat()
    done = {r[0] for r in conn.execute("SELECT symbol FROM pwin_daily WHERE date=?", (d,)).fetchall()}
    syms = [
        r[0]
        for r in conn.execute(
            "SELECT symbol FROM universe_broad "
            "WHERE mcap_cr BETWEEN 1000 AND 8000 "
            "AND symbol NOT LIKE '%$%' AND symbol NOT LIKE '% %' "
            "ORDER BY mcap_cr DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ]
    core = [r[0] for r in conn.execute("SELECT symbol FROM stocks WHERE active=1").fetchall()]
    todo = [s for s in sorted(set(syms) | set(core)) if s not in done]
    n = 0
    for sym in todo:
        try:
            r = meta_model.score_symbol(sym, use_yahoo=False)
        except Exception:
            continue
        if not r or r.get("p_win") is None:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO pwin_daily VALUES (?,?,?,?)", (sym, d, r["p_win"], json.dumps(r.get("why", [])))
        )
        n += 1
        if n % 50 == 0:
            conn.commit()
            print(f"  ...{n}/{len(todo)}")
    conn.commit()
    conn.close()
    print(f"[PWIN] cached {n} new scores for {d}")
    return n


if __name__ == "__main__":
    refresh_all()
