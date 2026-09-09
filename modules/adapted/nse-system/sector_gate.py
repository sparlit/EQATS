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
Sector Momentum Gate (B1).
Ranks sectors by relative strength and only allows swing setups
from the top-N leadership sectors.
"""
import db
import pandas as pd

TOP_N = 3
MIN_STOCKS_PER_SECTOR = 3


def sector_perf(conn):
    rows = conn.execute(
        "SELECT s.sector, u.perf1m, u.perf3m "
        "FROM universe_broad u JOIN stocks s ON s.symbol=u.symbol "
        "WHERE s.sector IS NOT NULL AND s.sector!='' "
        "AND u.perf1m IS NOT NULL"
    ).fetchall()

    if not rows:
        return pd.DataFrame(columns=["sector", "p1", "p3", "n", "score"])

    df = pd.DataFrame(rows, columns=["sector", "p1", "p3"])
    g = (
        df.groupby("sector")
        .agg(
            p1=("p1", "mean"),
            p3=("p3", "mean"),
            n=("sector", "size"),
        )
        .reset_index()
    )
    g = g[g.n >= MIN_STOCKS_PER_SECTOR]
    g["score"] = 0.6 * g.p1 + 0.4 * g.p3
    return g.sort_values("score", ascending=False)


def allowed_sectors(top=TOP_N):
    conn = db.get_conn()
    g = sector_perf(conn)
    conn.close()
    if g.empty:
        return set()
    return set(g.head(top)["sector"].tolist())


def sector_of(symbol):
    conn = db.get_conn()
    r = conn.execute("SELECT sector FROM stocks WHERE symbol=?", (symbol,)).fetchone()
    conn.close()
    return r[0] if r else None


def passes(symbol, allowed=None):
    """True if the symbol's sector is in the leadership set."""
    sec = sector_of(symbol)
    if sec is None:
        return True  # no sector info -> don't block
    if allowed is None:
        allowed = allowed_sectors()
    if not allowed:
        return True  # gate unavailable -> don't block
    return sec in allowed


if __name__ == "__main__":
    conn = db.get_conn()
    g = sector_perf(conn)
    conn.close()
    print("SECTOR MOMENTUM RANKING:")
    for _, r in g.head(8).iterrows():
        mark = "✅" if r["sector"] in allowed_sectors() else "  "
        print(
            f"{mark} {r['sector']:<22} score {r['score']:+.2f} (1M {r['p1']:+.1%}, 3M {r['p3']:+.1%}, n={int(r['n'])})"
        )
