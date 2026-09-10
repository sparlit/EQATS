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


import os
import sys

from dotenv import load_dotenv
from sqlalchemy import text

# Ensure we can import from app
sys.path.append(os.getcwd())

# Load env
load_dotenv("web/.env")

from app.database import DatabaseManager

DB_URL = os.getenv("DATABASE_URL")

if __name__ == "__main__":
    if not DB_URL:
        print("DATABASE_URL not set")
        sys.exit(1)

    print("Starting duplicate cleanup...")
    db = DatabaseManager(db_url=DB_URL)
    session = db.Session()

    try:
        # SQL to keep the row with Max ID and delete others for same etf_id and date
        # Postgres specific
        query = text("""
            DELETE FROM etf_daily_prices a
            USING etf_daily_prices b
            WHERE a.id < b.id
            AND a.etf_id = b.etf_id
            AND a.date = b.date
        """)

        result = session.execute(query)
        rows_deleted = result.rowcount
        session.commit()
        print(f"Cleanup complete. Deleted {rows_deleted} duplicate rows.")

    except Exception as e:
        session.rollback()
        print(f"Error executing cleanup: {e}")
    finally:
        session.close()
