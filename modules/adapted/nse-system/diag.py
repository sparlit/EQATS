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


import db
import scoring

conn = db.get_conn()

print("DB SECTORS:")
for sym in ["MUTHOOTFIN", "BBTC", "DIXON"]:
    r = conn.execute("SELECT sector FROM stocks WHERE symbol=?", (sym,)).fetchone()
    print("  ", sym, "->", r[0])

med = scoring.sector_pe_medians(conn)
cols = [c[1] for c in conn.execute("PRAGMA table_info(fundamentals)")]

for sym in ["MUTHOOTFIN", "BBTC", "DIXON"]:
    row = conn.execute("SELECT * FROM fundamentals WHERE symbol=?", (sym,)).fetchone()
    m = dict(zip(cols, row, strict=False))
    sec = conn.execute("SELECT sector FROM stocks WHERE symbol=?", (sym,)).fetchone()[0]
    pe = m.get("pe")
    pg = m.get("profit_growth_3y")
    md = med.get(sec)
    ratio = None
    if pe and md:
        ratio = round(pe / md, 2)
    peg = None
    if pe and pg and pg > 0:
        peg = round(pe / pg, 2)
    print(
        sym,
        "| PE:",
        pe,
        "| sector:",
        sec,
        "| sector median PE:",
        md,
        "| PE ratio:",
        ratio,
        "| PEG:",
        peg,
        "| ROCE:",
        m.get("roce"),
        "| profit 3Y:",
        pg,
        "| sales 3Y:",
        m.get("sales_growth_3y"),
    )
