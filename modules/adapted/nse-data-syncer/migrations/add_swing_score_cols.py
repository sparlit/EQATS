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

from app.helpers import get_project_root
from dotenv import load_dotenv
from sqlalchemy import text

if not os.getenv("DATABASE_URL"):
    load_dotenv(get_project_root() / "web" / ".env")

from app.database import DatabaseManager

COLUMNS = ["strong_stock_score", "sector_score", "adr_score", "swing_score"]


def run_migration():
    print("Running migration to add swing score columns...")
    db = DatabaseManager()
    with db.engine.connect() as conn:
        for col in COLUMNS:
            try:
                conn.execute(text(f"ALTER TABLE stock_performance ADD COLUMN IF NOT EXISTS {col} DOUBLE PRECISION"))
                conn.commit()
                print(f"Migration successful: Added {col} column.")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print(f"Column {col} already exists.")
                else:
                    print(f"Migration failed for {col}: {e}")


if __name__ == "__main__":
    run_migration()
