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
Emergency fix: mark ALL existing presentations as kw_dispatched_at = NOW()
so the Lambda stops triggering more keyword analysis runs.

Usage:
    DATABASE_URL="postgres://..." python scripts/emergency_mark_dispatched.py
"""
import os

import psycopg2

url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(url)
conn.autocommit = True
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM nse_documents WHERE doc_type = 'presentation' AND kw_dispatched_at IS NULL")
(pending,) = cur.fetchone()
print(f"Presentations with kw_dispatched_at IS NULL: {pending}")

cur.execute("""
    UPDATE nse_documents
    SET kw_dispatched_at = NOW()
    WHERE doc_type = 'presentation'
      AND kw_dispatched_at IS NULL
""")
print(f"Marked {cur.rowcount} rows as dispatched. Lambda will stop queuing new runs on next poll.")

cur.close()
conn.close()
