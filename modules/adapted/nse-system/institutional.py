"""
A2 — Institutional footprint.
- accumulation_score: up-volume share over last 20d (reliable proxy).
- fetch_delivery_nse: best-effort NSE delivery % (skips if blocked).
Stored in institutional(symbol,date,accum,delivery_pct).
"""
import datetime as dt
import db

def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS institutional(
        symbol TEXT, date TEXT, accum REAL, delivery_pct REAL,
        UNIQUE(symbol, date))""")

def accumulation_score(symbol, conn=None):
    own = False
    if conn is None:
        conn = db.get_conn()
        own = True
    rows = conn.execute(
        "SELECT close, volume FROM prices_daily WHERE symbol=? "
        "ORDER BY date DESC LIMIT 21", (symbol,)).fetchall()
    if own:
        conn.close()
    if len(rows) < 10:
        return None
    rows = list(reversed(rows))
    up = dn = 0.0
    for i in range(1, len(rows)):
        pc, pv = rows[i - 1]
        c, v = rows[i]
        if c > pc:
            up += v
        elif c < pc:
            dn += v
    tot = up + dn
    if tot <= 0:
        return None
    return round(up / tot, 3)

def fetch_delivery_nse(symbol):
    """Best-effort NSE delivery %. Returns None if blocked."""
    try:
        import requests
        d = dt.date.today()
        for fmt in ("%d%m%Y",):
            url = ("https://archives.nseindia.com/products/content/"
                   f"sec_bhavdata_full_{d.strftime(fmt)}.csv")
            r = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                continue
            for line in r.text.splitlines():
                if line.startswith(f"{symbol},"):
                    parts = line.split(",")
                    try:
                        trd = float(parts[11])
                        deliv = float(parts[12])
                        if trd > 0:
                            return round(100 * deliv / trd, 1)
                    except Exception:
                        return None
        return None
    except Exception:
        return None

def refresh(limit=300, use_nse=False):
    conn = db.get_conn()
    _ensure(conn)
    syms = [r[0] for r in conn.execute(
        "SELECT symbol FROM universe_broad "
        "WHERE mcap_cr BETWEEN 1000 AND 8000 "
        "ORDER BY mcap_cr DESC LIMIT ?", (limit,))]
    today = dt.date.today().isoformat()
    n = 0
    for sym in syms:
        acc = accumulation_score(sym, conn)
        if acc is None:
            continue
        deliv = fetch_delivery_nse(sym) if use_nse else None
        conn.execute(
            "INSERT OR REPLACE INTO institutional(symbol,date,accum,"
            "delivery_pct) VALUES(?,?,?,?)", (sym, today, acc, deliv))
        n += 1
    conn.commit()
    conn.close()
    print(f"[INST] refreshed {n} symbols")
    return n

def top_accumulation(n=10, min_accum=0.6):
    conn = db.get_conn()
    _ensure(conn)
    rows = conn.execute(
        "SELECT symbol, accum, delivery_pct FROM institutional "
        "WHERE date=(SELECT MAX(date) FROM institutional) "
        "AND accum>=? ORDER BY accum DESC LIMIT ?",
        (min_accum, n)).fetchall()
    conn.close()
    return [{"symbol": s, "accum": a, "delivery_pct": d}
            for s, a, d in rows]

if __name__ == "__main__":
    refresh()
    print("TOP ACCUMULATION (smart-money footprint):")
    for r in top_accumulation():
        d = f" deliv {r['delivery_pct']}%" if r["delivery_pct"] else ""
        print(f"  🏦 {r['symbol']:<12} accum {r['accum']:.2f}{d}")