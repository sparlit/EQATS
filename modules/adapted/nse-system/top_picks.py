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
Top Picks — daily shortlist (fast: reads pwin_daily cache).
Composite = 50% P(WIN) + 30% accum + 20% sector RS (+10% live setup).
"""
import datetime as dt

import db
import institutional
import pandas as pd
import pwin_cache
import sector_gate


def _ensure(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS top_picks(
    date TEXT, symbol TEXT, p_win REAL, accum REAL,
    sector_rs REAL, sector TEXT, setup INTEGER, composite REAL)
    """)


def _sector_rs_map(conn):
    try:
        g = sector_gate.sector_perf(conn)
        if g is None or g.empty:
            return {}, {}
        n = len(g)
        sector_rank = {}
        for i, (_, row) in enumerate(g.iterrows()):
            sector_rank[row["sector"]] = 1.0 - (i / max(1, n - 1))
        symbol_sector = {}
        for sym, sec in conn.execute(
            "SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL AND sector!=''"
        ).fetchall():
            symbol_sector[sym] = sec
        return ({sym: sector_rank.get(sec, 0.5) for sym, sec in symbol_sector.items()}, symbol_sector)
    except Exception as e:
        print(f"[TOPPICKS] sector rs skipped: {e}")
        return {}, {}


def _detect_setup(conn, sym):
    try:
        from setup import SetupDetector

        rows = conn.execute(
            "SELECT date, close, high, low, volume FROM prices_daily WHERE symbol=? ORDER BY date", (sym,)
        ).fetchall()
        if len(rows) < 280:
            return 0
        df = pd.DataFrame(list(rows), columns=["date", "Close", "High", "Low", "Volume"]).set_index("date")
        df.index = pd.to_datetime(df.index)
        st = SetupDetector.detect(df, sym)
        return 1 if st.triggered else 0
    except Exception as e:
        print(f"[TOPPICKS] setup detect skipped for {sym}: {e}")
        return 0


def _latest_accumulation_map(conn):
    acc = {}
    try:
        for sym, a in conn.execute("""
                SELECT symbol, accum FROM institutional
                WHERE date=(SELECT MAX(date) FROM institutional)"""):
            if a is not None:
                acc[sym] = float(a)
    except Exception as e:
        print(f"[TOPPICKS] accumulation map skipped: {e}")
    return acc


def _universe(conn, limit=600):
    rows = conn.execute(
        "SELECT symbol FROM universe_broad "
        "WHERE mcap_cr BETWEEN 1000 AND 8000 "
        "AND symbol NOT LIKE '%$%' AND symbol NOT LIKE '% %' "
        "ORDER BY mcap_cr DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [r[0] for r in rows]


def compute(force=False):
    conn = db.get_conn()
    _ensure(conn)
    today = dt.date.today().isoformat()
    if not force:
        if conn.execute("SELECT COUNT(*) FROM top_picks WHERE date=?", (today,)).fetchone()[0] > 0:
            conn.close()
            return
    pwin = pwin_cache.get_map(conn)
    if not pwin:
        conn.close()
        pwin_cache.refresh_all()
        conn = db.get_conn()
        pwin = pwin_cache.get_map(conn)
    conn.execute("DELETE FROM top_picks WHERE date=?", (today,))
    symbol_rs, symbol_sector = _sector_rs_map(conn)
    accum_map = _latest_accumulation_map(conn)
    rows = []
    for sym in _universe(conn, limit=600):
        p_win = pwin.get(sym)
        if p_win is None:
            continue
        accum = accum_map.get(sym, 0.5)
        sector_rs = symbol_rs.get(sym, 0.5)
        composite = 0.50 * p_win + 0.30 * accum + 0.20 * sector_rs
        rows.append(
            [
                today,
                sym,
                round(p_win, 3),
                round(accum, 3),
                round(sector_rs, 3),
                symbol_sector.get(sym),
                0,
                round(composite, 3),
            ]
        )
    rows.sort(key=lambda x: -x[7])
    top50 = rows[:50]
    for row in top50:
        if _detect_setup(conn, row[1]):
            row[6] = 1
            row[7] = round(row[7] + 0.10, 3)
    top50.sort(key=lambda x: -x[7])
    conn.executemany("INSERT INTO top_picks VALUES (?,?,?,?,?,?,?,?)", top50)
    conn.commit()
    conn.close()
    print(f"[TOPPICKS] stored {len(top50)} (from {len(rows)} cached)")


def top(n=15):
    conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute(
        "SELECT symbol, p_win, accum, sector_rs, sector, setup, "
        "composite FROM top_picks "
        "WHERE date=(SELECT MAX(date) FROM top_picks) "
        "ORDER BY composite DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [
        {"symbol": s, "p_win": p, "accum": a, "sector_rs": sr, "sector": sec, "setup": bool(st), "composite": c}
        for s, p, a, sr, sec, st, c in rows
    ]


if __name__ == "__main__":
    compute(force=True)
    for r in top(15):
        tag = " 🏄" if r["setup"] else ""
        print(
            f"{r['symbol']:<14} comp {r['composite']:.2f} | "
            f"P {r['p_win']:.0%} | acc {r['accum']:.2f} | "
            f"{r['sector'] or '?'}{tag}"
        )
