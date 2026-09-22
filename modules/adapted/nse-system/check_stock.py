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


import sys

import db
import scoring

sym = sys.argv[2] if len(sys.argv) > 2 else "DIXON"
conn = db.get_conn()
cols = [c[1] for c in conn.execute("PRAGMA table_info(fundamentals)")]
row = conn.execute("SELECT * FROM fundamentals WHERE symbol=?", (sym,)).fetchone()
if row is None:
    print("no fundamentals for", sym)
    sys.exit()
m = dict(zip(cols, row, strict=False))

print("RAW FUNDAMENTALS:", sym)
for k in [
    "pe",
    "roe",
    "roce",
    "debt_to_equity",
    "sales_growth_3y",
    "profit_growth_3y",
    "cfo_positive",
    "market_cap_cr",
]:
    print(f"  {k} = {m.get(k)}")

med = scoring.sector_pe_medians(conn)
r = scoring.score_stock(conn, sym, med)
print("sector:", r["sector"], "| sector median PE:", med.get(r["sector"]))
print("roce_s:", r["roce_s"], "| growth_s:", r["growth_s"], "| val_s:", r["val_s"], "| composite:", r["composite"])
print("GATES:")
for g in r["gates"]:
    print("  ", g[0], "| passed:", g[1], "|", g[4])
