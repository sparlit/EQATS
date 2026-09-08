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


"""One-time: download 5y daily history for smallcap band (1000-8000 cr)."""
import math
import time

import db
import yfinance as yf


def run(limit=600, min_mcap=1000, max_mcap=8000):
    conn = db.get_conn()
    syms = [
        r[0]
        for r in conn.execute(
            "SELECT symbol FROM universe_broad WHERE mcap_cr BETWEEN ? AND ? ORDER BY mcap_cr DESC LIMIT ?",
            (min_mcap, max_mcap, limit),
        )
    ]
    print(f"ingesting {len(syms)} smallcaps...")
    done = 0
    for sym in syms:
        have = conn.execute("SELECT COUNT(*) FROM prices_daily WHERE symbol=?", (sym,)).fetchone()[0]
        if have >= 250:
            done += 1
            continue
        try:
            tk = yf.Ticker(sym + ".NS")
            df = tk.history(period="5y", auto_adjust=True)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        rows = []
        for idx, r in df.iterrows():
            o = float(r["Open"])
            h = float(r["High"])
            l = float(r["Low"])
            c = float(r["Close"])
            v = float(r["Volume"])
            if any(math.isnan(x) for x in (o, h, l, c, v)):
                continue
            rows.append((sym, str(idx.date()), o, h, l, c, v))
        conn.executemany("INSERT OR REPLACE INTO prices_daily VALUES (?,?,?,?,?,?,?)", rows)
        conn.commit()
        done += 1
        print(f"[{done}/{len(syms)}] {sym}: {len(rows)} rows")
        time.sleep(0.2)
    print("smallcap history ingest complete")
    conn.close()


if __name__ == "__main__":
    run()
