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
Fill stocks.sector for the tracked universe (best-effort via Yahoo).
Activates sector gate (B1) + sector layer in Top Picks / meta model.
"""
import time

import db


def _upsert(conn, sym, sec, name):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(stocks)")]
    vals = {"symbol": sym}
    if "sector" in cols:
        vals["sector"] = sec
    if "name" in cols:
        vals["name"] = name
    if "active" in cols:
        vals["active"] = 1
    keys = list(vals.keys())
    ph = ",".join("?" for _ in keys)
    conn.execute("DELETE FROM stocks WHERE symbol=?", (sym,))
    conn.execute(f"INSERT INTO stocks({','.join(keys)}) VALUES({ph})", [vals[k] for k in keys])


def refresh(limit=900):
    import yfinance as yf

    conn = db.get_conn()
    syms = [
        r[0]
        for r in conn.execute(
            "SELECT symbol FROM universe_broad WHERE mcap_cr BETWEEN 1000 AND 8000 ORDER BY mcap_cr DESC LIMIT ?",
            (limit,),
        )
    ]
    n = 0
    for sym in syms:
        row = conn.execute("SELECT sector FROM stocks WHERE symbol=?", (sym,)).fetchone()
        if row and row[0]:
            continue
        try:
            info = yf.Ticker(sym + ".NS").info or {}
        except Exception:
            continue
        sec = info.get("sector")
        if not sec:
            continue
        _upsert(conn, sym, sec, info.get("shortName") or sym)
        n += 1
        if n % 50 == 0:
            print(f"  ...{n}")
        time.sleep(0.25)
    conn.commit()
    conn.close()
    print(f"[SECTORS] filled {n} sectors")


if __name__ == "__main__":
    refresh()
